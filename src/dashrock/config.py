"""Configuration models — Pydantic validated, YAML loaded.

All trading parameters are defined here with validation constraints.
Supports hot-reload for safe settings, restart-required for structural ones.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─── Strategy ───────────────────────────────────────────────────


class RegimeDetectionCfg(BaseModel):
    enabled: bool = False
    method: Literal["adx", "bollinger_squeeze", "both"] = "adx"
    adx_period: int = Field(default=14, ge=5)
    adx_trending_threshold: float = Field(default=25.0, ge=0)
    skip_ranging: bool = True


class StrategyCfg(BaseModel):
    name: str = "donchian_breakout"
    lookback_candles: int = Field(ge=1, le=500)
    offset_pips: float = Field(ge=0)
    pending_refresh_mode: Literal["dynamic", "fixed", "hybrid_tighter"] = "dynamic"
    cooldown_candles: int = Field(ge=0)
    cooldown_trigger: Literal["any_close", "sl_only", "after_fill"] = "any_close"
    use_pct_pips: bool = True
    min_channel_width_pct: float = Field(default=0.05, ge=0)
    regime_detection: RegimeDetectionCfg = RegimeDetectionCfg()
    params: dict[str, Any] = Field(default_factory=dict)  # strategy-specific extra params


# ─── Sizing & Risk ──────────────────────────────────────────────


class SizingCfg(BaseModel):
    mode: Literal["fixed", "risk_per_trade", "equity_fraction"] = "risk_per_trade"
    risk_per_trade_pct: float = Field(default=1.0, ge=0.01, le=10.0)  # % of equity risked per trade
    fallback_fixed_usd: float = Field(ge=0, default=50)
    leverage: int = Field(default=10, ge=1, le=125)


class PortfolioRiskCfg(BaseModel):
    max_open_positions: int = Field(default=3, ge=1)
    max_total_exposure_pct: float = Field(default=300.0, ge=0)  # % of equity across all positions
    max_per_symbol_exposure_pct: float = Field(default=100.0, ge=0)


class EquityCfg(BaseModel):
    source: Literal["auto", "manual"] = "auto"
    manual_value: float = Field(ge=0, default=1000)


# ─── Stops ──────────────────────────────────────────────────────


class StopsCfg(BaseModel):
    sl_pips: float = Field(ge=0)
    tp_pips: float = Field(ge=0)
    use_pct_pips: bool = True


class TrailingCfg(BaseModel):
    enabled: bool = True
    mode: Literal["step", "activation_trail", "off"] = "step"
    step_pips: float = Field(ge=0)
    stop_pips: float = Field(ge=0)
    activation_pips: float = Field(ge=0)
    use_pct_pips: bool = True


class ReversedOrderCfg(BaseModel):
    mode: Literal["cancel", "keep_reverse", "keep_close_only", "hedge"] = "cancel"


# ─── Time Filter ────────────────────────────────────────────────


class SessionWindow(BaseModel):
    start: str
    end: str


class BlackoutWindow(BaseModel):
    start: str
    end: str
    behavior: Literal["close_on_entry", "let_run_no_new"] = "let_run_no_new"


class TimeFilterCfg(BaseModel):
    enabled: bool = False
    timezone: str = "UTC"
    sessions: list[SessionWindow] = Field(default_factory=list)
    weekdays_off: list[str] = Field(default_factory=list)
    blackouts: list[BlackoutWindow] = Field(default_factory=list)


# ─── Spread & Slippage ─────────────────────────────────────────


class SpreadCfg(BaseModel):
    max_pips: float = Field(ge=0, default=5)
    dynamic_atr_mult: float = Field(ge=0, default=0.2)
    use_dynamic: bool = False
    log_only: bool = False


class SlippageCfg(BaseModel):
    max_pct: float = Field(ge=0, default=0.1)
    on_violation: Literal["alert", "close_immediately"] = "alert"


# ─── Simulator ──────────────────────────────────────────────────


class SimulatorCfg(BaseModel):
    taker_fee_pct: float = Field(ge=0, default=0.04)
    slippage_noise_pips: float = Field(ge=0, default=0.01)
    starting_equity_usd: float = Field(ge=0, default=1000)
    simulate_funding: bool = True
    funding_rate_pct: float = Field(default=0.01, ge=0)  # 0.01% per 8h
    latency_ms: int = Field(default=0, ge=0)


# ─── Volatility Scanner ────────────────────────────────────────


class VolatilityWeights(BaseModel):
    natr: float = Field(ge=0, le=1, default=0.4)
    expansion: float = Field(ge=0, le=1, default=0.3)
    donchian_atr: float = Field(ge=0, le=1, default=0.3)


class VolatilityCfg(BaseModel):
    mode: Literal["normalized_atr", "composite"] = "composite"
    weights: VolatilityWeights = VolatilityWeights()
    min_score: float = Field(ge=0, default=0.2)
    min_24h_volume_usd: float = Field(ge=0, default=5_000_000)


# ─── Safety ─────────────────────────────────────────────────────


class SafetyCfg(BaseModel):
    max_daily_loss_pct: float = Field(ge=0, default=5.0)
    max_drawdown_pct: float = Field(ge=0, default=15.0)
    max_consecutive_losses: int = Field(ge=0, default=5)
    check_on_tick: bool = True  # real-time safety on every N ticks
    tick_check_interval: int = Field(default=100, ge=1)  # check every N ticks
    orphan_order_policy: Literal["alert_only", "cancel"] = "alert_only"
    reconciliation_interval_sec: int = Field(ge=10, default=300)


# ─── Infrastructure ────────────────────────────────────────────


class DatabaseCfg(BaseModel):
    url: str = ""  # overridden by DATABASE_URL env var
    pool_min: int = Field(default=5, ge=1)
    pool_max: int = Field(default=15, ge=2)


class AuthCfg(BaseModel):
    enabled: bool = True
    jwt_secret: str = ""  # overridden by JWT_SECRET env var
    token_expiry_hours: int = Field(default=24, ge=1)
    admin_username: str = ""  # overridden by ADMIN_USERNAME env var
    admin_password: str = ""  # overridden by ADMIN_PASSWORD env var


class LoggingCfg(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: str = "logs/bot.log"
    max_size_mb: int = Field(ge=1, default=50)


class NotificationsCfg(BaseModel):
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook: str = ""
    events: list[str] = Field(default_factory=lambda: [
        "trade_opened", "trade_closed", "error", "kill_switch", "safety_triggered",
    ])


class LiveCfg(BaseModel):
    """Settings specific to live/testnet trading on Binance."""
    auto_set_leverage: bool = True
    auto_set_margin_type: bool = True
    margin_type: Literal["ISOLATED", "CROSSED"] = "ISOLATED"
    recv_window_ms: int = Field(default=5000, ge=1000, le=60000)
    listen_key_refresh_sec: int = Field(default=1800, ge=60)  # 30 min
    startup_reconcile: bool = True
    max_retries: int = Field(default=3, ge=1, le=10)
    retry_delay_sec: float = Field(default=1.0, ge=0.1, le=30)


# ─── Root Config ────────────────────────────────────────────────


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: Literal["paper", "testnet", "live"]
    watchlist: list[str]
    trade_list: list[str] = Field(default_factory=list)
    timeframe: Literal["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"]

    strategy: StrategyCfg
    sizing: SizingCfg
    portfolio_risk: PortfolioRiskCfg = PortfolioRiskCfg()
    equity: EquityCfg = EquityCfg()
    stops: StopsCfg
    trailing: TrailingCfg
    reversed_order: ReversedOrderCfg = ReversedOrderCfg()
    time_filter: TimeFilterCfg = TimeFilterCfg()
    spread: SpreadCfg = SpreadCfg()
    slippage: SlippageCfg = SlippageCfg()
    simulator: SimulatorCfg = SimulatorCfg()
    volatility: VolatilityCfg = VolatilityCfg()
    safety: SafetyCfg = SafetyCfg()
    database: DatabaseCfg = DatabaseCfg()
    auth: AuthCfg = AuthCfg()
    logging: LoggingCfg = LoggingCfg()
    notifications: NotificationsCfg = NotificationsCfg()
    live: LiveCfg = LiveCfg()

    @field_validator("watchlist")
    @classmethod
    def _uppercase_watchlist(cls, v: list[str]) -> list[str]:
        return [s.upper() for s in v]

    @field_validator("trade_list")
    @classmethod
    def _uppercase_trade_list(cls, v: list[str]) -> list[str]:
        return [s.upper() for s in v]


def load_config(path: Path) -> Config:
    """Load and validate config from a YAML file."""
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config.model_validate(data)
