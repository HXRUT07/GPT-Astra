from dataclasses import replace
import json

import pandas as pd
import pytest

from stock_signal.backtest import BacktestConfig, run_backtest


def bars(rows):
    timestamps = pd.date_range("2024-01-01", periods=len(rows), freq="D", tz="UTC")
    records = []
    for timestamp, overrides in zip(timestamps, rows):
        row = {"timestamp": timestamp, "open": 100., "high": 101., "low": 99.,
               "close": 100., "volume": 1000., "dividend": 0., "split_ratio": 1.}
        row.update(overrides)
        records.append(row)
    return pd.DataFrame(records)


def signal(frame, index=0, **overrides):
    row = {"schema_version": 1, "signal_id": f"test-{index}", "ticker": "TEST",
           "timestamp": frame.iloc[index]["timestamp"].isoformat(), "qualified": True,
           "entry_trigger_price": frame.iloc[index]["close"], "stop_loss": 95.,
           "take_profit": 112., "min_reward_risk": 2.}
    row.update(overrides)
    return row


def test_signal_close_never_executes_and_next_session_open_is_used():
    frame = bars([{"close": 80., "open": 80., "high": 120., "low": 70.}, {}, {}])
    frame.loc[1:, "timestamp"] = pd.to_datetime(["2024-01-05", "2024-01-08"], utc=True)
    result = run_backtest(frame, [signal(frame)])
    assert result["trades"] == []
    position = result["open_position"]
    assert position["entry_timestamp"] == frame.iloc[1]["timestamp"].isoformat()
    assert position["entry_price"] == pytest.approx(100.1)
    assert position["quantity"] == 100
    assert position["entry_commission"] == pytest.approx(10.01)
    assert position["planned_risk"] == pytest.approx(539.0005)
    assert position["net_reward_risk"] == pytest.approx(2.147681124600069)
    assert result["equity"][0]["position_quantity"] == 0


def test_real_next_open_rejects_previously_qualified_reward_risk():
    frame = bars([{}, {"open": 105., "high": 106., "low": 104., "close": 105.}])
    result = run_backtest(frame, [signal(frame)])
    assert result["open_position"] is None
    assert result["trades"] == []
    rejected = result["rejected_entries"][0]
    assert rejected["reason"] == "gross_reward_risk_below_minimum"
    assert rejected["actual_entry_price"] == pytest.approx(105.105)
    assert rejected["net_reward_risk"] == pytest.approx(.63134622, abs=1e-7)


def test_net_cost_gate_rejects_gross_two_to_one():
    frame = bars([{}, {}])
    result = run_backtest(frame, [signal(frame, take_profit=110.)],
                          replace(BacktestConfig(), slippage_bps=0.))
    assert result["rejected_entries"][0]["reason"] == "net_reward_risk_below_minimum"
    assert result["rejected_entries"][0]["reward_risk"] == 2.


@pytest.mark.parametrize("exit_bar, expected_reference, expected_fill", [
    ({"open": 100., "high": 114., "low": 94., "close": 101.}, 95., "stop_first"),
    ({"open": 90., "high": 114., "low": 89., "close": 100.}, 90., "gap_stop"),
    ({"open": 100., "high": 101., "low": 94., "close": 100.}, 95., "intrabar_stop"),
    ({"open": 115., "high": 116., "low": 113., "close": 115.}, 112., "gap_target_at_target"),
    ({"open": 100., "high": 114., "low": 99., "close": 111.}, 112., "intrabar_target"),
])
def test_gap_and_intrabar_conservative_fills(exit_bar, expected_reference, expected_fill):
    frame = bars([{}, {}, exit_bar])
    result = run_backtest(frame, [signal(frame)])
    trade = result["trades"][0]
    assert trade["exit_reference_price"] == expected_reference
    assert trade["exit_price"] == pytest.approx(expected_reference * .999)
    assert trade["fill_reason"] == expected_fill
    proceeds = expected_reference * .999 * trade["quantity"] * .999
    assert trade["net_pnl"] == pytest.approx(proceeds - trade["entry_cost"])
    assert result["metrics"]["final_equity"] == pytest.approx(100_000 + trade["net_pnl"])


def test_entry_bar_can_stop_and_target_but_always_chooses_stop():
    frame = bars([{}, {"high": 113., "low": 94.}])
    result = run_backtest(frame, [signal(frame)])
    assert result["trades"][0]["fill_reason"] == "stop_first"
    assert result["metrics"]["closed_trades"] == 1
    assert result["metrics"]["win_rate_pct"] == 0.


@pytest.mark.parametrize("config", [
    replace(BacktestConfig(), starting_cash=9_000, risk_fraction=1.),
    replace(BacktestConfig(), starting_cash=100_000, risk_fraction=.001),
])
def test_cash_and_risk_caps_reject_unaffordable_full_lot(config):
    frame = bars([{}, {}])
    result = run_backtest(frame, [signal(frame)], config)
    assert result["open_position"] is None
    assert result["rejected_entries"][0]["reason"] == "insufficient_cash_or_risk_budget_for_lot"
    assert result["metrics"]["ending_cash"] == config.starting_cash


