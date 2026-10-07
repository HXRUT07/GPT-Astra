from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import pytest

from forex_signal.strategy import ForexConfig, _atr, _in_session, _rsi, generate_signals


def bars(closes):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-10-05", periods=len(closes), freq="15min", tz="UTC"),
        "open": closes,
        "high": [value + 0.5 for value in closes],
        "low": [value - 0.5 for value in closes],
        "close": closes,
    })


def small_config(**overrides):
    return replace(ForexConfig(), fast_ema=2, slow_ema=3, trend_ema=4, atr_period=2, atr_ma_period=2, rsi_period=2, **overrides)


def test_indicators_use_wilder_rsi_and_true_range():
    assert _rsi([1.0] * 5, 2)[2:] == [50.0, 50.0, 50.0]
    frame = bars([10.0, 12.0, 11.0])
    assert _atr(frame, 2)[1] == pytest.approx(1.75)


def test_session_boundaries_and_friday_overnight():
    config = ForexConfig()
    assert _in_session(pd.Timestamp("2026-10-07 07:00:00+00:00"), config)  # 14:00 Bangkok
    assert _in_session(pd.Timestamp("2026-10-06 18:59:00+00:00"), config)  # 01:59 Bangkok
    assert not _in_session(pd.Timestamp("2026-10-07 06:59:00+00:00"), config)  # 13:59 Bangkok
    assert _in_session(pd.Timestamp("2026-10-09 18:00:00+00:00"), config)  # Saturday 01:00 Bangkok, Friday session continuation
    assert not _in_session(pd.Timestamp("2026-10-10 18:00:00+00:00"), config)  # Sunday 01:00 Bangkok


def test_signals_have_blueprint_payload_and_reject_outside_session():
    prices = [100.0] * 200 + [99.0, 99.5, 100.0, 101.0, 102.0]
    signal_rows = generate_signals(bars(prices), "XAUUSD", "M15", small_config())
    assert signal_rows
    assert all(signal["schema_version"] == 1 for signal in signal_rows)
    assert all(signal["session"] == "LONDON_NY_WINDOW" for signal in signal_rows)
    assert all("outside_session" in signal["rejection_reasons"] for signal in signal_rows)
    assert all(signal["reward_risk"] == pytest.approx(2.0) for signal in signal_rows)


def test_invalid_market_and_frame_are_rejected():
    with pytest.raises(ValueError, match="timeframe"):
        generate_signals(bars([100.0] * 10), "EURUSD", "D1", small_config())
    with pytest.raises(ValueError, match="timezone"):
        generate_signals(bars([100.0] * 10).assign(timestamp=lambda frame: frame.timestamp.dt.tz_localize(None)), "EURUSD", "M15", small_config())
    with pytest.raises(ValueError, match="asset"):
        generate_signals(bars([100.0] * 10), "EUR/USD", "M15", small_config())


def test_config_does_not_allow_unmet_two_to_one_target():
    with pytest.raises(ValueError, match="reward/risk"):
        ForexConfig(stop_atr_multiple=2.0, target_atr_multiple=3.0)
