# TradingView FX/XAUUSD trigger

`forex_signal.pine` is a Pine v6 indicator for M15, M30 and H1 Forex or XAUUSD charts. It uses EMA200 trend, EMA20/50 cross, ATR14 expansion above its 20-bar mean, RSI14 bounds and a fixed 14:00–02:00 Asia/Bangkok window. It emits BUY and SELL JSON only after a confirmed bar closes.

The file has not been compiled or run in a TradingView account here. Paste it into Pine Editor and resolve any compiler error before creating an alert. Create the alert with “Any alert() function call”; historical markers do not deliver historical webhooks.

The blueprint calls this window a London/New York overlap. A fixed 14:00–02:00 Bangkok interval is a broad London/New York liquidity window, not the exact overlap throughout the year. London and New York daylight-saving changes shift their Bangkok times. This first stage exposes `sessionTimezone` but does not infer DST or broker-server time. Align the chart timezone and the Python `ForexConfig` before comparing signals.

The script uses TradingView's built-in `ta.ema`, `ta.atr` and `ta.rsi`. The Python implementation uses the same indicator concepts but should be checked against the selected broker/provider's bars; different history, price precision, spread and timezone can change a cross. Spot-FX volume is not used because it is usually tick volume rather than consolidated bank volume.

The payload follows the PDF fields and is an alert candidate, not proof of execution:

```json
{
  "schema_version": 1,
  "asset": "XAUUSD",
  "action": "BUY",
  "timeframe": "M15",
  "session": "LONDON_NY_WINDOW",
  "trigger_price": 2650.40,
  "atr_14": 4.85,
  "suggested_sl": 2643.12,
  "suggested_tp": 2664.95,
  "rsi_14": 56.8,
  "session_timezone": "Asia/Bangkok",
  "timestamp": "2026-10-07T21:15:00+07:00"
}
```

`SL = 1.5 × ATR` and `TP = 3.0 × ATR` gives a gross 2:1 ratio before spread, commission, slippage and gap risk. The blueprint's 1–2% sizing rule is intentionally not implemented in this indicator; account currency, contract size, tick value and broker margin must be supplied by the execution venue before sizing.

Do not place API keys, Telegram tokens, broker credentials or webhook secrets in this file. A future receiver should validate the schema and durably queue the event before enrichment. TradingView documents that webhook requests taking longer than three seconds are cancelled and delivery can fail, so news/AI work must not block the acknowledgement path.
