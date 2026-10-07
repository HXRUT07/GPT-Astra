"""Optional Gemini consultation layer.

The client is deliberately downstream of :mod:`forex_signal.agent`: Gemini may
explain risks, but it cannot change the deterministic guard verdict or enable
execution. The API key is read from ``GEMINI_API_KEY`` and never returned.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class GeminiError(RuntimeError):
    """Gemini was unavailable or returned an invalid consultation."""


def build_prompt(signal: Mapping[str, object], guard: Mapping[str, object], context: Mapping[str, object] | None = None) -> str:
    """Create a bounded, secret-free prompt with an explicit JSON contract."""
    packet = {
        "signal": dict(signal),
        "deterministic_guard": dict(guard),
        "context": dict(context or {}),
    }
    serialized = json.dumps(packet, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return (
        "You are a cautious market-risk reviewer. This is research, not an order request. "
        "Do not invent news, prices, probabilities, broker conditions, or missing data. "
        "The deterministic guard is authoritative: never override PAUSE or REVIEW and never authorize execution. "
        "Return JSON only with exactly these fields: "
        "recommendation (SUPPORT, CAUTION, OPPOSE, or INSUFFICIENT_DATA), "
        "summary (short string), risk_flags (array of strings), missing_data (array of strings).\n\n"
        f"Research packet:\n{serialized}"
    )


def _extract_text(response: Mapping[str, object]) -> str:
    try:
        candidates = response["candidates"]
        first = candidates[0]
        parts = first["content"]["parts"]
        return str(parts[0]["text"])
    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiError("Gemini response did not contain candidate text") from exc


def _parse_review(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()
        if cleaned.startswith("json\n"):
            cleaned = cleaned[5:]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiError("Gemini did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise GeminiError("Gemini JSON review must be an object")
    recommendation = parsed.get("recommendation")
    if recommendation not in {"SUPPORT", "CAUTION", "OPPOSE", "INSUFFICIENT_DATA"}:
        raise GeminiError("Gemini recommendation is outside the allowed enum")
    if not isinstance(parsed.get("summary"), str) or not isinstance(parsed.get("risk_flags"), list) or not isinstance(parsed.get("missing_data"), list):
        raise GeminiError("Gemini review has an invalid schema")
    return {
        "recommendation": recommendation,
        "summary": parsed["summary"],
        "risk_flags": [str(item) for item in parsed["risk_flags"]],
        "missing_data": [str(item) for item in parsed["missing_data"]],
    }


class GeminiClient:
    def __init__(self, api_key: str | None = None, *, model: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise GeminiError("GEMINI_API_KEY is not set")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout = timeout

    def _request_json(self, payload: dict) -> dict:
        query = urlencode({"key": self.api_key})
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?{query}"
        request = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "GPT-Astra-Forex-Research/0.1"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            raise GeminiError(f"Gemini HTTP error {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GeminiError("Gemini request failed") from exc

    def consult(self, signal: Mapping[str, object], guard: Mapping[str, object], context: Mapping[str, object] | None = None) -> dict:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": build_prompt(signal, guard, context)}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        review = _parse_review(_extract_text(self._request_json(payload)))
        return {
            "provider": "google-gemini",
            "model": self.model,
            "consulted_at": datetime.now(timezone.utc).isoformat(),
            **review,
            "guard_decision": guard.get("decision"),
            "final_decision": guard.get("decision"),
            "execution_allowed": False,
            "guard_is_authoritative": True,
        }
