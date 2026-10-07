# TradingView signal generator

`stock_signal.pine` is a Pine Script v6 indicator for **SET shares on a standard 1D chart**. It emits a JSON alert only after a daily bar closes and both the technical and risk gates pass. It does not place orders or backtest trades. This file has not been compiled or executed in TradingView; the checks below require manual validation in the Pine Editor.

## Rules shared with the Python default strategy

- At least 200 bars have been observed and `close > EMA200`.
- `EMA20` crosses above `EMA50`, **or** the close exceeds the highest high of the previous 20 bars.
- Current volume is strictly greater than 1.5 times the previous 20 bars' mean volume. The signal bar is excluded from that mean.
- Wilder RSI14 is within 50–70, including the endpoints.
- Support/stop is the previous 20 bars' lowest low. Resistance/target is the previous 60 bars' highest high. The signal bar is excluded from both windows.
- Both gross and net reward/risk must be at least 2. The levels must satisfy `0 < stop < close < target`, and the estimated slipped entry must remain below the target.

Each EMA is initialized with the arithmetic mean of its first complete period, then updated recursively with `alpha=2/(period+1)`, matching Python. This seed differs from TradingView's built-in `ta.ema`; comparing against a separate built-in EMA can show differences near the beginning of the history. RSI uses arithmetic-mean-seeded Wilder averages and a neutral value of 50 when both averaged gains and losses are zero, also matching Python.

An all-time-high breakout can fail because the historical target is below the entry. The script rejects it rather than creating a target to satisfy the ratio. The PDF example with entry 152.50, support 147.00 and resistance 162.00 also fails: its gross reward/risk is approximately 1.73, before costs.

The configurable transaction costs must match the Python configuration: `commission_rate=0.001` per side (0.1%) and `slippage_bps=10` per side (0.1%) by default. With `C=close`, `S=stop`, `T=target`, `f=commission_rate` and `s=slippage_bps/10000`:

```text
gross_reward_risk = (T - C) / (C - S)
estimated_entry  = C * (1 + s)
entry_cost       = estimated_entry * (1 + f)
stop_proceeds    = S * (1 - s) * (1 - f)
target_proceeds  = T * (1 - s) * (1 - f)
net_reward_risk  = (target_proceeds - entry_cost) / (entry_cost - stop_proceeds)
```

These costs are configurable assumptions, not a quotation of a broker's total charges. Real spreads, gaps, liquidity and charges can differ. The Python backtest rechecks risk using the next session's executable entry; an eligible closing-bar signal can therefore fail the entry-time gate.

## Install and inspect

1. Open a SET stock such as `SET:KBANK`, select **1D**, and use standard candles or bars. The script raises an error on another exchange, timeframe or synthetic chart type.
2. Open Pine Editor, paste `stock_signal.pine`, save, and select **Add to chart**. Resolve any editor/compiler error before creating an alert.
3. Check EMA values, prior-bar support/target, RSI, volume multiple and both reward/risk values in the chart's Data Window. Confirm that the windows exclude the signal bar and no qualified marker is displayed on an unclosed bar.
4. Keep Python's default periods and thresholds unchanged for a comparison. If those Python settings change, update the corresponding Pine constants/calculations before comparing results. Match both configurable cost inputs as well.
5. Record the chart's price-adjustment settings and data provider. Compare only aligned session dates and OHLCV data; divergent historical data can produce different signals even with identical rules.

TradingView chart adjustments for splits/dividends and Yahoo/provider adjustment options can differ. The current Python engine requires raw, unadjusted OHLCV and rejects a window containing a stock split. Use a split-free comparison window and disable dividend adjustment in TradingView; verify the actual OHLCV values still match. Historical adjusted prices are not necessarily the cash prices traded on those dates. Daily candle timestamps also differ: Pine reports the confirmed bar's closing time; a provider may label daily data with local midnight. Normalize the SET session date and symbol for comparisons rather than comparing raw timestamps. Additional historical warm-up data changes the EMA seed, so compare the same starting history where possible. A matching lookback length alone does not ensure identical initial history.

## Create an alert after validation

Complete the manual fixture and chart checks below before enabling a live alert.

