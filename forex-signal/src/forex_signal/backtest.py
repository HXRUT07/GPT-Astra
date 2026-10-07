"""Broker-neutral paper backtest for short-term Forex/XAUUSD signals.

This is deliberately not an order router. It models a single position, the
next-bar entry, bid/ask spread, adverse slippage, configurable commission,
risk-based lot sizing and conservative OHLC exit ordering.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import pandas as pd

from .strategy import _validated_frame


@dataclass(frozen=True)
class ForexBacktestConfig:
    starting_equity: float = 10_000.0
    risk_fraction: float = 0.01
    contract_units: float = 100_000.0
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_leverage: float = 30.0
    spread_price: float = 0.00008
    slippage_bps: float = 2.0
    commission_per_lot: float = 0.0
    max_holding_bars: int = 96
    min_reward_risk: float = 2.0
    quote_to_account: float = 1.0

    def __post_init__(self) -> None:
        for name in ("starting_equity", "risk_fraction", "contract_units", "min_lot", "lot_step", "max_leverage", "quote_to_account"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.risk_fraction > 1:
            raise ValueError("risk_fraction must be at most 1")
        if self.commission_per_lot < 0 or not math.isfinite(self.commission_per_lot):
            raise ValueError("commission_per_lot must be finite and nonnegative")
        if self.spread_price < 0 or not math.isfinite(self.spread_price):
            raise ValueError("spread_price must be finite and nonnegative")
        if not 0 <= self.slippage_bps < 10_000 or not math.isfinite(self.slippage_bps):
            raise ValueError("slippage_bps must be in [0, 10000)")
        if not isinstance(self.max_holding_bars, int) or self.max_holding_bars < 1:
            raise ValueError("max_holding_bars must be a positive integer")
        if self.lot_step < self.min_lot:
            raise ValueError("lot_step must be at least min_lot")
        if not math.isfinite(self.min_reward_risk) or self.min_reward_risk <= 0:
            raise ValueError("min_reward_risk must be finite and positive")


def _round_lots(value: float, config: ForexBacktestConfig) -> float:
    if value < config.min_lot:
        return 0.0
    steps = math.floor((value + 1e-12) / config.lot_step)
    lots = steps * config.lot_step
    return round(lots, 10) if lots >= config.min_lot else 0.0


def _fill(reference: float, action: str, *, entry: bool, config: ForexBacktestConfig) -> float:
    half_spread = config.spread_price / 2.0
    slip = config.slippage_bps / 10_000.0
    if action == "BUY":
        raw = reference + half_spread if entry else reference - half_spread
        return raw * (1.0 + slip if entry else 1.0 - slip)
    raw = reference - half_spread if entry else reference + half_spread
    return raw * (1.0 - slip if entry else 1.0 + slip)


def run_backtest(
    frame: pd.DataFrame,
    signals: list[dict],
    config: ForexBacktestConfig = ForexBacktestConfig(),
) -> dict:
    """Run one-symbol paper trading with next-bar entries.

    The bar's stop is checked before its target when both are touched. A gap
    through a stop is filled at the adverse open. A gap through a target is
    filled at the target, not at a more favorable open. An open position is
    marked at the final bar and is never silently converted into a win/loss.
    """
    bars = _validated_frame(frame)
    timestamps = {value: index for index, value in enumerate(bars["timestamp"])}
    pending: dict[int, list[dict]] = {}
    rejected: list[dict] = []
    for signal in signals:
        if not signal.get("qualified", False):
            continue
        try:
            timestamp = pd.Timestamp(signal["timestamp"])
            if timestamp.tzinfo is None:
                raise ValueError
            timestamp = timestamp.tz_convert("UTC")
            index = timestamps.get(timestamp)
        except (KeyError, TypeError, ValueError):
            index = None
        if index is None:
            rejected.append({"signal_id": signal.get("signal_id"), "reason": "signal_not_in_data"})
        elif index + 1 >= len(bars):
            rejected.append({"signal_id": signal.get("signal_id"), "reason": "no_next_bar"})
        else:
            pending.setdefault(index + 1, []).append(signal)

    balance = float(config.starting_equity)
    position: dict | None = None
    trades: list[dict] = []
    equity_curve: list[dict] = []
    peak = balance
    max_drawdown = 0.0
    holding_bars = 0

    def reject(signal: dict, reason: str, index: int, **details: object) -> None:
        rejected.append({
            "signal_id": signal.get("signal_id"),
            "signal_timestamp": signal.get("timestamp"),
            "entry_timestamp": bars.iloc[index]["timestamp"].isoformat(),
            "reason": reason,
            **details,
        })

    for index, bar in bars.iterrows():
        timestamp = bar["timestamp"].isoformat()
        for signal in sorted(pending.get(index, []), key=lambda item: str(item.get("signal_id", ""))):
            if position is not None:
                reject(signal, "position_open", index)
                continue
            action = str(signal.get("action", "")).upper()
            if action not in {"BUY", "SELL"}:
                reject(signal, "invalid_action", index)
                continue
            try:
                stop = float(signal["suggested_sl"])
                target = float(signal["suggested_tp"])
            except (KeyError, TypeError, ValueError):
                reject(signal, "invalid_stop_or_target", index)
                continue
            entry = _fill(float(bar["open"]), action, entry=True, config=config)
            valid_direction = stop < entry < target if action == "BUY" else target < entry < stop
            gross_rr = abs(target - entry) / abs(entry - stop) if valid_direction else None
            if not valid_direction:
                reject(signal, "stop_target_wrong_side_of_entry", index, actual_entry=entry, reward_risk=gross_rr)
                continue
            threshold = max(config.min_reward_risk, float(signal.get("min_reward_risk", config.min_reward_risk)))
            if gross_rr < threshold:
                reject(signal, "actual_reward_risk_below_minimum", index, actual_entry=entry, reward_risk=gross_rr)
                continue
            risk_per_lot = abs(entry - stop) * config.contract_units * config.quote_to_account + 2.0 * config.commission_per_lot
            if risk_per_lot <= 0:
                reject(signal, "zero_risk_distance", index)
                continue
            risk_budget = balance * config.risk_fraction
            lots_by_risk = risk_budget / risk_per_lot
            lots_by_leverage = balance * config.max_leverage / (entry * config.contract_units * config.quote_to_account)
            lots = _round_lots(min(lots_by_risk, lots_by_leverage), config)
            if lots <= 0:
                reject(signal, "insufficient_equity_for_min_lot", index, risk_budget=risk_budget)
                continue
            units = lots * config.contract_units
            entry_commission = lots * config.commission_per_lot
            balance -= entry_commission
            position = {
                "signal_id": signal.get("signal_id"), "asset": signal.get("asset"), "action": action,
                "signal_timestamp": signal.get("timestamp"), "entry_timestamp": timestamp,
                "entry_index": index, "entry_price": entry, "stop_loss": stop, "take_profit": target,
                "lots": lots, "units": units, "entry_commission": entry_commission,
                "reward_risk": gross_rr, "risk_budget": risk_budget,
            }

        if position is not None:
            holding_bars += 1
            action = position["action"]
            stop, target = position["stop_loss"], position["take_profit"]
            open_price, high, low = float(bar["open"]), float(bar["high"]), float(bar["low"])
            exit_reference = None
            exit_reason = None
            fill_reason = None
            if action == "BUY":
                if open_price <= stop:
                    exit_reference, exit_reason, fill_reason = open_price, "stop_loss", "gap_stop"
                elif open_price >= target:
                    exit_reference, exit_reason, fill_reason = target, "take_profit", "gap_target_at_target"
                elif low <= stop:
                    exit_reference, exit_reason = stop, "stop_loss"
                    fill_reason = "stop_first" if high >= target else "intrabar_stop"
                elif high >= target:
                    exit_reference, exit_reason, fill_reason = target, "take_profit", "intrabar_target"
            else:
                if open_price >= stop:
                    exit_reference, exit_reason, fill_reason = open_price, "stop_loss", "gap_stop"
                elif open_price <= target:
                    exit_reference, exit_reason, fill_reason = target, "take_profit", "gap_target_at_target"
                elif high >= stop:
                    exit_reference, exit_reason = stop, "stop_loss"
                    fill_reason = "stop_first" if low <= target else "intrabar_stop"
                elif low <= target:
                    exit_reference, exit_reason, fill_reason = target, "take_profit", "intrabar_target"
            duration = index - position["entry_index"] + 1
            if exit_reference is None and duration >= config.max_holding_bars:
                exit_reference, exit_reason, fill_reason = float(bar["close"]), "max_holding_bars", "close"
            if exit_reference is not None:
                exit_price = _fill(exit_reference, action, entry=False, config=config)
                exit_commission = position["lots"] * config.commission_per_lot
                price_pnl = (exit_price - position["entry_price"]) * position["units"] if action == "BUY" else (position["entry_price"] - exit_price) * position["units"]
                net_pnl = price_pnl * config.quote_to_account - position["entry_commission"] - exit_commission
                balance += price_pnl * config.quote_to_account - exit_commission
                trades.append({
                    **{key: value for key, value in position.items() if key != "entry_index"},
                    "exit_timestamp": timestamp, "exit_reference_price": exit_reference,
                    "exit_price": exit_price, "exit_commission": exit_commission,
                    "exit_reason": exit_reason, "fill_reason": fill_reason,
                    "holding_bars": duration, "net_pnl": net_pnl,
                    "return_pct": 100.0 * net_pnl / max(abs(position["entry_price"] * position["units"]) * config.quote_to_account, 1e-12),
                })
                position = None

        marked = balance
        if position is not None:
            mark_reference = float(bar["close"])
            mark_price = _fill(mark_reference, position["action"], entry=False, config=config)
            unrealized = ((mark_price - position["entry_price"]) if position["action"] == "BUY" else (position["entry_price"] - mark_price)) * position["units"] * config.quote_to_account
            marked += unrealized
        peak = max(peak, marked)
        max_drawdown = max(max_drawdown, 100.0 * (peak - marked) / peak)
        equity_curve.append({"timestamp": timestamp, "balance": balance, "equity": marked, "position": position["action"] if position else None})

    open_position = None
    if position is not None:
        mark = float(bars.iloc[-1]["close"])
        mark_price = _fill(mark, position["action"], entry=False, config=config)
        unrealized = ((mark_price - position["entry_price"]) if position["action"] == "BUY" else (position["entry_price"] - mark_price)) * position["units"] * config.quote_to_account
        open_position = {**{key: value for key, value in position.items() if key != "entry_index"}, "mark_price": mark_price, "unrealized_pnl": unrealized, "mark_timestamp": bars.iloc[-1]["timestamp"].isoformat()}

    winners = [trade for trade in trades if trade["net_pnl"] > 0]
    losers = [trade for trade in trades if trade["net_pnl"] < 0]
    gross_profit = math.fsum(trade["net_pnl"] for trade in winners)
    gross_loss = -math.fsum(trade["net_pnl"] for trade in losers)
    final_equity = equity_curve[-1]["equity"] if equity_curve else config.starting_equity
    return {
        "schema_version": 1,
        "config": asdict(config),
        "metrics": {
            "starting_equity": config.starting_equity, "ending_balance": balance, "final_equity": final_equity,
            "total_return_pct": 100.0 * (final_equity / config.starting_equity - 1.0),
            "realized_net_profit": math.fsum(trade["net_pnl"] for trade in trades),
            "closed_trades": len(trades), "winning_trades": len(winners), "losing_trades": len(losers),
            "win_rate_pct": 100.0 * len(winners) / len(trades) if trades else None,
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "max_drawdown_pct": max_drawdown, "exposure_pct": 100.0 * holding_bars / len(bars) if len(bars) else 0.0,
            "open_positions": 1 if position else 0,
        },
        "equity": equity_curve, "trades": trades, "rejected_entries": rejected, "open_position": open_position,
        "assumptions": [
            "Qualified completed-bar signals enter at the next bar open.",
            "Bid/ask spread is represented by half-spread on each side; slippage is adverse.",
            "Stops are checked before targets when both are touched in one OHLC bar.",
            "Gap stops fill at the adverse open; gap targets fill at the target, not a favorable open.",
            "Risk sizing uses configured contract units, leverage and quote-to-account conversion.",
            "This is paper research only; broker execution, swaps, margin calls and news are not modeled.",
        ],
    }
