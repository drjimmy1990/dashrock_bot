//+------------------------------------------------------------------------------+
//|                                       Coded by rOcKDaSh |
//|                                  rock.dash@engineer.com |
//|                                           t.me/rOcKDaSh |
//|                                         00201000690806  |
//+-------------------DO NOT REMOVE THIS HEADER----------------------------------+
#property copyright   "Coded by rOcKDaSh"
#property description "V1.11: Dashboard + Daily Limits + Comment."
#property description "V1.10: News Filter + OCO_REFILL + Spread + Equity Guard."
#property description "V1.8.7: REENTER infinite-loop fix. V1.7: Trail minStep. V1.5: Auto Lot."
#property description "----------------------------------------------------------"
#property version     "1.11"
#property strict
#include <Trade\Trade.mqh>

CTrade trade;

// OCO behaviour when a leg triggers
enum ENUM_OCO_MODE
{
   OCO_DELETE  = 0,  // Delete:  Cancel opposite pending orders and restart fresh
   OCO_REENTER = 1,  // ReEnter: Keep opposite pending + re-enter same direction if conditions met
   OCO_WAIT    = 2,  // Wait:    Keep all pending orders, no action until they resolve
   OCO_REFILL  = 3   // Refill:  Keep opposite pending, refill missing side after close + cooldown
};

// News filter impact level
enum ENUM_NEWS_IMPACT
{
   NEWS_HIGH_ONLY   = 0,  // High Impact Only
   NEWS_MEDIUM_HIGH = 1,  // Medium + High Impact
   NEWS_ALL         = 2   // All Impact Levels
};

input group "=== Multi-Timeframe Settings ==="
input ENUM_TIMEFRAMES InpTimeFrame    = PERIOD_M5; 
input int             InpLookbackBars = 20;
input int             InpOffset       = 0;

input group "=== Position Sizing ==="
input double InpLotSize1     = 0.10;    // Leg 1 Lot Size
input double InpLotSize2     = 0.05;    // Leg 2 Lot Size (0 = disabled)
input int    InpStopLoss     = 200;
input int    InpTakeProfit   = 700;

input group "=== Auto Lot ==="
input bool   InpUseAutoLot     = false;   // Enable Auto Lot
input double InpAutoLotBalance = 1000;    // Base balance for lot calculation

input group "=== Leg 1 — Trailing Stop ==="
input bool   InpLot1Trail      = true;    // Enable Trailing for Leg 1
input int    InpTrailStart1    = 400;     // Trail Start (points)
input int    InpTrailStep1     = 200;     // Trail Step (points)

input group "=== Leg 1 — Break-Even ==="
input bool   InpLot1BE         = false;   // Enable Break-Even for Leg 1
input int    InpBE_Trigger1    = 400;     // BE Trigger (points)
input int    InpBE_LockPips1   = 200;     // BE Lock Profit (points)

input group "=== Leg 2 — Trailing Stop ==="
input bool   InpLot2Trail      = true;    // Enable Trailing for Leg 2
input int    InpTrailStart2    = 400;     // Trail Start (points)
input int    InpTrailStep2     = 200;     // Trail Step (points)

input group "=== Leg 2 — Break-Even ==="
input bool   InpLot2BE         = false;   // Enable Break-Even for Leg 2
input int    InpBE_Trigger2    = 400;     // BE Trigger (points)
input int    InpBE_LockPips2   = 200;     // BE Lock Profit (points)

input group "=== Time Filter & Auto Kill Switch ==="
input bool   InpUseTimeFilter      = false;
input int    InpStartHour          = 9;
input int    InpEndHour            = 22;
input bool   InpUseAutoKill        = true;  // Enable dynamic session closer
input int    InpMinutesBeforeClose = 15;    // Minutes before session close
input int    InpMaxSpread          = 0;     // Max spread in points (0 = disabled)

input group "=== Equity Guard ==="
input bool   InpUseEquityGuard     = false;   // Enable Equity Guard
input double InpMaxDrawdownPct     = 20.0;    // Max drawdown % from balance (e.g. 20 = lock at 80% equity)

input group "=== Daily Limits ==="
input double InpMaxDailyLossPct    = 0;       // Max Daily Loss % (0 = disabled, e.g. 5 = stop after -5%)
input double InpMaxDailyProfitPct  = 0;       // Max Daily Profit % (0 = disabled, e.g. 3 = stop after +3%)

input group "=== News Filter ==="
input bool              InpUseNewsFilter    = false;   // Enable News Filter (uses MT5 Economic Calendar)
input int               InpNewsMinsBefore   = 30;      // Minutes before news to stop trading
input int               InpNewsMinsAfter    = 15;      // Minutes after news to resume trading
input ENUM_NEWS_IMPACT  InpNewsImpact       = NEWS_HIGH_ONLY; // Minimum news impact to filter

input group "=== Advanced ==="
input int    InpUpdateThreshold    = 100;      // Min points change to update pending
input long   InpMagic1             = 690806;   // Magic Number Leg 1 (0 = Service Mode: manage ALL positions)
input long   InpMagic2             = 690807;   // Magic Number Leg 2 (ignored in Service Mode)
input ENUM_OCO_MODE InpOCOMode           = OCO_DELETE;  // OCO Mode: Delete / ReEnter / Wait
input int    InpMaxReEnter         = 1;         // Max re-entries per direction (OCO_REENTER only)
input int    InpCooldownBars       = 0;        // Bars to wait after close before new orders (0 = off)
input bool   InpUseDupFilter       = false;    // Skip if pending/position exists at same price
input int    InpPointScale         = 10;       // Point multiplier (10 = 1 pip, XAUUSD: 200 = $2)
input string InpComment            = "rOcKDaSh"; // Order comment
input bool   InpShowDashboard      = true;       // Show Dashboard on chart

ulong magic_leg1;
ulong magic_leg2;
double g_pipSize;                              // = InpPointScale * _Point
datetime g_lastCloseBar  = 0;
int      g_prevPositions = 0;
datetime g_lastError4756 = 0;                  // Cooldown: last time error 4756 occurred
datetime g_lastForceClose = 0;                 // Cooldown: last ForceCloseAll attempt
bool     g_equityLocked   = false;             // Equity Guard: permanently locked until EA restart
double   g_dayStartBalance = 0;                // Daily Limits: balance at start of trading day
int      g_dayStartDay     = -1;               // Daily Limits: day of month when balance was recorded
bool     g_dailyLocked     = false;            // Daily Limits: locked for today (resets at midnight)

//+------------------------------------------------------------------+
//| Service Mode: Magic1 = 0 → manage ALL positions on this symbol   |
//+------------------------------------------------------------------+
bool IsServiceMode()
{
   return (InpMagic1 == 0);
}

//+------------------------------------------------------------------+
//| Helper: Check if a magic belongs to us                           |
//| In Service Mode: always true (manage all positions)              |
//+------------------------------------------------------------------+
bool IsOurMagic(long magic)
{
   if(IsServiceMode()) return true;
   return (magic == (long)magic_leg1 || magic == (long)magic_leg2);
}

bool IsLeg2Enabled()
{
   return (!IsServiceMode() && InpLotSize2 > 0);
}

//+------------------------------------------------------------------+
//| Helper: Get broker minimum distance for pending orders (price)   |
//| Prevents error 4756 "invalid price" when market moves fast       |
//+------------------------------------------------------------------+
double GetMinDist()
{
   long stopsLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   // Use at least 1 pip as minimum even if broker reports 0
   double minDist = MathMax((double)stopsLevel, (double)InpPointScale) * _Point;
   return minDist;
}

//+------------------------------------------------------------------+
//| Helper: Calculate auto lot based on balance                      |
//| Formula: lot = (balance / baseBalance) * baseLot                 |
//| Example: $1000 base, 0.10 lot → $2000 = 0.20, $500 = 0.05        |
//+------------------------------------------------------------------+
double CalcAutoLot(double baseLot)
{
   if(!InpUseAutoLot || InpAutoLotBalance <= 0)
      return baseLot;
   
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double lot = (balance / InpAutoLotBalance) * baseLot;
   
   return lot;
}

//+------------------------------------------------------------------+
//| Helper: Check if a pending order or position already exists at   |
//| a given price on this symbol (from OTHER EAs, skips our magic)   |
//+------------------------------------------------------------------+
bool IsPriceAlreadyUsed(double price)
{
   double tolerance = 5.0 * _Point;   // Tight tolerance: only exact duplicates
   
   // Check pending orders only (skip our own magic)
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderSelect(ticket))
      {
         if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
         if(IsOurMagic(OrderGetInteger(ORDER_MAGIC))) continue;
         double orderPrice = OrderGetDouble(ORDER_PRICE_OPEN);
         if(MathAbs(price - orderPrice) <= tolerance)
            return true;
      }
   }
   
   return false;
}