def test_cash_cap_includes_commission_and_rounds_down_to_lots():
    frame = bars([{}, {}])
    config = replace(BacktestConfig(), starting_cash=20_000., risk_fraction=1.)
    result = run_backtest(frame, [signal(frame)], config)
    assert result["open_position"]["quantity"] == 100
    assert result["metrics"]["ending_cash"] == pytest.approx(9_979.99)
    assert result["metrics"]["ending_cash"] >= 0


def test_dividend_paid_to_previous_close_holder_even_if_selling_today():
    frame = bars([{}, {}, {"dividend": 2., "open": 94., "low": 93., "high": 95., "close": 94.}])
    result = run_backtest(frame, [signal(frame)])
    trade = result["trades"][0]
    assert trade["dividends"] == 200.
    assert result["metrics"]["dividends_received"] == 200.
    exit_net = 94. * .999 * 100 * .999
    assert trade["net_pnl"] == pytest.approx(exit_net - 10_020.01 + 200.)
    assert result["metrics"]["ending_cash"] == pytest.approx(100_000 + trade["net_pnl"])


def test_ex_date_entry_receives_no_dividend_and_open_holder_accrues_later():
    frame = bars([{}, {"dividend": 3.}, {"dividend": 2.}])
    result = run_backtest(frame, [signal(frame)])
    assert result["metrics"]["dividends_received"] == 200.
    assert result["open_position"]["dividends"] == 200.
    assert result["metrics"]["final_equity"] == pytest.approx(100_000 - 20.01 + 200.)
    assert result["metrics"]["realized_net_profit"] == 0.


def test_intraday_exit_cannot_fund_same_day_open_entry():
    frame = bars([{}, {}, {"low": 94.}, {}])
    result = run_backtest(frame, [signal(frame, 0), signal(frame, 1)])
    assert len(result["trades"]) == 1
    assert result["open_position"] is None
    assert result["rejected_entries"][0]["signal_id"] == "test-1"
    assert result["rejected_entries"][0]["reason"] == "position_open"


def test_max_holding_exit_counts_entry_day_and_includes_exit_costs():
    frame = bars([{}, {}, {}, {}])
    result = run_backtest(frame, [signal(frame)], replace(BacktestConfig(), max_holding_bars=2))
    trade = result["trades"][0]
    assert trade["holding_bars"] == 2
    assert trade["exit_timestamp"] == frame.iloc[2]["timestamp"].isoformat()
    assert trade["exit_reason"] == "max_holding_bars"
    assert trade["exit_price"] == pytest.approx(99.9)
    assert trade["net_pnl"] < 0


def test_zero_closed_trades_report_null_win_rate_and_separate_open_position():
    frame = bars([{}, {}])
    result = run_backtest(frame, [signal(frame)])
    metrics = result["metrics"]
    assert metrics["closed_trades"] == 0
    assert metrics["win_rate_pct"] is None and metrics["profit_factor"] is None
    assert metrics["open_positions"] == 1
    assert result["open_position"] is not None
    assert metrics["final_equity"] == pytest.approx(99_979.99)
    assert metrics["max_drawdown_pct"] == pytest.approx(.02001)
    json.dumps(result, allow_nan=False)


def test_empty_and_unqualified_runs_are_honest_and_json_ready():
    frame = bars([{}, {}])
    result = run_backtest(frame, [signal(frame, qualified=False)])
    assert result["metrics"]["closed_trades"] == 0
    assert result["metrics"]["final_equity"] == 100_000.
    assert result["metrics"]["win_rate_pct"] is None
    assert result["rejected_entries"] == []
    assert result["open_position"] is None
    empty = run_backtest(frame.iloc[:0], [])
    assert empty["equity"] == []
    assert empty["metrics"]["final_equity"] == 100_000.
    json.dumps(result, allow_nan=False)
    json.dumps(empty, allow_nan=False)


def test_last_signal_has_no_next_bar_and_does_not_force_a_trade():
    frame = bars([{}, {}])
    result = run_backtest(frame, [signal(frame, 1)])
    assert result["trades"] == []
    assert result["rejected_entries"][0]["reason"] == "no_next_bar"


@pytest.mark.parametrize("stop, target, reason", [
    (101., 120., "stop_not_below_entry"),
    (95., 100., "target_not_above_entry"),
    (float("nan"), 120., "invalid_stop_or_target"),
])
def test_invalid_actual_entry_levels_rejected(stop, target, reason):
    frame = bars([{}, {}])
    result = run_backtest(frame, [signal(frame, stop_loss=stop, take_profit=target)])
    assert result["rejected_entries"][0]["reason"] == reason
    json.dumps(result, allow_nan=False)


def test_splits_rejected_before_any_backtest_and_frame_not_mutated():
    frame = bars([{}, {}])
    original = frame.copy(deep=True)
    run_backtest(frame, [signal(frame)])
    pd.testing.assert_frame_equal(frame, original)
    frame.loc[1, "split_ratio"] = 2.
    with pytest.raises(ValueError, match="Stock splits are unsupported"):
        run_backtest(frame, [signal(frame)])


def test_multiple_symbols_cannot_share_independent_portfolio():
    frame = bars([{}, {}, {}])
    with pytest.raises(ValueError, match="single symbol"):
        run_backtest(frame, [signal(frame), signal(frame, 1, ticker="OTHER")])
