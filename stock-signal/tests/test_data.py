from copy import deepcopy
from datetime import date, datetime, timezone
import json

import httpx
import pandas as pd
import pytest

from stock_signal.data import DataError, fetch_prices, load_prices, parse_chart, save_prices, validate_frame


def payload():
    stamps = [int(datetime(2026, 10, day, 3, tzinfo=timezone.utc).timestamp()) for day in (2, 5, 6, 7)]
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": "KBANK.BK", "currency": "THB", "exchangeTimezoneName": "Asia/Bangkok", "exchangeName": "SET"},
        "timestamp": stamps,
        "indicators": {"quote": [{"open": [100] * 4, "high": [103] * 4,
                                    "low": [99] * 4, "close": [102] * 4, "volume": [1000] * 4}]},
        "events": {"dividends": {"event": {"date": stamps[1], "amount": 3.0}}},
    }]}}


def test_excludes_current_bar_and_retains_raw_prices_dividends():
    result = parse_chart(payload(), "KBANK.BK", date(2026, 10, 7))
    assert len(result.frame) == 3
    assert result.frame.close.tolist() == [102, 102, 102]
    assert result.frame.dividend.tolist() == [0, 3, 0]
    assert result.metadata["excluded_current_or_future_rows"] == 1
    assert result.metadata["last_session"] == "2026-10-06"
    assert "not verified" in result.metadata["calendar_completeness"]


def test_missing_candle_is_counted_without_filling():
    source = payload()
    source["chart"]["result"][0]["indicators"]["quote"][0]["close"][0] = None
    result = parse_chart(source, "KBANK.BK", date(2026, 10, 7))
    assert len(result.frame) == 2
    assert result.metadata["excluded_missing_rows"] == 1
    assert result.metadata["missing_row_details"][0]["date"] == "2026-10-02"


@pytest.mark.parametrize("mutation", ["currency", "symbol", "misaligned", "duplicate"])
def test_bad_source_is_rejected(mutation):
    source = payload()
    chart = source["chart"]["result"][0]
    if mutation == "currency":
        chart["meta"]["currency"] = "USD"
    elif mutation == "symbol":
        chart["meta"]["symbol"] = "SCB.BK"
    elif mutation == "misaligned":
        chart["indicators"]["quote"][0]["open"].pop()
    elif mutation == "range":
        chart["indicators"]["quote"][0]["high"][0] = 98
    elif mutation == "duplicate":
        chart["timestamp"][1] = chart["timestamp"][0]
    with pytest.raises(DataError):
        parse_chart(source, "KBANK.BK", date(2026, 10, 7))


def test_bad_ohlc_is_excluded_and_reported():
    source = payload()
    source["chart"]["result"][0]["indicators"]["quote"][0]["high"][0] = 98
    result = parse_chart(source, "KBANK.BK", date(2026, 10, 7))
    assert len(result.frame) == 2
    assert result.metadata["excluded_missing_rows"] == 1
    assert result.metadata["missing_row_details"][0]["reason"].startswith("OHLCV")


def test_action_on_missing_candle_cannot_disappear():
    source = payload()
    source["chart"]["result"][0]["indicators"]["quote"][0]["close"][1] = None
    with pytest.raises(DataError, match="corporate action"):
        parse_chart(source, "KBANK.BK", date(2026, 10, 7))


def test_split_record_retained_for_engine_to_reject():
    source = payload()
    chart = source["chart"]["result"][0]
    chart["events"]["splits"] = {"event": {"date": chart["timestamp"][2], "numerator": 2, "denominator": 1}}
    result = parse_chart(source, "KBANK.BK", date(2026, 10, 7))
    assert result.frame.split_ratio.tolist() == [1, 1, 2]
    assert result.metadata["split_events"] == 1


def test_saved_cache_roundtrip_and_tampering(tmp_path):
    raw = payload()
    original = parse_chart(raw, "KBANK.BK", date(2026, 10, 7))
    save_prices(original, raw, tmp_path)
    restored = load_prices("KBANK.BK", tmp_path)
    pd.testing.assert_frame_equal(original.frame, restored.frame, check_dtype=False)
    csv = tmp_path / "KBANK.BK.csv"
    csv.write_text(csv.read_text().replace("102.0", "101.0"))
    with pytest.raises(DataError, match="checksum"):
        load_prices("KBANK.BK", tmp_path)


def test_http_fetch_without_network():
    def handler(request):
        assert request.url.params["events"] == "div,splits"
        return httpx.Response(200, json=payload())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result, raw = fetch_prices("KBANK.BK", as_of=date(2026, 10, 7), client=client)
    assert result.metadata["response_sha256"]
    assert result.metadata["retrieved_at"]
    assert raw == payload()


def test_naive_daily_timestamps_rejected():
    result = parse_chart(payload(), "KBANK.BK", date(2026, 10, 7))
    result.frame.timestamp = result.frame.timestamp.dt.tz_localize(None)
    with pytest.raises(DataError, match="timezone-aware"):
        validate_frame(result.frame)
