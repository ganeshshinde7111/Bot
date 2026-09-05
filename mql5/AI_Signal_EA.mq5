//+------------------------------------------------------------------+
//|                                              AI_Signal_EA.mq5     |
//| Foundational MT5 Expert Advisor: computes an EMA-crossover +      |
//| RSI-filter signal each new bar and POSTs it as JSON to the        |
//| webhook_listener service so the MCP/Claude decision layer can     |
//| see it -- mirrors pine_scripts/ai_signal_bridge.pine so both      |
//| platforms feed the same downstream pipeline.                      |
//|                                                                     |
//| IMPORTANT: MT5's WebRequest() only works against URLs you have    |
//| explicitly whitelisted in Tools > Options > Expert Advisors >     |
//| "Allow WebRequest for listed URL". Add your VPS's HTTPS webhook   |
//| URL there first, or every WebRequest call fails with error 4060.  |
//+------------------------------------------------------------------+
#property copyright "AI Algo Trading Bot"
#property strict

input string WebhookURL      = "https://your-vps-domain.example/webhook/mt5";
input string WebhookSecret   = "CHANGE_ME"; // must match WEBHOOK_SHARED_SECRET
input int    FastEMAPeriod   = 9;
input int    SlowEMAPeriod   = 21;
input int    RSIPeriod       = 14;
input double RSILongThresh   = 55.0;
input double RSIShortThresh  = 45.0;

int fastEmaHandle, slowEmaHandle, rsiHandle;
datetime lastBarTime = 0;

int OnInit()
{
   fastEmaHandle = iMA(_Symbol, _Period, FastEMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
   slowEmaHandle = iMA(_Symbol, _Period, SlowEMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
   rsiHandle     = iRSI(_Symbol, _Period, RSIPeriod, PRICE_CLOSE);
   if(fastEmaHandle == INVALID_HANDLE || slowEmaHandle == INVALID_HANDLE || rsiHandle == INVALID_HANDLE)
   {
      Print("Failed to create indicator handles");
      return(INIT_FAILED);
   }
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   IndicatorRelease(fastEmaHandle);
   IndicatorRelease(slowEmaHandle);
   IndicatorRelease(rsiHandle);
}

void OnTick()
{
   datetime currentBarTime = iTime(_Symbol, _Period, 0);
   if(currentBarTime == lastBarTime) return; // only act once per closed bar
   lastBarTime = currentBarTime;

   double fastEma[], slowEma[], rsi[];
   ArraySetAsSeries(fastEma, true);
   ArraySetAsSeries(slowEma, true);
   ArraySetAsSeries(rsi, true);

   if(CopyBuffer(fastEmaHandle, 0, 1, 2, fastEma) < 2) return;
   if(CopyBuffer(slowEmaHandle, 0, 1, 2, slowEma) < 2) return;
   if(CopyBuffer(rsiHandle, 0, 1, 1, rsi) < 1) return;

   bool crossUp   = fastEma[1] <= slowEma[1] && fastEma[0] > slowEma[0];
   bool crossDown = fastEma[1] >= slowEma[1] && fastEma[0] < slowEma[0];

   string action = "HOLD";
   if(crossUp && rsi[0] > RSILongThresh)        action = "BUY";
   else if(crossDown && rsi[0] < RSIShortThresh) action = "SELL";

   if(action == "HOLD") return; // don't spam the webhook every bar

   SendSignal(action, fastEma[0], slowEma[0], rsi[0]);
}

void SendSignal(string action, double fastEma, double slowEma, double rsi)
{
   string json = StringFormat(
      "{\"secret\":\"%s\",\"symbol\":\"%s\",\"action\":\"%s\",\"price\":%.5f,"
      "\"timeframe\":\"%s\",\"strategy\":\"ema_rsi_v1_mt5\","
      "\"indicators\":{\"rsi\":%.2f,\"fast_ema\":%.5f,\"slow_ema\":%.5f}}",
      WebhookSecret, _Symbol, action, SymbolInfoDouble(_Symbol, SYMBOL_BID),
      EnumToString((ENUM_TIMEFRAMES)_Period), rsi, fastEma, slowEma
   );

   char postData[];
   StringToCharArray(json, postData, 0, StringLen(json));
   char result[];
   string resultHeaders;
   string headers = "Content-Type: application/json\r\n";

   int res = WebRequest("POST", WebhookURL, headers, 5000, postData, result, resultHeaders);
   if(res == -1)
      Print("WebRequest failed, error: ", GetLastError(), " -- check the whitelisted URL list.");
   else
      Print("Signal sent: ", json, " -> HTTP ", res);
}
//+------------------------------------------------------------------+
