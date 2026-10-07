# FBS MT5 candle bridge

`GPT_Astra_CandleBridge.mq5` sends completed OHLC bars from the chart symbol to a local HTTP gateway. It has no `OrderSend`, position management or broker execution code.

## Local setup

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

The Python gateway and MQL5 source have been statically reviewed here; MetaEditor compilation and WebRequest delivery must be verified on the user's MT5 installation. If FBS displays a symbol suffix (for example a spread/account variant), use the exact chart symbol in `--symbol` and the EA sends that name automatically.
