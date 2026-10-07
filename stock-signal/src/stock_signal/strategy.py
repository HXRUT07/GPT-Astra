"""Deterministic end-of-day signals on raw, unadjusted daily OHLCV bars.

Every rolling reference excludes the signal bar. Indicators use arithmetic-mean
seeds followed by recursive EMA/Wilder updates, so adding future bars cannot
change an earlier signal. Splits are deliberately unsupported until as-of price
adjustment is implemented; adjusted-close data must not be substituted for close.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math

import pandas as pd


SCHEMA_VERSION = 1
STRATEGY_NAME = "EMA_Trend_Breakout_V1"


@dataclass(frozen=True)
class StrategyConfig:
    fast: int = 20
    slow: int = 50
    trend: int = 200
    rsi_period: int = 14
    volume_window: int = 20
    breakout_window: int = 20
    support_window: int = 20
    resistance_window: int = 60
    volume_multiple: float = 1.5
    rsi_min: float = 50.0
    rsi_max: float = 70.0
    min_reward_risk: float = 2.0
    commission_rate: float = 0.001
    slippage_bps: float = 10.0

    def __post_init__(self) -> None:
        for name in (
            "fast", "slow", "trend", "rsi_period", "volume_window",
            "breakout_window", "support_window", "resistance_window",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not self.fast < self.slow <= self.trend:
            raise ValueError("EMA periods must satisfy fast < slow <= trend")
        for name in ("volume_multiple", "min_reward_risk"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not 0 <= self.rsi_min <= self.rsi_max <= 100:
            raise ValueError("RSI bounds must satisfy 0 <= rsi_min <= rsi_max <= 100")
        _validate_costs(self.commission_rate, self.slippage_bps)


def _validate_costs(commission_rate: float, slippage_bps: float) -> None:
    if not math.isfinite(commission_rate) or not 0 <= commission_rate < 1:
        raise ValueError("commission_rate must be finite and in [0, 1)")
    if not math.isfinite(slippage_bps) or not 0 <= slippage_bps < 10_000:
        raise ValueError("slippage_bps must be finite and in [0, 10000)")


def _validated_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate direct API calls too, without mutating the caller's frame."""
    required = ("timestamp", "open", "high", "low", "close", "volume")
    missing = set(required).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(sorted(missing))}")
    result = frame.copy().reset_index(drop=True)
    parsed = [pd.Timestamp(value) for value in result["timestamp"]]
    if any(pd.isna(value) or value.tzinfo is None for value in parsed):
        raise ValueError("timestamp values must be timezone-aware")
    result["timestamp"] = pd.to_datetime(parsed, utc=True)
    if not result["timestamp"].is_monotonic_increasing or result["timestamp"].duplicated().any():
        raise ValueError("timestamp values must be strictly increasing and unique")
    for name in ("open", "high", "low", "close", "volume", "dividend", "split_ratio"):
        if name not in result:
            result[name] = 0.0 if name == "dividend" else 1.0
        try:
            result[name] = pd.to_numeric(result[name], errors="raise").astype(float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not all(math.isfinite(value) for value in result[name]):
            raise ValueError(f"{name} must contain only finite values")
    if (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (result["volume"] < 0).any() or (result["dividend"] < 0).any():
        raise ValueError("volume and dividend must be nonnegative")
    if (
        (result["low"] > result[["open", "close"]].min(axis=1)).any()
        or (result["high"] < result[["open", "close"]].max(axis=1)).any()
        or (result["high"] < result["low"]).any()
    ):
        raise ValueError("OHLC prices have inconsistent high/low ranges")
    if (result["split_ratio"] != 1.0).any():
        raise ValueError(
            "Stock splits are unsupported: provide a split-free raw-price date range; "
            "as-of split adjustment is required before signals or backtesting."
        )
    return result


def _ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    current = math.fsum(values[:period]) / period
    result[period - 1] = current
    alpha = 2.0 / (period + 1.0)
    for index in range(period, len(values)):
        current += alpha * (values[index] - current)
        result[index] = current
    return result


def _rsi(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result
    differences = [values[i] - values[i - 1] for i in range(1, len(values))]
    gain = math.fsum(max(delta, 0.0) for delta in differences[:period]) / period
    loss = math.fsum(max(-delta, 0.0) for delta in differences[:period]) / period

    def value() -> float:
        if loss == 0:
            return 50.0 if gain == 0 else 100.0
        return 100.0 - 100.0 / (1.0 + gain / loss)

    result[period] = value()
    for index in range(period + 1, len(values)):
        delta = differences[index - 1]
        gain = (gain * (period - 1) + max(delta, 0.0)) / period
        loss = (loss * (period - 1) + max(-delta, 0.0)) / period
        result[index] = value()
    return result


def _reward_risk(
    entry: float,
    stop: float,
    target: float,
    commission_rate: float,
    slippage_bps: float,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Entry is already slipped. Returns gross RR, net RR, risk, reward/share."""
    if not all(math.isfinite(value) and value > 0 for value in (entry, stop, target)):
        return None, None, None, None
    if stop >= entry or target <= entry:
        return None, None, None, None
    slip = slippage_bps / 10_000.0
    entry_cost = entry * (1.0 + commission_rate)
    stop_proceeds = stop * (1.0 - slip) * (1.0 - commission_rate)
    target_proceeds = target * (1.0 - slip) * (1.0 - commission_rate)
    risk = entry_cost - stop_proceeds
    reward = target_proceeds - entry_cost
    return (target - entry) / (entry - stop), reward / risk, risk, reward


def generate_signals(
    frame: pd.DataFrame,
    symbol: str,
    config: StrategyConfig = StrategyConfig(),
) -> list[dict]:
    """Return every warmed-up crossover/breakout, with qualification reasons.

    ``entry_trigger_price`` is the completed signal bar's close, never an
    executable same-close fill. Execution is delegated to next-open backtesting.
    ``reward_risk`` is gross; ``net_reward_risk`` includes both sides' costs.
    """
    bars = _validated_frame(frame)
    source_symbol = symbol.strip().upper()
    if not source_symbol:
        raise ValueError("symbol must be nonempty")
    ticker = source_symbol[:-3] if source_symbol.endswith(".BK") else source_symbol
    closes = bars["close"].tolist()
    fast = _ema(closes, config.fast)
    slow = _ema(closes, config.slow)
    trend = _ema(closes, config.trend)
    rsi = _rsi(closes, config.rsi_period)
    prior_high = bars["high"].shift(1).rolling(config.breakout_window).max()
    support = bars["low"].shift(1).rolling(config.support_window).min()
    resistance = bars["high"].shift(1).rolling(config.resistance_window).max()
    prior_volume = bars["volume"].shift(1).rolling(config.volume_window).mean()
    fingerprint = hashlib.sha256(
        json.dumps(asdict(config), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    warmup_index = max(
        config.trend - 1, config.slow, config.rsi_period,
        config.volume_window, config.breakout_window,
        config.support_window, config.resistance_window,
    )
    signals: list[dict] = []
    for index in range(warmup_index, len(bars)):
        cross = bool(fast[index] > slow[index] and fast[index - 1] <= slow[index - 1])
        breakout = bool(closes[index] > prior_high.iloc[index])
        if not (cross or breakout):
            continue
        close = closes[index]
        stop = float(support.iloc[index])
        target = float(resistance.iloc[index])
        baseline = float(prior_volume.iloc[index])
        multiple = float(bars.iloc[index]["volume"]) / baseline if baseline > 0 else None
        raw_gross, _, _, _ = _reward_risk(close, stop, target, 0.0, 0.0)
        estimated_entry = close * (1.0 + config.slippage_bps / 10_000.0)
        _, net_rr, _, _ = _reward_risk(
            estimated_entry, stop, target, config.commission_rate, config.slippage_bps
        )
        reasons: list[str] = []
        if close <= trend[index]:
            reasons.append("below_trend")
        if baseline <= 0:
            reasons.append("invalid_volume_baseline")
        elif not float(bars.iloc[index]["volume"]) > config.volume_multiple * baseline:
            reasons.append("insufficient_volume")
        if not config.rsi_min <= rsi[index] <= config.rsi_max:
            reasons.append("rsi_out_of_range")
        if stop >= close:
            reasons.append("stop_not_below_entry")
        if target <= close:
            reasons.append("target_not_above_entry")
        if raw_gross is not None and raw_gross < config.min_reward_risk:
            reasons.append("gross_reward_risk_below_minimum")
        if target <= estimated_entry and target > close:
            reasons.append("target_not_above_slipped_entry")
        if net_rr is not None and net_rr < config.min_reward_risk:
            reasons.append("net_reward_risk_below_minimum")
        timestamp = bars.iloc[index]["timestamp"].isoformat()
        identity = {
            "schema_version": SCHEMA_VERSION, "strategy_name": STRATEGY_NAME,
            "source_symbol": source_symbol, "timestamp": timestamp,
            "config_fingerprint": fingerprint,
        }
        signal_id = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        signals.append({
            "schema_version": SCHEMA_VERSION,
            "signal_id": signal_id,
            "config_fingerprint": fingerprint,
            "ticker": ticker,
            "source_symbol": source_symbol,
            "market": "SET",
            "timeframe": "1D",
            "strategy_name": STRATEGY_NAME,
            "timestamp": timestamp,
            "entry_trigger_price": close,
            "estimated_entry_price": estimated_entry,
            "support_level": stop,
            "resistance_level": target,
            "volume_multiple": multiple,
            "rsi_14": float(rsi[index]),
            "rsi_period": config.rsi_period,
            "ema_fast": float(fast[index]),
            "ema_slow": float(slow[index]),
            "ema_trend": float(trend[index]),
            "prior_breakout_high": float(prior_high.iloc[index]),
            "prior_volume_mean": baseline,
            "stop_loss": stop,
            "take_profit": target,
            "reward_risk": raw_gross,
            "net_reward_risk": net_rr,
            "min_reward_risk": config.min_reward_risk,
            "qualified": not reasons,
            "rejection_reasons": reasons,
            "ema_cross": cross,
            "breakout": breakout,
        })
    return signals
