"""Download a public exploratory intraday candle file."""

from __future__ import annotations

import argparse
from pathlib import Path

from .data import fetch_yahoo_intraday, save_intraday


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download public Yahoo intraday Forex candles")
    parser.add_argument("--asset", default="EURUSD")
    parser.add_argument("--interval", choices=("15m", "30m", "60m"), default="15m")
    parser.add_argument("--range", dest="range_", default="60d")
    parser.add_argument("--output", type=Path, default=Path("data/EURUSD_M15.csv"))
    args = parser.parse_args(argv)
    frame, metadata = fetch_yahoo_intraday(args.asset, interval=args.interval, range_=args.range_)
    save_intraday(frame, metadata, args.output)
    print(f"{metadata['asset']} {metadata['interval']}: {len(frame)} candles")
    print(f"Saved: {args.output}")
    print(f"Provider: {metadata['provider']}; broker equivalence: {metadata['broker_equivalence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
