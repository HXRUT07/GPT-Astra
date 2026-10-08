//+------------------------------------------------------------------+
//| GPT Astra Candle Bridge                                          |
//| Sends completed OHLC bars only. It contains no trade functions.   |
//+------------------------------------------------------------------+
#property strict
#property version   "1.2"

input string          InpEndpoint      = "http://127.0.0.1:8787/v1/mt5/candle";
input string          InpBearerToken   = "CHANGE_ME_LONG_RANDOM_TOKEN";
input ENUM_TIMEFRAMES InpTimeframe     = PERIOD_M15;
input int             InpTimerSeconds  = 5;
input bool            InpSendLatest   = true;

datetime g_last_closed_bar = 0;

string TimeframeName(const ENUM_TIMEFRAMES timeframe)
  {
   if(timeframe == PERIOD_M1)  return "M1";
   if(timeframe == PERIOD_M5)  return "M5";
   if(timeframe == PERIOD_M15) return "M15";
   if(timeframe == PERIOD_M30) return "M30";
   if(timeframe == PERIOD_H1)  return "H1";
   if(timeframe == PERIOD_H4)  return "H4";
   if(timeframe == PERIOD_D1)  return "D1";
   return "UNKNOWN";
  }

int OnInit()
  {
   if(InpBearerToken == "" || InpBearerToken == "CHANGE_ME_LONG_RANDOM_TOKEN")
     {
      Print("Set a private bearer token in the EA inputs before starting.");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpEndpoint == "")
      return INIT_PARAMETERS_INCORRECT;
   if(!EventSetTimer(MathMax(InpTimerSeconds,1)))
      return INIT_FAILED;
   if(InpSendLatest)
      SendClosedBar();
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTimer()
  {
   SendClosedBar();
  }

void SendClosedBar()
  {
   // Request only shift 1 so a static array never selects the forming bar.
   MqlRates rates[1];
   if(CopyRates(_Symbol,InpTimeframe,1,1,rates) != 1)
      return;
   datetime closed_time = rates[0].time;
   if(closed_time <= g_last_closed_bar)
      return;

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol,tick))
      return;
   int digits = (int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   double point = SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   double spread = tick.ask - tick.bid;
   string timeframe = TimeframeName(InpTimeframe);
   if(timeframe == "UNKNOWN")
      return;

   string payload = "{";
   payload += "\"symbol\":\"" + _Symbol + "\",";
   payload += "\"timeframe\":\"" + timeframe + "\",";
   // MT5 bar times use broker time. Round the live server/GMT offset to minutes.
   payload += "\"timestamp_epoch\":" + IntegerToString((long)closed_time - (long)MathRound((double)(TimeTradeServer() - TimeGMT()) / 60.0) * 60) + ",";
   payload += "\"server_time\":\"" + TimeToString(closed_time,TIME_DATE|TIME_SECONDS) + "\",";
   payload += "\"open\":" + DoubleToString(rates[0].open,digits) + ",";
   payload += "\"high\":" + DoubleToString(rates[0].high,digits) + ",";
   payload += "\"low\":" + DoubleToString(rates[0].low,digits) + ",";
   payload += "\"close\":" + DoubleToString(rates[0].close,digits) + ",";
   payload += "\"tick_volume\":" + IntegerToString((int)rates[0].tick_volume) + ",";
   payload += "\"bid\":" + DoubleToString(tick.bid,digits) + ",";
   payload += "\"ask\":" + DoubleToString(tick.ask,digits) + ",";
   payload += "\"spread\":" + DoubleToString(spread,digits) + ",";
   payload += "\"digits\":" + IntegerToString(digits) + ",";
   payload += "\"point\":" + DoubleToString(point,digits) + ",";
   payload += "\"closed\":true}";

   char body[];
   StringToCharArray(payload,body,0,-1,CP_UTF8);
   if(ArraySize(body) > 0)
      ArrayResize(body,ArraySize(body)-1);
   string headers = "Content-Type: application/json\r\nAuthorization: Bearer " + InpBearerToken + "\r\n";
   char result[];
   string result_headers;
   ResetLastError();
   int code = WebRequest("POST",InpEndpoint,headers,5000,body,result,result_headers);
   if(code == 200)
      g_last_closed_bar = closed_time;
   else
      PrintFormat("GPT Astra bridge HTTP=%d error=%d; add endpoint to MT5 WebRequest allowlist",code,GetLastError());
  }
