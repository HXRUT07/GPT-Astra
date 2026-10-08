# FBS MT5 candle bridge

`GPT_Astra_CandleBridge.mq5` sends completed OHLC bars from the chart symbol to a local HTTP gateway. It has no `OrderSend`, position management or broker execution code.

## Local setup

Use bridge version 1.1 or later. Version 1.0 called `ArraySetAsSeries` on
a static two-element array; MT5 ignores that flag on static arrays, so index
1 selected the forming candle instead of the completed candle. Version 1.1
requests exactly one candle at shift 1 and reads index 0. Compile this version
in MetaEditor before collecting new data. This environment cannot compile MQL5.

Preserve databases collected with version 1.0 as unverified legacy data. Their
OHLC values may have been captured before the candle closed, so do not mix them
with the corrected feed for signal evaluation or backtests. Start version 1.1
with a separate database and monitor output directory, or rebuild the affected
history from verified completed broker candles. Do not delete the legacy data.

1. On the computer where FBS MT5 is installed, set a random token in the shell environment:

   ```bash
   export MT5_INGEST_TOKEN='use-a-long-random-token-here'
   ```

2. Start the gateway from the project root:

   ```bash
   uv run --project forex-signal forex-mt5-gateway \
     --host 127.0.0.1 --port 8787 \
     --db forex-signal/data/mt5-candles.sqlite3
   ```

   The gateway refuses to start if the token is missing or shorter than 16 characters. It accepts only `POST /v1/mt5/candle` and stores unique `(symbol, timeframe, timestamp)` rows in SQLite. `GET /health` is read-only.

3. In MT5, open `Tools → Options → Expert Advisors → Allow WebRequest for listed URL` and add exactly `http://127.0.0.1:8787`.

4. Open MetaEditor, compile the EA, attach it to the FBS symbol chart (start with `EURUSD`, M15), and set `InpBearerToken` to the same token. The EA sends shift-1, completed bars on a timer. MT5 server time is retained for audit, but the epoch timestamp is normalized to UTC by the gateway.

5. Export received candles for the existing strategy:

   ```bash
   uv run --project forex-signal forex-mt5-export \
     --db forex-signal/data/mt5-candles.sqlite3 \
     --symbol EURUSD --timeframe M15 \
     --output forex-signal/data/EURUSD_FBS_M15.csv
   ```

   Then run the local signal/backtest command on that CSV. The MT5 bridge and gateway remain paper/data-only.

To let the Agent consume the MT5 database continuously without a manual CSV export, run this in a second terminal:

```bash
uv run --project forex-signal forex-mt5-monitor \
  --db forex-signal/data/mt5-candles.sqlite3 \
  --symbol EURUSD --timeframe M15 \
  --poll-seconds 10 \
  --output-dir forex-signal/reports/mt5-monitor
```

Add `--gemini` only after setting `GEMINI_API_KEY` in that process environment. The monitor remains review/paper-only and does not invoke any MT5 order function.

The Python gateway and MQL5 source have been statically reviewed here; MetaEditor compilation and WebRequest delivery must be verified on the user's MT5 installation. If FBS displays a symbol suffix (for example a spread/account variant), use the exact chart symbol in `--symbol` and the EA sends that name automatically.
