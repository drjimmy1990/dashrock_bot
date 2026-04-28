# rOcKDaSh MQ5 v1.11 vs Dashrock v2 — Full Comparison

> [!IMPORTANT]
> This document covers **every single difference** between the original MetaTrader 5 Expert Advisor (1,752 lines of MQL5) and the Python-based Dashrock v2 engine. Features are rated: ✅ = implemented, ⚠️ = partially implemented, ❌ = missing.

---

## 1. Core Strategy — Donchian Channel Breakout

Both bots share the **exact same core strategy**: place a **Buy Stop** above the Highest High and a **Sell Stop** below the Lowest Low of the last N candles.

| Parameter | MQ5 rOcKDaSh | Dashrock v2 | Match? |
|---|---|---|---|
| Strategy | Donchian Breakout (HH/LL) | Donchian Breakout (HH/LL) | ✅ Same |
| Lookback source | `CopyHigh/CopyLow` from bars 1..N | `highest_high/lowest_low` from candles `[-(n+1):-1]` | ✅ Same logic |
| Lookback bars | `InpLookbackBars` (default 20) | `lookback_candles` (configurable) | ✅ Same |
| Offset | `InpOffset * g_pipSize` added to HH, subtracted from LL | `offset_pips` as % or absolute | ✅ Same |
| Price validation | `buyPrice <= ask + minDist → skip` | `buy_price <= current_price → adjust upward` | ⚠️ Different approach |
| Min channel width | ❌ Not implemented | `min_channel_width_pct` — skip if channel too narrow | ✅ Dashrock extra |

### Key Difference: Price Distance Validation
- **MQ5**: Uses the broker's `SYMBOL_TRADE_STOPS_LEVEL` (minimum distance from market) to reject stops that are too close. If `buyPrice <= ask + minDist`, the buy side is completely zeroed out.
- **Dashrock**: Adjusts the price upward if it's at or below `current_price`. Falls back to `trigger.high + offset`, then `current_price * (1 + offset%)`. Never skips — always tries to place.

---

## 2. Position Sizing

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Fixed lot | ✅ `InpLotSize1` / `InpLotSize2` | ✅ `fallback_fixed_usd` |
| Auto Lot | ✅ `balance / baseBalance * baseLot` (linear scaling) | ❌ Not implemented |
| Risk-per-trade | ❌ Not implemented | ✅ `risk_per_trade_pct` — calculates qty from equity, entry, and SL distance |
| Equity fraction | ❌ Not implemented | ✅ `equity_fraction` mode |
| Lot validation | ✅ `ValidateLot()` — minLot, maxLot, lotStep, rounding | ✅ `round_qty()` + `validate_order()` via SymbolRegistry |

### Key Differences:
- **MQ5 Auto Lot** is dead simple: `lot = (balance / 1000) * 0.10`. If your balance doubles, your lot doubles. No risk calculation.
- **Dashrock risk_per_trade** is far more sophisticated: it computes position size so that if SL is hit, you lose exactly X% of equity. This is **professional-grade** risk management that the MQ5 bot completely lacks.

> [!TIP]
> Dashrock's `risk_per_trade` mode is objectively superior. The MQ5 Auto Lot can result in catastrophically large positions in volatile markets because it doesn't factor in the SL distance at all.

---

## 3. Multi-Leg System (Leg 1 / Leg 2)

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Dual legs | ✅ Leg 1 (larger lot) + Leg 2 (smaller lot) at same price | ❌ Single position only |
| Independent trailing per leg | ✅ Leg 1 and Leg 2 have separate trailing settings | N/A |
| Independent break-even per leg | ✅ Leg 1 and Leg 2 have separate BE settings | ❌ No break-even at all |
| Magic number separation | ✅ `InpMagic1` / `InpMagic2` | N/A (uses `clientAlgoId` tags) |
| Leg 2 retry | ✅ `PlaceMissingLeg2()` — retries if L2 failed but L1 exists | N/A |

### What this means:
The MQ5 bot can split a trade into two positions: for example, 0.10 lot (Leg 1) with tight trailing, and 0.05 lot (Leg 2) with wide trailing. This lets you lock partial profit early while running the second half for bigger moves. **Dashrock doesn't have this feature at all.**

---

## 4. OCO (One-Cancels-Other) Behavior

This is a **major architectural difference**. The MQ5 bot has 4 distinct OCO modes that control what happens when one pending order triggers:

