"""CLI entry point for the long-running Forex paper monitor."""

from __future__ import annotations

import argparse
from pathlib import Path

from .monitor import MonitorConfig, PaperMonitor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a deduplicated Forex paper monitor")
    parser.add_argument("--asset", default="EURUSD")
    parser.add_argument("--interval", choices=("15m", "30m", "60m"), default="15m")
    parser.add_argument("--range", dest="range_", default="60d")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/monitor"))
    parser.add_argument("--once", action="store_true", help="poll once and exit; useful for smoke tests")
    parser.add_argument("--replay-history", action="store_true", help="review all existing triggers on first run")
    args = parser.parse_args(argv)
    timeframe = {"15m": "M15", "30m": "M30", "60m": "H1"}[args.interval]
    monitor = PaperMonitor(MonitorConfig(asset=args.asset.upper(), interval=args.interval, timeframe=timeframe, range_=args.range_, poll_seconds=args.poll_seconds, output_dir=args.output_dir, warm_start=not args.replay_history))
    monitor.run(once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
