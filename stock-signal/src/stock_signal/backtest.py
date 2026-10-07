"""Conservative, single-symbol next-open backtesting on raw daily bars."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import pandas as pd

from .strategy import _reward_risk, _validate_costs, _validated_frame


@dataclass(frozen=True)
class BacktestConfig:
    starting_cash: float = 100_000.0
    risk_fraction: float = 0.01
    lot_size: int = 100
    commission_rate: float = 0.001
    slippage_bps: float = 10.0
    max_holding_bars: int = 20
    min_reward_risk: float = 2.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.starting_cash) or self.starting_cash <= 0:
            raise ValueError("starting_cash must be finite and positive")
        if not math.isfinite(self.risk_fraction) or not 0 < self.risk_fraction <= 1:
            raise ValueError("risk_fraction must be in (0, 1]")
        for name in ("lot_size", "max_holding_bars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not math.isfinite(self.min_reward_risk) or self.min_reward_risk <= 0:
            raise ValueError("min_reward_risk must be finite and positive")
        _validate_costs(self.commission_rate, self.slippage_bps)


def run_backtest(
    frame: pd.DataFrame,
    signals: list[dict],
    config: BacktestConfig = BacktestConfig(),
) -> dict:
    """Execute qualified signals at the following bar's open only.

    A signal never supplies an executable price. Recheck its actual historical
    stop/target against the slipped next-open fill. One position may be open;
    signals received while holding at the open are rejected even if an intraday
    exit later occurs. Stop takes priority when both levels lie inside a bar.
    Dividends accrue as cash on the ex-date to previous-close holders, with no
    withholding tax or payment-date delay. Unclosed positions remain open.
    """
    bars = _validated_frame(frame)
    cash = float(config.starting_cash)
    slip = config.slippage_bps / 10_000.0
    dates = {timestamp: index for index, timestamp in enumerate(bars["timestamp"])}
    tickers = {signal.get("ticker") for signal in signals if signal.get("ticker")}
    if len(tickers) > 1:
        raise ValueError("run_backtest requires signals for a single symbol")
    ticker = next(iter(tickers), None)
    pending: dict[int, list[dict]] = {}
    rejected: list[dict] = []
    trades: list[dict] = []
    equity: list[dict] = []
    position: dict | None = None
    total_dividends = 0.0
    holding_bars = 0

    def reject(signal: dict, reason: str, index: int | None = None, **details) -> None:
        rejected.append({
            "signal_id": signal.get("signal_id"),
            "signal_timestamp": signal.get("timestamp"),
            "entry_timestamp": bars.iloc[index]["timestamp"].isoformat() if index is not None else None,
            "reason": reason,
            "rejection_reasons": [reason],
            **details,
        })

    for signal in signals:
        if not signal.get("qualified", False):
            continue
        try:
            timestamp = pd.Timestamp(signal["timestamp"])
            if pd.isna(timestamp) or timestamp.tzinfo is None:
                raise ValueError("naive or missing timestamp")
            timestamp = timestamp.tz_convert("UTC")
        except (KeyError, TypeError, ValueError):
            reject(signal, "invalid_signal_timestamp")
            continue
        index = dates.get(timestamp)
        if index is None:
            reject(signal, "signal_not_in_data")
        elif index + 1 >= len(bars):
            reject(signal, "no_next_bar")
        else:
            pending.setdefault(index + 1, []).append(signal)

    peak = float(config.starting_cash)
    max_drawdown = 0.0
    for index, bar in bars.iterrows():
        timestamp = bar["timestamp"].isoformat()
        held_at_open = position is not None
        if held_at_open:
            dividend = float(bar["dividend"]) * position["quantity"]
            cash += dividend
            total_dividends += dividend
            position["dividends"] += dividend

        for signal in sorted(pending.get(index, []), key=lambda item: str(item.get("signal_id", ""))):
            if held_at_open or position is not None:
                reject(signal, "position_open", index)
                continue
            try:
                stop = float(signal["stop_loss"])
                target = float(signal["take_profit"])
            except (KeyError, TypeError, ValueError):
                reject(signal, "invalid_stop_or_target", index)
                continue
            entry = float(bar["open"]) * (1.0 + slip)
            gross_rr, net_rr, risk_per_share, reward_per_share = _reward_risk(
                entry, stop, target, config.commission_rate, config.slippage_bps
            )
            detail = {"actual_entry_price": entry, "reward_risk": gross_rr, "net_reward_risk": net_rr}
            if not all(math.isfinite(value) and value > 0 for value in (stop, target)):
                reject(signal, "invalid_stop_or_target", index, **detail)
                continue
            if stop >= entry:
                reject(signal, "stop_not_below_entry", index, **detail)
                continue
            if target <= entry:
                reject(signal, "target_not_above_entry", index, **detail)
                continue
            threshold = max(config.min_reward_risk, float(signal.get("min_reward_risk", config.min_reward_risk)))
            if not math.isfinite(threshold) or threshold <= 0:
                reject(signal, "invalid_reward_risk_threshold", index, **detail)
                continue
            if gross_rr < threshold:
                reject(signal, "gross_reward_risk_below_minimum", index, **detail)
                continue
            if net_rr < threshold or reward_per_share <= 0:
                reject(signal, "net_reward_risk_below_minimum", index, **detail)
                continue
            risk_budget = cash * config.risk_fraction
            unit_cost = entry * (1.0 + config.commission_rate)
            max_quantity = min(cash / unit_cost, risk_budget / risk_per_share)
            quantity = math.floor(max_quantity / config.lot_size) * config.lot_size
            if quantity < config.lot_size:
                reject(signal, "insufficient_cash_or_risk_budget_for_lot", index, **detail)
                continue
            entry_commission = quantity * entry * config.commission_rate
            entry_cost = quantity * entry + entry_commission
            cash -= entry_cost
            position = {
                "signal_id": signal.get("signal_id"),
                "ticker": signal.get("ticker", ticker),
                "signal_timestamp": signal["timestamp"],
                "entry_timestamp": timestamp,
                "entry_index": index,
                "entry_price": entry,
                "entry_commission": entry_commission,
                "entry_cost": entry_cost,
                "quantity": quantity,
                "stop_loss": stop,
                "take_profit": target,
                "reward_risk": gross_rr,
                "net_reward_risk": net_rr,
                "risk_budget": risk_budget,
                "planned_risk": risk_per_share * quantity,
                "dividends": 0.0,
            }

        if position is not None:
            holding_bars += 1
            duration = index - position["entry_index"] + 1
            stop = position["stop_loss"]
            target = position["take_profit"]
            exit_reference = None
            exit_reason = None
            fill_reason = None
            if float(bar["open"]) <= stop:
                exit_reference, exit_reason, fill_reason = float(bar["open"]), "stop_loss", "gap_stop"
            elif float(bar["open"]) >= target:
                exit_reference, exit_reason, fill_reason = target, "take_profit", "gap_target_at_target"
            elif float(bar["low"]) <= stop:
                exit_reference, exit_reason = stop, "stop_loss"
                fill_reason = "stop_first" if float(bar["high"]) >= target else "intrabar_stop"
            elif float(bar["high"]) >= target:
                exit_reference, exit_reason = target, "take_profit"
                fill_reason = "gap_target_at_target" if float(bar["open"]) >= target else "intrabar_target"
            elif duration >= config.max_holding_bars:
                exit_reference, exit_reason, fill_reason = float(bar["close"]), "max_holding_bars", "close"
            if exit_reference is not None:
                exit_price = exit_reference * (1.0 - slip)
                exit_commission = exit_price * position["quantity"] * config.commission_rate
                net_proceeds = exit_price * position["quantity"] - exit_commission
                cash += net_proceeds
                net_pnl = net_proceeds - position["entry_cost"] + position["dividends"]
                trades.append({
                    **{key: value for key, value in position.items() if key != "entry_index"},
                    "exit_timestamp": timestamp,
                    "exit_price": exit_price,
                    "exit_reference_price": exit_reference,
                    "exit_commission": exit_commission,
                    "exit_reason": exit_reason,
                    "fill_reason": fill_reason,
                    "holding_bars": duration,
                    "gross_pnl": (exit_price - position["entry_price"]) * position["quantity"],
                    "net_pnl": net_pnl,
                    "return_pct": 100.0 * net_pnl / position["entry_cost"],
                })
                position = None

        quantity = position["quantity"] if position else 0
        value = cash + quantity * float(bar["close"])
        peak = max(peak, value)
        drawdown = 100.0 * (peak - value) / peak
        max_drawdown = max(max_drawdown, drawdown)
        equity.append({
            "timestamp": timestamp,
            "cash": cash,
            "position_quantity": quantity,
            "close_price": float(bar["close"]),
            "equity": value,
            "drawdown_pct": drawdown,
        })

    final_equity = equity[-1]["equity"] if equity else float(config.starting_cash)
    open_position = None
    if position:
        mark = float(bars.iloc[-1]["close"])
        liquidation = mark * (1.0 - slip) * (1.0 - config.commission_rate) * position["quantity"]
        open_position = {
            **{key: value for key, value in position.items() if key != "entry_index"},
            "mark_timestamp": bars.iloc[-1]["timestamp"].isoformat(),
            "mark_price": mark,
            "market_value": mark * position["quantity"],
            "holding_bars": len(bars) - position["entry_index"],
            "unrealized_net_pnl_at_liquidation": liquidation - position["entry_cost"] + position["dividends"],
        }
    winners = [trade for trade in trades if trade["net_pnl"] > 0]
    losers = [trade for trade in trades if trade["net_pnl"] < 0]
    gross_profit = math.fsum(trade["net_pnl"] for trade in winners)
    gross_loss = -math.fsum(trade["net_pnl"] for trade in losers)
    return {
        "schema_version": 1,
        "ticker": ticker,
        "config": asdict(config),
        "metrics": {
            "starting_cash": float(config.starting_cash),
            "ending_cash": cash,
            "final_equity": final_equity,
            "total_return_pct": 100.0 * (final_equity / config.starting_cash - 1.0),
            "net_profit": final_equity - config.starting_cash,
            "realized_net_profit": math.fsum(trade["net_pnl"] for trade in trades),
            "closed_trades": len(trades),
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "breakeven_trades": len(trades) - len(winners) - len(losers),
            "win_rate_pct": 100.0 * len(winners) / len(trades) if trades else None,
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
            "max_drawdown_pct": max_drawdown,
            "dividends_received": total_dividends,
            "exposure_pct": 100.0 * holding_bars / len(bars) if len(bars) else 0.0,
            "open_positions": 1 if position else 0,
        },
        "equity": equity,
        "trades": trades,
        "rejected_entries": rejected,
        "open_position": open_position,
        "assumptions": [
            "One independent cash portfolio per symbol; no overlapping positions or portfolio aggregation.",
            "Qualified end-of-day signals enter only at the following available bar's open.",
            "Both stop and target touched in one bar: stop first; gap stops use open, gap targets use target.",
            "Every buy/sell has proportional commission and adverse slippage; gap losses can exceed planned risk.",
            "Dividends credited on ex-date to previous-close holders; payment delays and tax are omitted.",
            "Raw unadjusted OHLC prices; split-bearing datasets are explicitly unsupported.",
            "Maximum holding period exits at that bar's close; final open positions are marked, not forced closed.",
        ],
    }