//+------------------------------------------------------------------+
//| Helper: Count managed positions (all in service mode, own only   |
//| in normal mode), filtered by symbol                              |
//+------------------------------------------------------------------+
int CountOwnPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
      {
         if(IsOurMagic(PositionGetInteger(POSITION_MAGIC)) &&
            PositionGetString(POSITION_SYMBOL) == _Symbol)
            count++;
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Helper: Count own pending orders (filtered by magic + symbol)    |
//| Always uses own magic (service mode has no pending management)   |
//+------------------------------------------------------------------+
int CountOwnOrders()
{
   int count = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(OrderSelect(ticket))
      {
         if(IsOurMagic(OrderGetInteger(ORDER_MAGIC)) &&
            OrderGetString(ORDER_SYMBOL) == _Symbol)
            count++;
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Helper: Validate and normalize lot size                          |
//+------------------------------------------------------------------+
double ValidateLot(double lot)
{
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   
   lot = MathMax(lot, minLot);
   lot = MathMin(lot, maxLot);
   lot = MathFloor(lot / lotStep) * lotStep;
   
   int digits = (int)MathCeil(-MathLog10(lotStep));
   lot = NormalizeDouble(lot, digits);
   
   return lot;
}

//+------------------------------------------------------------------+
//| Reactive Duplicate Cleanup — GROUP-BASED                         |
//|                                                                  |
//| Problem with per-order check: if M1's Leg1 (ticket 501) falls    |
//| between M5's Leg1 (500) and Leg2 (502), the old logic would      |
//| wrongly delete M5's Leg2 (501 < 502 → "older dup exists").       |
//|                                                                  |
//| Fix: compare GROUPS atomically.                                  |
//|   minOwn    = earliest ticket among OUR orders at this price     |
//|   minForeign= earliest ticket among FOREIGN orders at this price |
//|   If minForeign < minOwn → delete ALL our orders at this price   |
//|   If minOwn <= minForeign → we were first, keep all ours         |
//|                                                                  |
//| Result: Leg1 + Leg2 always survive or die together as a unit.    |
//| Skipped in Service Mode (no pending orders to manage)            |
//+------------------------------------------------------------------+
void CleanDuplicates()
{
   if(!InpUseDupFilter || IsServiceMode()) return;
   
   double tolerance = 5.0 * _Point;
   
   // --- Step 1: collect unique price levels of OWN pending orders ---
   double ownPrices[];
   int    priceCount = 0;
   
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !OrderSelect(ticket)) continue;
      if(!IsOurMagic(OrderGetInteger(ORDER_MAGIC))) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      
      double price = OrderGetDouble(ORDER_PRICE_OPEN);
      bool found = false;
      for(int k = 0; k < priceCount; k++)
         if(MathAbs(ownPrices[k] - price) <= tolerance) { found = true; break; }
      if(!found)
      {
         ArrayResize(ownPrices, priceCount + 1);
         ownPrices[priceCount++] = price;
      }
   }
   
   // --- Step 2: for each price level, compare group min-tickets ---
   for(int p = 0; p < priceCount; p++)
   {
      double checkPrice = ownPrices[p];
      
      ulong minOwnTicket     = ULONG_MAX;
      ulong minForeignTicket = ULONG_MAX;
      
      for(int i = OrdersTotal() - 1; i >= 0; i--)
      {
         ulong t = OrderGetTicket(i);
         if(t == 0 || !OrderSelect(t)) continue;
         if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
         if(MathAbs(OrderGetDouble(ORDER_PRICE_OPEN) - checkPrice) > tolerance) continue;
         
         bool isOwn = IsOurMagic(OrderGetInteger(ORDER_MAGIC));
         if(isOwn)    { if(t < minOwnTicket)     minOwnTicket     = t; }
         else         { if(t < minForeignTicket)  minForeignTicket = t; }
      }
      
      // Foreign EA was first → delete ALL our orders at this price
      if(minForeignTicket < minOwnTicket)
      {
         for(int i = OrdersTotal() - 1; i >= 0; i--)
         {
            ulong t = OrderGetTicket(i);
            if(t == 0 || !OrderSelect(t)) continue;
            long ordMagic = OrderGetInteger(ORDER_MAGIC);
            if(!IsOurMagic(ordMagic)) continue;
            if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
            if(MathAbs(OrderGetDouble(ORDER_PRICE_OPEN) - checkPrice) > tolerance) continue;
            
            trade.SetExpertMagicNumber((ulong)ordMagic);
            trade.OrderDelete(t);
            PrintFormat("[rOcKDaSh] DupFilter: Removed #%d at %.5f (foreign EA was first: ticket %d < %d)",
                        t, checkPrice, minForeignTicket, minOwnTicket);
         }
      }
   }
   trade.SetExpertMagicNumber(magic_leg1);
}

int OnInit()
{
   magic_leg1 = (ulong)InpMagic1;
   magic_leg2 = (ulong)InpMagic2;
   g_pipSize  = InpPointScale * _Point;
   trade.SetExpertMagicNumber(magic_leg1);
   
   if(IsServiceMode())
      PrintFormat("[rOcKDaSh] Init: SERVICE MODE — Trailing/BE will apply to ALL positions on %s", _Symbol);
   else
      PrintFormat("[rOcKDaSh] Init: NORMAL MODE — Magic1=%d Magic2=%d | _Point=%.5f Scale=%d PipSize=%.5f",
                  InpMagic1, InpMagic2, _Point, InpPointScale, g_pipSize);
   
   if(InpUseEquityGuard)
      PrintFormat("[rOcKDaSh] Init: Equity Guard ON — max drawdown %.1f%%", InpMaxDrawdownPct);
   if(InpMaxSpread > 0)
      PrintFormat("[rOcKDaSh] Init: Spread Filter ON — max %d points", InpMaxSpread);
   if(InpUseNewsFilter)
      PrintFormat("[rOcKDaSh] Init: News Filter ON — %d min before / %d min after | Impact: %s",
                  InpNewsMinsBefore, InpNewsMinsAfter,
                  InpNewsImpact == NEWS_HIGH_ONLY ? "High" : InpNewsImpact == NEWS_MEDIUM_HIGH ? "Medium+High" : "All");
   if(InpMaxDailyLossPct > 0)
      PrintFormat("[rOcKDaSh] Init: Max Daily Loss ON — %.1f%%", InpMaxDailyLossPct);
   if(InpMaxDailyProfitPct > 0)
      PrintFormat("[rOcKDaSh] Init: Max Daily Profit ON — %.1f%%", InpMaxDailyProfitPct);
   // Dashboard: draw immediately + start timer for updates when market is closed
   if(InpShowDashboard)
   {
      DrawDashboard();
      EventSetTimer(1);  // 1-second timer for dashboard refresh
   }
   
   return INIT_SUCCEEDED;
}

void OnTimer()
{
   if(InpShowDashboard) DrawDashboard();
}

void OnDeinit(const int reason)
{
   PrintFormat("[rOcKDaSh] Deinit: reason=%d (%s)", reason,
               reason == REASON_REMOVE     ? "EA Removed" :
               reason == REASON_CHARTCHANGE ? "Chart Changed" :
               reason == REASON_RECOMPILE   ? "Recompiled" :
               reason == REASON_PARAMETERS  ? "Inputs Changed" :
               reason == REASON_ACCOUNT     ? "Account Changed" :
               reason == REASON_CLOSE       ? "Terminal Closed" : "Other");
   
   DeleteDashboard();
   EventKillTimer();
   
   // Only delete pending orders when EA is explicitly removed,
   // NOT on chart-change — that caused order deletion + re-placement loops.
   if(reason == REASON_REMOVE && !IsServiceMode())
   {
      DeleteAllPending();
   }
}

void OnTick()
{
   // Guard: skip if trading is disabled (Algo Trading button off)
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED)) return;

   // Dashboard: always update first (before any early returns)
   if(InpShowDashboard) DrawDashboard();

   // Equity Guard: if locked, do nothing (EA must be removed and re-attached to reset)
   if(g_equityLocked) return;

   // Equity Guard: check drawdown
   if(InpUseEquityGuard && InpMaxDrawdownPct > 0)
   {
      double balance = AccountInfoDouble(ACCOUNT_BALANCE);
      double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
      if(balance > 0)
      {
         double drawdownPct = ((balance - equity) / balance) * 100.0;
         if(drawdownPct >= InpMaxDrawdownPct)
         {
            PrintFormat("[rOcKDaSh] EQUITY GUARD TRIGGERED: Drawdown %.1f%% >= %.1f%% | Balance=%.2f Equity=%.2f",
                        drawdownPct, InpMaxDrawdownPct, balance, equity);
            PrintFormat("[rOcKDaSh] EQUITY GUARD: Closing ALL positions & orders -- EA is LOCKED");
            g_lastForceClose = 0;  // Bypass cooldown — this is an emergency
            ForceCloseAll();
            // Only lock if all positions are actually closed
            if(CountOwnPositions() == 0)
               g_equityLocked = true;
            // If positions still open (e.g. market closed), retry next tick
            return;
         }
      }
   }
   // Daily Limits: reset at start of new day
   MqlDateTime dtNow;
   TimeCurrent(dtNow);
   if(dtNow.day != g_dayStartDay)
   {
      g_dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      g_dayStartDay     = dtNow.day;
      g_dailyLocked     = false;  // Reset daily lock
      PrintFormat("[rOcKDaSh] New trading day — daily balance snapshot: %.2f", g_dayStartBalance);
   }

   // Daily Limits: check P&L
   if(g_dailyLocked)
   {
      // Still allow BE + Trailing for open positions, but skip everything else
      int curPos = CountOwnPositions();
      if(curPos > 0)
      {
         ManageBreakEven();
         ManageTrailingStop();
      }
      return;
   }

   if(g_dayStartBalance > 0 && (InpMaxDailyLossPct > 0 || InpMaxDailyProfitPct > 0))
   {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double dailyPnlPct = ((equity - g_dayStartBalance) / g_dayStartBalance) * 100.0;
      
      if(InpMaxDailyLossPct > 0 && dailyPnlPct <= -InpMaxDailyLossPct)
      {
         PrintFormat("[rOcKDaSh] DAILY LOSS LIMIT: P&L %.1f%% <= -%.1f%% | Start=%.2f Equity=%.2f",
                     dailyPnlPct, InpMaxDailyLossPct, g_dayStartBalance, equity);
         PrintFormat("[rOcKDaSh] DAILY LOSS LIMIT: Closing positions & orders — locked until tomorrow");
         g_lastForceClose = 0;
         ForceCloseAll();
         if(CountOwnPositions() == 0)
            g_dailyLocked = true;
         return;
      }
      
      if(InpMaxDailyProfitPct > 0 && dailyPnlPct >= InpMaxDailyProfitPct)
      {
         PrintFormat("[rOcKDaSh] DAILY PROFIT TARGET: P&L +%.1f%% >= +%.1f%% | Start=%.2f Equity=%.2f",
                     dailyPnlPct, InpMaxDailyProfitPct, g_dayStartBalance, equity);
         PrintFormat("[rOcKDaSh] DAILY PROFIT TARGET: Closing positions & orders — locked until tomorrow");
         g_lastForceClose = 0;
         ForceCloseAll();
         if(CountOwnPositions() == 0)
            g_dailyLocked = true;
         return;
      }
   }

   // 0. Reactive duplicate cleanup (skipped in service mode)
   CleanDuplicates();

   // 1. Dynamic Kill Switch
   if(InpUseAutoKill && IsKillZone())
   {
      PrintFormat("[rOcKDaSh] KILL ZONE active — closing all positions & orders");
      ForceCloseAll();
      return;
   }

   // Track position count (used for cooldown detection + management)
   int currentPositions = CountOwnPositions();
   
   // Detect position close for cooldown
   if(g_prevPositions > 0 && currentPositions == 0)
   {
      g_lastCloseBar = iTime(_Symbol, InpTimeFrame, 0);
   }
   
   // One-time log when position opens under WAIT/REFILL mode
   if(g_prevPositions == 0 && currentPositions > 0)
   {
      if(InpOCOMode == OCO_WAIT)
         PrintFormat("[rOcKDaSh] OCO WAIT: Position opened — keeping all pending, no new placements");
      else if(InpOCOMode == OCO_REFILL)
         PrintFormat("[rOcKDaSh] OCO REFILL: Position opened — keeping pending, will refill missing side after close");
   }
   
   g_prevPositions = currentPositions;

   // 2. Position Management (BE + Trailing) — runs in both modes
   if(currentPositions > 0)
   {
      ManageBreakEven();
      ManageTrailingStop();
   }

   // 2b. Retry missing Leg 2 if Leg 1 was placed but Leg 2 failed
   PlaceMissingLeg2();

   // ── Service Mode stops here: no breakout order logic ──────────────
   if(IsServiceMode()) return;

   // 3. Static Time Filter (Normal Mode only)
   if(InpUseTimeFilter && !IsTradingTime())
   {
      if(CountOwnOrders() > 0)
      {
         PrintFormat("[rOcKDaSh] Outside trading hours (%d-%d) — deleting pending orders", InpStartHour, InpEndHour);
         DeleteAllPending();
      }
      return;
   }

   // ── Compute breakout prices early — needed by OCO ReEnter + step 4 ──
   double high[];
   double low[];
   ArraySetAsSeries(high, true);
   ArraySetAsSeries(low, true);
   
   double buyPrice  = 0;
   double sellPrice = 0;
   
   if(CopyHigh(_Symbol, InpTimeFrame, 1, InpLookbackBars, high) > 0 &&
      CopyLow (_Symbol, InpTimeFrame, 1, InpLookbackBars, low)  > 0)
   {
      double ask0 = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double bid0 = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      buyPrice  = NormalizeDouble(high[ArrayMaximum(high)] + InpOffset * g_pipSize, _Digits);
      sellPrice = NormalizeDouble(low [ArrayMinimum(low)]  - InpOffset * g_pipSize, _Digits);
      double mDist0 = GetMinDist();
      if(buyPrice  <= ask0 + mDist0) buyPrice  = 0;  // too close — will not use
      if(sellPrice >= bid0 - mDist0) sellPrice = 0;
   }

   // OCO Logic — 4 modes (must run even during wide spread for cleanup)
   if(currentPositions > 0)
   {
      if(InpOCOMode == OCO_DELETE)
      {
         // Mode 1: Delete all pending → next tick starts fresh after position closes
         if(CountOwnOrders() > 0)
         {
            PrintFormat("[rOcKDaSh] OCO DELETE: Position active — deleting pending orders");
            DeleteAllPending();
         }
         return;
      }
      else if(InpOCOMode == OCO_REENTER)
      {
         // Mode 2: Keep opposite pending, try to re-enter same direction
         HandleReEnter(buyPrice, sellPrice);
         return;
      }
      else // OCO_WAIT or OCO_REFILL — while position is active, both behave the same
      {
         // Keep existing pending at correct levels, NO new placements until position closes
         if(CountOwnOrders() > 0)
            UpdatePendingOrders(buyPrice, sellPrice);
         return;
      }
   }

   // 3b. Spread Filter — block new order PLACEMENT when spread is too wide
   // Placed AFTER OCO block so OCO cleanup still works during wide spread
   if(InpMaxSpread > 0)
   {
      double askSF = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double bidSF = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      int currentSpread = (int)MathRound((askSF - bidSF) / _Point);
      if(currentSpread > InpMaxSpread)
      {
         static datetime lastSpreadLog = 0;
         if(TimeCurrent() - lastSpreadLog >= 60)  // Log once per minute to avoid spam
         {
            PrintFormat("[rOcKDaSh] Spread filter: %d > %d points — skipping order placement", currentSpread, InpMaxSpread);
            lastSpreadLog = TimeCurrent();
         }
         return;
      }
   }

   // 3c. News Filter — block new orders around high-impact news events
   if(InpUseNewsFilter && IsNewsTime())
   {
      static datetime lastNewsLog = 0;
      if(TimeCurrent() - lastNewsLog >= 60)
      {
         PrintFormat("[rOcKDaSh] News filter: upcoming/recent news event — skipping order placement");
         lastNewsLog = TimeCurrent();
      }
      return;
   }

   // Cooldown: Wait X bars after last close
   if(InpCooldownBars > 0 && g_lastCloseBar > 0)
   {
      int barsSinceClose = iBarShift(_Symbol, InpTimeFrame, g_lastCloseBar, false);
      if(barsSinceClose < 0) barsSinceClose = InpCooldownBars;  // treat invalid shift as expired
      if(barsSinceClose < InpCooldownBars)
      {
         static datetime lastCooldownLog = 0;
         if(TimeCurrent() - lastCooldownLog >= 60)
         {
            PrintFormat("[rOcKDaSh] Cooldown: waiting %d/%d bars before new orders", barsSinceClose, InpCooldownBars);
            lastCooldownLog = TimeCurrent();
         }
         return;
      }
   }

   // 4. Breakout Logic (Normal Mode only) — prices already computed above
   if(buyPrice == 0 && sellPrice == 0) return;  // both invalid this tick

   if(CountOwnOrders() == 0)
   {
      PlaceBreakoutOrders(buyPrice, sellPrice);
   }
   else if(InpOCOMode == OCO_REFILL)
   {
      // Mode 4: Refill — place only the missing side + update existing
      RefillMissingOrders(buyPrice, sellPrice);
   }
   else
   {
      UpdatePendingOrders(buyPrice, sellPrice);
   }
}

