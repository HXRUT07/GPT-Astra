"""Export accepted MT5 candles from SQLite to the strategy CSV format."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .mt5_gateway import CandleStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export local MT5 candle database")
    parser.add_argument("--db", type=Path, default=Path("data/mt5-candles.sqlite3"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = CandleStore(args.db).export(args.symbol, args.timeframe)
    if not rows:
        raise SystemExit("no candles found")
    frame = pd.DataFrame(rows)[["timestamp", "open", "high", "low", "close", "tick_volume"]].rename(columns={"tick_volume": "volume"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False)
    print(f"Exported {len(frame)} candles to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
