"""Exploratory daily Yahoo chart data, with explicit quality and provenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

WATCHLIST = ("KBANK.BK", "SCB.BK", "PTT.BK", "ADVANC.BK", "CPALL.BK")
COLUMNS = ("timestamp", "open", "high", "low", "close", "volume", "dividend", "split_ratio")
BANGKOK = ZoneInfo("Asia/Bangkok")


class DataError(ValueError):
    """The source cannot provide a trustworthy candle series."""


@dataclass
class PriceData:
    frame: pd.DataFrame
    metadata: dict


def _number(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise DataError(f"{name}: boolean is not a price")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DataError(f"{name}: missing or nonnumeric value") from exc
    if not math.isfinite(result):
        raise DataError(f"{name}: nonfinite value")
    return result


def validate_frame(frame: pd.DataFrame) -> None:
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise DataError(f"missing columns: {sorted(missing)}")
    if frame.empty:
        raise DataError("no complete daily candles")
    source_timestamps = [pd.Timestamp(value) for value in frame["timestamp"]]
    if any(pd.isna(value) or value.tzinfo is None for value in source_timestamps):
        raise DataError("timestamps must be timezone-aware")
    timestamps = pd.to_datetime(source_timestamps, utc=True, errors="raise")
    if timestamps.isna().any() or timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise DataError("timestamps must be unique and increasing")
    if pd.Series(timestamps.tz_convert(BANGKOK).date).duplicated().any():
        raise DataError("more than one candle for a daily Thai session")
    for row in frame.itertuples(index=False):
        values = {name: _number(getattr(row, name), name) for name in COLUMNS[1:]}
        if min(values[name] for name in ("open", "high", "low", "close")) <= 0:
            raise DataError("OHLC prices must be positive")
        if not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]:
            raise DataError("OHLC prices are outside candle range")
        if values["volume"] < 0 or values["dividend"] < 0 or values["split_ratio"] <= 0:
            raise DataError("invalid volume or corporate action")


def parse_chart(payload: dict, symbol: str, as_of: date | None = None) -> PriceData:
    """Keep sessions strictly before as_of (today in Bangkok by default).

    This intentionally excludes today's bar even after market close. Timestamps
    are source candle labels, not the time an alert was generated.
    """
    cutoff = as_of or datetime.now(BANGKOK).date()
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise DataError(f"provider error: {chart['error'].get('description', 'unknown')}")
    results = chart.get("result") or []
    if not results:
        raise DataError("empty chart response")
    source = results[0]
    meta = source.get("meta", {})
    if meta.get("symbol", "").upper() != symbol.upper():
        raise DataError("provider returned a different symbol")
    if meta.get("currency") != "THB" or meta.get("exchangeTimezoneName") != "Asia/Bangkok":
        raise DataError("expected a Thai baht series in Asia/Bangkok")
    timestamps = source.get("timestamp") or []
    quotes = source.get("indicators", {}).get("quote") or []
    if not quotes or not timestamps:
        raise DataError("missing daily price history")
    quote = quotes[0]
    for name in COLUMNS[1:6]:
        if len(quote.get(name, [])) != len(timestamps):
            raise DataError(f"misaligned {name} history")

    dividends: dict[date, float] = {}
    splits: dict[date, float] = {}
    events = source.get("events", {})
    for event in events.get("dividends", {}).values():
        session = datetime.fromtimestamp(event["date"], BANGKOK).date()
        amount = _number(event.get("amount"), "dividend")
        if amount < 0:
            raise DataError("negative dividend")
        dividends[session] = dividends.get(session, 0.0) + amount
    for event in events.get("splits", {}).values():
        session = datetime.fromtimestamp(event["date"], BANGKOK).date()
        numerator = _number(event.get("numerator"), "split numerator")
        denominator = _number(event.get("denominator"), "split denominator")
        if min(numerator, denominator) <= 0:
            raise DataError("invalid split ratio")
        splits[session] = splits.get(session, 1.0) * numerator / denominator

    rows = []
    excluded_current_or_future = 0
    invalid = []
    for index, stamp in enumerate(timestamps):
        timestamp = datetime.fromtimestamp(stamp, timezone.utc)
        session = timestamp.astimezone(BANGKOK).date()
        if session >= cutoff:
            excluded_current_or_future += 1
            continue
        try:
            values = {name: _number(quote[name][index], name) for name in COLUMNS[1:6]}
        except DataError as exc:
            invalid.append({"date": session.isoformat(), "reason": str(exc)})
            continue
        if (
            values["low"] > min(values["open"], values["close"])
            or values["high"] < max(values["open"], values["close"])
            or values["high"] < values["low"]
            or values["volume"] < 0
        ):
            invalid.append({"date": session.isoformat(), "reason": "OHLCV range or volume is invalid"})
            continue
        rows.append({"timestamp": timestamp, **values,
                     "dividend": dividends.get(session, 0.0), "split_ratio": splits.get(session, 1.0)})
    frame = pd.DataFrame(rows, columns=COLUMNS)
    validate_frame(frame)
    actual_sessions = set(frame.timestamp.dt.tz_convert(BANGKOK).dt.date)
    missing_action_sessions = sorted(str(day) for day in (set(dividends) | set(splits))
                                    if day < cutoff and day not in actual_sessions)
    if missing_action_sessions:
        raise DataError(f"corporate action without a valid candle: {missing_action_sessions}")
    gaps = frame.timestamp.diff().dt.total_seconds().div(86400).dropna()
    info = {
        "symbol": symbol.upper(), "provider": "Yahoo Finance chart (exploratory)",
        "currency": meta["currency"], "exchange": meta.get("exchangeName"),
        "timezone": meta["exchangeTimezoneName"], "price_basis": "raw unadjusted OHLC",
        "interval": "1d", "cutoff_exclusive_bangkok": cutoff.isoformat(),
        "rows": len(frame), "source_rows": len(timestamps),
        "first_session": frame.timestamp.iloc[0].astimezone(BANGKOK).date().isoformat(),
        "last_session": frame.timestamp.iloc[-1].astimezone(BANGKOK).date().isoformat(),
        "excluded_current_or_future_rows": excluded_current_or_future,
        "excluded_missing_rows": len(invalid), "missing_row_details": invalid,
        "dividend_events": int((frame.dividend > 0).sum()),
        "split_events": int((frame.split_ratio != 1).sum()),
        "largest_calendar_gap_days": float(gaps.max()) if len(gaps) else 0,
        "calendar_completeness": "not verified against official SET session calendar",
        "fundamentals_news_earnings": "not verified; not supplied by this price probe",
        "production_data_license": "not verified",
    }
    return PriceData(frame, info)


def fetch_prices(symbol: str, *, as_of: date | None = None, client: httpx.Client | None = None) -> tuple[PriceData, dict]:
    symbol = symbol.upper()
    if not symbol.endswith(".BK") or not symbol[:-3].replace("-", "").isalnum():
        raise DataError("use a Yahoo SET symbol such as KBANK.BK")
    owns_client = client is None
    active_client = client or httpx.Client(timeout=25.0, headers={"User-Agent": "GPT-Astra-Research/0.1"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        for attempt in range(3):
            try:
                response = active_client.get(url, params={"range": "5y", "interval": "1d", "events": "div,splits"})
                response.raise_for_status()
                payload = response.json()
                result = parse_chart(payload, symbol, as_of)
                result.metadata.update({"retrieved_at": datetime.now(timezone.utc).isoformat(),
                                        "source_url": str(response.url),
                                        "response_sha256": hashlib.sha256(response.content).hexdigest()})
                return result, payload
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if attempt == 2 or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in (429, 500, 502, 503, 504)):
                    raise
                time.sleep(0.5 * (attempt + 1))
    finally:
        if owns_client:
            active_client.close()
    raise DataError("could not retrieve history")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def save_prices(result: PriceData, payload: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    symbol = result.metadata["symbol"]
    csv_path = directory / f"{symbol}.csv"
    result.frame.to_csv(csv_path, index=False)
    result.metadata["csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    write_json(directory / f"{symbol}.metadata.json", result.metadata)
    write_json(directory / f"{symbol}.raw.json", payload)


def load_prices(symbol: str, directory: Path) -> PriceData:
    csv_path = directory / f"{symbol}.csv"
    metadata = json.loads((directory / f"{symbol}.metadata.json").read_text(encoding="utf-8"))
    if hashlib.sha256(csv_path.read_bytes()).hexdigest() != metadata.get("csv_sha256"):
        raise DataError("cached CSV checksum mismatch; fetch again")
    if metadata.get("symbol") != symbol:
        raise DataError("cached symbol mismatch")
    frame = pd.read_csv(csv_path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    validate_frame(frame)
    return PriceData(frame, metadata)