//+------------------------------------------------------------------+
//| Place breakout pending orders for both legs                      |
//+------------------------------------------------------------------+
void PlaceBreakoutOrders(double buyPrice, double sellPrice)
{
   // Self-guard — if we already have our own orders, skip placement.
   if(CountOwnOrders() > 0)
      return;

   // Duplicate filter: check each side independently
   if(InpUseDupFilter)
   {
      if(buyPrice > 0 && IsPriceAlreadyUsed(buyPrice))
      {
         PrintFormat("[rOcKDaSh] DupFilter: Buy side blocked (price %.5f already used)", buyPrice);
         buyPrice = 0;
      }
      if(sellPrice > 0 && IsPriceAlreadyUsed(sellPrice))
      {
         PrintFormat("[rOcKDaSh] DupFilter: Sell side blocked (price %.5f already used)", sellPrice);
         sellPrice = 0;
      }
      if(buyPrice == 0 && sellPrice == 0) return;
   }

   // Final guard: re-check stops level distance before placement
   double ask2  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid2  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double minDist = GetMinDist();
   if(buyPrice <= ask2 + minDist)
   {
      PrintFormat("[rOcKDaSh] PlaceBreakout: BuyStop %.5f too close to ask %.5f (minDist=%.5f) — skipped", buyPrice, ask2, minDist);
      buyPrice = 0;   // disable buy leg this tick
   }
   if(sellPrice >= bid2 - minDist)
   {
      PrintFormat("[rOcKDaSh] PlaceBreakout: SellStop %.5f too close to bid %.5f (minDist=%.5f) — skipped", sellPrice, bid2, minDist);
      sellPrice = 0;  // disable sell leg this tick
   }
   if(buyPrice == 0 && sellPrice == 0) return;

   double buySL  = buyPrice  > 0 ? buyPrice  - InpStopLoss  * g_pipSize : 0;
   double buyTP  = buyPrice  > 0 ? buyPrice  + InpTakeProfit * g_pipSize : 0;
   double sellSL = sellPrice > 0 ? sellPrice + InpStopLoss  * g_pipSize : 0;
   double sellTP = sellPrice > 0 ? sellPrice - InpTakeProfit * g_pipSize : 0;
   
   string comment1 = StringFormat("%s|L1|%d", InpComment, magic_leg1);
   
   // --- Leg 1 ---
   double lot1 = ValidateLot(CalcAutoLot(InpLotSize1));
   trade.SetExpertMagicNumber(magic_leg1);
   
   if(buyPrice > 0)
   {
      if(trade.BuyStop(lot1, buyPrice, _Symbol, buySL, buyTP, ORDER_TIME_GTC, 0, comment1))
         PrintFormat("[rOcKDaSh] L1 BuyStop PLACED: %.5f | Lot=%.2f | SL=%.5f | TP=%.5f", buyPrice, lot1, buySL, buyTP);
      else
         PrintFormat("[rOcKDaSh] L1 BuyStop FAILED: error %d", GetLastError());
   }
      
   if(sellPrice > 0)
   {
      if(trade.SellStop(lot1, sellPrice, _Symbol, sellSL, sellTP, ORDER_TIME_GTC, 0, comment1))
         PrintFormat("[rOcKDaSh] L1 SellStop PLACED: %.5f | Lot=%.2f | SL=%.5f | TP=%.5f", sellPrice, lot1, sellSL, sellTP);
      else
         PrintFormat("[rOcKDaSh] L1 SellStop FAILED: error %d", GetLastError());
   }
   
   // --- Leg 2 ---
   if(IsLeg2Enabled())
   {
      string comment2 = StringFormat("%s|L2|%d", InpComment, magic_leg2);
      double lot2 = ValidateLot(CalcAutoLot(InpLotSize2));
      trade.SetExpertMagicNumber(magic_leg2);
      
      // Re-fetch price: market may have moved since L1 was placed
      double askNow = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double bidNow = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double mDist  = GetMinDist();
      
      double buy2  = (buyPrice  > 0 && buyPrice  > askNow + mDist) ? buyPrice  : 0;
      double sell2 = (sellPrice > 0 && sellPrice < bidNow - mDist) ? sellPrice : 0;
      
      if(buy2 == 0 && buyPrice > 0)
         PrintFormat("[rOcKDaSh] L2 BuyStop %.5f skipped — market moved (ask=%.5f), will retry next tick", buyPrice, askNow);
      if(sell2 == 0 && sellPrice > 0)
         PrintFormat("[rOcKDaSh] L2 SellStop %.5f skipped — market moved (bid=%.5f), will retry next tick", sellPrice, bidNow);
      
      if(buy2 > 0)
      {
         if(trade.BuyStop(lot2, buy2, _Symbol, buySL, buyTP, ORDER_TIME_GTC, 0, comment2))
            PrintFormat("[rOcKDaSh] L2 BuyStop PLACED: %.5f | Lot=%.2f | SL=%.5f | TP=%.5f", buy2, lot2, buySL, buyTP);
         else
            PrintFormat("[rOcKDaSh] L2 BuyStop FAILED: error %d", GetLastError());
      }
         
      if(sell2 > 0)
      {
         if(trade.SellStop(lot2, sell2, _Symbol, sellSL, sellTP, ORDER_TIME_GTC, 0, comment2))
            PrintFormat("[rOcKDaSh] L2 SellStop PLACED: %.5f | Lot=%.2f | SL=%.5f | TP=%.5f", sell2, lot2, sellSL, sellTP);
         else
            PrintFormat("[rOcKDaSh] L2 SellStop FAILED: error %d", GetLastError());
      }
      
      trade.SetExpertMagicNumber(magic_leg1);
   }
}

