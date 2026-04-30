# Dashrock Trailing Stop — Complete Guide

## The Three Modes

| Feature | `activation_trail` | `step` | `binance_native` ✨ |
|---------|-------------------|--------|---------------------|
| Where it runs | Dashrock (your server) | Dashrock (your server) | **Binance (their server)** |
| API calls per position | 20-100+ (cancel/place loop) | 20-100+ | **1 (set and forget)** |
| -2021 errors | ⚠️ Frequent on tight settings | ⚠️ Frequent | ✅ **Impossible** |
| Latency risk | High (network delay) | High | ✅ **Zero** (server-side) |
| Min trail distance | Any | Any | 0.1% (Binance limit) |
| Max trail distance | Any | Any | 10% (Binance limit) |
| Activation threshold | Yes | No | Yes |
| Best for | Custom logic needs | Discrete step control | **Most traders (recommended)** |

---

## Mode 1: `binance_native` ✨ (RECOMMENDED)

**How it works:** After entry fill, Dashrock places ONE `TRAILING_STOP_MARKET` order on Binance. Binance tracks the price watermark on their servers and triggers the stop when price reverses by `callbackRate%`. Zero cancel/replace cycles, zero -2021 errors, zero latency.

### Parameters:

| Dashrock Config | Binance API | Your Value | Meaning |
|-----------------|-------------|-----------|---------|
| `stop_pips` | `callbackRate` | `0.1` | Trail distance = **0.1%** behind watermark |
| `activation_pips` | `activatePrice` | `0.15` | Trailing activates after **0.15%** profit |
| `step_pips` | — | — | ❌ Not used |
| `use_pct_pips` | — | — | ❌ Not used (Binance always uses %) |

> **Binance Limits:** `callbackRate` must be between **0.1%** and **10%**

### LONG Example (BUY XAGUSDT @ $72.00):

```
Config: stop_pips=0.3, activation_pips=0.15
 → callbackRate = 0.3%
 → activatePrice = 72.00 × 1.0015 = $72.108

┌─ ENTRY ──────────────────────────────────────────────────────┐
│  Dashrock places 1 order:                                    │
│  TRAILING_STOP_MARKET SELL qty=1.396                         │
│  callbackRate=0.3%  activatePrice=$72.108                    │
│  ✅ Done. Binance handles everything from here.              │
└──────────────────────────────────────────────────────────────┘

Price    $72.00 → $72.05 → $72.11 → $72.30 → $72.50 → $72.35
                           ↑ ACTIVATED!
                           (price crossed $72.108)
                                     Binance watermark: $72.50
                                     Trigger: $72.50 × 0.997 = $72.28

Price continues: $72.50 → $72.60 → $72.40 → $72.30 → $72.28
                                                       ↑ TRIGGERED!
Binance watermark: ──$72.50──$72.60──$72.60──$72.60──$72.60
Trigger price:     ──$72.28──$72.38──$72.38──$72.38──$72.38
                                                      ↑ price hit trigger!
                                                      EXIT @ ~$72.38

Profit: $72.38 - $72.00 = +$0.38 (+0.53%)
```

**What happened:**
1. Entry at $72.00 → Dashrock places 1 trailing order
2. Price climbs to $72.11 → Binance activates trailing (crossed $72.108)
3. Price reaches $72.60 → Binance tracks watermark at $72.60
4. Price drops → when it falls 0.3% from $72.60 ($72.42) → SELL triggers
5. **Zero API calls from Dashrock during the entire trailing process**

### SHORT Example (SELL XAGUSDT @ $72.00):

```
Config: stop_pips=0.3, activation_pips=0.15
 → callbackRate = 0.3%
 → activatePrice = 72.00 × 0.9985 = $71.892

┌─ ENTRY ──────────────────────────────────────────────────────┐
│  Dashrock places 1 order:                                    │
│  TRAILING_STOP_MARKET BUY qty=1.396                          │
│  callbackRate=0.3%  activatePrice=$71.892                    │
└──────────────────────────────────────────────────────────────┘

Price    $72.00 → $71.95 → $71.89 → $71.60 → $71.40 → $71.50
                           ↑ ACTIVATED!
                           (price crossed $71.892)
                                     Binance watermark: $71.40
                                     Trigger: $71.40 × 1.003 = $71.61

Price continues: $71.40 → $71.30 → $71.45 → $71.55 → $71.61
                                                       ↑ TRIGGERED!
Binance watermark: ──$71.40──$71.30──$71.30──$71.30──$71.30
Trigger price:     ──$71.61──$71.51──$71.51──$71.51──$71.51
                                                      ↑ price hit trigger!
                                                      EXIT @ ~$71.51

Profit: $72.00 - $71.51 = +$0.49 (+0.68%)
```

### What Happens Behind the Scenes:

```
                    CUSTOM TRAILING                    BINANCE NATIVE
                    ──────────────                     ──────────────
Entry Fill    →  Place STOP_MARKET SL              →  Place TRAILING_STOP_MARKET
                      ↓                                     ↓
Tick 1        →  Cancel old SL                     →  (nothing — Binance handles it)
              →  Place new SL at tighter price
              →  If -2021: emergency SL loop!
                      ↓
Tick 2        →  Cancel old SL                     →  (nothing)
              →  Place new SL
                      ↓
Tick N        →  Cancel old SL                     →  (nothing)
              →  Place new SL
              →  If -2021: close at market!
                      ↓                                     ↓
Exit          →  Fill from STOP_MARKET             →  Fill from TRAILING_STOP_MARKET
                                                      
Total API calls:  20-100+                              1 ✨
```

### Activation Price Logic:

