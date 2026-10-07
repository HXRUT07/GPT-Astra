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

Python engine รับ DataFrame OHLC ที่มี `timestamp` แบบ timezone-aware และไม่ดึงข้อมูลภายนอกเอง:

```python
from forex_signal.strategy import generate_signals
signals = generate_signals(frame, "XAUUSD", "M15")
```

ทุก trigger จะมี `qualified` และ `rejection_reasons` เพื่อแยก trigger ที่โดน session/เทรนด์/ATR/RSI กรองออก ไม่ตีความคะแนนหรือ signal เป็นโอกาสชนะ

## สิ่งที่ต้องยืนยันก่อนใช้จริง

เวลา London/New York เปลี่ยนตาม daylight saving และโบรกเกอร์แต่ละรายอาจใช้ server timezone ต่างกัน หน้าต่างคงที่ 14:00–02:00 จึงเป็น approximation ที่ต้องปรับและทดสอบกับข้อมูลจริง นอกจากนี้ราคา XAUUSD/Forex จากโบรกเกอร์มี spread, tick size, contract size และ swap ต่างกัน จึงยังคำนวณ lot 1–2% หรือ backtest รวมต้นทุนไม่ได้จาก blueprint เพียงอย่างเดียว

ไฟล์ Pine อยู่ที่ [tradingview/forex_signal.pine](tradingview/forex_signal.pine) และขั้นตอนตรวจด้วยตนเองอยู่ที่ [tradingview/README.md](tradingview/README.md) ต้อง compile และทดสอบ alert ใน TradingView ก่อนเชื่อม webhook
