"""Run the Forex signal engine and paper backtest on a local OHLC CSV."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .backtest import ForexBacktestConfig, run_backtest
from .strategy import ForexConfig, generate_signals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forex/XAUUSD local signal and paper backtest")
    parser.add_argument("csv", type=Path, help="CSV with timestamp, open, high, low, close")
    parser.add_argument("--asset", default="XAUUSD")
    parser.add_argument("--timeframe", choices=("M15", "M30", "H1"), default="M15")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    frame = pd.read_csv(args.csv)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    signals = generate_signals(frame, args.asset, args.timeframe, ForexConfig())
    result = run_backtest(frame, signals, ForexBacktestConfig())
    payload = {"asset": args.asset.upper(), "timeframe": args.timeframe, "signal_count": len(signals), "qualified_count": sum(bool(signal["qualified"]) for signal in signals), "signals": signals, "backtest": result}
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(args.output)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
