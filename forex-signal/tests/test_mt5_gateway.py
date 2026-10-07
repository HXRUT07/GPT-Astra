from datetime import datetime, timezone
import json

import pytest

from forex_signal.mt5_gateway import CandleStore, GatewayError, validate_payload


def payload(**overrides):
    value = {
        "symbol": "EURUSD", "timeframe": "M15",
        "timestamp_epoch": int(datetime(2026, 10, 7, 14, tzinfo=timezone.utc).timestamp()),
        "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15,
        "tick_volume": 100, "bid": 1.1499, "ask": 1.1501,
        "digits": 5, "point": 0.00001, "closed": True,
    }
    value.update(overrides)
    return value


def test_payload_normalizes_epoch_and_spread():
    normalized = validate_payload(payload())
    assert normalized["timestamp"] == "2026-10-07T14:00:00+00:00"
    assert normalized["source"] == "FBS_MT5"
    assert normalized["spread"] == pytest.approx(0.0002)


@pytest.mark.parametrize("change", [{"closed": False}, {"timeframe": "TICK"}, {"ask": 1.0}, {"high": 0.9}])
def test_invalid_payload_is_rejected(change):
    with pytest.raises(GatewayError):
        validate_payload(payload(**change))


def test_store_deduplicates_same_candle(tmp_path):
    store = CandleStore(tmp_path / "candles.sqlite3")
    normalized = validate_payload(payload())
    assert store.insert(normalized) is True
    assert store.insert(normalized) is False
    rows = store.export("EURUSD", "M15")
    assert len(rows) == 1
    assert rows[0]["close"] == 1.15


def test_timezone_is_required_for_iso_timestamp():
    with pytest.raises(GatewayError, match="timezone"):
        validate_payload(payload(timestamp_epoch=None, timestamp="2026-10-07T14:00:00"))
