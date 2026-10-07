"""Local research commands; no broker or outbound message integration."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from .data import WATCHLIST, fetch_prices, load_prices, save_prices, write_json
from .strategy import StrategyConfig, generate_signals
from .backtest import BacktestConfig, run_backtest
from .analysis import gate_funnel, walk_forward


def probe(symbols: list[str], data_dir: Path, report_dir: Path, as_of: date | None) -> dict:
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "stocks": [], "errors": []}
    for symbol in symbols:
        try:
            prices, raw = fetch_prices(symbol, as_of=as_of)
            save_prices(prices, raw, data_dir)
            report["stocks"].append(prices.metadata)
            print(f"{symbol}: {prices.metadata['rows']} bars, {prices.metadata['first_session']} .. {prices.metadata['last_session']}")
        except Exception as exc:
            report["errors"].append({"symbol": symbol, "error": str(exc)})
            print(f"{symbol}: ERROR {exc}")
    write_json(report_dir / "data-quality.json", report)
    return report


def backtest(symbols: list[str], data_dir: Path, report_dir: Path) -> dict:
    strategy = StrategyConfig()
    execution = BacktestConfig()
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategy": asdict(strategy), "execution": asdict(execution),
        "evaluation": "last 20% of each available history, fixed parameters; no tuning on evaluation",
        "portfolio_basis": "independent THB 100,000 per symbol; not a combined portfolio",
        "stocks": [], "errors": [],
        "limitations": ["unverified SET calendar and provider production license",
                        "news, fundamentals and earnings calendars have not been integrated",
                        "no inference of profitability from this initial backtest",
                        "only complete past sessions; today's candle always excluded",
                        "fixed commission/slippage estimates, not broker-specific costs",
                        "split-bearing histories explicitly unsupported",
                        "holdout excludes positions entered before the split; starts with cash",
                        "no AI evaluation, order execution or external notifications"],
    }
    for symbol in symbols:
        try:
            prices = load_prices(symbol, data_dir)
            frame = prices.frame
            signals = generate_signals(frame, symbol, strategy)
            split = max(strategy.trend + 1, int(len(frame) * 0.8))
            if split >= len(frame) - 1:
                raise ValueError("insufficient history for a separate evaluation period")
            evaluation_frame = frame.iloc[split:].reset_index(drop=True)
            first_evaluation = evaluation_frame.timestamp.iloc[0]
            evaluation_signals = [signal for signal in signals if pd.Timestamp(signal["timestamp"]) >= first_evaluation]
            full_result = run_backtest(frame, signals, execution)
            evaluation_result = run_backtest(evaluation_frame, evaluation_signals, execution)
            rejections = Counter(reason for signal in signals for reason in signal["rejection_reasons"])
            stock = {"symbol": symbol, "data": prices.metadata,
                     "raw_trigger_count": len(signals),
                     "qualified_signal_count": sum(bool(signal["qualified"]) for signal in signals),
                     "rejection_counts": dict(rejections),
                     "evaluation_start": first_evaluation.isoformat(),
                     "evaluation_bars": len(evaluation_frame),
                     "full_history": full_result, "evaluation": evaluation_result}
            report["stocks"].append(stock)
            write_json(report_dir / f"{symbol}.signals.json", signals)
            write_json(report_dir / f"{symbol}.backtest.json", stock)
            print(f"{symbol}: triggers={len(signals)}, qualified={stock['qualified_signal_count']}, evaluation from {first_evaluation.date()}")
        except Exception as exc:
            report["errors"].append({"symbol": symbol, "error": str(exc)})
            print(f"{symbol}: ERROR {exc}")
    write_json(report_dir / "backtest-summary.json", report)
    return report


def analyze(symbols: list[str], data_dir: Path, report_dir: Path) -> dict:
    strategy = StrategyConfig()
    execution = BacktestConfig()
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "sequential gate funnel plus expanding walk-forward",
        "selection": "baseline parameters fixed from blueprint; no test-window tuning",
        "stocks": [], "errors": [],
    }
    for symbol in symbols:
        try:
            prices = load_prices(symbol, data_dir)
            signals = generate_signals(prices.frame, symbol, strategy)
            stock = {
                "symbol": symbol,
                "data": prices.metadata,
                "full_history_gate_funnel": gate_funnel(signals),
                "walk_forward": walk_forward(prices.frame, symbol, strategy, execution),
            }
            report["stocks"].append(stock)
            write_json(report_dir / f"{symbol}.gate-analysis.json", stock)
            aggregate = stock["walk_forward"]["aggregate"]
            print(f"{symbol}: full triggers={len(signals)}, full qualified={stock['full_history_gate_funnel']['qualified_count']}, "
                  f"walk-forward trades={aggregate['closed_trades']}")
        except Exception as exc:
            report["errors"].append({"symbol": symbol, "error": str(exc)})
            print(f"{symbol}: ERROR {exc}")
    write_json(report_dir / "gate-walk-forward-summary.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SET daily stock research prototype")
    parser.add_argument("command", choices=("probe", "backtest", "analyze", "run"))
    parser.add_argument("--symbols", nargs="+", default=list(WATCHLIST))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/latest"))
    parser.add_argument("--as-of", type=date.fromisoformat, help="exclude sessions on/after this Thai date (probe only)")
    args = parser.parse_args(argv)
    symbols = [symbol.upper() for symbol in args.symbols]
    if len(symbols) != len(set(symbols)):
        parser.error("symbols must be unique")
    if args.as_of and args.command == "backtest":
        parser.error("--as-of applies to probe/run; backtest uses the saved dataset cutoff")
    errors = []
    if args.command in ("probe", "run"):
        result = probe(symbols, args.data_dir, args.report_dir, args.as_of)
        errors.extend(result["errors"])
        if args.command == "run":
            # Never replace a failed fetch with an older cached price history.
            symbols = [stock["symbol"] for stock in result["stocks"]]
    if args.command in ("backtest", "run"):
        result = backtest(symbols, args.data_dir, args.report_dir)
        errors.extend(result["errors"])
    if args.command == "analyze":
        result = analyze(symbols, args.data_dir, args.report_dir)
        errors.extend(result["errors"])
    print(f"Reports: {args.report_dir.resolve()}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
