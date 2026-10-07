"""Gate funnel and chronological walk-forward diagnostics.

This module evaluates the locked blueprint baseline. It does not tune a
strategy on the test windows, so the output describes generalisation of the
specified rules rather than an optimized backtest.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import pandas as pd

from .backtest import BacktestConfig, run_backtest
from .strategy import StrategyConfig, generate_signals


Gate = tuple[str, frozenset[str]]
GATES: tuple[Gate, ...] = (
    ("trend", frozenset({"below_trend"})),
    ("volume", frozenset({"insufficient_volume", "invalid_volume_baseline"})),
    ("rsi", frozenset({"rsi_out_of_range"})),
    ("levels", frozenset({"stop_not_below_entry", "target_not_above_entry", "target_not_above_slipped_entry"})),
    ("gross_reward_risk", frozenset({"gross_reward_risk_below_minimum"})),
    ("net_reward_risk", frozenset({"net_reward_risk_below_minimum"})),
)


def gate_funnel(signals: list[dict]) -> dict:
    """Count each rejection after the preceding gates have passed.

    A signal can have several rejection reasons. ``rejected_by_stage`` is
    sequential and therefore answers where a signal first falls out; the raw
    reason counter is also included for auditability.
    """
    remaining = list(signals)
    stages = []
    first_rejections: Counter[str] = Counter()
    for name, reasons in GATES:
        before = len(remaining)
        rejected = [signal for signal in remaining if reasons.intersection(signal.get("rejection_reasons", []))]
        remaining = [signal for signal in remaining if not reasons.intersection(signal.get("rejection_reasons", []))]
        first_rejections.update({name: len(rejected)})
        stages.append({"gate": name, "input": before, "passed": len(remaining), "rejected": len(rejected)})
    first_rejections["qualified"] = len([signal for signal in remaining if not signal.get("rejection_reasons")])
    raw_reasons = Counter(reason for signal in signals for reason in signal.get("rejection_reasons", []))
    return {
        "trigger_count": len(signals),
        "stages": stages,
        "first_rejection_by_gate": dict(first_rejections),
        "raw_rejection_reason_counts": dict(raw_reasons),
        "qualified_count": sum(bool(signal.get("qualified")) for signal in signals),
    }


def _iso(value: object) -> str:
    return pd.Timestamp(value).isoformat()


def walk_forward(
    frame: pd.DataFrame,
    symbol: str,
    strategy: StrategyConfig = StrategyConfig(),
    execution: BacktestConfig = BacktestConfig(),
    *,
    initial_train_fraction: float = 0.50,
    test_fraction: float = 0.15,
    minimum_test_bars: int = 63,
) -> dict:
    """Run locked-parameter sequential test windows with historical context.

    Each fold computes indicators using bars available up to that fold's test
    end, then filters signals to the test interval. The test backtest starts
    with cash and no position, so performance from one fold cannot leak into
    another. The full training history is retained as indicator context.
    """
    if not 0 < initial_train_fraction < 1 or not 0 < test_fraction < 1:
        raise ValueError("walk-forward fractions must be between zero and one")
    if minimum_test_bars < 2:
        raise ValueError("minimum_test_bars must be at least two")
    bars = frame.reset_index(drop=True)
    total = len(bars)
    initial_train_bars = max(strategy.trend + 1, int(total * initial_train_fraction))
    test_bars = max(minimum_test_bars, int(total * test_fraction))
    folds = []
    test_start = initial_train_bars
    while test_start < total:
        test_end = min(test_start + test_bars, total)
        if test_end - test_start < minimum_test_bars:
            break
        # Recompute with only information that existed by test_end. This also
        # makes the no-future-data boundary explicit rather than relying only
        # on the strategy's prefix-invariance test.
        available = bars.iloc[:test_end].reset_index(drop=True)
        signals = generate_signals(available, symbol, strategy)
        start_timestamp = bars.iloc[test_start]["timestamp"]
        end_timestamp = bars.iloc[test_end - 1]["timestamp"]
        test_signals = [
            signal for signal in signals
            if pd.Timestamp(signal["timestamp"]) >= start_timestamp
            and pd.Timestamp(signal["timestamp"]) <= end_timestamp
        ]
        test_frame = bars.iloc[test_start:test_end].reset_index(drop=True)
        result = run_backtest(test_frame, test_signals, execution)
        folds.append({
            "fold": len(folds) + 1,
            "train_start": _iso(bars.iloc[0]["timestamp"]),
            "train_end_exclusive": _iso(start_timestamp),
            "test_start": _iso(start_timestamp),
            "test_end_inclusive": _iso(end_timestamp),
            "train_bars": test_start,
            "test_bars": len(test_frame),
            "gate_funnel": gate_funnel(test_signals),
            "metrics": result["metrics"],
            "rejected_entry_counts": dict(Counter(item["reason"] for item in result["rejected_entries"])),
        })
        test_start = test_end
    aggregate_trades = sum(fold["metrics"]["closed_trades"] for fold in folds)
    aggregate_profit = sum(fold["metrics"]["realized_net_profit"] for fold in folds)
    aggregate_triggers = sum(fold["gate_funnel"]["trigger_count"] for fold in folds)
    aggregate_qualified = sum(fold["gate_funnel"]["qualified_count"] for fold in folds)
    return {
        "method": "expanding walk-forward with locked blueprint parameters",
        "parameter_selection": "none; StrategyConfig is fixed before every fold",
        "initial_train_fraction": initial_train_fraction,
        "test_fraction": test_fraction,
        "minimum_test_bars": minimum_test_bars,
        "strategy": asdict(strategy),
        "execution": asdict(execution),
        "fold_count": len(folds),
        "folds": folds,
        "aggregate": {
            "test_trigger_count": aggregate_triggers,
            "test_qualified_signal_count": aggregate_qualified,
            "closed_trades": aggregate_trades,
            "realized_net_profit_sum_of_folds": aggregate_profit,
            "warning": "sum of independent fold profits is not a compounded portfolio return",
        },
    }
