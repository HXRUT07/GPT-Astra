"""Run the paper monitor from candles received by the local MT5 gateway."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .gemini import GeminiClient
from .monitor import MonitorConfig, PaperMonitor
from .mt5_gateway import CandleStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Forex paper monitor from FBS MT5 SQLite candles")
    parser.add_argument("--db", type=Path, default=Path("data/mt5-candles.sqlite3"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", choices=("M15", "M30", "H1"), default="M15")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/mt5-monitor"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--gemini", action="store_true")
    args = parser.parse_args(argv)
    interval = {"M15": "15m", "M30": "30m", "H1": "60m"}[args.timeframe]
    store = CandleStore(args.db)

    def fetcher(asset: str, **kwargs):
        rows = store.export(args.symbol, args.timeframe)
        if not rows:
            raise ValueError("MT5 database has no candles yet")
        frame = pd.DataFrame(rows)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame[["timestamp", "open", "high", "low", "close", "tick_volume"]].rename(columns={"tick_volume": "volume"})
        return frame, {"provider": "FBS_MT5_local_gateway", "symbol": args.symbol, "timeframe": args.timeframe, "rows": len(frame)}

    gemini = GeminiClient() if args.gemini else None
    monitor = PaperMonitor(MonitorConfig(asset=args.symbol.upper(), interval=interval, timeframe=args.timeframe, poll_seconds=args.poll_seconds, output_dir=args.output_dir), fetcher=fetcher, gemini=gemini)
    monitor.run(once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
