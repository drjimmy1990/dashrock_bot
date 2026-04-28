# Dashrock v2 — Complete Config Reference

Every setting from `config.yaml` with its **type**, **allowed values**, **default**, and **your current value**.

---

## 🌐 Root Settings

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `mode` | string | `paper` · `testnet` · `live` | — (required) | `testnet` |
| `watchlist` | list[string] | Any Binance symbol (auto-uppercased) | — (required) | 5 symbols |
| `trade_list` | list[string] | Subset of watchlist (auto-uppercased) | `[]` | `XAGUSDT` |
| `timeframe` | string | `1m` · `3m` · `5m` · `15m` · `30m` · `1h` · `2h` · `4h` · `6h` · `8h` · `12h` · `1d` | — (required) | `1m` |

---

## 📊 Strategy

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `strategy.name` | string | `donchian_breakout` | `donchian_breakout` | `donchian_breakout` |
| `strategy.lookback_candles` | int | `2` – `500` | — (required) | `2` |
| `strategy.offset_pips` | float | `≥ 0` | — (required) | `0.0` |
| `strategy.pending_refresh_mode` | string | `dynamic` · `fixed` · `hybrid_tighter` | `dynamic` | `fixed` |
| `strategy.cooldown_candles` | int | `≥ 0` | — (required) | `1` |
| `strategy.cooldown_trigger` | string | `any_close` · `sl_only` · `after_fill` | `any_close` | `any_close` |
| `strategy.use_pct_pips` | bool | `true` / `false` | `true` | `true` |
| `strategy.min_channel_width_pct` | float | `≥ 0` | `0.05` | `0.0` |
| `strategy.params` | dict | Any key-value pairs | `{}` | `{}` |

### Regime Detection (nested under `strategy`)

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `strategy.regime_detection.enabled` | bool | `true` / `false` | `false` | `false` |
| `strategy.regime_detection.method` | string | `adx` · `bollinger_squeeze` · `both` | `adx` | `adx` |
| `strategy.regime_detection.adx_period` | int | `≥ 5` | `14` | `14` |
| `strategy.regime_detection.adx_trending_threshold` | float | `≥ 0` | `25.0` | `25.0` |
| `strategy.regime_detection.skip_ranging` | bool | `true` / `false` | `true` | `false` |

---

## 💰 Sizing

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `sizing.mode` | string | `fixed` · `risk_per_trade` · `equity_fraction` | `risk_per_trade` | `equity_fraction` |
| `sizing.risk_per_trade_pct` | float | `0.01` – `10.0` | `1.0` | `0.1` |
| `sizing.fallback_fixed_usd` | float | `≥ 0` | `50` | `50.0` |
| `sizing.leverage` | int | `1` – `125` | `10` | `20` |

---

## 📈 Portfolio Risk

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `portfolio_risk.max_open_positions` | int | `≥ 1` | `3` | `3` |
| `portfolio_risk.max_total_exposure_pct` | float | `≥ 0` | `300.0` | `300.0` |
| `portfolio_risk.max_per_symbol_exposure_pct` | float | `≥ 0` | `100.0` | `100.0` |

---

## 🏦 Equity

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `equity.source` | string | `auto` · `manual` | `auto` | `manual` |
| `equity.manual_value` | float | `≥ 0` | `1000` | `1000.0` |

---

## 🛑 Stops

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `stops.sl_pips` | float | `≥ 0` | — (required) | `0.15` |
| `stops.tp_pips` | float | `≥ 0` (0 = no TP) | — (required) | `0.0` |
| `stops.use_pct_pips` | bool | `true` / `false` | `true` | `true` |

---

## 🔄 Trailing

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `trailing.enabled` | bool | `true` / `false` | `true` | `true` |
| `trailing.mode` | string | `step` · `activation_trail` · `off` | `step` | `step` |
| `trailing.step_pips` | float | `≥ 0` | — (required) | `0.05` |
| `trailing.stop_pips` | float | `≥ 0` | — (required) | `0.15` |
| `trailing.activation_pips` | float | `≥ 0` | — (required) | `0.1` |
| `trailing.use_pct_pips` | bool | `true` / `false` | `true` | `true` |

---

## 🔄 Reversed Order (opposite side on fill)

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `reversed_order.mode` | string | `cancel` · `keep_reverse` · `keep_close_only` · `hedge` | `cancel` | `cancel` |

---

## ⏰ Time Filter

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `time_filter.enabled` | bool | `true` / `false` | `false` | `false` |
| `time_filter.timezone` | string | Any timezone string (e.g. `UTC`, `US/Eastern`) | `UTC` | `UTC` |
| `time_filter.sessions` | list | Objects with `start` and `end` (HH:MM strings) | `[]` | `[]` |
| `time_filter.weekdays_off` | list[string] | Day names (e.g. `Saturday`, `Sunday`) | `[]` | `[]` |
| `time_filter.blackouts` | list | Objects with `start`, `end`, `behavior` | `[]` | `[]` |
| ↳ `blackouts[].behavior` | string | `close_on_entry` · `let_run_no_new` | `let_run_no_new` | — |