Select this indicator in TradingView's **Create Alert** dialog and choose **Any alert() function call**. The script supplies the JSON message and uses `alert.freq_once_per_bar_close`; it also requires `barstate.isconfirmed`. Historical chart markers do not send historical alerts. Each qualifying subsequent bar can emit another signal; the breakout rule is a price condition rather than a one-shot crossover.

For this first stage, inspect notifications or the alert log. A receiving server is not part of this implementation. Configure a webhook only when a receiver is available. Keep API keys, passwords, broker credentials and bot tokens out of the script, payload and example URLs. Changing the script or its inputs requires recreating an existing TradingView alert because alerts retain a saved copy of their script/settings.

The [TradingView webhook documentation](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/) states that requests taking longer than three seconds are cancelled and webhook delivery can fail. A future receiver should validate and durably queue each event before promptly acknowledging it; enrichment and model analysis should run separately.

## Payload contract

Every qualified event includes the blueprint's fields plus deterministic risk details:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1` |
| `signal_id` | Stable source-specific identifier for the symbol, strategy, bar-close timestamp and cost settings |
| `ticker`, `market`, `timeframe` | Chart symbol without its exchange prefix; `SET`; `1D` |
| `strategy_name` | `EMA_Trend_Breakout_V1` |
| `timestamp` | Confirmed bar's closing time as ISO 8601 UTC, ending in `Z` |
| `entry_trigger_price` | Signal-bar close; not a guaranteed execution price |
| `support_level`, `stop_loss` | Previous 20 bars' lowest low |
| `resistance_level`, `take_profit` | Previous 60 bars' highest high |
| `volume_multiple` | Signal volume divided by the prior 20 bars' mean volume |
| `rsi_14` | Wilder RSI14 |
| `reward_risk` | Gross ratio based on the signal close |
| `net_reward_risk` | Ratio after configured commission and adverse slippage |
| `commission_rate`, `slippage_bps` | Cost assumptions included for auditability |

Pine IDs use `1|strategy|exchange:ticker|1D|bar_close_epoch_ms|fee=...|slip_bps=...`. Python IDs use a SHA256 fingerprint with its provider timestamp and configuration. Each is deterministic within its source; they are not interchangeable. A later receiver should deduplicate within the source and normalize session date, symbol and settings for cross-source reconciliation. Neither timestamps nor these IDs establish that an alert was delivered or that an order was executed.

## Manual acceptance checks

Before creating an alert, use a temporary scratch copy in Pine Editor to inspect the calculations with these fixed inputs, then restore the production price series. With default costs, the risk calculations should produce:

| Close / stop / target | Gross reward/risk | Net reward/risk | Risk gate only |
| --- | --- | --- | --- |
| 152.50 / 147 / 162 | 1.7272727273 | 1.4545009838 | Reject |
| 100 / 99 / 102 | 2.0000000000 | 1.1416315153 | Reject |
| 100 / 98 / 106 | 3.0000000000 | 2.3322209247 | Pass |

These fixtures check the risk gate independently; a passing fixture does not establish that the technical conditions pass. Also inspect `seededEma` using a scratch source increasing from 1 to 21 with period 20: its first defined result should be 10.5 on observation 20, then 11.5 on observation 21. A flat scratch price series should yield RSI 50 after Wilder warm-up. These Pine fixture checks have not been run here.

- Pine Editor accepts version 6 and the complete script without errors.
- SET/1D standard-chart inputs run; non-SET, other timeframes and synthetic charts fail visibly.
- There are no alerts during the first 199 bars, before daily confirmation, or when required data/volume is missing.
- Both qualifying trigger types work; RSI endpoints are allowed, while exactly 1.5 volume multiple is rejected.
- Setups below either 2:1 gate are rejected; changing cost inputs can reduce qualifying signals.
- A live qualified event's alert-log message parses as JSON and contains the fields above with finite numbers. Daily signals may be sparse; absence of a live event alone does not establish successful alert delivery.

Compilation, chart comparisons, live alert timing and actual delivery remain manual checks in TradingView. No TradingView account access or live webhook delivery has been tested here.
