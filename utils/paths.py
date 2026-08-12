"""Resolve app / resource paths for source runs and frozen executables.

Frozen (.exe) user data lives under %LOCALAPPDATA%/HMBotTrader so the
distributable folder never contains another person's settings, trade history,
or account leftovers when you zip and share the build.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_DATA_NAME = "HMBotTrader"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """
    Writable app root.
    - Frozen: %LOCALAPPDATA%/HMBotTrader (per Windows user)
    - Source: TradingBot/ project folder
    """
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            path = Path(base) / APP_DATA_NAME
        else:
            path = Path.home() / f".{APP_DATA_NAME}"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(__file__).resolve().parents[1]


def install_dir() -> Path:
    """Folder containing the .exe (or TradingBot/ when running from source)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_dir() -> Path:
    """Bundled read-only assets (PyInstaller _MEIPASS, or TradingBot/ in source)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", install_dir()))
    return Path(__file__).resolve().parents[1]


def settings_path() -> Path:
    """User-writable settings location (never ships inside the .exe bundle)."""
    if is_frozen():
        return app_dir() / "settings.json"
    return app_dir() / "config" / "settings.json"


def default_db_path() -> Path:
    """User-writable trade database (created empty for each Windows user)."""
    if is_frozen():
        return app_dir() / "trades.db"
    return app_dir() / "database" / "trades.db"


def admin_config_path() -> Path:
    """Owner-side admin config (username hash, secret control path, signing key)."""
    return app_dir() / "admin.json"


def admin_db_path() -> Path:
    """Owner-side admin database (customers, payments, issued license keys)."""
    if is_frozen():
        return app_dir() / "control.db"
    return app_dir() / "database" / "control.db"


def ensure_user_settings() -> Path:
    """
    Ensure a writable settings.json exists for this user.

    On first run of the .exe, seeds ONLY from the bundled settings.dist.json
    (clean defaults: dry_run=true, empty credentials — never the developer's
    personal settings.json).
    """
    user_path = settings_path()
    if user_path.exists():
        return user_path

    user_path.parent.mkdir(parents=True, exist_ok=True)

    if is_frozen():
        bundled = resource_dir() / "config" / "settings.dist.json"
        if bundled.exists():
            shutil.copyfile(bundled, user_path)
        else:
            # Absolute fallback: write minimal safe defaults
            user_path.write_text(
                '{\n  "dry_run": true,\n  "mt5": {"login": 0, "password": "", "server": ""}\n}\n',
                encoding="utf-8",
            )
    return user_path
