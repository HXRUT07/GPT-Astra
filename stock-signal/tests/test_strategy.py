from dataclasses import replace
import json

import pandas as pd
import pytest

from stock_signal.strategy import StrategyConfig, _ema, _rsi, generate_signals


def bars(closes, *, highs=None, lows=None, volumes=None):
    count = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=count, freq="D", tz="UTC"),
        "open": closes,
        "high": highs if highs is not None else [price + 0.5 for price in closes],
        "low": lows if lows is not None else [price - 0.5 for price in closes],
        "close": closes,
        "volume": volumes if volumes is not None else [100.0] * count,
        "dividend": [0.0] * count,
        "split_ratio": [1.0] * count,
    })


def small_config(**overrides):
    return replace(StrategyConfig(), fast=1, slow=2, trend=3, rsi_period=2,
                   volume_window=2, breakout_window=2, support_window=2,
                   resistance_window=6, rsi_min=0, rsi_max=100, **overrides)


def rr_example(*, final_volume=200):
    return bars([35.0] * 6 + [36.0],
                highs=[38.6] + [35.5] * 5 + [36.5],
                lows=[34.5] * 7,
                volumes=[100.0] * 6 + [float(final_volume)])


def default_example():
    prices = [99.0 if index % 2 else 95.0 for index in range(200)]
    prices.extend([100.0 if index % 2 else 96.0 for index in range(21)])
    prices.append(101.0)
    frame = bars(prices)
    frame.loc[170, "high"] = 120.0
    frame.loc[len(frame) - 1, "volume"] = 500.0
    return frame


def test_recursive_ema_and_wilder_rsi_arithmetic_seeds():
    assert _ema([1., 2., 3., 4., 5.], 3) == [None, None, 2., 3., 4.]
    values = _rsi([1., 2., 3., 2., 4.], 3)
    assert values[:3] == [None, None, None]
    assert values[3] == pytest.approx(100 * 2 / 3)
    assert values[4] == pytest.approx(100 * 5 / 6)
    assert _rsi([1.] * 5, 3)[3:] == [50., 50.]
    assert _rsi([1., 2., 3., 4.], 3)[-1] == 100.
    assert _rsi([4., 3., 2., 1.], 3)[-1] == 0.


def test_default_warmup_and_qualified_record_schema():
    frame = default_example()
    assert generate_signals(frame.iloc[:199], "TEST.BK") == []
    signal = generate_signals(frame, "test.bk")[-1]
    assert signal["qualified"] is True
    assert signal["rejection_reasons"] == []
    assert signal["ticker"] == "TEST"
    assert signal["source_symbol"] == "TEST.BK"
    assert signal["schema_version"] == 1
    assert signal["market"] == "SET" and signal["timeframe"] == "1D"
    assert signal["strategy_name"] == "EMA_Trend_Breakout_V1"
    assert signal["breakout"] is True
    assert 50 <= signal["rsi_14"] <= 70
    assert signal["reward_risk"] >= 2 and signal["net_reward_risk"] >= 2
    assert signal["timestamp"] == frame.iloc[-1]["timestamp"].isoformat()
    json.dumps(signal, allow_nan=False)


def test_prefix_invariance_for_every_earlier_payload_and_id():
    prefix = default_example()
    future = bars([900., 2., 700., 4.])
    future["timestamp"] = pd.date_range(prefix.iloc[-1]["timestamp"] + pd.Timedelta(days=1),
                                         periods=4, tz="UTC")
    full = pd.concat([prefix, future], ignore_index=True)
    original = generate_signals(prefix, "TEST.BK")
    cutoff = prefix.iloc[-1]["timestamp"].isoformat()
    extended = [signal for signal in generate_signals(full, "TEST.BK")
                if signal["timestamp"] <= cutoff]
    assert extended == original
    assert len(original) > 0


