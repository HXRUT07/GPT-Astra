import pytest

from forex_signal.gemini import GeminiClient, GeminiError, build_prompt


SIGNAL = {
    "signal_id": "sig-1", "asset": "EURUSD", "action": "BUY",
    "timestamp": "2026-10-07T14:00:00+00:00", "trigger_price": 1.1,
    "suggested_sl": 1.09, "suggested_tp": 1.12, "reward_risk": 2.0,
}
GUARD = {"decision": "PAUSE", "score": 10, "execution_allowed": False}


def test_prompt_is_structured_and_does_not_contain_api_key():
    prompt = build_prompt(SIGNAL, GUARD, {"dxy": {"direction": "UP"}})
    assert "Research packet" in prompt
    assert "PAUSE" in prompt
    assert "GEMINI_API_KEY" not in prompt
    assert "Return JSON only" in prompt


def test_missing_key_is_rejected(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(GeminiError, match="GEMINI_API_KEY"):
        GeminiClient()


def test_consult_parses_json_and_guard_remains_authoritative(monkeypatch):
    client = GeminiClient("test-secret", model="test-model")
    monkeypatch.setattr(client, "_request_json", lambda payload: {
        "candidates": [{"content": {"parts": [{"text": '{"recommendation":"SUPPORT","summary":"Looks coherent","risk_flags":[],"missing_data":[]}'}]}}]
    })
    result = client.consult(SIGNAL, GUARD)
    assert result["recommendation"] == "SUPPORT"
    assert result["guard_decision"] == "PAUSE"
    assert result["final_decision"] == "PAUSE"
    assert result["execution_allowed"] is False
    assert result["model"] == "test-model"


def test_invalid_gemini_json_is_rejected(monkeypatch):
    client = GeminiClient("test-secret")
    monkeypatch.setattr(client, "_request_json", lambda payload: {
        "candidates": [{"content": {"parts": [{"text": "not-json"}]}}]
    })
    with pytest.raises(GeminiError, match="valid JSON"):
        client.consult(SIGNAL, GUARD)
