from datetime import datetime, timezone

import pandas as pd

from forex_signal.backtest import ForexBacktestConfig, run_backtest


def bars(opens, highs, lows, closes=None):
    closes = closes or opens
    return pd.DataFrame({
        "timestamp": pd.date_range(datetime(2026, 1, 5, tzinfo=timezone.utc), periods=len(opens), freq="15min"),
        "open": opens, "high": highs, "low": lows, "close": closes,
    })


def signal(action="BUY", timestamp="2026-01-05T00:00:00+00:00", stop=99.0, target=105.0):
    return {"signal_id": "s1", "asset": "EURUSD", "action": action, "timestamp": timestamp,
            "suggested_sl": stop, "suggested_tp": target, "qualified": True}


def config(**overrides):
    base = dict(starting_equity=1000.0, risk_fraction=.1, contract_units=1.0,
                min_lot=1.0, lot_step=1.0, max_leverage=100.0,
                spread_price=0.0, slippage_bps=0.0, commission_per_lot=0.0,
                max_holding_bars=20)
    base.update(overrides)
    return ForexBacktestConfig(**base)


def test_enters_next_bar_and_takes_buy_target():
    frame = bars([100, 101, 103], [101, 106, 104], [99, 100, 102])
    result = run_backtest(frame, [signal()], config())
    assert result["metrics"]["closed_trades"] == 1
    trade = result["trades"][0]
    assert trade["entry_timestamp"] == frame.iloc[1].timestamp.isoformat()
    assert trade["exit_reason"] == "take_profit"
    assert trade["net_pnl"] == 200.0


def test_stop_has_priority_when_both_levels_touch():
    frame = bars([100, 100, 100], [101, 111, 101], [99, 94, 99])
    result = run_backtest(frame, [signal(stop=95, target=110)], config())
    trade = result["trades"][0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["fill_reason"] == "stop_first"


def test_short_trade_and_gap_stop():
    frame = bars([100, 100, 108], [101, 101, 109], [99, 99, 107])
    result = run_backtest(frame, [signal("SELL", stop=105, target=90)], config())
    assert result["trades"][0]["fill_reason"] == "gap_stop"
    assert result["trades"][0]["exit_reason"] == "stop_loss"


def test_gap_at_entry_rechecks_reward_risk():
    frame = bars([100, 104, 104], [101, 105, 105], [99, 103, 103])
    result = run_backtest(frame, [signal(stop=95, target=105)], config())
    assert result["metrics"]["closed_trades"] == 0
    assert result["rejected_entries"][0]["reason"] == "actual_reward_risk_below_minimum"


def test_final_position_is_marked_not_forced_closed():
    frame = bars([100, 101, 102], [101, 102, 103], [99, 100, 101])
    result = run_backtest(frame, [signal(stop=90, target=124)], config(max_holding_bars=20))
    assert result["metrics"]["closed_trades"] == 0
    assert result["metrics"]["open_positions"] == 1
    assert result["open_position"]["unrealized_pnl"] == 9.0


def test_spread_can_make_minimum_lot_or_risk_fail():
    frame = bars([100, 100.01, 100.01], [101, 100.02, 100.02], [99, 99.99, 99.99])
    result = run_backtest(frame, [signal(stop=99.99, target=100.03)], config(spread_price=.02, risk_fraction=.001))
    assert result["metrics"]["closed_trades"] == 0
    assert result["rejected_entries"][0]["reason"] in {"actual_reward_risk_below_minimum", "insufficient_equity_for_min_lot"}
