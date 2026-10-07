from datetime import datetime, timezone

from forex_signal.agent import review_signal


def signal(action="BUY", asset="EURUSD"):
    return {
        "signal_id": "sig-1", "asset": asset, "action": action,
        "timestamp": "2026-10-07T14:00:00+00:00", "trigger_price": 1.1,
        "suggested_sl": 1.09 if action == "BUY" else 1.11,
        "suggested_tp": 1.12 if action == "BUY" else 1.08,
        "reward_risk": 2.0, "qualified": True, "rejection_reasons": [],
    }


def test_clean_signal_is_approved_but_never_execution_enabled():
    result = review_signal(signal(), events=[], dxy={"direction": "FLAT"})
    assert result["decision"] == "APPROVED"
    assert result["score"] == 10
    assert result["score_is_probability"] is False
    assert result["execution_allowed"] is False


def test_high_impact_usd_event_pauses_eurusd():
    result = review_signal(signal(), events=[{
        "currency": "USD", "impact": "HIGH", "title": "CPI",
        "timestamp": "2026-10-07T14:30:00+00:00",
    }])
    assert result["decision"] == "PAUSE"
    assert any(reason["code"] == "HIGH_IMPACT_NEWS_WINDOW" for reason in result["reasons"])


def test_dxy_conflict_requires_review():
    result = review_signal(signal("BUY", "XAUUSD"), dxy={"direction": "UP", "breakout": True})
    assert result["decision"] == "REVIEW"
    assert result["score"] == 7
    assert any(reason["code"] == "DXY_DIVERGENCE_WARNING" for reason in result["reasons"])


def test_missing_or_unqualified_signal_is_not_approved():
    unqualified = signal()
    unqualified["qualified"] = False
    unqualified["rejection_reasons"] = ["outside_session"]
    result = review_signal(unqualified)
    assert result["decision"] == "REVIEW"
    assert any(reason["code"] == "TECHNICAL_SIGNAL_NOT_QUALIFIED" for reason in result["reasons"])


def test_event_outside_window_does_not_pause():
    result = review_signal(signal(), events=[{
        "currency": "USD", "impact": "HIGH", "timestamp": "2026-10-07T16:01:00+00:00",
    }])
    assert result["decision"] == "APPROVED"