//+------------------------------------------------------------------+
//| OCO Refill Mode: place only the MISSING side after position close |
//| Called when currentPositions == 0 and some pending orders exist   |
//| Scans existing orders to find which side is present, places the   |
//| other side fresh, and updates existing orders to latest levels.   |
//+------------------------------------------------------------------+
void RefillMissingOrders(double buyPrice, double sellPrice)
{
   // --- Step 1: Check which sides already have pending orders ---
   bool hasBuyStop  = false;
   bool hasSellStop = false;
   
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(t == 0 || !OrderSelect(t)) continue;
      if(!IsOurMagic(OrderGetInteger(ORDER_MAGIC))) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      long typ = OrderGetInteger(ORDER_TYPE);
      if(typ == ORDER_TYPE_BUY_STOP)  hasBuyStop  = true;
      if(typ == ORDER_TYPE_SELL_STOP) hasSellStop = true;
   }
   
   // If both sides already exist, just update them
   if(hasBuyStop && hasSellStop)
   {
      UpdatePendingOrders(buyPrice, sellPrice);
      return;
   }
   
   // --- Step 2: Place the missing side ---
   double ask2  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid2  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double mDist = GetMinDist();
   
   // Place missing BUY side
   if(!hasBuyStop && buyPrice > 0 && buyPrice > ask2 + mDist)
   {
      // DupFilter check
      if(InpUseDupFilter && IsPriceAlreadyUsed(buyPrice))
      {
         PrintFormat("[rOcKDaSh] REFILL: Buy side blocked by DupFilter (%.5f)", buyPrice);
      }
      else
      {
         double buySL = buyPrice - InpStopLoss  * g_pipSize;
         double buyTP = buyPrice + InpTakeProfit * g_pipSize;
         
         // Leg 1
         double lot1 = ValidateLot(CalcAutoLot(InpLotSize1));
         string c1 = StringFormat("%s|L1|%d", InpComment, magic_leg1);
         trade.SetExpertMagicNumber(magic_leg1);
         if(trade.BuyStop(lot1, buyPrice, _Symbol, buySL, buyTP, ORDER_TIME_GTC, 0, c1))
            PrintFormat("[rOcKDaSh] REFILL L1 BuyStop PLACED: %.5f | Lot=%.2f", buyPrice, lot1);
         else
            PrintFormat("[rOcKDaSh] REFILL L1 BuyStop FAILED: error %d", GetLastError());
         
         // Leg 2
         if(IsLeg2Enabled())
         {
            double lot2 = ValidateLot(CalcAutoLot(InpLotSize2));
            string c2 = StringFormat("%s|L2|%d", InpComment, magic_leg2);
            trade.SetExpertMagicNumber(magic_leg2);
            double askNow = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
            if(buyPrice > askNow + mDist)
            {
               if(trade.BuyStop(lot2, buyPrice, _Symbol, buySL, buyTP, ORDER_TIME_GTC, 0, c2))
                  PrintFormat("[rOcKDaSh] REFILL L2 BuyStop PLACED: %.5f | Lot=%.2f", buyPrice, lot2);
               else
                  PrintFormat("[rOcKDaSh] REFILL L2 BuyStop FAILED: error %d", GetLastError());
            }
         }
      }
   }
   else if(!hasBuyStop && buyPrice > 0)
   {
      PrintFormat("[rOcKDaSh] REFILL: Buy side skipped — price %.5f too close to ask %.5f (minDist=%.5f)", buyPrice, ask2, mDist);
   }
   
   // Place missing SELL side
   if(!hasSellStop && sellPrice > 0 && sellPrice < bid2 - mDist)
   {
      // DupFilter check
      if(InpUseDupFilter && IsPriceAlreadyUsed(sellPrice))
      {
         PrintFormat("[rOcKDaSh] REFILL: Sell side blocked by DupFilter (%.5f)", sellPrice);
      }
      else
      {
         double sellSL = sellPrice + InpStopLoss  * g_pipSize;
         double sellTP = sellPrice - InpTakeProfit * g_pipSize;
         
         // Leg 1
         double lot1 = ValidateLot(CalcAutoLot(InpLotSize1));
         string c1 = StringFormat("%s|L1|%d", InpComment, magic_leg1);
         trade.SetExpertMagicNumber(magic_leg1);
         if(trade.SellStop(lot1, sellPrice, _Symbol, sellSL, sellTP, ORDER_TIME_GTC, 0, c1))
            PrintFormat("[rOcKDaSh] REFILL L1 SellStop PLACED: %.5f | Lot=%.2f", sellPrice, lot1);
         else
            PrintFormat("[rOcKDaSh] REFILL L1 SellStop FAILED: error %d", GetLastError());
         
         // Leg 2
         if(IsLeg2Enabled())
         {
            double lot2 = ValidateLot(CalcAutoLot(InpLotSize2));
            string c2 = StringFormat("%s|L2|%d", InpComment, magic_leg2);
            trade.SetExpertMagicNumber(magic_leg2);
            double bidNow = SymbolInfoDouble(_Symbol, SYMBOL_BID);
            if(sellPrice < bidNow - mDist)
            {
               if(trade.SellStop(lot2, sellPrice, _Symbol, sellSL, sellTP, ORDER_TIME_GTC, 0, c2))
                  PrintFormat("[rOcKDaSh] REFILL L2 SellStop PLACED: %.5f | Lot=%.2f", sellPrice, lot2);
               else
                  PrintFormat("[rOcKDaSh] REFILL L2 SellStop FAILED: error %d", GetLastError());
            }
         }
      }
   }
   else if(!hasSellStop && sellPrice > 0)
   {
      PrintFormat("[rOcKDaSh] REFILL: Sell side skipped — price %.5f too close to bid %.5f (minDist=%.5f)", sellPrice, bid2, mDist);
   }
   
   trade.SetExpertMagicNumber(magic_leg1);
   
   // --- Step 3: Update existing orders to latest breakout levels ---
   UpdatePendingOrders(buyPrice, sellPrice);
}