| OCO Mode | MQ5 rOcKDaSh | Dashrock v2 Equivalent |
|---|---|---|
| **OCO_DELETE** | ✅ Cancel opposite pending, restart fresh after close | ⚠️ `reversed_order.mode: cancel` — cancels opposite |
| **OCO_REENTER** | ✅ Keep opposite pending + place NEW same-direction order (with cap) | ❌ Not implemented |
| **OCO_WAIT** | ✅ Keep all pending orders, no new actions until close | ❌ Not implemented |
| **OCO_REFILL** | ✅ Keep opposite, refill missing side after close + cooldown | ❌ Not implemented |
| Max re-entries cap | ✅ `InpMaxReEnter` (default 1) | ❌ Not implemented |

### Dashrock's `reversed_order` modes:
- `cancel` — cancel opposite entry (similar to OCO_DELETE)
- `keep_reverse` — let opposite trigger and reverse position
- `keep_close_only` — modify opposite to reduce_only (close position, don't open new)
- `hedge` — keep both sides open (hedge mode)

> [!WARNING]
> The MQ5 `OCO_REENTER` mode is a **pyramid entry system** — it adds positions in the same direction while already in a trade. This is high-risk and not implemented in Dashrock. The `OCO_REFILL` mode is a conservative alternative that waits for the position to close before placing a new order on the now-empty side.

---

## 5. Trailing Stop

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Activation distance | ✅ `InpTrailStart` (points) — trail only after X profit | ✅ `activation_pips` in `activation_trail` mode |
| Trail distance | ✅ `InpTrailStep` (points from current price) | ✅ `stop_pips` (distance behind watermark) |
| Step mode | ❌ Not implemented (trail is smooth, not stepped) | ✅ `step` mode — SL moves in discrete jumps |
| Trail per leg | ✅ Independent settings for Leg 1 and Leg 2 | ❌ Single trailing config |
| Min trail move | ✅ `minTrailMove = InpPointScale * _Point` (1 pip minimum) | ✅ Throttled to 1 update/sec |
| Error cooldown | ✅ 2-second pause after error 4756 | ✅ `time.monotonic()` based throttle |
| SL modification method | ✅ `PositionModify()` — modifies existing SL on the position | ⚠️ Cancel old SL order + place new one (two API calls) |

### Key Difference: Trailing Mechanism
- **MQ5**: Directly modifies the SL field on the open position using `trade.PositionModify()`. This is a single atomic operation — the broker guarantees the SL is always valid.
- **Dashrock**: Cancels the old SL stop-market order, then places a new one. There is a brief window between cancel and place where the position has **no stop loss**. If the engine crashes between these two steps, the position would be unprotected.

> [!CAUTION]
> Dashrock's cancel-then-replace approach for trailing stop creates a **gap window** where the position has no SL. This is an inherent limitation of Binance's conditional order API (algoOrders can't be modified in-place, only cancelled and re-placed).

---

## 6. Break-Even

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Break-even system | ✅ Full implementation | ❌ **Completely missing** |
| BE trigger | ✅ `InpBE_Trigger` — activate when profit ≥ X points | ❌ |
| BE lock profit | ✅ `InpBE_LockPips` — move SL to entry + Y points | ❌ |
| Per-leg BE | ✅ Independent for Leg 1 and Leg 2 | ❌ |

### What Break-Even does:
When the trade reaches a certain profit (e.g., 400 points), the SL is moved to entry price + a small lock profit (e.g., 200 points). This **guarantees** you can't lose money on this trade. It fires **before** the trailing stop activates.

> [!IMPORTANT]
> Break-even is a critical safety feature for live trading. The MQ5 bot has it; Dashrock does not. You should consider implementing this as a priority.

---

## 7. Pending Order Refresh & Update Threshold

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Update threshold | ✅ `InpUpdateThreshold = 100` points — won't modify if price change < threshold | ⚠️ Only skips if `current_price == intent.stop_price` |
| Pending refresh modes | ✅ Dynamic (always fresh) | ✅ `dynamic`, `fixed`, `hybrid_tighter` |
| Stops level enforcement | ✅ `GetMinDist()` — enforces broker min distance | ❌ No broker distance check |

### Key Difference:
- **MQ5**: Won't waste API calls modifying a pending order if the breakout level only shifted by a trivial amount (< 100 points). This prevents order modification spam.
- **Dashrock**: Has `pending_refresh_mode` with three smart modes (fixed, dynamic, hybrid_tighter) which the MQ5 bot doesn't have. But it lacks the minimum-change threshold — it will try to modify orders even for tiny price changes.

---

## 8. Duplicate Filter

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Duplicate filter | ✅ `InpUseDupFilter` — checks if another EA has orders at same price | ❌ Not needed (single bot) |
| Group-based cleanup | ✅ `CleanDuplicates()` — atomic group comparison | ❌ Not implemented |

This is specific to MT5 where multiple EAs can run on the same symbol. Irrelevant for Dashrock since it's the only bot on the account.

---

## 9. Safety & Risk Guards

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Equity Guard (max drawdown) | ✅ `InpMaxDrawdownPct` — locks EA permanently until restart | ✅ `max_drawdown_pct` in SafetyCfg |
| Daily Loss Limit | ✅ `InpMaxDailyLossPct` — locks until midnight | ✅ `max_daily_loss_pct` |
| Daily Profit Target | ✅ `InpMaxDailyProfitPct` — locks until midnight | ❌ Not implemented |
| Max consecutive losses | ❌ Not implemented | ✅ `max_consecutive_losses` |
| Max open positions | ❌ Not implemented (runs on single symbol) | ✅ `max_open_positions` (portfolio-wide) |
| Max total exposure | ❌ Not implemented | ✅ `max_total_exposure_pct` |
| Max per-symbol exposure | ❌ Not implemented | ✅ `max_per_symbol_exposure_pct` |
| Force close on guard trigger | ✅ `ForceCloseAll()` — closes positions + deletes orders | ⚠️ Pauses engine, doesn't force-close |

> [!WARNING]
> **Daily Profit Target** is present in MQ5 but missing in Dashrock. This feature locks trading after reaching a daily profit goal, preventing overtrading and protecting gains. Consider adding it.

---

## 10. Time Filters

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Trading hours filter | ✅ `InpStartHour` / `InpEndHour` (supports overnight) | ✅ `sessions` with start/end windows |
| Auto Kill Switch | ✅ `IsKillZone()` — closes all X minutes before session end | ❌ Not implemented |
| Weekend off | ❌ Manual via time filter | ✅ `weekdays_off` |
| Blackout windows | ❌ Not implemented | ✅ `blackouts` with behavior (close_on_entry / let_run_no_new) |

### Key Difference: Auto Kill Switch
The MQ5 bot reads the broker's **actual session schedule** (`SymbolInfoSessionTrade`) and automatically closes all positions X minutes before the market closes. This prevents overnight gaps on instruments like Gold (XAU/USD). **Dashrock doesn't have this.**

---

## 11. News Filter

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| News filter | ✅ Uses MT5's built-in Economic Calendar | ❌ **Completely missing** |
| Impact levels | ✅ High / Medium+High / All | ❌ |
| Before/after window | ✅ `InpNewsMinsBefore` / `InpNewsMinsAfter` | ❌ |
| Currency matching | ✅ Checks both base and quote currencies | ❌ |
| Caching | ✅ 60-second cache for performance | ❌ |

> [!IMPORTANT]
> The news filter is a **significant feature gap** in Dashrock. In crypto, major events (Fed rate decisions, CPI releases) cause massive wicks that can blow through stops. Consider integrating a third-party calendar API (e.g., ForexFactory, Investing.com) or Binance announcements.

---

## 12. Spread Filter

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Spread filter | ✅ `InpMaxSpread` — blocks new order placement when spread > X | ✅ `SpreadCfg` with `max_pips` |
| Dynamic spread | ❌ Fixed threshold only | ✅ `dynamic_atr_mult` — ATR-based dynamic threshold |
| Log-only mode | ❌ Always blocks | ✅ `log_only` option |

Dashrock's spread filter is more sophisticated with dynamic ATR-based thresholds.

---

## 13. Cooldown

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Cooldown after close | ✅ `InpCooldownBars` — wait X bars after last close | ✅ `cooldown_candles` |
| Cooldown trigger | ❌ Any close triggers cooldown | ✅ `any_close`, `sl_only`, `after_fill` modes |

Dashrock has more granular cooldown triggers.

---

## 14. Regime Detection

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Regime detection | ❌ **Not implemented** — trades in all conditions | ✅ ADX-based trending/ranging detection |
| ADX filter | ❌ | ✅ Skip entries when ADX < threshold (ranging market) |
| Bollinger Squeeze | ❌ | ✅ Detects low-volatility squeeze periods |

> [!TIP]
> Regime detection is a significant advantage for Dashrock. Trading breakouts in ranging markets leads to many false breakouts and whipsaws. The MQ5 bot has no way to detect and skip these conditions.

---

## 15. Volatility Scanner

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Scanner | ❌ Runs on single symbol only | ✅ Multi-symbol volatility scanner |
| NATR ranking | ❌ | ✅ Normalized ATR scoring |
| Composite scoring | ❌ | ✅ NATR + expansion + Donchian/ATR ratio |
| Dynamic watchlist | ❌ | ✅ Rank and select best symbols |

The MQ5 bot is attached to a single chart = single symbol. To trade multiple symbols, you need to open multiple charts with separate EA instances. Dashrock can scan and rank 50+ symbols from a single engine.

---

## 16. Service Mode

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Service Mode | ✅ `InpMagic1 = 0` — manages ALL positions (any EA's) | ❌ Not applicable |

When Magic is set to 0, the MQ5 bot becomes a **trailing/BE management overlay** — it won't place breakout orders but will manage trailing stops and break-even for ALL positions on the chart, regardless of which EA opened them. Useful for manual traders who want automated exit management.

---

## 17. Dashboard & UI

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Dashboard | ✅ On-chart overlay (1-second refresh) | ✅ Full React web dashboard |
| Shows balance/equity | ✅ | ✅ |
| Shows daily P&L | ✅ (floating + closed) | ✅ |
| Shows spread status | ✅ | ✅ |
| Shows news filter status | ✅ | ❌ |
| Shows equity guard status | ✅ | ⚠️ |
| Interactive controls | ❌ Read-only overlay | ✅ Full control (start/stop, config edit, manual orders) |
| TradingView charts | ❌ | ✅ |
| Trade history table | ❌ | ✅ |

Dashrock's web dashboard is vastly more feature-rich and interactive compared to the MQ5's simple on-chart text overlay.

---

## 18. Infrastructure & Architecture

| Feature | MQ5 rOcKDaSh | Dashrock v2 |
|---|---|---|
| Language | MQL5 (C++-like) | Python 3.12 |
| Execution | Runs inside MT5 terminal | Standalone async Python service |
| Exchange | Any MT5 broker (Forex, CFD, Crypto) | Binance Futures only |
| Persistence | ❌ No database (state lost on restart) | ✅ PostgreSQL (crash recovery) |
| REST API | ❌ | ✅ Full REST API with JWT auth |
| WebSocket data | MT5 handles internally | ✅ Direct Binance WS (kline + bookTicker) |
| Order types | Native BuyStop/SellStop (broker-managed) | Conditional algoOrders via Binance API |
| Backtesting | ✅ MT5 Strategy Tester (built-in) | ⚠️ Simulator mode (basic) |
| Config | Input parameters (compile-time) | YAML config (hot-reloadable) |
| Event system | ❌ | ✅ EventBus (notifications, logging) |
| Notifications | ❌ | ✅ Telegram + Discord webhooks |

---

## Summary: What Dashrock is MISSING from MQ5

| # | Missing Feature | Priority | Difficulty |
|---|---|---|---|
| 1 | **Break-Even system** | 🔴 High | Medium |
| 2 | **Multi-Leg (Leg 1 / Leg 2)** | 🟡 Medium | High |
| 3 | **Daily Profit Target** (lock after +X%) | 🟡 Medium | Low |
| 4 | **OCO ReEnter mode** (pyramid same-direction) | 🟡 Medium | High |
| 5 | **OCO Refill mode** (refill missing side) | 🟡 Medium | Medium |
| 6 | **Auto Kill Switch** (close before session end) | 🟡 Medium | Low |
| 7 | **News filter** | 🟡 Medium | Medium |
| 8 | **Update threshold** (min points to modify order) | 🟢 Low | Low |
| 9 | **Auto Lot** (balance-proportional sizing) | 🟢 Low | Low (risk_per_trade is better) |

## Summary: What Dashrock HAS that MQ5 doesn't

| # | Extra Feature | Value |
|---|---|---|
| 1 | **Risk-per-trade sizing** (professional position sizing) | 🔴 Critical |
| 2 | **Regime detection** (ADX/Bollinger) | 🔴 Critical |
| 3 | **Multi-symbol scanning & ranking** | 🔴 Critical |
| 4 | **PostgreSQL persistence** (crash recovery) | 🔴 Critical |
| 5 | **Web dashboard** with full control | 🟡 High |
| 6 | **Portfolio risk limits** (max positions, exposure) | 🟡 High |
| 7 | **Blackout windows** with behavior options | 🟢 Medium |
| 8 | **Dynamic spread filter** (ATR-based) | 🟢 Medium |
| 9 | **Configurable cooldown triggers** | 🟢 Low |
| 10 | **Telegram/Discord notifications** | 🟢 Low |