| Scenario | `activation_pips` | What happens |
|----------|------------------|-------------|
| With activation | `0.15` | LONG: activates at entry × 1.0015. SHORT: entry × 0.9985. Trailing starts only after price confirms profit direction. |
| No activation | `0.0` | Trailing starts immediately at current market price. More responsive but may trail prematurely on entry noise. |

### Fallback Safety:

If the `TRAILING_STOP_MARKET` order fails to place (rare — e.g., Binance maintenance), Dashrock automatically falls back to a fixed `STOP_MARKET` SL using your `stops.sl_pips` setting. The position is **never unprotected**.

---

## Mode 2: `activation_trail`

**How it works:** Dashrock monitors price on every tick. After price moves `activation_pips%` in your favor, the SL starts trailing `stop_pips%` behind the highest/lowest point (watermark). Dashrock cancels and re-places the SL order on Binance every time the watermark improves.

### Parameters Used:
| Param | Meaning |
|-------|---------|
| `activation_pips` | ✅ Profit needed to activate trailing |
| `stop_pips` | ✅ Trail distance behind watermark |
| `step_pips` | ❌ Not used |

### LONG Example (BUY @ $72.00, stop_pips=0.1, activation_pips=0.15):

```
Entry: $72.00
Initial SL: $71.856  (72.00 - 0.2% from stops.sl_pips)
Activation: $72.108  (72.00 + 0.15%)

Price    $72.00 → $72.05 → $72.11 → $72.20 → $72.15 → $72.10
SL       $71.86   $71.86   ★$72.04  $72.13   $72.13   $72.13
                           ↑ ACTIVATED!       (watermark=$72.20, SL only moves UP)

Price continues: $72.25 → $72.30 → $72.22
SL                $72.18   $72.23   $72.23  ← SL hit! Exit @ ~$72.23
```

### SHORT Example (SELL @ $72.00):

```
Entry: $72.00
Initial SL: $72.144  (72.00 + 0.2%)
Activation: $71.892  (72.00 - 0.15%)

Price    $72.00 → $71.95 → $71.89 → $71.80 → $71.85 → $71.90
SL       $72.14   $72.14   ★$71.96  $71.87   $71.87   $71.87
                           ↑ ACTIVATED!       (watermark=$71.80, SL only moves DOWN)

Price continues: $71.75 → $71.70 → $71.78
SL                $71.82   $71.77   $71.77  ← SL hit! Exit @ ~$71.77
```

⚠️ **Known issue:** With tight settings (stop_pips < 0.2%), fast reversals cause -2021 errors. The engine now detects breached SL and closes at market, but this adds slippage. **Use `binance_native` to avoid this entirely.**

---

## Mode 3: `step`

**How it works:** Move SL in fixed step increments. Every time price gains one `step_pips%`, SL jumps up by `step_pips%` (minus `stop_pips%` buffer).

### Parameters Used:
| Param | Meaning |
|-------|---------|
| `step_pips` | ✅ Step size for both trigger and SL move |
| `stop_pips` | ✅ Distance between step level and SL |
| `activation_pips` | ❌ Not used |

### LONG Example (BUY @ $72.00, step_pips=0.05, stop_pips=0.1):

```
step = 72.00 × 0.05% = $0.036
stop_distance = 72.00 × 0.1% = $0.072

Watermark   Steps   Step Level          SL (level - stop_distance)
$72.036     1       72.00 + 0.036       = $71.964  (< initial SL, no move)
$72.072     2       72.00 + 0.072       = $72.000  (= entry, move SL!)
$72.108     3       72.00 + 0.108       = $72.036
$72.144     4       72.00 + 0.144       = $72.072

SL moves in discrete jumps, not continuously.
```

---

## Recommended Configurations

### 🏆 Best Overall (Binance Native):
```yaml
trailing:
  enabled: true
  mode: binance_native
  stop_pips: 0.3       # callbackRate = 0.3% (good balance)
  activation_pips: 0.15 # activate after 0.15% profit
  use_pct_pips: true
```
✅ Zero -2021 errors. Zero API overhead. Binance handles everything.

### Conservative (Binance Native):
```yaml
trailing:
  enabled: true
  mode: binance_native
  stop_pips: 0.5       # wider trail = less exits, bigger moves captured
  activation_pips: 0.3  # activate later = more confirmed trend
  use_pct_pips: true
```

### Tight Scalping (Binance Native):
```yaml
trailing:
  enabled: true
  mode: binance_native
  stop_pips: 0.1       # minimum allowed (0.1%), very tight
  activation_pips: 0.0  # immediate activation, no delay
  use_pct_pips: true
```
⚠️ Very tight — will exit quickly on any reversal. Good for strong momentum plays.

### Custom Trailing (if you need non-% logic):
```yaml
trailing:
  enabled: true
  mode: activation_trail
  stop_pips: 0.2
  activation_pips: 0.3
  use_pct_pips: true
```

---

## Quick Reference: All Parameters

| Parameter | `binance_native` | `activation_trail` | `step` |
|-----------|-----------------|-------------------|--------|
| `stop_pips` | ✅ callbackRate % (0.1-10) | ✅ Trail distance | ✅ Buffer distance |
| `activation_pips` | ✅ activatePrice calc | ✅ Profit to activate | ❌ Not used |
| `step_pips` | ❌ Not used | ❌ Not used | ✅ Step size |
| `use_pct_pips` | ❌ Always % | ✅ Toggle % vs pips | ✅ Toggle |

## Safety Nets

| Scenario | What Dashrock Does |
|----------|--------------------|
| `binance_native` order fails to place | Falls back to fixed STOP_MARKET SL |
| Custom trailing SL breached by price | Closes at MARKET immediately |
| Custom trailing SL placement fails (-2021) | Closes at MARKET immediately |
| SL ID lost (sl_id=None with position) | Emergency re-placement on next tick |
