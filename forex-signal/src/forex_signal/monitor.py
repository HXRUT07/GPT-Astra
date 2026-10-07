"""Long-running public-feed paper monitor.

It polls completed candles, deduplicates by candle timestamp, runs the local
review agent, and appends auditable JSONL records. It deliberately has no
broker, Telegram, Discord or LLM side effect.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Callable

import pandas as pd

from .agent import review_signal
from .data import fetch_yahoo_intraday
from .gemini import GeminiClient, GeminiError
from .strategy import ForexConfig, generate_signals


Fetcher = Callable[..., tuple[pd.DataFrame, dict]]


@dataclass(frozen=True)
class MonitorConfig:
    asset: str = "EURUSD"
    interval: str = "15m"
    timeframe: str = "M15"
    range_: str = "60d"
    poll_seconds: int = 60
    output_dir: Path = Path("reports/monitor")
    warm_start: bool = True

    def __post_init__(self) -> None:
        if self.interval not in {"15m", "30m", "60m"}:
            raise ValueError("interval must be 15m, 30m or 60m")
        expected = {"15m": "M15", "30m": "M30", "60m": "H1"}[self.interval]
        if self.timeframe != expected:
            raise ValueError("timeframe must match interval")
        if not isinstance(self.poll_seconds, int) or self.poll_seconds < 10:
            raise ValueError("poll_seconds must be at least 10 seconds")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaperMonitor:
    def __init__(self, config: MonitorConfig = MonitorConfig(), *, fetcher: Fetcher = fetch_yahoo_intraday, gemini: GeminiClient | None = None):
        self.config = config
        self.fetcher = fetcher
        self.gemini = gemini
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.config.output_dir / "state.json"
        self.event_path = self.config.output_dir / "events.jsonl"
        self.error_path = self.config.output_dir / "errors.jsonl"

    def _read_state(self) -> dict:
        if not self.state_path.exists():
            return {"schema_version": 1, "last_processed_timestamp": None, "poll_count": 0, "signals_seen": 0}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _write_state(self, state: dict) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(self.state_path)

    def _append(self, path: Path, value: dict) -> None:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")

    def run_once(self) -> dict:
        frame, metadata = self.fetcher(self.config.asset, interval=self.config.interval, range_=self.config.range_)
        if frame.empty:
            raise ValueError("data provider returned no candles")
        strategy = ForexConfig()
        signals = generate_signals(frame, self.config.asset, self.config.timeframe, strategy)
        state = self._read_state()
        previous = state.get("last_processed_timestamp")
        warm_started = False
        if previous is None and self.config.warm_start and len(frame) > 1:
            # Preserve the latest completed candle for a first-run review while
            # avoiding replay of the entire public 60-day history.
            previous = frame.iloc[-2]["timestamp"].isoformat()
            warm_started = True
        new_signals = [signal for signal in signals if previous is None or pd.Timestamp(signal["timestamp"]) > pd.Timestamp(previous)]
        decisions = []
        for signal in new_signals:
            decision = review_signal(signal, events=[], dxy=None)
            record = {"recorded_at": _now(), "signal": signal, "agent": decision, "source": metadata}
            if self.gemini is not None:
                try:
                    record["gemini"] = self.gemini.consult(signal, decision)
                except GeminiError as exc:
                    record["gemini_error"] = str(exc)
            self._append(self.event_path, record)
            decisions.append(decision)
        latest = frame.iloc[-1]["timestamp"].isoformat()
        state.update({
            "schema_version": 1, "asset": self.config.asset, "interval": self.config.interval,
            "last_processed_timestamp": latest, "last_poll_at": _now(),
            "last_bar_timestamp": latest, "bars_seen": len(frame),
            "poll_count": int(state.get("poll_count", 0)) + 1,
            "signals_seen": int(state.get("signals_seen", 0)) + len(new_signals),
        })
        self._write_state(state)
        summary = {
            "asset": self.config.asset, "interval": self.config.interval, "bar_timestamp": latest,
            "bars_seen": len(frame), "signals_seen_this_poll": len(new_signals),
            "decisions": {name: sum(decision["decision"] == name for decision in decisions) for name in ("APPROVED", "PAUSE", "REVIEW")},
            "warm_started": warm_started,
        }
        print(json.dumps(summary, ensure_ascii=False))
        return summary

    def run(self, *, once: bool = False) -> None:
        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                print("Monitor stopped.")
                return
            except Exception as exc:
                self._append(self.error_path, {"recorded_at": _now(), "error": str(exc)})
                print(f"Monitor error: {exc}")
                if once:
                    raise
            if once:
                return
            time.sleep(self.config.poll_seconds)
