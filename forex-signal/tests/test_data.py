from datetime import datetime, timezone

import pytest

from forex_signal.data import DataError, parse_yahoo_chart


def payload():
    stamps = [int(datetime(2026, 1, 5, 14, minute, tzinfo=timezone.utc).timestamp()) for minute in (0, 15, 30)]
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": "EURUSD=X", "currency": "USD", "exchangeTimezoneName": "Europe/London"},
        "timestamp": stamps,
        "indicators": {"quote": [{"open": [1.1, 1.2, 1.1], "high": [1.2, 1.3, 1.2], "low": [1.0, 1.1, 1.0], "close": [1.15, 1.25, 1.15]}]},
    }]}}


def test_parser_excludes_current_interval_and_keeps_utc():
    now = datetime.fromtimestamp(1767624300, timezone.utc)  # 2026-01-05 14:45 UTC
    frame, metadata = parse_yahoo_chart(payload(), "EURUSD", interval="15m", now=now)
    assert len(frame) == 3
    assert str(frame["timestamp"].dt.tz) == "UTC"
    assert metadata["source_symbol"] == "EURUSD=X"


def test_parser_rejects_wrong_symbol_or_invalid_candle():
    source = payload()
    source["chart"]["result"][0]["meta"]["symbol"] = "GBPUSD=X"
    with pytest.raises(DataError, match="unexpected Yahoo symbol"):
        parse_yahoo_chart(source, "EURUSD", now=datetime(2026, 1, 5, 15, tzinfo=timezone.utc))
    source = payload()
    source["chart"]["result"][0]["indicators"]["quote"][0]["high"][0] = 0.9
    frame, metadata = parse_yahoo_chart(source, "EURUSD", now=datetime(2026, 1, 5, 15, tzinfo=timezone.utc))
    assert len(frame) == 2
    assert metadata["excluded_invalid_rows"] == 1