---

## 📏 Spread

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `spread.max_pips` | float | `≥ 0` | `5` | `5.0` |
| `spread.dynamic_atr_mult` | float | `≥ 0` | `0.2` | `0.2` |
| `spread.use_dynamic` | bool | `true` / `false` | `false` | `false` |
| `spread.log_only` | bool | `true` / `false` | `false` | `false` |

---

## 📉 Slippage

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `slippage.max_pct` | float | `≥ 0` | `0.1` | `0.1` |
| `slippage.on_violation` | string | `alert` · `close_immediately` | `alert` | `alert` |

---

## 🧪 Simulator (paper mode only)

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `simulator.taker_fee_pct` | float | `≥ 0` | `0.04` | `0.04` |
| `simulator.slippage_noise_pips` | float | `≥ 0` | `0.01` | `0.01` |
| `simulator.starting_equity_usd` | float | `≥ 0` | `1000` | `1000.0` |
| `simulator.simulate_funding` | bool | `true` / `false` | `true` | `true` |
| `simulator.funding_rate_pct` | float | `≥ 0` | `0.01` | `0.01` |
| `simulator.latency_ms` | int | `≥ 0` | `0` | `0` |

---

## 🔬 Volatility Scanner

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `volatility.mode` | string | `normalized_atr` · `composite` | `composite` | `composite` |
| `volatility.min_score` | float | `≥ 0` | `0.2` | `0.2` |
| `volatility.min_24h_volume_usd` | float | `≥ 0` | `5,000,000` | `5,000,000` |

### Volatility Weights (nested)

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `volatility.weights.natr` | float | `0` – `1` | `0.4` | `0.4` |
| `volatility.weights.expansion` | float | `0` – `1` | `0.3` | `0.3` |
| `volatility.weights.donchian_atr` | float | `0` – `1` | `0.3` | `0.3` |

---

## 🛡️ Safety

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `safety.max_daily_loss_pct` | float | `≥ 0` | `5.0` | `5.0` |
| `safety.max_drawdown_pct` | float | `≥ 0` | `15.0` | `15.0` |
| `safety.max_consecutive_losses` | int | `≥ 0` | `5` | `5` |
| `safety.check_on_tick` | bool | `true` / `false` | `true` | `true` |
| `safety.tick_check_interval` | int | `≥ 1` | `100` | `100` |
| `safety.orphan_order_policy` | string | `alert_only` · `cancel` | `alert_only` | `alert_only` |
| `safety.reconciliation_interval_sec` | int | `≥ 10` | `300` | `300` |

---

## 🗄️ Database

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `database.url` | string | PostgreSQL connection string | `""` (use `DATABASE_URL` env) | *(from .env)* |
| `database.pool_min` | int | `≥ 1` | `5` | `2` |
| `database.pool_max` | int | `≥ 2` | `15` | `10` |

---

## 🔐 Auth

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `auth.enabled` | bool | `true` / `false` | `true` | `true` |
| `auth.jwt_secret` | string | Any string (use env `JWT_SECRET`) | `""` | *(from .env)* |
| `auth.token_expiry_hours` | int | `≥ 1` | `24` | `24` |
| `auth.admin_username` | string | Any string (use env `ADMIN_USERNAME`) | `""` | *(from .env)* |
| `auth.admin_password` | string | Any string (use env `ADMIN_PASSWORD`) | `""` | *(from .env)* |

---

## 📝 Logging

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `logging.level` | string | `DEBUG` · `INFO` · `WARNING` · `ERROR` | `INFO` | `INFO` |
| `logging.file` | string | Any file path | `logs/bot.log` | `logs/bot.log` |
| `logging.max_size_mb` | int | `≥ 1` | `50` | `50` |

---

## 🔔 Notifications

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `notifications.telegram_bot_token` | string | Telegram bot token | `""` | `""` |
| `notifications.telegram_chat_id` | string | Telegram chat ID | `""` | `""` |
| `notifications.discord_webhook` | string | Discord webhook URL | `""` | `""` |
| `notifications.events` | list[string] | `trade_opened` · `trade_closed` · `error` · `kill_switch` · `safety_triggered` | all 5 | all 5 |

---

## 🔴 Live Trading (testnet/live only)

| Setting | Type | Allowed Values | Default | Your Value |
|---------|------|---------------|---------|------------|
| `live.auto_set_leverage` | bool | `true` / `false` | `true` | `true` |
| `live.auto_set_margin_type` | bool | `true` / `false` | `true` | `true` |
| `live.margin_type` | string | `ISOLATED` · `CROSSED` | `ISOLATED` | `CROSSED` |
| `live.recv_window_ms` | int | `1000` – `60000` | `5000` | `5000` |
| `live.listen_key_refresh_sec` | int | `≥ 60` | `1800` | `1800` |
| `live.startup_reconcile` | bool | `true` / `false` | `true` | `true` |
| `live.max_retries` | int | `1` – `10` | `3` | `3` |
| `live.retry_delay_sec` | float | `0.1` – `30` | `1.0` | `1.0` |
