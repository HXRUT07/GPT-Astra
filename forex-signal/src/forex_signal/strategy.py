"""Session-filtered FX and gold signals from completed OHLC bars.

The blueprint uses ATR instead of exchange volume because spot FX is OTC and
platform volume is usually tick volume. This module therefore requires OHLC,
does not use volume, and never sends orders or network requests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
import hashlib
import json
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd


SCHEMA_VERSION = 1
STRATEGY_NAME = "FX_EMA_ATR_SESSION_V1"
REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close")
_ASSET = re.compile(r"^[A-Z0-9]{3,15}$")


@dataclass(frozen=True)
class ForexConfig:
    fast_ema: int = 20
    slow_ema: int = 50
    trend_ema: int = 200
    atr_period: int = 14
    atr_ma_period: int = 20
    rsi_period: int = 14
    stop_atr_multiple: float = 1.5
    target_atr_multiple: float = 3.0
    min_reward_risk: float = 2.0
    buy_rsi_min: float = 52.0
    buy_rsi_max: float = 68.0
    sell_rsi_min: float = 32.0
    sell_rsi_max: float = 48.0
    session_start_minutes: int = 14 * 60
    session_end_minutes: int = 2 * 60
    session_timezone: str = "Asia/Bangkok"
    session_name: str = "LONDON_NY_WINDOW"

    def __post_init__(self) -> None:
        periods = ("fast_ema", "slow_ema", "trend_ema", "atr_period", "atr_ma_period", "rsi_period")
        for name in periods:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not self.fast_ema < self.slow_ema <= self.trend_ema:
            raise ValueError("EMA periods must satisfy fast_ema < slow_ema <= trend_ema")
        for name in ("stop_atr_multiple", "target_atr_multiple", "min_reward_risk"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.target_atr_multiple / self.stop_atr_multiple < self.min_reward_risk:
            raise ValueError("ATR target/stop multiples must meet the reward/risk gate")
        if not 0 <= self.buy_rsi_min <= self.buy_rsi_max <= 100:
            raise ValueError("buy RSI range is invalid")
        if not 0 <= self.sell_rsi_min <= self.sell_rsi_max <= 100:
            raise ValueError("sell RSI range is invalid")
        if not 0 <= self.session_start_minutes < 1440 or not 0 <= self.session_end_minutes < 1440:
            raise ValueError("session minutes must be in [0, 1440)")
        try:
            ZoneInfo(self.session_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown session timezone: {self.session_timezone}") from exc
        if not self.session_name.strip():
            raise ValueError("session_name must be nonempty")


def _validated_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {sorted(missing)}")
    result = frame.loc[:, list(REQUIRED_COLUMNS)].copy().reset_index(drop=True)
    timestamps = [pd.Timestamp(value) for value in result["timestamp"]]
    if any(pd.isna(value) or value.tzinfo is None for value in timestamps):
        raise ValueError("timestamps must be timezone-aware")
    result["timestamp"] = pd.to_datetime(timestamps, utc=True)
    if result["timestamp"].duplicated().any() or not result["timestamp"].is_monotonic_increasing:
        raise ValueError("timestamps must be unique and increasing")
    for name in REQUIRED_COLUMNS[1:]:
        result[name] = pd.to_numeric(result[name], errors="raise").astype(float)
        if not result[name].map(math.isfinite).all():
            raise ValueError(f"{name} must contain finite numbers")
    if (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (result["low"] > result[["open", "close"]].min(axis=1)).any():
        raise ValueError("low is above an open or close")
    if (result["high"] < result[["open", "close"]].max(axis=1)).any() or (result["high"] < result["low"]).any():
        raise ValueError("high/low range is inconsistent")
    return result


def _ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if not values:
        return result
    current = values[0]
    result[0] = current
    alpha = 2.0 / (period + 1.0)
    for index in range(1, len(values)):
        current += alpha * (values[index] - current)
        result[index] = current
    return result


def _rma(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    current = math.fsum(values[:period]) / period
    result[period - 1] = current
    for index in range(period, len(values)):
        current = (current * (period - 1) + values[index]) / period
        result[index] = current
    return result


def _rsi(values: list[float], period: int) -> list[float | None]:
    if len(values) <= period:
        return [None] * len(values)
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = _rma([max(change, 0.0) for change in changes], period)
    losses = _rma([max(-change, 0.0) for change in changes], period)
    result: list[float | None] = [None] * len(values)
    for index in range(period, len(values)):
        gain, loss = gains[index - 1], losses[index - 1]
        if gain is None or loss is None:
            continue
        result[index] = 50.0 if loss == 0 and gain == 0 else (100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss))
    return result


def _atr(frame: pd.DataFrame, period: int) -> list[float | None]:
    highs, lows, closes = (frame[name].tolist() for name in ("high", "low", "close"))
    true_ranges = []
    for index, (high, low) in enumerate(zip(highs, lows)):
        true_ranges.append(high - low if index == 0 else max(high - low, abs(high - closes[index - 1]), abs(low - closes[index - 1])))
    return _rma(true_ranges, period)


def _in_session(timestamp: pd.Timestamp, config: ForexConfig) -> bool:
    local = timestamp.tz_convert(ZoneInfo(config.session_timezone))
    minutes = local.hour * 60 + local.minute
    start, end = config.session_start_minutes, config.session_end_minutes
    if start <= end:
        return local.weekday() < 5 and start <= minutes < end
    if minutes >= start:
        return local.weekday() < 5
    previous_day = local.date() - timedelta(days=1)
    return previous_day.weekday() < 5 and minutes < end


def generate_signals(
    frame: pd.DataFrame,
    asset: str,
    timeframe: str,
    config: ForexConfig = ForexConfig(),
) -> list[dict]:
    """Return all EMA-cross trigger bars with qualification reasons.

    ``timestamp`` is the supplied completed-bar timestamp. It is not a broker
    fill time. Session filtering uses the configured fixed timezone; London and
    New York daylight-saving changes are not inferred by this first-stage rule.
    """
    bars = _validated_frame(frame)
    asset = asset.strip().upper()
    timeframe = timeframe.strip().upper()
    if not _ASSET.fullmatch(asset):
        raise ValueError("asset must be a simple uppercase symbol such as EURUSD or XAUUSD")
    if timeframe not in {"M15", "M30", "H1"}:
        raise ValueError("timeframe must be M15, M30 or H1")
    closes = bars["close"].tolist()
    fast = _ema(closes, config.fast_ema)
    slow = _ema(closes, config.slow_ema)
    trend = _ema(closes, config.trend_ema)
    atr = _atr(bars, config.atr_period)
    atr_average = pd.Series(atr, dtype="float64").rolling(config.atr_ma_period).mean().tolist()
    rsi = _rsi(closes, config.rsi_period)
    fingerprint = hashlib.sha256(json.dumps(asdict(config), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    signals: list[dict] = []
    for index in range(1, len(bars)):
        if None in (fast[index], fast[index - 1], slow[index], slow[index - 1], trend[index], atr[index], atr_average[index], rsi[index]):
            continue
        crossed_up = fast[index] > slow[index] and fast[index - 1] <= slow[index - 1]
        crossed_down = fast[index] < slow[index] and fast[index - 1] >= slow[index - 1]
        if not (crossed_up or crossed_down):
            continue
        action = "BUY" if crossed_up else "SELL"
        close = closes[index]
        volatility_ok = atr[index] > atr_average[index]
        trend_ok = close > trend[index] if action == "BUY" else close < trend[index]
        rsi_ok = (config.buy_rsi_min <= rsi[index] <= config.buy_rsi_max) if action == "BUY" else (config.sell_rsi_min <= rsi[index] <= config.sell_rsi_max)
        session_ok = _in_session(bars.loc[index, "timestamp"], config)
        stop = close - config.stop_atr_multiple * atr[index] if action == "BUY" else close + config.stop_atr_multiple * atr[index]
        target = close + config.target_atr_multiple * atr[index] if action == "BUY" else close - config.target_atr_multiple * atr[index]
        reasons = []
        if not trend_ok:
            reasons.append("trend_mismatch")
        if not volatility_ok:
            reasons.append("atr_not_expanding")
        if not rsi_ok:
            reasons.append("rsi_out_of_range")
        if not session_ok:
            reasons.append("outside_session")
        gross_rr = abs(target - close) / abs(close - stop) if close != stop else None
        if gross_rr is None or gross_rr < config.min_reward_risk:
            reasons.append("reward_risk_below_minimum")
        timestamp = bars.loc[index, "timestamp"].isoformat()
        identity = {"schema_version": SCHEMA_VERSION, "strategy_name": STRATEGY_NAME, "asset": asset, "timeframe": timeframe, "action": action, "timestamp": timestamp, "config_fingerprint": fingerprint}
        signals.append({
            "schema_version": SCHEMA_VERSION,
            "signal_id": hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "config_fingerprint": fingerprint,
            "asset": asset,
            "action": action,
            "timeframe": timeframe,
            "session": config.session_name,
            "strategy_name": STRATEGY_NAME,
            "timestamp": timestamp,
            "trigger_price": close,
            "atr_14": float(atr[index]),
            "suggested_sl": stop,
            "suggested_tp": target,
            "rsi_14": float(rsi[index]),
            "reward_risk": gross_rr,
            "session_timezone": config.session_timezone,
            "qualified": not reasons,
            "rejection_reasons": reasons,
            "ema_cross": "UP" if crossed_up else "DOWN",
        })
    return signals
