"""Load and persist bot configuration from settings.json."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from utils.paths import ensure_user_settings

from config.secrets import harden_runtime_config, sanitize_config_for_disk, secrets_on_disk_warnings


def default_settings_path() -> Path:
    return ensure_user_settings()


@dataclass
class IndicatorConfig:
    rsi_period: int = 14
    ema_fast: int = 48
    ema_slow: int = 50
    rsi_levels: list[int] = field(
        default_factory=lambda: [0, 15, 30, 39, 50, 63, 70, 85, 100]
    )


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    remember_token: bool = False


@dataclass
class MT5Config:
    path: str = ""
    login: int = 0
    password: str = ""
    server: str = ""
    remember_password: bool = False


@dataclass
class MT5BridgeConfig:
    enabled: bool = False
    url: str = "wss://tradebot.headmaster.fun/bridge/ws"
    token: str = ""


@dataclass
class AppConfig:
    symbol: str = "Crash 500 Index"
    timeframe: str = "M1"
    lot_size: float = 0.2
    risk_percent: float = 1.0
    use_risk_sizing: bool = False
    stop_loss_points: float = 200.0
    take_profit_points: float = 300.0
    magic_number: int = 50014
    comment: str = "HMBotRSI"
    slippage: int = 30
    spread_limit: float = 150.0
    cooldown_candles: int = 3
    max_trades_per_day: int = 10
    daily_profit_target: float = 50.0
    daily_loss_limit: float = 30.0
    session_start: str = "00:00"
    session_end: str = "23:59"
    close_on_reverse: bool = True
    dry_run: bool = True
    enable_notifications: bool = True
    dark_mode: bool = True
    candle_count: int = 300
    poll_interval_ms: int = 500
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)
    mt5: MT5Config = field(default_factory=MT5Config)
    mt5_bridge: MT5BridgeConfig = field(default_factory=MT5BridgeConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge(defaults: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _build_config(data: dict[str, Any]) -> AppConfig:
    tg = data.get("telegram") or {}
    mt5 = data.get("mt5") or {}
    bridge = data.get("mt5_bridge") or {}
    return AppConfig(
        symbol=data["symbol"],
        timeframe=data["timeframe"],
        lot_size=float(data["lot_size"]),
        risk_percent=float(data["risk_percent"]),
        use_risk_sizing=bool(data["use_risk_sizing"]),
        stop_loss_points=float(data["stop_loss_points"]),
        take_profit_points=float(data["take_profit_points"]),
        magic_number=int(data["magic_number"]),
        comment=str(data["comment"]),
        slippage=int(data["slippage"]),
        spread_limit=float(data["spread_limit"]),
        cooldown_candles=int(data["cooldown_candles"]),
        max_trades_per_day=int(data["max_trades_per_day"]),
        daily_profit_target=float(data["daily_profit_target"]),
        daily_loss_limit=float(data["daily_loss_limit"]),
        session_start=str(data["session_start"]),
        session_end=str(data["session_end"]),
        close_on_reverse=bool(data["close_on_reverse"]),
        dry_run=bool(data["dry_run"]),
        enable_notifications=bool(data["enable_notifications"]),
        dark_mode=bool(data["dark_mode"]),
        candle_count=int(data["candle_count"]),
        poll_interval_ms=int(data["poll_interval_ms"]),
        telegram=TelegramConfig(
            enabled=bool(tg.get("enabled", False)),
            bot_token=str(tg.get("bot_token", "")),
            chat_id=str(tg.get("chat_id", "")),
            remember_token=bool(tg.get("remember_token", False)),
        ),
        indicators=IndicatorConfig(**data["indicators"]),
        mt5=MT5Config(
            path=str(mt5.get("path", "")),
            login=int(mt5.get("login", 0) or 0),
            password=str(mt5.get("password", "")),
            server=str(mt5.get("server", "")),
            remember_password=bool(mt5.get("remember_password", False)),
        ),
        mt5_bridge=MT5BridgeConfig(
            enabled=bool(bridge.get("enabled", False)),
            url=str(bridge.get("url", "wss://tradebot.headmaster.fun/bridge/ws")),
            token=str(bridge.get("token", "")),
        ),
    )


def load_config(path: Path | str | None = None) -> AppConfig:
    settings_path = Path(path) if path else default_settings_path()
    defaults = AppConfig().to_dict()
    if settings_path.exists():
        with settings_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        data = _merge(defaults, loaded)
    else:
        data = defaults
        save_config(AppConfig(), settings_path)

    config = _build_config(data)
    harden_runtime_config(config)
    return config


def save_config(config: AppConfig, path: Path | str | None = None) -> None:
    settings_path = Path(path) if path else default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = sanitize_config_for_disk(config)
    with settings_path.open("w", encoding="utf-8") as handle:
        json.dump(payload.to_dict(), handle, indent=2)


def config_security_notices(config: AppConfig) -> list[str]:
    """Warnings about secrets stored on disk (call after load_config)."""
    return secrets_on_disk_warnings(config)
