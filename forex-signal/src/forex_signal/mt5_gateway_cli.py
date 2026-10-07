"""Run the local FBS MT5 candle gateway."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .mt5_gateway import run_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local orderless FBS MT5 candle gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--db", type=Path, default=Path("data/mt5-candles.sqlite3"))
    parser.add_argument("--token-env", default="MT5_INGEST_TOKEN")
    args = parser.parse_args(argv)
    token = os.getenv(args.token_env, "")
    run_server(args.host, args.port, args.db, token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
