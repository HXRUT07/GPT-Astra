from datetime import datetime, timezone

import pandas as pd

from stock_signal.analysis import gate_funnel, walk_forward
from stock_signal.backtest import BacktestConfig
from stock_signal.strategy import StrategyConfig


def test_gate_funnel_counts_sequentially_and_raw_reasons():
    signals = [
        {"qualified": True, "rejection_reasons": []},
        {"qualified": False, "rejection_reasons": ["below_trend", "rsi_out_of_range"]},
        {"qualified": False, "rejection_reasons": ["insufficient_volume", "net_reward_risk_below_minimum"]},
        {"qualified": False, "rejection_reasons": ["target_not_above_entry"]},
    ]
    result = gate_funnel(signals)
    assert result["trigger_count"] == 4
    assert result["stages"][0] == {"gate": "trend", "input": 4, "passed": 3, "rejected": 1}
    assert result["stages"][1]["input"] == 3
    assert result["stages"][-1]["passed"] == 1
    assert result["qualified_count"] == 1
    assert result["raw_rejection_reason_counts"]["rsi_out_of_range"] == 1


def test_walk_forward_has_nonoverlapping_test_windows():
    count = 420
    close = [100.0 + (index % 7) * 0.1 for index in range(count)]
    frame = pd.DataFrame({
        "timestamp": pd.date_range(datetime(2020, 1, 1, tzinfo=timezone.utc), periods=count, freq="D"),
        "open": close, "high": [value + 0.5 for value in close],
        "low": [value - 0.5 for value in close], "close": close,
        "volume": [1000.0] * count, "dividend": [0.0] * count, "split_ratio": [1.0] * count,
    })
    strategy = StrategyConfig()
    result = walk_forward(frame, "TEST.BK", strategy, BacktestConfig(), initial_train_fraction=.5, test_fraction=.2, minimum_test_bars=50)
    assert result["fold_count"] == 2
    assert all(fold["train_bars"] >= strategy.trend + 1 for fold in result["folds"])
    assert result["folds"][0]["test_end_inclusive"] < result["folds"][1]["test_start"]
    assert result["parameter_selection"].startswith("none")
