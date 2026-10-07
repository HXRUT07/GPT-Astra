# SET daily stock signal prototype

ต้นแบบระยะแรกของโปรเจกต์จาก `ai_stock_signal_blueprint.pdf` ใช้ข้อมูลราคาหุ้นไทยรายวันจาก Yahoo Finance เพื่อทดสอบกฎที่ตรวจสอบซ้ำได้ก่อนต่อกับข่าว, LLM, Telegram หรือระบบส่งคำสั่งซื้อขาย

ระบบนี้เป็นงานวิจัยและ paper backtest เท่านั้น ไม่มี broker connection, API key, การแจ้งเตือนภายนอก หรือการส่งคำสั่งซื้อขาย

## สิ่งที่ทำแล้ว

- ทดลองดึงข้อมูล 5 ปีของ `KBANK.BK`, `SCB.BK`, `PTT.BK`, `ADVANC.BK`, `CPALL.BK`
- เก็บ OHLCV แบบ raw พร้อมวันเวลาที่ดึงข้อมูล, SHA-256 ของ response/CSV และรายการแถวที่ตัดออก
- ตัดแท่งของวันปัจจุบันในเขตเวลา Asia/Bangkok เสมอ และไม่เติมข้อมูลแถวที่หาย
- ใช้กฎ EMA20/50/200, breakout 20 วัน, volume มากกว่า 1.5 เท่าของค่าเฉลี่ย 20 วัน, RSI14 50–70 และ reward/risk ขั้นต่ำ 2:1
- สร้าง payload JSON ตาม schema ของ blueprint พร้อม stop, target, gross/net reward-risk และเหตุผลที่ไม่ผ่าน
- backtest ซื้อที่เปิดของวันถัดไป หักค่าธรรมเนียม 0.1% และ slippage 10 bps ต่อขา, ใช้ lot 100 หุ้น และจัดการ gap/stop/target/dividend อย่างอนุรักษ์นิยม
- มี Pine Script สำหรับ TradingView ที่เขียนกฎเดียวกันและส่ง JSON หลังแท่งปิด โดยยังต้อง compile/ตรวจบน TradingView เอง

## วิธีรัน

ต้องใช้ Python 3.11+ และ `uv`:

```bash
cd /workspace/GPT-Astra
uv sync --project stock-signal --cache-dir /tmp/gpt-astra-uv-cache
uv run --project stock-signal stock-signal run \
  --data-dir stock-signal/data \
  --report-dir stock-signal/reports/latest
```

แยกดึงข้อมูลหรือรัน backtest ได้ด้วยคำสั่ง `probe` และ `backtest` รายงาน JSON จะอยู่ใน `stock-signal/reports/latest/` ข้อมูลราคาและรายงานที่สร้างจากการรันถูก ignore จาก git เพื่อไม่ฝัง dataset ที่เปลี่ยนทุกวันลงใน source

รันทดสอบด้วย:

```bash
uv run --project stock-signal pytest
```

## ผลการตรวจล่าสุด

การทดลองวันที่ 7 ตุลาคม 2026 ได้ข้อมูลที่ผ่านการตรวจ 1,085–1,217 แท่งต่อหุ้น (ประมาณ 4–5 ปี) พบแถว OHLC ผิดช่วง 1–2 แถวต่อหุ้นและตัดออกพร้อมบันทึกเหตุผล ไม่พบ split ในช่วงที่ตรวจ

สัญญาณดิบมี 54–82 ครั้งต่อหุ้น แต่สัญญาณที่ผ่านทุก gate เป็น 0 ครั้งทั้ง 5 หุ้น เพราะ volume, RSI, ระดับ target ย้อนหลัง และ net reward/risk 2:1 มักไม่ผ่านพร้อมกัน ดังนั้น backtest รอบนี้มี 0 trade และห้ามตีความเป็นผลกำไรหรือขาดทุนของกลยุทธ์

## ข้อจำกัดที่ต้องแก้ก่อนใช้งานจริง

Yahoo endpoint นี้เป็น exploratory source; license, ความครบถ้วนของปฏิทิน SET, ข่าว, งบการเงิน และ earnings calendar ยังไม่ได้ยืนยัน ระบบปฏิเสธชุดข้อมูลที่มี split จนกว่าจะทำ as-of adjustment ที่ถูกต้อง และ timestamp ของผู้ให้บริการเป็น candle label จึงต้องเทียบด้วย session date เมื่อเชื่อม TradingView

อ่านรายละเอียด TradingView, payload และขั้นตอนตรวจด้วยตนเองที่ [tradingview/README.md](tradingview/README.md)
