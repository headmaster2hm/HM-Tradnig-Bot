"""Secret handling — prefer env vars / logged-in MT5 terminal over disk passwords."""

from __future__ import annotations

import os
from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.config_loader import AppConfig


ENV_MT5_PASSWORD = "HM_MT5_PASSWORD"
ENV_TELEGRAM_TOKEN = "HM_TELEGRAM_BOT_TOKEN"
ENV_BRIDGE_TOKEN = "HM_BRIDGE_TOKEN"


def resolve_mt5_password(config: AppConfig) -> str:
    env = os.environ.get(ENV_MT5_PASSWORD, "").strip()
    if env:
        return env
    return (config.mt5.password or "").strip()


def resolve_bridge_token(config: AppConfig) -> str:
    env = os.environ.get(ENV_BRIDGE_TOKEN, "").strip()
    if env:
        return env
    return (config.mt5_bridge.token or "").strip()


def resolve_telegram_token(config: AppConfig) -> str:
    env = os.environ.get(ENV_TELEGRAM_TOKEN, "").strip()
    if env:
        return env
    return (config.telegram.bot_token or "").strip()


def secrets_on_disk_warnings(config: AppConfig) -> list[str]:
    warnings: list[str] = []
    if (config.mt5.password or "").strip():
        warnings.append(
            "MT5 password is stored in settings.json. "
            f"Prefer an already-logged-in MT5 terminal, or set {ENV_MT5_PASSWORD}."
        )
    if (config.telegram.bot_token or "").strip():
        warnings.append(
            "Telegram bot token is stored in settings.json. "
            f"Prefer {ENV_TELEGRAM_TOKEN} instead."
        )
    if (config.mt5_bridge.token or "").strip():
        warnings.append(
            "Bridge token is stored in settings.json. "
            f"Prefer the {ENV_BRIDGE_TOKEN} environment variable instead."
        )
    return warnings


def harden_runtime_config(config: AppConfig) -> list[str]:
    """Apply safety defaults at startup. Returns human-readable notices."""
    notices: list[str] = []
    if not config.dry_run and config.stop_loss_points <= 0:
        config.dry_run = True
        notices.append(
            "Live mode disabled at startup: stop_loss_points must be > 0. Forced dry_run=true."
        )
    return notices


def sanitize_config_for_disk(config: AppConfig) -> AppConfig:
    """Return a copy safe to write: strip secrets unless user opted in."""
    clean = deepcopy(config)
    if not getattr(clean.mt5, "remember_password", False):
        clean.mt5.password = ""
    if not getattr(clean.telegram, "remember_token", False):
        clean.telegram.bot_token = ""
    clean.mt5_bridge.token = ""
    return clean