//+------------------------------------------------------------------+
//| OCO ReEnter Mode: keep opposite pending, add same-direction order|
//| Called when currentPositions > 0 and OCO_REENTER is active       |
//+------------------------------------------------------------------+
void HandleReEnter(double buyPrice, double sellPrice)
{
   // Find what direction(s) are open and what pending orders exist
   bool hasBuyPosition  = false;
   bool hasSellPosition = false;
   bool hasBuyOrder     = false;
   bool hasSellOrder    = false;
   
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(!PositionSelectByTicket(t)) continue;
      if(!IsOurMagic(PositionGetInteger(POSITION_MAGIC))) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)  hasBuyPosition  = true;
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_SELL) hasSellPosition = true;
   }
   
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(t == 0 || !OrderSelect(t)) continue;
      if(!IsOurMagic(OrderGetInteger(ORDER_MAGIC))) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(OrderGetInteger(ORDER_TYPE) == ORDER_TYPE_BUY_STOP)  hasBuyOrder  = true;
      if(OrderGetInteger(ORDER_TYPE) == ORDER_TYPE_SELL_STOP) hasSellOrder = true;
   }
   
   double askNow = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bidNow = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double mDist  = GetMinDist();
   
   // Count existing buy/sell positions to enforce InpMaxReEnter cap
   int buyPosCount  = 0;
   int sellPosCount = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(!PositionSelectByTicket(t)) continue;
      if(!IsOurMagic(PositionGetInteger(POSITION_MAGIC))) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      // Count only leg1 positions to get pair count (leg2 mirrors leg1)
      if(PositionGetInteger(POSITION_MAGIC) == (long)magic_leg1)
      {
         if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)  buyPosCount++;
         if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_SELL) sellPosCount++;
      }
   }
   
   // If buy position is open but no buy pending AND under re-entry cap → re-enter buy
   if(hasBuyPosition && !hasBuyOrder && buyPrice > askNow + mDist && buyPosCount < InpMaxReEnter)
   {
      double buySL = buyPrice - InpStopLoss  * g_pipSize;
      double buyTP = buyPrice + InpTakeProfit * g_pipSize;
      string c1 = StringFormat("%s|L1|%d|RE", InpComment, magic_leg1);
      double lot1 = ValidateLot(CalcAutoLot(InpLotSize1));
      trade.SetExpertMagicNumber(magic_leg1);
      if(trade.BuyStop(lot1, buyPrice, _Symbol, buySL, buyTP, ORDER_TIME_GTC, 0, c1))
         PrintFormat("[rOcKDaSh] REENTER L1 BuyStop PLACED: %.5f | Lot=%.2f", buyPrice, lot1);
      else
         PrintFormat("[rOcKDaSh] REENTER L1 BuyStop FAILED: error %d", GetLastError());
      
      if(IsLeg2Enabled())
      {
         string c2 = StringFormat("%s|L2|%d|RE", InpComment, magic_leg2);
         double lot2 = ValidateLot(CalcAutoLot(InpLotSize2));
         trade.SetExpertMagicNumber(magic_leg2);
         if(trade.BuyStop(lot2, buyPrice, _Symbol, buySL, buyTP, ORDER_TIME_GTC, 0, c2))
            PrintFormat("[rOcKDaSh] REENTER L2 BuyStop PLACED: %.5f | Lot=%.2f", buyPrice, lot2);
         else
            PrintFormat("[rOcKDaSh] REENTER L2 BuyStop FAILED: error %d", GetLastError());
      }
   }
   else if(hasBuyPosition && !hasBuyOrder)
   {
      // Log why re-entry was skipped
      if(buyPosCount >= InpMaxReEnter)
         PrintFormat("[rOcKDaSh] REENTER Buy skipped: max re-entries reached (%d/%d)", buyPosCount, InpMaxReEnter);
      else if(buyPrice <= askNow + mDist)
         PrintFormat("[rOcKDaSh] REENTER Buy skipped: price %.5f too close to ask %.5f", buyPrice, askNow);
   }
   
   // If sell position is open but no sell pending AND under re-entry cap → re-enter sell
   if(hasSellPosition && !hasSellOrder && sellPrice < bidNow - mDist && sellPosCount < InpMaxReEnter)
   {
      double sellSL = sellPrice + InpStopLoss  * g_pipSize;
      double sellTP = sellPrice - InpTakeProfit * g_pipSize;
      string c1 = StringFormat("%s|L1|%d|RE", InpComment, magic_leg1);
      double lot1 = ValidateLot(CalcAutoLot(InpLotSize1));
      trade.SetExpertMagicNumber(magic_leg1);
      if(trade.SellStop(lot1, sellPrice, _Symbol, sellSL, sellTP, ORDER_TIME_GTC, 0, c1))
         PrintFormat("[rOcKDaSh] REENTER L1 SellStop PLACED: %.5f | Lot=%.2f", sellPrice, lot1);
      else
         PrintFormat("[rOcKDaSh] REENTER L1 SellStop FAILED: error %d", GetLastError());
      
      if(IsLeg2Enabled())
      {
         string c2 = StringFormat("%s|L2|%d|RE", InpComment, magic_leg2);
         double lot2 = ValidateLot(CalcAutoLot(InpLotSize2));
         trade.SetExpertMagicNumber(magic_leg2);
         if(trade.SellStop(lot2, sellPrice, _Symbol, sellSL, sellTP, ORDER_TIME_GTC, 0, c2))
            PrintFormat("[rOcKDaSh] REENTER L2 SellStop PLACED: %.5f | Lot=%.2f", sellPrice, lot2);
         else
            PrintFormat("[rOcKDaSh] REENTER L2 SellStop FAILED: error %d", GetLastError());
      }
   }
   else if(hasSellPosition && !hasSellOrder)
   {
      if(sellPosCount >= InpMaxReEnter)
         PrintFormat("[rOcKDaSh] REENTER Sell skipped: max re-entries reached (%d/%d)", sellPosCount, InpMaxReEnter);
      else if(sellPrice >= bidNow - mDist)
         PrintFormat("[rOcKDaSh] REENTER Sell skipped: price %.5f too close to bid %.5f", sellPrice, bidNow);
   }
   
   // Still update existing pending orders to track latest breakout levels
   if(hasBuyOrder || hasSellOrder)
      UpdatePendingOrders(buyPrice, sellPrice);
   
   trade.SetExpertMagicNumber(magic_leg1);
}