def test_current_spike_excluded_from_high_low_volume_references():
    frame = rr_example(final_volume=10_000)
    frame.loc[6, "high"] = 1000.
    frame.loc[6, "low"] = 1.
    signal = generate_signals(frame, "TEST.BK", small_config())[-1]
    assert signal["breakout"] is True
    assert signal["prior_breakout_high"] == 35.5
    assert signal["prior_volume_mean"] == 100.
    assert signal["volume_multiple"] == 100.
    assert signal["support_level"] == 34.5
    assert signal["resistance_level"] == 38.6


def test_historic_target_rejects_documented_1_73_reward_risk():
    signal = generate_signals(rr_example(), "TEST.BK", small_config())[-1]
    assert signal["reward_risk"] == pytest.approx(2.6 / 1.5)
    assert signal["take_profit"] == 38.6
    assert signal["qualified"] is False
    assert "gross_reward_risk_below_minimum" in signal["rejection_reasons"]
    assert "net_reward_risk_below_minimum" in signal["rejection_reasons"]


def test_gross_two_to_one_still_rejected_after_costs():
    frame = rr_example()
    frame.loc[0, "high"] = 110.
    frame["open"] = [100.] * 6 + [101.]
    frame["close"] = [100.] * 6 + [101.]
    frame["high"] = [113.] + [100.5] * 5 + [101.5]
    frame["low"] = 97.
    # Entry101, stop97, target109 gives exactly2 gross, but less net.
    frame.loc[0, "high"] = 109.
    signal = generate_signals(frame, "TEST.BK", small_config())[-1]
    assert signal["reward_risk"] == 2.
    assert signal["net_reward_risk"] < 2.
    assert "net_reward_risk_below_minimum" in signal["rejection_reasons"]


def test_strict_volume_threshold_and_rsi_inclusive_bounds():
    signal = generate_signals(rr_example(final_volume=150), "TEST", small_config())[-1]
    assert "insufficient_volume" in signal["rejection_reasons"]
    frame = default_example()
    original = generate_signals(frame, "TEST")[-1]
    rsi = original["rsi_14"]
    at_boundary = replace(StrategyConfig(), rsi_min=rsi, rsi_max=rsi)
    assert "rsi_out_of_range" not in generate_signals(frame, "TEST", at_boundary)[-1]["rejection_reasons"]
    outside = replace(StrategyConfig(), rsi_min=rsi + .00001, rsi_max=100.)
    assert "rsi_out_of_range" in generate_signals(frame, "TEST", outside)[-1]["rejection_reasons"]


def test_invalid_historical_risk_levels_have_explicit_reasons():
    frame = rr_example()
    frame.loc[0, "high"] = 35.5
    signal = generate_signals(frame, "TEST", small_config())[-1]
    assert signal["take_profit"] == 35.5
    assert signal["reward_risk"] is None and signal["net_reward_risk"] is None
    assert "target_not_above_entry" in signal["rejection_reasons"]
    assert not signal["qualified"]


def test_signal_id_deterministic_and_config_sensitive():
    frame = rr_example()
    config = small_config()
    first = generate_signals(frame, "TEST.BK", config)[-1]
    assert first == generate_signals(frame.copy(), "test.bk", config)[-1]
    changed = generate_signals(frame, "TEST.BK", replace(config, slippage_bps=20.))[-1]
    assert changed["signal_id"] != first["signal_id"]
    assert changed["config_fingerprint"] != first["config_fingerprint"]


def test_split_data_rejected_before_indicators_and_frame_unchanged():
    frame = rr_example()
    original = frame.copy(deep=True)
    generate_signals(frame, "TEST", small_config())
    pd.testing.assert_frame_equal(frame, original)
    frame.loc[3, "split_ratio"] = 2.
    with pytest.raises(ValueError, match="Stock splits are unsupported"):
        generate_signals(frame, "TEST", small_config())


@pytest.mark.parametrize("overrides", [{"fast": 50}, {"volume_multiple": 0},
                                       {"rsi_min": 80, "rsi_max": 70},
                                       {"slippage_bps": 10_000}])
def test_invalid_config_rejected(overrides):
    with pytest.raises(ValueError):
        StrategyConfig(**overrides)
