# Forex and XAUUSD signal prototype

เฟสแรกจาก `ai_forex_signal_blueprint.pdf` ทำเฉพาะ deterministic signal engine และ TradingView alert candidate ก่อน ยังไม่มีข่าวเศรษฐกิจ, DXY, AI agent, Telegram, broker connection หรือการส่งคำสั่งซื้อขาย

กฎที่ทำไว้คือ EMA200 เป็นตัวกรองแนวโน้ม, EMA20/50 cross เป็น trigger, ATR14 ต้องมากกว่าค่าเฉลี่ย ATR 20 แท่ง, RSI14 ใช้ช่วง 52–68 สำหรับ BUY และ 32–48 สำหรับ SELL, และสัญญาณต้องอยู่ในหน้าต่าง 14:00–02:00 ตามเวลา Asia/Bangkok สำหรับ M15/M30/H1 ทั้งหมดเป็นเงื่อนไขของแท่งที่ปิดแล้ว

ตลาด spot Forex ไม่มี consolidated volume แบบตลาดหุ้น ระบบจึงไม่ใช้ volume และใช้ ATR เป็นตัววัด expansion ตาม blueprint แทน ส่วน `SL = 1.5 × ATR`, `TP = 3 × ATR` เป็น gross 2:1 ก่อน spread/commission/slippage

## ทดลองรัน

```bash
cd /workspace/GPT-Astra
uv sync --project forex-signal --cache-dir /tmp/gpt-astra-uv-cache
cd forex-signal && uv run pytest
```

ดึงข้อมูลสาธารณะสำหรับทดลองได้ด้วยคำสั่งนี้:

```bash
uv run --project forex-signal forex-download \
  --asset EURUSD --interval 15m --range 60d \
  --output forex-signal/data/EURUSD_M15.csv
```

ตัวดาวน์โหลดตัดแท่งปัจจุบันที่อาจยังไม่ปิด, ตัดแถว OHLC ที่ไม่ครบหรือผิดช่วง และบันทึก metadata กับ SHA-256 ไว้ข้างไฟล์ ข้อมูล Yahoo เป็น public exploratory feed มีประวัติ intraday จำกัดและไม่เท่ากับราคา/สเปรดของ broker

Python engine รับ DataFrame OHLC ที่มี `timestamp` แบบ timezone-aware และไม่ดึงข้อมูลภายนอกเอง:

```python
from forex_signal.strategy import generate_signals
signals = generate_signals(frame, "XAUUSD", "M15")
```

ทุก trigger จะมี `qualified` และ `rejection_reasons` เพื่อแยก trigger ที่โดน session/เทรนด์/ATR/RSI กรองออก ไม่ตีความคะแนนหรือ signal เป็นโอกาสชนะ

## Paper backtest ระยะสั้น

เมื่อมีไฟล์ CSV จาก broker/data feed ที่มีคอลัมน์ `timestamp,open,high,low,close` และ timestamp เป็น timezone-aware ให้รันได้ด้วย:

```bash
uv run --project forex-signal forex-signal candles.csv \
  --asset EURUSD --timeframe M15 \
  --output reports/eurusd-m15.json
```

Backtest จะเข้าเฉพาะแท่งถัดไปของสัญญาณที่ผ่าน, ใช้ spread เริ่มต้น `0.00008`, slippage 2 bps, ความเสี่ยง 1% ต่อครั้ง, leverage สูงสุด 30x และ contract 100,000 หน่วยสำหรับคู่เงินที่มี quote เป็น USD ค่าพวกนี้เป็นค่าเริ่มต้นเพื่อการวิจัย ไม่ใช่เงื่อนไขของ broker ใด หากเป็น XAUUSD ต้องตั้ง `contract_units`, `spread_price`, `quote_to_account`, commission และ leverage ตามสัญญาจริงผ่าน Python API ก่อนเชื่อถือผล

ผลลัพธ์จะแยก `closed_trades`, `open_position`, `rejected_entries`, drawdown และเหตุผลการออกจากตลาด ห้ามนำ `final_equity` ไปตีความเป็นยอดเงินจริง เพราะยังไม่รวม swap, margin call, ข่าว, การหลุดราคา และกฎ execution ของ broker

## รัน monitor ต่อเนื่อง

คำสั่งนี้จะดึงแท่งทุก 60 วินาที, ประมวลผลเฉพาะแท่งใหม่, กันสัญญาณซ้ำด้วย `state.json` และเขียนผลลง `events.jsonl`:

```bash
uv run --project forex-signal forex-monitor \
  --asset EURUSD --interval 15m --poll-seconds 60 \
  --output-dir forex-signal/reports/monitor
```

กด `Ctrl+C` เพื่อหยุดได้ การเริ่มครั้งแรกจะ warm-start ที่แท่งล่าสุด ไม่ replay trigger ย้อนหลังทั้ง 60 วัน; ใช้ `--replay-history` หากต้องการ replay ข้อมูลเก่า โหมดนี้ยังเป็น paper monitor: ไม่มี LLM/news/DXY adapter, ไม่มี Telegram และไม่มี broker order ดังนั้นผล Agent จะเป็น `REVIEW` เมื่อ macro context ยังไม่ถูกส่งเข้าไป

ถ้าต้องการให้เริ่มเองหลัง reboot ให้รันคำสั่งนี้ผ่าน systemd/Task Scheduler ของเครื่อง โดยใช้ user ที่มีสิทธิ์เขียน `reports/monitor` และอย่าใส่ API token ใน command line

## Review Agent

มี deterministic review agent สำหรับคัดกรองสัญญาณก่อนค่อยต่อ LLM:

```python
from forex_signal.agent import review_signal

decision = review_signal(
    signal,
    events=[{"currency": "USD", "impact": "HIGH", "timestamp": "2026-10-07T14:30:00Z"}],
    dxy={"direction": "UP"},
)
```

ผลลัพธ์เป็น `APPROVED`, `PAUSE` หรือ `REVIEW` พร้อมเหตุผล, ตรวจข่าวกล่องแดงในช่วง ±60 นาที และตรวจ DXY divergence สำหรับ EURUSD/XAUUSD คะแนนเป็น priority score ไม่ใช่เปอร์เซ็นต์ชนะ และ `execution_allowed` ถูกล็อกเป็น `false` เสมอในเฟสนี้ Agent ยังไม่ดึงข่าวเอง, ไม่เรียก LLM, ไม่ส่ง Telegram และไม่ส่งคำสั่ง broker

## สิ่งที่ต้องยืนยันก่อนใช้จริง

เวลา London/New York เปลี่ยนตาม daylight saving และโบรกเกอร์แต่ละรายอาจใช้ server timezone ต่างกัน หน้าต่างคงที่ 14:00–02:00 จึงเป็น approximation ที่ต้องปรับและทดสอบกับข้อมูลจริง นอกจากนี้ราคา XAUUSD/Forex จากโบรกเกอร์มี spread, tick size, contract size และ swap ต่างกัน จึงยังคำนวณ lot 1–2% หรือ backtest รวมต้นทุนไม่ได้จาก blueprint เพียงอย่างเดียว

ไฟล์ Pine อยู่ที่ [tradingview/forex_signal.pine](tradingview/forex_signal.pine) และขั้นตอนตรวจด้วยตนเองอยู่ที่ [tradingview/README.md](tradingview/README.md) ต้อง compile และทดสอบ alert ใน TradingView ก่อนเชื่อม webhook
