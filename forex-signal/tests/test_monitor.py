from datetime import datetime, timezone
import json

import pandas as pd
import pytest

from forex_signal.monitor import MonitorConfig, PaperMonitor


def frame():
    return pd.DataFrame({
        "timestamp": pd.date_range(datetime(2026, 10, 7, 14, tzinfo=timezone.utc), periods=3, freq="15min"),
        "open": [1.1, 1.1, 1.1], "high": [1.2, 1.2, 1.2],
        "low": [1.0, 1.0, 1.0], "close": [1.1, 1.1, 1.1],
    })


def test_monitor_deduplicates_candle_signals(tmp_path, monkeypatch):
    candles = frame()
    signals = [{
        "signal_id": "s1", "asset": "EURUSD", "action": "BUY",
        "timestamp": candles.iloc[1].timestamp.isoformat(), "trigger_price": 1.1,
        "suggested_sl": 1.09, "suggested_tp": 1.12, "reward_risk": 2,
        "qualified": True, "rejection_reasons": [],
    }]
    monkeypatch.setattr("forex_signal.monitor.generate_signals", lambda *args: signals)

    def fetcher(*args, **kwargs):
        return candles, {"provider": "test", "rows": len(candles)}

    monitor = PaperMonitor(MonitorConfig(output_dir=tmp_path, poll_seconds=10, warm_start=False), fetcher=fetcher)
    first = monitor.run_once()
    second = monitor.run_once()
    assert first["signals_seen_this_poll"] == 1
    assert second["signals_seen_this_poll"] == 0
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 1
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["poll_count"] == 2
    assert state["signals_seen"] == 1


def test_monitor_warm_start_only_reviews_latest_trigger(tmp_path, monkeypatch):
    candles = frame()
    signals = [{
        "signal_id": f"s{i}", "asset": "EURUSD", "action": "BUY",
        "timestamp": candles.iloc[i].timestamp.isoformat(), "trigger_price": 1.1,
        "suggested_sl": 1.09, "suggested_tp": 1.12, "reward_risk": 2,
        "qualified": True, "rejection_reasons": [],
    } for i in (0, 2)]
    monkeypatch.setattr("forex_signal.monitor.generate_signals", lambda *args: signals)
    monitor = PaperMonitor(MonitorConfig(output_dir=tmp_path, poll_seconds=10), fetcher=lambda *args, **kwargs: (candles, {"provider": "test"}))
    summary = monitor.run_once()
    assert summary["warm_started"] is True
    assert summary["signals_seen_this_poll"] == 1
    assert json.loads((tmp_path / "events.jsonl").read_text().splitlines()[0])["signal"]["signal_id"] == "s2"


def test_monitor_rejects_too_fast_poll():
    with pytest.raises(ValueError, match="at least 10"):
        MonitorConfig(poll_seconds=1)