//+------------------------------------------------------------------+
//| Retry Leg 2 if Leg 1 exists but Leg 2 is missing                 |
//| Handles case where Leg 2 failed due to mid-placement price move  |
//+------------------------------------------------------------------+
void PlaceMissingLeg2()
{
   if(!IsLeg2Enabled()) return;
   
   bool hasLeg1Buy  = false;
   bool hasLeg1Sell = false;
   bool hasLeg2Buy  = false;
   bool hasLeg2Sell = false;
   double leg1BuyPrice  = 0, leg1BuySL = 0, leg1BuyTP = 0;
   double leg1SellPrice = 0, leg1SellSL = 0, leg1SellTP = 0;
   
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong t = OrderGetTicket(i);
      if(t == 0 || !OrderSelect(t)) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      long mag = OrderGetInteger(ORDER_MAGIC);
      long typ = OrderGetInteger(ORDER_TYPE);
      
      if(mag == (long)magic_leg1)
      {
         if(typ == ORDER_TYPE_BUY_STOP)  { hasLeg1Buy  = true; leg1BuyPrice  = OrderGetDouble(ORDER_PRICE_OPEN); leg1BuySL = OrderGetDouble(ORDER_SL); leg1BuyTP = OrderGetDouble(ORDER_TP); }
         if(typ == ORDER_TYPE_SELL_STOP) { hasLeg1Sell = true; leg1SellPrice = OrderGetDouble(ORDER_PRICE_OPEN); leg1SellSL = OrderGetDouble(ORDER_SL); leg1SellTP = OrderGetDouble(ORDER_TP); }
      }
      if(mag == (long)magic_leg2)
      {
         if(typ == ORDER_TYPE_BUY_STOP)  hasLeg2Buy  = true;
         if(typ == ORDER_TYPE_SELL_STOP) hasLeg2Sell = true;
      }
   }
   
   // Nothing to retry if both legs complete or L1 not placed yet
   if((!hasLeg1Buy && !hasLeg1Sell) || (hasLeg2Buy && hasLeg2Sell)) return;
   
   double askNow = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bidNow = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double mDist  = GetMinDist();
   double lot2   = ValidateLot(CalcAutoLot(InpLotSize2));
   string comment2 = StringFormat("%s|L2|%d", InpComment, magic_leg2);
   trade.SetExpertMagicNumber(magic_leg2);
   
   if(hasLeg1Buy && !hasLeg2Buy && leg1BuyPrice > askNow + mDist)
   {
      if(trade.BuyStop(lot2, leg1BuyPrice, _Symbol, leg1BuySL, leg1BuyTP, ORDER_TIME_GTC, 0, comment2))
         PrintFormat("[rOcKDaSh] L2 BuyStop RETRY OK: %.5f | Lot=%.2f", leg1BuyPrice, lot2);
      else
         PrintFormat("[rOcKDaSh] L2 BuyStop RETRY FAILED: error %d", GetLastError());
   }
   
   if(hasLeg1Sell && !hasLeg2Sell && leg1SellPrice < bidNow - mDist)
   {
      if(trade.SellStop(lot2, leg1SellPrice, _Symbol, leg1SellSL, leg1SellTP, ORDER_TIME_GTC, 0, comment2))
         PrintFormat("[rOcKDaSh] L2 SellStop RETRY OK: %.5f | Lot=%.2f", leg1SellPrice, lot2);
      else
         PrintFormat("[rOcKDaSh] L2 SellStop RETRY FAILED: error %d", GetLastError());
   }
   
   trade.SetExpertMagicNumber(magic_leg1);
}

//+------------------------------------------------------------------+
//| Dynamic Kill Zone Checker                                        |
//+------------------------------------------------------------------+
bool IsKillZone()
{
   datetime current_time = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(current_time, dt);
   ENUM_DAY_OF_WEEK day = (ENUM_DAY_OF_WEEK)dt.day_of_week;

   datetime start_time, end_time;
   
   // Check ALL session indices (some brokers have multiple sessions per day)
   for(int sess = 0; sess < 10; sess++)
   {
      if(!SymbolInfoSessionTrade(_Symbol, day, sess, start_time, end_time))
         break;  // no more sessions
      
      int seconds_today = dt.hour * 3600 + dt.min * 60 + dt.sec;
      
      MqlDateTime end_dt;
      TimeToStruct(end_time, end_dt);
      int end_seconds = end_dt.hour * 3600 + end_dt.min * 60 + end_dt.sec;
      
      int seconds_left = end_seconds - seconds_today;
      // Handle overnight sessions (end < start): add 24h
      if(seconds_left < 0) seconds_left += 86400;
      
      if(seconds_left > 0 && seconds_left <= InpMinutesBeforeClose * 60)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| News Filter: Check if a high-impact news event is near           |
//| Uses MQL5 built-in Economic Calendar (no external API needed)    |
//| Checks both base and quote currencies of the current symbol      |
//| NOTE: Does NOT work in Strategy Tester — only live/demo          |
//+------------------------------------------------------------------+
bool IsNewsTime()
{
   if(!InpUseNewsFilter) return false;
   
   // Cache: only check calendar every 60 seconds to avoid performance hit
   static datetime lastCheck = 0;
   static bool     lastResult = false;
   
   if(TimeCurrent() - lastCheck < 60)
      return lastResult;  // Return cached result
   
   lastCheck = TimeCurrent();
   
   // Get currencies for this symbol (e.g. XAUUSD → XAU + USD, EURUSD → EUR + USD)
   string baseCurrency  = SymbolInfoString(_Symbol, SYMBOL_CURRENCY_BASE);    // e.g. "XAU", "EUR"
   string quoteCurrency = SymbolInfoString(_Symbol, SYMBOL_CURRENCY_PROFIT);  // e.g. "USD"
   
   // Time window: from X minutes ago to Y minutes in the future
   datetime now   = TimeCurrent();
   datetime from  = now - InpNewsMinsAfter  * 60;   // Look back (after period)
   datetime to    = now + InpNewsMinsBefore  * 60;   // Look forward (before period)
   
   // Determine minimum importance level to filter
   ENUM_CALENDAR_EVENT_IMPORTANCE minImportance;
   if(InpNewsImpact == NEWS_HIGH_ONLY)
      minImportance = CALENDAR_IMPORTANCE_HIGH;
   else if(InpNewsImpact == NEWS_MEDIUM_HIGH)
      minImportance = CALENDAR_IMPORTANCE_MODERATE;
   else
      minImportance = CALENDAR_IMPORTANCE_LOW;
   
   // Check both currencies
   string currencies[2];
   currencies[0] = baseCurrency;
   currencies[1] = quoteCurrency;
   
   for(int c = 0; c < 2; c++)
   {
      if(currencies[c] == "" || currencies[c] == "RUR") continue;  // Skip empty/invalid
      
      MqlCalendarValue values[];
      int count = CalendarValueHistory(values, from, to, NULL, currencies[c]);
      
      if(count <= 0) continue;
      
      for(int i = 0; i < count; i++)
      {
         MqlCalendarEvent event;
         if(!CalendarEventById(values[i].event_id, event)) continue;
         
         // Check importance level
         if(event.importance >= minImportance)
         {
            lastResult = true;
            return true;  // Found a matching news event in the time window
         }
      }
   }
   
   lastResult = false;
   return false;
}

//+------------------------------------------------------------------+
//| Force Close Everything — respects mode:                          |
//| Service Mode → closes ALL positions on symbol                    |
//| Normal Mode  → closes only own (magic-filtered) positions        |
//+------------------------------------------------------------------+
void ForceCloseAll()
{
   // Cooldown: avoid spamming close requests every tick (3-second pause between attempts)
   if(TimeCurrent() - g_lastForceClose < 3) return;
   g_lastForceClose = TimeCurrent();

   if(!IsServiceMode()) DeleteAllPending();
   
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
      {
         if(!IsOurMagic(PositionGetInteger(POSITION_MAGIC))) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         
         long posMagic = PositionGetInteger(POSITION_MAGIC);
         trade.SetExpertMagicNumber((ulong)posMagic);
         
         if(!trade.PositionClose(ticket))
            PrintFormat("[rOcKDaSh] ForceClose #%d FAILED: error %d", ticket, GetLastError());
         else
            PrintFormat("[rOcKDaSh] ForceClose #%d OK", ticket);
      }
   }
   if(!IsServiceMode()) trade.SetExpertMagicNumber(magic_leg1);
}

bool IsTradingTime()
{
   MqlDateTime dt;
   TimeCurrent(dt);
   // Support overnight sessions (e.g. Start=22, End=6)
   if(InpStartHour < InpEndHour)
      return (dt.hour >= InpStartHour && dt.hour < InpEndHour);
   else
      return (dt.hour >= InpStartHour || dt.hour < InpEndHour);
}

//+------------------------------------------------------------------+
//| Break-Even: Fully independent per leg (Normal Mode)              |
//| Service Mode: applies Leg 1 BE settings to ALL positions         |
//+------------------------------------------------------------------+
void ManageBreakEven()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
      {
         long posMagic = PositionGetInteger(POSITION_MAGIC);
         if(!IsOurMagic(posMagic)) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         
         bool   useBE;
         int    beTrigger;
         int    beLock;
         
         if(IsServiceMode())
         {
            // Service Mode: use Leg 1 settings for all positions
            useBE     = InpLot1BE;
            beTrigger = InpBE_Trigger1;
            beLock    = InpBE_LockPips1;
         }
         else if(posMagic == (long)magic_leg1)
         {
            useBE     = InpLot1BE;
            beTrigger = InpBE_Trigger1;
            beLock    = InpBE_LockPips1;
         }
         else
         {
            useBE     = InpLot2BE;
            beTrigger = InpBE_Trigger2;
            beLock    = InpBE_LockPips2;
         }
         
         if(!useBE) continue;
         
         long posType    = PositionGetInteger(POSITION_TYPE);
         double currentSL = PositionGetDouble(POSITION_SL);
         double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
         double tp        = PositionGetDouble(POSITION_TP);
         
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         
         trade.SetExpertMagicNumber((ulong)posMagic);
         
         if(posType == POSITION_TYPE_BUY)
         {
            double beSL = NormalizeDouble(openPrice + beLock * g_pipSize, _Digits);
            
            if(bid - openPrice >= beTrigger * g_pipSize && currentSL < beSL)
            {
               if(trade.PositionModify(ticket, beSL, tp))
                  PrintFormat("[rOcKDaSh] BE BUY #%d: SL moved %.5f → %.5f (lock +%d pts)", ticket, currentSL, beSL, beLock);
               else
                  PrintFormat("[rOcKDaSh] BE BUY #%d FAILED: error %d", ticket, GetLastError());
            }
         }
         else if(posType == POSITION_TYPE_SELL)
         {
            double beSL = NormalizeDouble(openPrice - beLock * g_pipSize, _Digits);
            
            if(openPrice - ask >= beTrigger * g_pipSize && (currentSL > beSL || currentSL == 0))
            {
               if(trade.PositionModify(ticket, beSL, tp))
                  PrintFormat("[rOcKDaSh] BE SELL #%d: SL moved %.5f → %.5f (lock +%d pts)", ticket, currentSL, beSL, beLock);
               else
                  PrintFormat("[rOcKDaSh] BE SELL #%d FAILED: error %d", ticket, GetLastError());
            }
         }
      }
   }
   if(!IsServiceMode()) trade.SetExpertMagicNumber(magic_leg1);
}

