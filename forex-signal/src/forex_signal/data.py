"""Public exploratory intraday data download for the Forex prototype."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .strategy import REQUIRED_COLUMNS


class DataError(ValueError):
    """The public response cannot be used as a candle series."""


def _number(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DataError(f"{name} is missing or nonnumeric") from exc
    if not math.isfinite(number):
        raise DataError(f"{name} is nonfinite")
    return number


def _validate(frame: pd.DataFrame) -> None:
    missing = set(REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise DataError(f"missing columns: {sorted(missing)}")
    if frame.empty:
        raise DataError("no complete candles")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise DataError("timestamps must be unique and increasing")
    for name in REQUIRED_COLUMNS[1:]:
        values = pd.to_numeric(frame[name], errors="raise")
        if not values.map(math.isfinite).all():
            raise DataError(f"{name} contains nonfinite values")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise DataError("OHLC prices must be positive")
    if (frame["low"] > frame[["open", "close"]].min(axis=1)).any() or (frame["high"] < frame[["open", "close"]].max(axis=1)).any():
        raise DataError("OHLC range is inconsistent")


def parse_yahoo_chart(payload: dict, asset: str, *, interval: str = "15m", now: datetime | None = None) -> tuple[pd.DataFrame, dict]:
    """Parse Yahoo chart JSON and conservatively exclude the current candle."""
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise DataError(str(chart["error"].get("description", "Yahoo chart error")))
    result = (chart.get("result") or [None])[0]
    if not result:
        raise DataError("Yahoo returned no result")
    meta = result.get("meta", {})
    expected_symbol = f"{asset.upper()}=X"
    if meta.get("symbol", "").upper() != expected_symbol:
        raise DataError(f"unexpected Yahoo symbol: {meta.get('symbol')}")
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [None])[0]
    if not quote or not timestamps:
        raise DataError("Yahoo returned no intraday candles")
    for name in ("open", "high", "low", "close"):
        if len(quote.get(name, [])) != len(timestamps):
            raise DataError(f"Yahoo {name} array is misaligned")
    interval_minutes = int(interval.rstrip("m")) if interval.endswith("m") else (60 if interval == "1h" else 0)
    if interval_minutes <= 0:
        raise DataError("only minute intervals such as 15m are supported")
    current = now or datetime.now(timezone.utc)
    current_floor = int(current.timestamp() // (interval_minutes * 60)) * interval_minutes * 60
    rows = []
    excluded_incomplete = 0
    excluded_invalid = []
    for index, stamp in enumerate(timestamps):
        if int(stamp) >= current_floor:
            excluded_incomplete += 1
            continue
        try:
            values = {name: _number(quote[name][index], name) for name in REQUIRED_COLUMNS[1:]}
            if values["low"] > min(values["open"], values["close"]) or values["high"] < max(values["open"], values["close"]) or values["high"] < values["low"]:
                raise DataError("OHLC range is inconsistent")
        except DataError as exc:
            excluded_invalid.append({"timestamp": datetime.fromtimestamp(stamp, timezone.utc).isoformat(), "reason": str(exc)})
            continue
        rows.append({"timestamp": datetime.fromtimestamp(stamp, timezone.utc), **values})
    frame = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
    _validate(frame)
    metadata = {
        "asset": asset.upper(), "provider": "Yahoo Finance chart (public exploratory feed)",
        "source_symbol": expected_symbol, "interval": interval,
        "provider_timezone": meta.get("exchangeTimezoneName"), "currency": meta.get("currency"),
        "retrieved_at": current.isoformat(), "rows": len(frame), "source_rows": len(timestamps),
        "excluded_incomplete_or_future_rows": excluded_incomplete, "excluded_invalid_rows": len(excluded_invalid),
        "invalid_row_details": excluded_invalid, "data_basis": "provider OHLC; no consolidated FX volume",
        "broker_equivalence": "not established; broker spread, liquidity and timestamps may differ",
        "maximum_history_note": "Yahoo intraday retention depends on interval and is not a 1-2 year broker archive",
    }
    return frame, metadata


def fetch_yahoo_intraday(asset: str = "EURUSD", *, interval: str = "15m", range_: str = "60d", timeout: float = 30.0) -> tuple[pd.DataFrame, dict]:
    asset = asset.strip().upper()
    if not asset.isalnum() or len(asset) < 6:
        raise DataError("asset must be a symbol such as EURUSD")
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + f"{asset}=X"
    query = urlencode({"range": range_, "interval": interval, "events": "div,splits"})
    request = Request(f"{url}?{query}", headers={"User-Agent": "GPT-Astra-Research/0.1"})
    with urlopen(request, timeout=timeout) as response:
        content = response.read()
    frame, metadata = parse_yahoo_chart(json.loads(content), asset, interval=interval)
    metadata["source_url"] = f"{url}?{query}"
    metadata["response_sha256"] = hashlib.sha256(content).hexdigest()
    return frame, metadata


def save_intraday(frame: pd.DataFrame, metadata: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    metadata = dict(metadata)
    metadata["csv_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
