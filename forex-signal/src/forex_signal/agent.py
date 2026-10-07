"""Deterministic signal-review agent for the Forex prototype.

The agent only reviews a completed signal. It never fetches news, calls an LLM,
places an order or sends a notification. External adapters can later normalize
calendar/DXY data into the small context dictionaries accepted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Iterable, Mapping

import pandas as pd


@dataclass(frozen=True)
class AgentConfig:
    news_blackout_minutes: int = 60
    minimum_reward_risk: float = 2.0
    approval_score: int = 8
    dxy_conflict_penalty: int = 3

    def __post_init__(self) -> None:
        if self.news_blackout_minutes < 0 or self.approval_score < 1 or self.approval_score > 10:
            raise ValueError("agent thresholds are invalid")
        if not math.isfinite(self.minimum_reward_risk) or self.minimum_reward_risk <= 0:
            raise ValueError("minimum_reward_risk must be finite and positive")
        if self.dxy_conflict_penalty < 0 or self.dxy_conflict_penalty > 10:
            raise ValueError("dxy_conflict_penalty must be in [0, 10]")


def _timestamp(value: object, label: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or pd.isna(parsed):
        raise ValueError(f"{label} must be timezone-aware")
    return parsed.tz_convert("UTC")


def _asset_currencies(asset: str) -> set[str]:
    symbol = asset.upper().replace("/", "")
    if symbol == "XAUUSD":
        return {"USD"}
    if len(symbol) >= 6:
        return {symbol[:3], symbol[-3:]}
    return set()


def _event_matches(signal_time: pd.Timestamp, event: Mapping[str, object], asset_currencies: set[str], config: AgentConfig) -> tuple[bool, str | None]:
    impact = str(event.get("impact", "")).upper()
    currency = str(event.get("currency", "")).upper()
    if impact not in {"HIGH", "RED", "3"} or currency not in asset_currencies:
        return False, None
    try:
        event_time = _timestamp(event.get("timestamp"), "event timestamp")
    except ValueError as exc:
        return False, str(exc)
    distance = abs((event_time - signal_time).total_seconds()) / 60.0
    if distance <= config.news_blackout_minutes:
        title = str(event.get("title", "high-impact event"))
        return True, f"{currency} {title} within {distance:.0f} minutes"
    return False, None


def review_signal(
    signal: Mapping[str, object],
    *,
    events: Iterable[Mapping[str, object]] = (),
    dxy: Mapping[str, object] | None = None,
    now: datetime | None = None,
    config: AgentConfig = AgentConfig(),
) -> dict:
    """Review a signal and return an auditable APPROVED/PAUSE/REVIEW verdict.

    The score is a rule-based priority score, not a calibrated probability.
    Missing news or DXY data never becomes a claim that risk is absent.
    """
    reasons: list[dict] = []
    checks: dict[str, object] = {}
    try:
        signal_time = _timestamp(signal.get("timestamp"), "signal timestamp")
    except ValueError as exc:
        signal_time = None
        reasons.append({"code": "INVALID_SIGNAL_TIME", "detail": str(exc), "severity": "BLOCK"})
    action = str(signal.get("action", "")).upper()
    asset = str(signal.get("asset", "")).upper()
    if action not in {"BUY", "SELL"}:
        reasons.append({"code": "INVALID_ACTION", "detail": "action must be BUY or SELL", "severity": "BLOCK"})
    if not asset:
        reasons.append({"code": "INVALID_ASSET", "detail": "asset is missing", "severity": "BLOCK"})
    try:
        trigger = float(signal["trigger_price"])
        stop = float(signal["suggested_sl"])
        target = float(signal["suggested_tp"])
        raw_reward_risk = signal.get("reward_risk")
        reward_risk = float(raw_reward_risk) if raw_reward_risk is not None else abs(target - trigger) / abs(trigger - stop)
        numeric_ok = all(math.isfinite(value) and value > 0 for value in (trigger, stop, target, reward_risk))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        numeric_ok = False
        reward_risk = None
    checks["numeric_levels"] = numeric_ok
    if not numeric_ok:
        reasons.append({"code": "INVALID_LEVELS", "detail": "trigger/SL/TP/RR are not finite positive numbers", "severity": "BLOCK"})
    elif reward_risk < config.minimum_reward_risk:
        reasons.append({"code": "RR_BELOW_MINIMUM", "detail": f"reward/risk {reward_risk:.4f} < {config.minimum_reward_risk:.4f}", "severity": "BLOCK"})
    checks["reward_risk"] = reward_risk
    qualified = bool(signal.get("qualified", False))
    checks["technical_signal_qualified"] = qualified
    if not qualified:
        reasons.append({"code": "TECHNICAL_SIGNAL_NOT_QUALIFIED", "detail": signal.get("rejection_reasons", []), "severity": "BLOCK"})

    high_events = []
    invalid_event_context = []
    if signal_time is not None:
        currencies = _asset_currencies(asset)
        for event in events:
            matched, detail = _event_matches(signal_time, event, currencies, config)
            if detail and matched:
                high_events.append(detail)
            elif detail and not matched:
                invalid_event_context.append(detail)
    checks["high_impact_events_in_window"] = high_events
    checks["calendar_context"] = "provided" if events else "not_provided"
    if high_events:
        reasons.append({"code": "HIGH_IMPACT_NEWS_WINDOW", "detail": high_events, "severity": "PAUSE"})
    if invalid_event_context:
        reasons.append({"code": "INVALID_CALENDAR_CONTEXT", "detail": invalid_event_context, "severity": "REVIEW"})

    score = 10
    conflict = False
    dxy_direction = str((dxy or {}).get("direction", "UNKNOWN")).upper()
    if dxy is None:
        checks["dxy_context"] = "not_provided"
    else:
        checks["dxy_context"] = "provided"
        if asset in {"XAUUSD", "EURUSD"} and dxy_direction in {"UP", "DOWN"}:
            conflict = (action == "BUY" and dxy_direction == "UP") or (action == "SELL" and dxy_direction == "DOWN")
    checks["dxy_conflict"] = conflict
    if conflict:
        score -= config.dxy_conflict_penalty
        reasons.append({"code": "DXY_DIVERGENCE_WARNING", "detail": f"{action} conflicts with DXY {dxy_direction}", "severity": "REVIEW"})
    score = max(0, min(10, score))
    hard_block = any(item["severity"] == "BLOCK" for item in reasons)
    pause = any(item["severity"] == "PAUSE" for item in reasons)
    decision = "PAUSE" if pause else ("REVIEW" if hard_block or score < config.approval_score else "APPROVED")
    if now is not None:
        current = _timestamp(now, "now")
        checks["signal_age_minutes"] = (current - signal_time).total_seconds() / 60.0 if signal_time is not None else None
    return {
        "agent_version": "deterministic-review-v1",
        "signal_id": signal.get("signal_id"),
        "asset": asset,
        "action": action,
        "signal_timestamp": signal.get("timestamp"),
        "decision": decision,
        "score": score,
        "score_is_probability": False,
        "reasons": reasons,
        "checks": checks,
        "execution_allowed": False,
        "external_context_limits": ["No news/DXY fetch is performed by this function.", "Missing context is not treated as safe.", "No broker order or notification is sent."],
    }