//+------------------------------------------------------------------+
//| Trailing Stop: Fully independent per leg (Normal Mode)           |
//| Service Mode: applies Leg 1 Trail settings to ALL positions      |
//+------------------------------------------------------------------+
void ManageTrailingStop()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(PositionSelectByTicket(ticket))
      {
         long posMagic = PositionGetInteger(POSITION_MAGIC);
         if(!IsOurMagic(posMagic)) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         
         bool   useTrail;
         int    trailStart;
         int    trailStep;
         
         if(IsServiceMode())
         {
            // Service Mode: use Leg 1 settings for all positions
            useTrail   = InpLot1Trail;
            trailStart = InpTrailStart1;
            trailStep  = InpTrailStep1;
         }
         else if(posMagic == (long)magic_leg1)
         {
            useTrail   = InpLot1Trail;
            trailStart = InpTrailStart1;
            trailStep  = InpTrailStep1;
         }
         else
         {
            useTrail   = InpLot2Trail;
            trailStart = InpTrailStart2;
            trailStep  = InpTrailStep2;
         }
         
         if(!useTrail) continue;
         
         long posType = PositionGetInteger(POSITION_TYPE);
         double currentSL = PositionGetDouble(POSITION_SL);
         double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
         
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         
         trade.SetExpertMagicNumber((ulong)posMagic);
         
         // Skip if error 4756 cooldown is active (2-second pause)
         if(TimeCurrent() - g_lastError4756 < 2) continue;

         // Minimum trail step = 1 pip (avoids sub-pip spam modifications)
         double minTrailMove = InpPointScale * _Point;

         if(posType == POSITION_TYPE_BUY)
         {
            if(bid - openPrice > trailStart * g_pipSize)
            {
               double newSL = NormalizeDouble(bid - trailStep * g_pipSize, _Digits);
               if(newSL > currentSL + minTrailMove || currentSL == 0)
               {
                  if(trade.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP)))
                     PrintFormat("[rOcKDaSh] TRAIL BUY #%d: SL moved %.5f → %.5f", ticket, currentSL, newSL);
                  else
                  {
                     int err = GetLastError();
                     PrintFormat("[rOcKDaSh] TRAIL BUY #%d FAILED: error %d", ticket, err);
                     if(err == 4756) g_lastError4756 = TimeCurrent();
                  }
               }
            }
         }
         else if(posType == POSITION_TYPE_SELL)
         {
            if(openPrice - ask > trailStart * g_pipSize)
            {
               double newSL = NormalizeDouble(ask + trailStep * g_pipSize, _Digits);
               if(newSL < currentSL - minTrailMove || currentSL == 0)
               {
                  if(trade.PositionModify(ticket, newSL, PositionGetDouble(POSITION_TP)))
                     PrintFormat("[rOcKDaSh] TRAIL SELL #%d: SL moved %.5f → %.5f", ticket, currentSL, newSL);
                  else
                  {
                     int err = GetLastError();
                     PrintFormat("[rOcKDaSh] TRAIL SELL #%d FAILED: error %d", ticket, err);
                     if(err == 4756) g_lastError4756 = TimeCurrent();
                  }
               }
            }
         }
      }
   }
   if(!IsServiceMode()) trade.SetExpertMagicNumber(magic_leg1);
}

//+------------------------------------------------------------------+
//| Update pending orders for both legs (Normal Mode only)           |
//| Skips any leg where the new price is 0 (too close to market)     |
//+------------------------------------------------------------------+
void UpdatePendingOrders(double b_price, double s_price)
{
   // Pre-compute SL/TP only for valid prices — avoid garbage values when price=0
   double buySL  = (b_price > 0) ? b_price - InpStopLoss  * g_pipSize : 0;
   double buyTP  = (b_price > 0) ? b_price + InpTakeProfit * g_pipSize : 0;
   double sellSL = (s_price > 0) ? s_price + InpStopLoss  * g_pipSize : 0;
   double sellTP = (s_price > 0) ? s_price - InpTakeProfit * g_pipSize : 0;

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderSelect(ticket))
      {
         long ordMagic = OrderGetInteger(ORDER_MAGIC);
         if(!IsOurMagic(ordMagic)) continue;
         if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
         
         long type = OrderGetInteger(ORDER_TYPE);
         double currentOpen = OrderGetDouble(ORDER_PRICE_OPEN);
         
         trade.SetExpertMagicNumber((ulong)ordMagic);
         
         // Validate price is still valid before modifying
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double minDist2 = GetMinDist();

         if(type == ORDER_TYPE_BUY_STOP)
         {
            if(b_price == 0) continue;  // Price zeroed (too close) — skip this leg
            if(MathAbs(b_price - currentOpen) <= InpUpdateThreshold * _Point) continue;  // Not enough change (points)
            if(b_price <= ask + minDist2) continue;  // Too close to market
            if(InpUseDupFilter && IsPriceAlreadyUsed(b_price)) continue;
            if(!trade.OrderModify(ticket, b_price, buySL, buyTP, 0, 0))
               PrintFormat("[rOcKDaSh] ModifyBuyStop #%d failed: error %d", ticket, GetLastError());
         }

         if(type == ORDER_TYPE_SELL_STOP)
         {
            if(s_price == 0) continue;  // Price zeroed (too close) — skip this leg
            if(MathAbs(s_price - currentOpen) <= InpUpdateThreshold * _Point) continue;  // Not enough change (points)
            if(s_price >= bid - minDist2) continue;  // Too close to market
            if(InpUseDupFilter && IsPriceAlreadyUsed(s_price)) continue;
            if(!trade.OrderModify(ticket, s_price, sellSL, sellTP, 0, 0))
               PrintFormat("[rOcKDaSh] ModifySellStop #%d failed: error %d", ticket, GetLastError());
         }
      }
   }
   trade.SetExpertMagicNumber(magic_leg1);
}

//+------------------------------------------------------------------+
//| Delete all OWN pending orders (both legs) — Normal Mode only     |
//+------------------------------------------------------------------+
void DeleteAllPending() 
{ 
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderSelect(ticket))
      {
         long ordMagic = OrderGetInteger(ORDER_MAGIC);
         if(!IsOurMagic(ordMagic)) continue;
         if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
         
         trade.SetExpertMagicNumber((ulong)ordMagic);
         
         if(!trade.OrderDelete(ticket))
            PrintFormat("[rOcKDaSh] OrderDelete #%d failed: error %d", ticket, GetLastError());
      }
   }
   trade.SetExpertMagicNumber(magic_leg1);
}

//+------------------------------------------------------------------+
//| Dashboard Helper: Create a text label on the chart               |
//+------------------------------------------------------------------+
void DashLabel(string name, int x, int y, string text, color clr, int fontSize = 9)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER,    CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR,    ANCHOR_LEFT_UPPER);
      ObjectSetString (0, name, OBJPROP_FONT,      "Consolas");
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN,     true);
   }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString (0, name, OBJPROP_TEXT,       text);
   ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   fontSize);
}

//+------------------------------------------------------------------+
//| Dashboard Helper: Create background panel                        |
//+------------------------------------------------------------------+
void DashPanel(string name, int x, int y, int w, int h, color bgClr)
{
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER,     CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE,  false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN,      true);
      ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE,     w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE,     h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR,   bgClr);
   ObjectSetInteger(0, name, OBJPROP_COLOR,     clrDimGray);
}

