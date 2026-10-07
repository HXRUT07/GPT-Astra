"""Local, orderless HTTP gateway for the FBS MT5 candle bridge."""

from __future__ import annotations

from datetime import datetime, timezone
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import math
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Mapping


SYMBOL_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
TIMEFRAMES = {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}


class GatewayError(ValueError):
    """Payload or gateway configuration is invalid."""


def _number(value: object, label: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GatewayError(f"{label} must be numeric") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise GatewayError(f"{label} is invalid")
    return result


def _timestamp(payload: Mapping[str, object]) -> str:
    if payload.get("timestamp_epoch") is not None:
        try:
            value = datetime.fromtimestamp(float(payload["timestamp_epoch"]), timezone.utc)
        except (TypeError, ValueError, OverflowError) as exc:
            raise GatewayError("timestamp_epoch is invalid") from exc
    else:
        raw = payload.get("timestamp")
        if not isinstance(raw, str):
            raise GatewayError("timestamp or timestamp_epoch is required")
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise GatewayError("timestamp must be ISO-8601") from exc
        if value.tzinfo is None:
            raise GatewayError("timestamp must include a timezone")
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def validate_payload(payload: Mapping[str, object]) -> dict:
    if payload.get("closed") is not True:
        raise GatewayError("only completed candles are accepted")
    symbol = str(payload.get("symbol", ""))
    timeframe = str(payload.get("timeframe", ""))
    if not SYMBOL_RE.fullmatch(symbol) or timeframe not in TIMEFRAMES:
        raise GatewayError("symbol or timeframe is invalid")
    values = {name: _number(payload.get(name), name, positive=True) for name in ("open", "high", "low", "close")}
    if values["low"] > min(values["open"], values["close"]) or values["high"] < max(values["open"], values["close"]) or values["high"] < values["low"]:
        raise GatewayError("OHLC range is inconsistent")
    volume = _number(payload.get("tick_volume", 0), "tick_volume")
    if volume < 0:
        raise GatewayError("tick_volume cannot be negative")
    bid = payload.get("bid")
    ask = payload.get("ask")
    if bid is not None:
        bid = _number(bid, "bid", positive=True)
    if ask is not None:
        ask = _number(ask, "ask", positive=True)
    if bid is not None and ask is not None and ask < bid:
        raise GatewayError("ask cannot be below bid")
    return {
        "symbol": symbol, "timeframe": timeframe, "timestamp": _timestamp(payload),
        **values, "tick_volume": volume, "bid": bid, "ask": ask,
        "spread": _number(payload.get("spread", (ask - bid) if bid is not None and ask is not None else 0), "spread"),
        "digits": int(payload.get("digits", 0)), "point": _number(payload.get("point", 0), "point"),
        "source": "FBS_MT5", "received_at": datetime.now(timezone.utc).isoformat(),
    }


class CandleStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS candles (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload TEXT NOT NULL,
                received_at TEXT NOT NULL,
                UNIQUE(symbol, timeframe, timestamp)
            )""")
            connection.commit()

    def insert(self, payload: dict) -> bool:
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO candles(symbol,timeframe,timestamp,payload,received_at) VALUES(?,?,?,?,?)",
                (payload["symbol"], payload["timeframe"], payload["timestamp"], json.dumps(payload, ensure_ascii=False), payload["received_at"]),
            )
            connection.commit()
            return cursor.rowcount == 1

    def export(self, symbol: str, timeframe: str) -> list[dict]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT payload FROM candles WHERE symbol=? AND timeframe=? ORDER BY timestamp", (symbol, timeframe)).fetchall()
        return [json.loads(row[0]) for row in rows]


def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def make_handler(store: CandleStore, token: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                _json_response(self, 200, {"ok": True, "service": "fbs-mt5-candle-gateway", "orders_enabled": False})
            else:
                _json_response(self, 404, {"error": "not_found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/v1/mt5/candle":
                _json_response(self, 404, {"error": "not_found"})
                return
            supplied = self.headers.get("Authorization", "")
            expected = f"Bearer {token}"
            if not hmac.compare_digest(supplied, expected):
                _json_response(self, 401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 32_768:
                    raise GatewayError("body size is invalid")
                payload = json.loads(self.rfile.read(length))
                normalized = validate_payload(payload)
                inserted = store.insert(normalized)
                _json_response(self, 200, {"accepted": True, "duplicate": not inserted, "orders_enabled": False})
            except (GatewayError, json.JSONDecodeError) as exc:
                _json_response(self, 400, {"error": str(exc)})
            except Exception:
                _json_response(self, 500, {"error": "storage_failure"})

        def log_message(self, format, *args):  # noqa: A002
            return

    return Handler


def run_server(host: str, port: int, db: Path, token: str) -> None:
    if not token or len(token) < 16:
        raise GatewayError("MT5_INGEST_TOKEN must be at least 16 characters")
    store = CandleStore(db)
    server = ThreadingHTTPServer((host, port), make_handler(store, token))
    print(f"MT5 candle gateway listening on http://{host}:{port}; orders disabled")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