//+------------------------------------------------------------------+
//| Draw Dashboard — modern dark panel on chart                      |
//+------------------------------------------------------------------+
void DrawDashboard()
{
   string p = "DASH_";  // prefix for all objects
   int x = 10, y = 25;  // top-left corner
   int w = 280;          // panel width
   int lineH = 18;       // line height
   int row = 0;
   
   color cTitle  = clrGold;
   color cLabel  = clrSilver;
   color cValue  = clrWhite;
   color cGreen  = clrLime;
   color cRed    = clrRed;
   color cOrange = clrOrange;
   color cBg     = C'20,20,30';      // Dark background
   
   // --- Gather data ---
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   
   double askNow = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bidNow = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int spread = (int)MathRound((askNow - bidNow) / _Point);
   
   // Count positions & lots
   int openPos = 0;
   double totalLots = 0;
   double ownFloating = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(!PositionSelectByTicket(t)) continue;
      if(!IsOurMagic(PositionGetInteger(POSITION_MAGIC))) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      openPos++;
      totalLots += PositionGetDouble(POSITION_VOLUME);
      ownFloating += PositionGetDouble(POSITION_PROFIT)
                   + PositionGetDouble(POSITION_SWAP);
   }
   
   int pendingOrders = CountOwnOrders();
   
   // Daily P&L
   double dailyPnl = 0;
   double dailyPnlPct = 0;
   if(g_dayStartBalance > 0)
   {
      dailyPnl    = equity - g_dayStartBalance;
      dailyPnlPct = (dailyPnl / g_dayStartBalance) * 100.0;
   }
   
   // Closed P&L today (from deal history)
   double closedPnl = 0;
   MqlDateTime dtDay;
   TimeCurrent(dtDay);
   dtDay.hour = 0; dtDay.min = 0; dtDay.sec = 0;
   datetime dayStart = StructToTime(dtDay);
   if(HistorySelect(dayStart, TimeCurrent()))
   {
      for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
      {
         ulong dTicket = HistoryDealGetTicket(i);
         if(dTicket == 0) continue;
         if(HistoryDealGetString(dTicket, DEAL_SYMBOL) != _Symbol) continue;
         if(!IsOurMagic(HistoryDealGetInteger(dTicket, DEAL_MAGIC))) continue;
         long entry = HistoryDealGetInteger(dTicket, DEAL_ENTRY);
         if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY)
         {
            closedPnl += HistoryDealGetDouble(dTicket, DEAL_PROFIT)
                       + HistoryDealGetDouble(dTicket, DEAL_SWAP)
                       + HistoryDealGetDouble(dTicket, DEAL_COMMISSION);
         }
      }
   }
   double totalPnl = closedPnl + ownFloating;
   
   // --- Draw panel background ---
   int totalRows = 18;
   int panelH = 30 + totalRows * lineH;
   DashPanel(p+"BG", x, y, w, panelH, cBg);
   
   // === HEADER ===
   row = 0;
   DashLabel(p+"TITLE", x+10, y+8, StringFormat("%s  |  %s  |  %s", InpComment, _Symbol,
             EnumToString(InpTimeFrame)), cTitle, 10);
   
   DashPanel(p+"SEP1", x+5, y+6+2*lineH, w-10, 1, clrDimGray);
   
   // === ACCOUNT ===
   row = 2;
   DashLabel(p+"LBL_BAL",  x+10, y+10+row*lineH, "Balance:",   cLabel);
   DashLabel(p+"VAL_BAL",  x+140, y+10+row*lineH, StringFormat("$%.2f", balance), cValue);
   
   row = 3;
   DashLabel(p+"LBL_EQ",   x+10, y+10+row*lineH, "Equity:",    cLabel);
   DashLabel(p+"VAL_EQ",   x+140, y+10+row*lineH, StringFormat("$%.2f", equity),
             equity >= balance ? cGreen : cRed);
   
   row = 4;
   DashLabel(p+"LBL_DPNL", x+10, y+10+row*lineH, "Daily P&L:", cLabel);
   DashLabel(p+"VAL_DPNL", x+140, y+10+row*lineH,
             StringFormat("%s$%.2f (%s%.1f%%)",
             dailyPnl >= 0 ? "+" : "", dailyPnl,
             dailyPnlPct >= 0 ? "+" : "", dailyPnlPct),
             dailyPnl >= 0 ? cGreen : cRed);
   
   DashPanel(p+"SEP2", x+5, y+8+5*lineH, w-10, 1, clrDimGray);
   
   // === POSITIONS ===
   row = 5;
   DashLabel(p+"LBL_POS",  x+10, y+10+row*lineH, "Positions:",  cLabel);
   DashLabel(p+"VAL_POS",  x+140, y+10+row*lineH, StringFormat("%d", openPos),
             openPos > 0 ? cOrange : cValue);
   
   row = 6;
   DashLabel(p+"LBL_PEND", x+10, y+10+row*lineH, "Pending:",    cLabel);
   DashLabel(p+"VAL_PEND", x+140, y+10+row*lineH, StringFormat("%d", pendingOrders), cValue);
   
   row = 7;
   DashLabel(p+"LBL_LOTS", x+10, y+10+row*lineH, "Total Lots:", cLabel);
   DashLabel(p+"VAL_LOTS", x+140, y+10+row*lineH, StringFormat("%.2f", totalLots), cValue);
   
   row = 8;
   DashLabel(p+"LBL_FPL",  x+10, y+10+row*lineH, "Floating:",   cLabel);
   DashLabel(p+"VAL_FPL",  x+140, y+10+row*lineH,
             StringFormat("%s$%.2f", ownFloating >= 0 ? "+" : "", ownFloating),
             ownFloating >= 0 ? cGreen : cRed);
   
   row = 9;
   DashLabel(p+"LBL_CPL",  x+10, y+10+row*lineH, "Closed P&L:", cLabel);
   DashLabel(p+"VAL_CPL",  x+140, y+10+row*lineH,
             StringFormat("%s$%.2f", closedPnl >= 0 ? "+" : "", closedPnl),
             closedPnl >= 0 ? cGreen : cRed);
   
   row = 10;
   DashLabel(p+"LBL_TPL",  x+10, y+10+row*lineH, "Total P&L:",  cLabel);
   DashLabel(p+"VAL_TPL",  x+140, y+10+row*lineH,
             StringFormat("%s$%.2f", totalPnl >= 0 ? "+" : "", totalPnl),
             totalPnl >= 0 ? cGreen : cRed, 10);
   
   DashPanel(p+"SEP3", x+5, y+8+11*lineH, w-10, 1, clrDimGray);
   
   // === FILTERS STATUS ===
   row = 11;
   DashLabel(p+"LBL_SPR",  x+10, y+10+row*lineH, "Spread:",     cLabel);
   bool spreadOK = (InpMaxSpread == 0 || spread <= InpMaxSpread);
   DashLabel(p+"VAL_SPR",  x+140, y+10+row*lineH,
             InpMaxSpread > 0 ? StringFormat("%d / %d pts", spread, InpMaxSpread)
                              : StringFormat("%d pts", spread),
             spreadOK ? cGreen : cRed);
   
   row = 12;
   DashLabel(p+"LBL_EG",   x+10, y+10+row*lineH, "Equity Guard:", cLabel);
   if(!InpUseEquityGuard)
      DashLabel(p+"VAL_EG", x+140, y+10+row*lineH, "OFF", clrDimGray);
   else if(g_equityLocked)
      DashLabel(p+"VAL_EG", x+140, y+10+row*lineH, "LOCKED", cRed);
   else
   {
      double dd = balance > 0 ? ((balance - equity) / balance) * 100.0 : 0;
      DashLabel(p+"VAL_EG", x+140, y+10+row*lineH,
                StringFormat("%.1f%% / %.0f%%", dd, InpMaxDrawdownPct),
                dd < InpMaxDrawdownPct * 0.7 ? cGreen : cOrange);
   }
   
   row = 13;
   DashLabel(p+"LBL_DL",   x+10, y+10+row*lineH, "Daily Limit:", cLabel);
   if(InpMaxDailyLossPct <= 0 && InpMaxDailyProfitPct <= 0)
      DashLabel(p+"VAL_DL", x+140, y+10+row*lineH, "OFF", clrDimGray);
   else if(g_dailyLocked)
      DashLabel(p+"VAL_DL", x+140, y+10+row*lineH, "LOCKED", cRed);
   else
      DashLabel(p+"VAL_DL", x+140, y+10+row*lineH,
                StringFormat("%s%.1f%%", dailyPnlPct >= 0 ? "+" : "", dailyPnlPct),
                MathAbs(dailyPnlPct) < 2.0 ? cGreen : cOrange);
   
   row = 14;
   DashLabel(p+"LBL_NF",   x+10, y+10+row*lineH, "News Filter:", cLabel);
   if(!InpUseNewsFilter)
      DashLabel(p+"VAL_NF", x+140, y+10+row*lineH, "OFF", clrDimGray);
   else
      DashLabel(p+"VAL_NF", x+140, y+10+row*lineH,
                IsNewsTime() ? "BLOCKED" : "CLEAR",
                IsNewsTime() ? cRed : cGreen);
   
   row = 15;
   DashLabel(p+"LBL_OCO",  x+10, y+10+row*lineH, "OCO Mode:",   cLabel);
   DashLabel(p+"VAL_OCO",  x+140, y+10+row*lineH,
             InpOCOMode == OCO_DELETE ? "Delete" :
             InpOCOMode == OCO_REENTER ? "ReEnter" :
             InpOCOMode == OCO_WAIT ? "Wait" : "Refill", cValue);
   
   DashPanel(p+"SEP4", x+5, y+8+16*lineH, w-10, 1, clrDimGray);
   
   row = 16;
   MqlDateTime dtDash;
   TimeCurrent(dtDash);
   DashLabel(p+"TIME", x+10, y+10+row*lineH,
             StringFormat("%02d:%02d:%02d  |  Magic: %d",
             dtDash.hour, dtDash.min, dtDash.sec, InpMagic1),
             clrDimGray, 8);
   
   ChartRedraw();
}

//+------------------------------------------------------------------+
//| Delete all dashboard objects from chart                           |
//+------------------------------------------------------------------+
void DeleteDashboard()
{
   int total = ObjectsTotal(0);
   for(int i = total - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i);
      if(StringFind(name, "DASH_") == 0)
         ObjectDelete(0, name);
   }
   ChartRedraw();
}

