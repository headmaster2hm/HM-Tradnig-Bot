"""HM Bot Trader — local web dashboard (browser UI).

Serves a modern single-page dashboard on 127.0.0.1 and drives the
trading engine from a single background thread. The engine is owned by
exactly one thread; HTTP handlers talk to it through a command queue so
the MT5 client and SQLite database are never touched concurrently.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd

from backtest import run_backtest
from bridge.manager import get_manager
from config import AppConfig, config_security_notices, load_config, save_config
from config.config_loader import _build_config, _merge
from database.admin_db import AdminDatabase
from execution import TradeExecutor
from utils import admin as admin_util
from utils import hmweb3
from utils import license as license_util
from utils.logger import get_logger
from utils.paths import app_dir

logger = get_logger("web")

WEB_DIR = Path(__file__).resolve().parent / "web"
ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets"
WINDOWS_SETUP = ASSETS_DIR / "HMBotTrader-Setup.exe"
WINDOWS_VERSION = "1.1.0"

# Hosts that are the public website. When the homepage is reached through one
# of these the browser gets the download page instead of the local dashboard.
PUBLIC_HOSTS = {"tradebot.headmaster.fun", "www.tradebot.headmaster.fun"}

# Cache for the installer checksum/size, keyed by mtime+size of the .exe.
_download_cache: tuple[str, str] | None = None

# Browser <-> server secret placeholder: the real value never leaves this machine.
KEEP = "__KEEP__"

_admin_db: AdminDatabase | None = None


def _get_admin_db() -> AdminDatabase:
    global _admin_db
    if _admin_db is None:
        _admin_db = AdminDatabase()
    return _admin_db


_connected_account_seen: dict[str, Any] = {"login": "", "ts": 0.0}


def _register_connected_account(telemetry: dict[str, Any]) -> None:
    """Auto-track MT5 accounts that connect via the bridge.

    The bridge agent pushes telemetry (with the MT5 account info) every
    second. When a real login appears we make sure a users row exists and
    stamp last_seen_at so the account shows up in the admin Users tab.
    Writes are throttled to ~once a minute per account.
    """
    account = telemetry.get("account") or {}
    login = str(account.get("login") or "").strip()
    if not login or login == "SIM" or not login.isdigit():
        return
    now = time.time()
    if login == _connected_account_seen["login"] and now - _connected_account_seen["ts"] < 60:
        return
    _connected_account_seen["login"] = login
    _connected_account_seen["ts"] = now
    try:
        db = _get_admin_db()
        db.get_or_create_user_by_account(login)
        db.touch_user_account(login)
    except Exception:  # noqa: BLE001
        logger.exception("failed to register connected MT5 account %s", login)


def _tail_log(max_lines: int = 300) -> list[str]:
    log_file = app_dir() / "logs" / "bot.log"
    try:
        if not log_file.is_file():
            return []
        with log_file.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
        return [line.rstrip("\n") for line in lines[-max_lines:]]
    except OSError:
        return []


def _human_bytes(num: int) -> str:
    """Format a byte count as a compact human string (e.g. 46.2 MB)."""
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def _file_sha256(path: Path) -> str:
    """Checksum of a file, cached until the file's mtime or size changes."""
    global _download_cache
    try:
        stat = path.stat()
        key = f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return ""
    if _download_cache is not None and _download_cache[0] == key:
        return _download_cache[1]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    _download_cache = (key, digest.hexdigest())
    return _download_cache[1]


def _time(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return float(value)


def _strip_keep(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            key: value
            for key, value in ((key, _strip_keep(v)) for key, v in obj.items())
            if value is not None and value != KEEP
        }
    return obj


class Engine:
    """Owns the TradeExecutor and a single background polling loop."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.executor = TradeExecutor(config)
        self._snapshot: Any = None
        self._lock = threading.Lock()
        self._license_error: str = ""
        self._queue: queue.Queue[tuple] = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="hm-engine")
        self._thread.start()

    # -- license <-> MT5 account binding --------------------------------
    def _license_account_error(self) -> str:
        """Reason the connected MT5 account is not licensed, or "" if OK."""
        if not license_util.is_activated():
            return ""
        try:
            login = self.executor.client.account_info().get("login")
        except Exception:  # noqa: BLE001
            return ""
        ok, error = license_util.check_account(login)
        return "" if ok else error

    def license_account_error(self) -> str:
        return self._license_error

    # -- background loop -------------------------------------------------
    def _loop(self) -> None:
        ticks = 0
        while True:
            self._drain_commands()
            try:
                snapshot = self.executor.tick()
            except Exception:  # noqa: BLE001
                logger.exception("engine tick failed")
                snapshot = None
            ticks += 1
            if ticks % 15 == 0:
                try:
                    self._license_error = self._license_account_error()
                except Exception:  # noqa: BLE001
                    self._license_error = ""
            if (
                self._license_error
                and snapshot is not None
                and getattr(snapshot, "status", "") == "RUNNING"
            ):
                logger.warning(
                    "Stopped bot — license/MT5 account mismatch: %s", self._license_error
                )
                try:
                    self.executor.stop()
                except Exception:  # noqa: BLE001
                    pass
            with self._lock:
                self._snapshot = snapshot
            interval = max(0.3, float(self.executor.config.poll_interval_ms) / 1000.0)
            time.sleep(interval)

    def _drain_commands(self) -> None:
        while True:
            try:
                name, kwargs, event, result = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                result["value"] = self._run_command(name, kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.exception("command %s failed", name)
                result["error"] = str(exc)
            finally:
                event.set()

    def _run_command(self, name: str, kwargs: dict[str, Any]) -> Any:
        ex = self.executor
        if name == "start":
            if not license_util.is_activated():
                raise ValueError(
                    "License required — pay the one-time "
                    f"{license_util.CURRENCY} {license_util.PRICE:.0f} fee and enter your "
                    "license key to activate the bot."
                )
            ok = ex.start()
            if not ok:
                return False
            mismatch = self._license_account_error()
            if mismatch:
                try:
                    ex.stop()
                except Exception:  # noqa: BLE001
                    pass
                raise ValueError(mismatch)
            return True
        if name == "stop":
            ex.stop()
            return True
        if name == "pause":
            ex.pause()
            return True
        if name == "resume":
            ex.resume()
            return True
        if name == "close_all":
            ex.close_all("Manual close (web)")
            return True
        if name == "close_position":
            ticket = int(kwargs.get("ticket", 0))
            result = ex.client.close_position(ticket)
            if result:
                ex._record_close(result, "Manual close (web)")
            return bool(result)
        if name == "reset_limits":
            ex.risk.reset_daily_limits()
            return True
        if name == "backtest":
            bars = max(100, min(int(kwargs.get("bars", 600)), 5000))
            candles = ex.client.copy_rates(bars)
            result = run_backtest(candles, ex.config)
            trades = [
                {
                    "side": t["side"],
                    "entry": round(float(t["entry"]), 5),
                    "exit": round(float(t["exit"]), 5),
                    "time": _time(t.get("time")),
                    "profit": round(float(t["profit"]), 2),
                }
                for t in result.trades
            ]
            return {
                "signals": result.signals,
                "win_rate": round(float(result.win_rate), 1),
                "net_profit": round(float(result.net_profit), 2),
                "trades": trades,
            }
        if name == "reload":
            new_config: AppConfig = kwargs["config"]
            old = self.executor
            try:
                old.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self.executor = TradeExecutor(new_config)
            self.config = new_config
            return True
        raise ValueError(f"Unknown command: {name}")

    def submit(self, name: str, **kwargs: Any) -> Any:
        event = threading.Event()
        result: dict[str, Any] = {}
        self._queue.put((name, kwargs, event, result))
        event.wait(30)
        if "error" in result:
            raise RuntimeError(result["error"])
        return result.get("value")

    def snapshot(self) -> Any:
        with self._lock:
            return self._snapshot


# -- serialization -------------------------------------------------------
def serialize_snapshot(snap: Any, config: AppConfig, executor: TradeExecutor) -> dict:
    if snap is None:
        return {"ok": False, "status": "IDLE"}

    candles: list[dict] | None = None
    if snap.candles is not None and not snap.candles.empty:
        tail = snap.candles.tail(220)
        candles = [
            {
                "t": _time(ts),
                "o": round(float(r["open"]), 5),
                "h": round(float(r["high"]), 5),
                "l": round(float(r["low"]), 5),
                "c": round(float(r["close"]), 5),
                "v": int(r["tick_volume"]),
            }
            for ts, r in tail.iterrows()
        ]

    indicators: list[dict] | None = None
    if snap.indicators is not None and not snap.indicators.empty:
        tail = snap.indicators.tail(220)
        indicators = [
            {
                "t": _time(ts),
                "rsi": _num(r["rsi"]),
                "ema48": _num(r["ema48"]),
                "ema50": _num(r["ema50"]),
            }
            for ts, r in tail.iterrows()
        ]

    markers = [
        {
            "kind": m["kind"],
            "price": float(m["price"]),
            "side": m.get("side"),
            "time": _time(m.get("time")),
        }
        for m in (snap.markers or [])
    ]

    signal = None
    if snap.signal is not None:
        s = snap.signal
        signal = {
            "signal": s.signal.value,
            "confidence": round(float(s.confidence), 1),
            "reason": s.reason,
            "rsi": _num(s.rsi),
            "ema48": _num(s.ema48),
            "ema50": _num(s.ema50),
            "bar_time": _time(s.bar_time),
        }

    risk = getattr(executor, "risk", None)
    try:
        spread = round(float(executor.client.symbol_spread_points()), 1)
    except Exception:
        spread = 20.0
    return {
        "ok": True,
        "status": snap.status,
        "paused": bool(executor.paused),
        "symbol": config.symbol,
        "spread": spread,
        "trades_today": int(risk.trades_today) if risk else 0,
        "mode": "LIVE" if not snap.dry_run else "DRY RUN",
        "simulated": bool(getattr(executor.client, "using_simulated_feed", False)),
        "connected": bool(snap.connected),
        "account": snap.account or {},
        "signal": signal,
        "rsi": _num(snap.rsi),
        "ema48": _num(snap.ema48),
        "ema50": _num(snap.ema50),
        "confidence": round(float(snap.confidence or 0.0), 1),
        "positions": snap.positions or [],
        "day_profit": round(float(snap.day_profit or 0.0), 2),
        "win_rate": round(float(snap.win_rate or 0.0), 1),
        "risk_reason": snap.risk_reason or "",
        "halted": bool(risk.halted) if risk else False,
        "logs": list((snap.logs or [])[-80:]),
        "candles": candles,
        "indicators": indicators,
        "markers": markers,
    }


def serialize_history(rows: list[dict]) -> list[dict]:
    return [
        {
            "id": r["id"],
            "ticket": r["ticket"],
            "time_open": r["time_open"],
            "time_close": r["time_close"],
            "type": r["trade_type"],
            "entry": r["entry_price"],
            "exit": r["exit_price"],
            "profit": r["profit"],
            "lot": r["lot_size"],
            "duration": r["duration_seconds"],
            "signal": r["signal"],
            "reason": r["reason_closed"],
            "confidence": r["confidence"],
            "dry_run": bool(r["dry_run"]),
        }
        for r in rows
    ]


# -- HTTP server ---------------------------------------------------------
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".exe": "application/x-msdownload",
}


def make_handler(engine: Engine) -> type[BaseHTTPRequestHandler]:
    get_manager().on_telemetry = _register_connected_account

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "HM Bot Trader/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug(fmt % args)

        # -- helpers ----------------------------------------------------
        def _send_json(
            self,
            payload: Any,
            status: int = 200,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}

        def _settings_payload(self) -> dict:
            cfg = engine.config
            data = cfg.to_dict()
            if cfg.mt5.password or os.environ.get("HM_MT5_PASSWORD"):
                data["mt5"]["password"] = KEEP
            if cfg.telegram.bot_token or os.environ.get("HM_TELEGRAM_BOT_TOKEN"):
                data["telegram"]["bot_token"] = KEEP
            if cfg.mt5_bridge.token or os.environ.get("HM_BRIDGE_TOKEN"):
                data["mt5_bridge"]["token"] = KEEP
            return {"config": data, "notices": config_security_notices(cfg)}

        def _save_settings(self, payload: dict) -> None:
            current = engine.config
            merged = _merge(current.to_dict(), _strip_keep(payload))
            new_config = _build_config(merged)
            save_config(new_config)
            reloaded = load_config()
            engine.submit("reload", config=reloaded)

        def _export_csv(self) -> None:
            tmp = Path(tempfile.gettempdir()) / "hm_trades.csv"
            engine.executor.db.export_csv(tmp)
            body = tmp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="hm_trades.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _is_public_host(self) -> bool:
            host = (self.headers.get("Host") or "").split(":", 1)[0].strip().lower()
            return host in PUBLIC_HOSTS

        def _download_info(self) -> None:
            info: dict[str, Any] = {
                "ok": False,
                "file": WINDOWS_SETUP.name,
                "version": WINDOWS_VERSION,
            }
            if not WINDOWS_SETUP.is_file():
                self._send_json(info, 404)
                return
            try:
                size = WINDOWS_SETUP.stat().st_size
            except OSError as exc:
                self._send_json({**info, "error": str(exc)}, 500)
                return
            info["ok"] = True
            info["size_bytes"] = size
            info["size_human"] = _human_bytes(size)
            info["sha256"] = _file_sha256(WINDOWS_SETUP)
            self._send_json(info)

        def _download_windows(self) -> None:
            if not WINDOWS_SETUP.is_file():
                self._send_json({"ok": False, "error": "Windows installer not found."}, 404)
                return
            try:
                size = WINDOWS_SETUP.stat().st_size
            except OSError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-msdownload")
            self.send_header(
                "Content-Disposition", 'attachment; filename="HMBotTrader-Setup.exe"'
            )
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                with WINDOWS_SETUP.open("rb") as handle:
                    while True:
                        chunk = handle.read(256 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _serve_static(self, path: str) -> None:
            if path in ("/", ""):
                path = "/download.html" if self._is_public_host() else "/home.html"
            elif path == "/app":
                path = "/index.html"
            elif path in ("/download", "/downloads"):
                path = "/download.html"
            target = (WEB_DIR / path.lstrip("/")).resolve()
            if not target.is_relative_to(WEB_DIR):
                self.send_error(403, "Forbidden")
                return
            # Control panel files are only reachable through the secret URL.
            if target.name in ("control.html", "control.css", "control.js"):
                self.send_error(404, "Not found")
                return
            if not target.is_file():
                target = WEB_DIR / "index.html"
            if not target.is_file():
                self.send_error(404, "Not found")
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type", MIME.get(target.suffix.lower(), "application/octet-stream")
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # -- control panel (owner) --------------------------------------
        def _cookie(self, name: str) -> str | None:
            raw = self.headers.get("Cookie") or ""
            for part in raw.split(";"):
                part = part.strip()
                if part.startswith(name + "="):
                    return part[len(name) + 1 :]
            return None

        def _control_authed(self) -> bool:
            return admin_util.session_verify(self._cookie(admin_util.SESSION_COOKIE))

        def _require_control(self) -> bool:
            if not self._control_authed():
                self._send_json({"ok": False, "error": "Not authorized"}, 401)
                return False
            return True

        def _session_cookie(self, token: str, max_age: int) -> str:
            return (
                f"{admin_util.SESSION_COOKIE}={token}; Path=/; HttpOnly; "
                f"SameSite=Strict; Max-Age={max_age}"
            )

        def _serve_control_file(self, filename: str) -> None:
            target = WEB_DIR / filename
            if not target.is_file():
                self.send_error(404, "Not found")
                return
            body = target.read_bytes()
            if filename == "control.html":
                prefix = "/" + admin_util.get_path_token()
                body = body.replace(b'href="ui.css"', f'href="{prefix}/ui.css"'.encode())
                body = body.replace(b'src="ui.js"', f'src="{prefix}/ui.js"'.encode())
            self.send_response(200)
            self.send_header(
                "Content-Type", MIME.get(target.suffix.lower(), "application/octet-stream")
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _engine_summary(self) -> dict:
            try:
                snap = engine.snapshot()
                if snap is None:
                    return {"ok": False, "status": "IDLE", "mode": "—"}
                return {
                    "ok": True,
                    "status": snap.status,
                    "mode": "LIVE" if not snap.dry_run else "DRY RUN",
                    "connected": bool(snap.connected),
                    "symbol": engine.config.symbol,
                    "dry_run": bool(snap.dry_run),
                    "paused": bool(engine.paused),
                    "day_profit": round(float(snap.day_profit or 0.0), 2),
                    "win_rate": round(float(snap.win_rate or 0.0), 1),
                    "trades_today": int(getattr(engine, "risk", None).trades_today)
                    if getattr(engine, "risk", None)
                    else 0,
                    "spread": 0.0,
                }
            except Exception:  # noqa: BLE001
                return {"ok": False, "status": "IDLE", "mode": "—"}

        def _control_overview(self) -> dict:
            db = _get_admin_db()
            return {
                "ok": True,
                "secured": admin_util.is_configured(),
                "username": admin_util.load_config().get("username") or "owner",
                "control_path": "/" + admin_util.get_path_token(),
                "store": db.overview(license_util.PRICE),
                "license": {"price": license_util.PRICE, "currency": license_util.CURRENCY},
                "engine": self._engine_summary(),
                "bridge": get_manager().bridge_status(),
                "payments": db.list_payments(status="pending")[:8],
            }

        def _handle_control_get(self, path: str, query: dict) -> None:
            if path == "/api/control/session":
                data = admin_util.load_config()
                self._send_json(
                    {
                        "ok": True,
                        "authed": self._control_authed(),
                        "secured": admin_util.is_configured(),
                        "username": data.get("username") or "owner",
                        "control_path": "/" + admin_util.get_path_token(),
                    }
                )
                return
            if path == "/api/control/overview":
                if not self._require_control():
                    return
                self._send_json(self._control_overview())
                return
            if path == "/api/control/settings":
                if not self._require_control():
                    return
                self._send_json(self._settings_payload())
                return
            if path == "/api/control/users":
                if not self._require_control():
                    return
                self._send_json({"ok": True, "users": _get_admin_db().list_users()})
                return
            if path == "/api/control/payments":
                if not self._require_control():
                    return
                self._send_json({"ok": True, "payments": _get_admin_db().list_payments()})
                return
            if path == "/api/control/keys":
                if not self._require_control():
                    return
                self._send_json({"ok": True, "keys": _get_admin_db().list_keys()})
                return
            if path == "/api/control/logs":
                if not self._require_control():
                    return
                lines = int(query.get("lines", ["300"])[0])
                self._send_json({"ok": True, "lines": _tail_log(lines)})
                return
            if path == "/api/control/history":
                if not self._require_control():
                    return
                rows = engine.executor.db.history(limit=500)
                self._send_json({"ok": True, "history": serialize_history(rows)})
                return
            if path == "/api/control/backtest":
                if not self._require_control():
                    return
                bars = int(query.get("bars", ["600"])[0])
                try:
                    self._send_json(engine.submit("backtest", bars=bars))
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            if path == "/api/control/export":
                if not self._control_authed():
                    self.send_error(401)
                    return
                try:
                    self._export_csv()
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            self._send_json({"ok": False, "error": "Not found"}, 404)

        def _handle_control_post(self, path: str, body: dict) -> None:
            if path == "/api/control/login":
                self._control_login(body)
                return
            if path == "/api/control/logout":
                self._send_json(
                    {"ok": True},
                    extra_headers={"Set-Cookie": self._session_cookie("", 0)},
                )
                return
            if not self._require_control():
                return

            db = _get_admin_db()
            if path == "/api/control/action":
                action = body.get("action", "")
                params = {k: v for k, v in body.items() if k != "action"}
                try:
                    self._send_json({"ok": bool(engine.submit(action, **params))})
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return
            if path == "/api/control/settings":
                try:
                    self._save_settings(body.get("config") or {})
                    self._send_json({"ok": True})
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                return

            # users
            if path == "/api/control/users":
                mt5_account = str(body.get("mt5_account", "") or "").strip()
                if not mt5_account:
                    self._send_json({"ok": False, "error": "MT5 account number is required."}, 400)
                    return
                if db.get_user_by_account(mt5_account):
                    self._send_json(
                        {"ok": False, "error": f"MT5 account {mt5_account} already exists."}, 400
                    )
                    return
                try:
                    user_id = db.create_user(
                        mt5_account,
                        str(body.get("email", "") or ""),
                        str(body.get("name", "") or ""),
                        str(body.get("notes", "") or ""),
                    )
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                    return
                self._send_json({"ok": True, "id": user_id})
                return
            if path == "/api/control/users/status":
                status = str(body.get("status", "") or "")
                if status not in ("active", "disabled"):
                    self._send_json({"ok": False, "error": "Invalid status."}, 400)
                    return
                db.set_user_status(int(body.get("id", 0)), status)
                self._send_json({"ok": True})
                return
            if path == "/api/control/users/update":
                mt5_account = str(body.get("mt5_account", "") or "").strip()
                if not mt5_account:
                    self._send_json({"ok": False, "error": "MT5 account number is required."}, 400)
                    return
                existing = db.get_user_by_account(mt5_account)
                if existing and existing["id"] != int(body.get("id", 0)):
                    self._send_json(
                        {"ok": False, "error": f"MT5 account {mt5_account} already exists."}, 400
                    )
                    return
                try:
                    db.update_user(
                        int(body.get("id", 0)),
                        mt5_account,
                        str(body.get("email", "") or ""),
                        str(body.get("name", "") or ""),
                        str(body.get("notes", "") or ""),
                    )
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                    return
                self._send_json({"ok": True})
                return
            if path == "/api/control/users/delete":
                db.delete_user(int(body.get("id", 0)))
                self._send_json({"ok": True})
                return

            # payments
            if path == "/api/control/payments":
                self._control_create_payment(body)
                return
            if path == "/api/control/payments/check":
                payment = db.get_payment(int(body.get("id", 0)))
                if not payment:
                    self._send_json({"ok": False, "error": "Payment not found."}, 404)
                    return
                try:
                    result = hmweb3.check_balance(payment["chain"], payment["address"])
                    self._send_json(
                        {
                            "ok": True,
                            "chain": result.get("chain", payment["chain"]),
                            "balance": result.get("balance"),
                            "unit": result.get("unit"),
                            "balance_usd": result.get("balance_usd"),
                        }
                    )
                except hmweb3.HmWeb3Error as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 502)
                return
            if path == "/api/control/payments/confirm":
                self._control_confirm_payment(body)
                return
            if path == "/api/control/payments/delete":
                db.delete_payment(int(body.get("id", 0)))
                self._send_json({"ok": True})
                return

            # keys
            if path == "/api/control/keys/generate":
                user_id = body.get("user_id")
                if not user_id:
                    self._send_json(
                        {"ok": False, "error": "Select the MT5 account this key is for."}, 400
                    )
                    return
                user = db.get_user(int(user_id))
                if not user:
                    self._send_json({"ok": False, "error": "Customer not found."}, 404)
                    return
                if not str(user.get("mt5_account") or "").strip():
                    self._send_json(
                        {"ok": False, "error": "Set the customer's MT5 account first (one key per account)."}, 400
                    )
                    return
                key = license_util.generate_key()
                db.add_key(key, int(user_id))
                self._send_json({"ok": True, "key": key, "mt5_account": user.get("mt5_account")})
                return
            if path == "/api/control/keys/revoke":
                db.set_key_status(str(body.get("key", "") or ""), "revoked")
                self._send_json({"ok": True})
                return

            # security
            if path == "/api/control/password":
                self._control_change_password(body)
                return

            self._send_json({"ok": False, "error": "Not found"}, 404)

        def _control_login(self, body: dict) -> None:
            ip = str(self.client_address[0])
            if admin_util.is_locked(ip):
                self._send_json(
                    {"ok": False, "error": "Too many attempts — try again later."}, 429
                )
                return
            username = str(body.get("username", "") or "")
            password = str(body.get("password", "") or "")
            if not admin_util.is_configured():
                self._send_json(
                    {"ok": False, "error": "Owner password not set. Run: python -m utils.admin set-password"},
                    503,
                )
                return
            if not admin_util.verify_password(username, password):
                admin_util.record_failure(ip)
                self._send_json({"ok": False, "error": "Invalid username or password."}, 401)
                return
            admin_util.reset_failures(ip)
            token = admin_util.issue_session()
            self._send_json(
                {"ok": True, "authed": True},
                extra_headers={"Set-Cookie": self._session_cookie(token, admin_util.SESSION_TTL_SECONDS)},
            )

        def _control_create_payment(self, body: dict) -> None:
            db = _get_admin_db()
            user_id = int(body.get("user_id", 0) or 0)
            chain = str(body.get("chain", "") or "").lower().strip()
            if chain not in hmweb3.PAYMENT_CHAINS:
                self._send_json({"ok": False, "error": f"Chain must be one of: {', '.join(hmweb3.PAYMENT_CHAINS)}."}, 400)
                return
            if not db.get_user(user_id):
                self._send_json({"ok": False, "error": "Customer not found."}, 404)
                return
            try:
                addresses = hmweb3.payment_addresses(force=True)
                address = addresses[chain]["address"]
            except hmweb3.HmWeb3Error as exc:
                self._send_json({"ok": False, "error": f"Could not generate address: {exc}"}, 502)
                return
            amount = body.get("amount_expected")
            try:
                amount = float(amount) if amount not in (None, "") else None
            except (TypeError, ValueError):
                amount = None
            unit = str(body.get("unit", "") or "").strip() or ("BTC" if chain == "btc" else "USDT")
            payment_id = db.create_payment(user_id, chain, address, amount, unit, str(body.get("notes", "") or ""))
            self._send_json({"ok": True, "id": payment_id, "address": address})

        def _control_confirm_payment(self, body: dict) -> None:
            db = _get_admin_db()
            payment_id = int(body.get("id", 0) or 0)
            payment = db.get_payment(payment_id)
            if not payment:
                self._send_json({"ok": False, "error": "Payment not found."}, 404)
                return
            txid = str(body.get("txid", "") or "")
            user_id = payment.get("user_id")
            if user_id:
                user = db.get_user(int(user_id))
                if not str(user.get("mt5_account") or "").strip():
                    self._send_json(
                        {"ok": False, "error": "Set the customer's MT5 account before confirming payment (one key per account)."}, 400
                    )
                    return
            if not db.set_payment_status(payment_id, "paid", txid=txid):
                self._send_json({"ok": False, "error": "Could not update payment."}, 500)
                return
            key = license_util.generate_key()
            db.add_key(key, user_id)
            if user_id:
                db.set_user_status(user_id, "active")
            self._send_json({"ok": True, "key": key, "payment": db.get_payment(payment_id)})

        def _control_change_password(self, body: dict) -> None:
            current = str(body.get("current", "") or "")
            username = str(body.get("username", "") or "").strip()
            new_password = str(body.get("new_password", "") or "")
            data = admin_util.load_config()
            if not admin_util.verify_password(data.get("username", ""), current):
                self._send_json({"ok": False, "error": "Current password is wrong."}, 401)
                return
            if not username:
                self._send_json({"ok": False, "error": "Username required."}, 400)
                return
            error = admin_util.set_password(username, new_password) if new_password else admin_util.set_password(username, current)
            if error:
                self._send_json({"ok": False, "error": error}, 400)
                return
            admin_util.reset_failures(str(self.client_address[0]))
            self._send_json({"ok": True})

        # -- routes -----------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/bridge/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
                from bridge.manager import get_manager
                from bridge.ws import serve as serve_bridge

                serve_bridge(self, get_manager())
                return
            if path == "/api/state":
                payload = serialize_snapshot(engine.snapshot(), engine.config, engine.executor)
                payload["license_account_error"] = engine.license_account_error()
                self._send_json(payload)
            elif path == "/api/license/status":
                self._send_json(license_util.status())
            elif path == "/api/payment/addresses":
                try:
                    self._send_json(hmweb3.payment_addresses())
                except hmweb3.HmWeb3Error as exc:
                    self._send_json({"ok": False, "error": str(exc), "status": exc.status})
                except Exception as exc:  # noqa: BLE001
                    logger.exception("payment address generation failed")
                    self._send_json({"ok": False, "error": str(exc)})
            elif path == "/api/history":
                rows = engine.executor.db.history(limit=1000)
                self._send_json(serialize_history(rows))
            elif path == "/api/settings":
                self._send_json(self._settings_payload())
            elif path == "/api/backtest":
                query = parse_qs(parsed.query)
                bars = int(query.get("bars", ["600"])[0])
                try:
                    self._send_json(engine.submit("backtest", bars=bars))
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"error": str(exc)}, 500)
            elif path == "/api/export":
                try:
                    self._export_csv()
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"error": str(exc)}, 500)
            elif path == "/api/download/info":
                self._download_info()
            elif path == "/api/download/windows":
                self._download_windows()
            elif path.startswith("/api/control/"):
                query = parse_qs(parsed.query)
                self._handle_control_get(path, query)
            else:
                token = admin_util.get_path_token()
                if path == f"/{token}":
                    self._serve_control_file("control.html")
                elif path == f"/{token}/ui.css":
                    self._serve_control_file("control.css")
                elif path == f"/{token}/ui.js":
                    self._serve_control_file("control.js")
                else:
                    self._serve_static(path)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            body = self._read_body()
            if path.startswith("/api/control/"):
                self._handle_control_post(path, body)
                return
            if path == "/api/action":
                action = body.get("action", "")
                params = {k: v for k, v in body.items() if k != "action"}
                try:
                    ok = bool(engine.submit(action, **params))
                    self._send_json({"ok": ok})
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(exc)}, 400)
            elif path == "/api/settings":
                try:
                    self._save_settings(body.get("config") or {})
                    self._send_json({"ok": True})
                except Exception as exc:  # noqa: BLE001
                    logger.exception("settings save failed")
                    self._send_json({"ok": False, "error": str(exc)}, 400)
            elif path == "/api/license/activate":
                key = str(body.get("key", "") or "").strip()
                mt5_account = str(body.get("mt5_account", "") or "").strip()
                if not mt5_account:
                    self._send_json(
                        {"ok": False, "error": "Enter the MT5 account number this license is for."}, 400
                    )
                    return
                ok, error = license_util.activate(key, mt5_account)
                if not ok:
                    self._send_json({"ok": False, "error": error}, 400)
                else:
                    self._send_json({"ok": True, "activated": True, **license_util.status()})
            elif path == "/api/payment/check":
                chain = str(body.get("chain", "") or "").strip().lower()
                address = str(body.get("address", "") or "").strip()
                try:
                    result = hmweb3.check_balance(chain, address)
                    self._send_json(
                        {
                            "ok": True,
                            "chain": result.get("chain", chain),
                            "address": result.get("address", address),
                            "balance": result.get("balance"),
                            "unit": result.get("unit"),
                            "balance_usd": result.get("balance_usd"),
                        }
                    )
                except hmweb3.HmWeb3Error as exc:
                    self._send_json({"ok": False, "error": str(exc), "status": exc.status}, 502)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("payment balance check failed")
                    self._send_json({"ok": False, "error": str(exc)}, 500)
            else:
                self._send_json({"ok": False, "error": "Not found"}, 404)

    return DashboardHandler


def create_server(host: str = "127.0.0.1", port: int = 0) -> tuple[ThreadingHTTPServer, Engine]:
    """Create (but do not serve) the dashboard HTTP server and its engine.

    Used by both the browser mode (``run_app``) and the native desktop
    window (``desktop.py``), which runs the server on a background thread.
    """
    config = load_config()
    engine = Engine(config)
    server = ThreadingHTTPServer((host, port), make_handler(engine))
    return server, engine


def run_app(host: str = "127.0.0.1", port: int = 0) -> None:
    server, engine = create_server(host, port)
    bound_port = int(server.server_address[1])
    local_url = f"http://127.0.0.1:{bound_port}"
    logger.info("HM Bot Trader dashboard ready at %s", local_url)
    print(f"\n  HM Bot Trader dashboard ->  {local_url}")
    control_url = f"{local_url}/{admin_util.get_path_token()}"
    secured = admin_util.is_configured()
    if not secured:
        print("  Owner control panel   ->  set a password first:  python -m utils.admin set-password")
    print(f"  Owner control panel   ->  {control_url}")
    if host in ("127.0.0.1", "localhost"):
        threading.Timer(0.8, lambda: webbrowser.open(local_url)).start()
    else:
        for ip in _lan_ips():
            print(f"  Mobile / network access  ->  http://{ip}:{bound_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _lan_ips() -> list[str]:
    """IPv4 addresses on this machine, excluding loopback."""
    try:
        import socket

        ips: list[str] = []
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
        return ips
    except Exception:  # noqa: BLE001
        return []


if __name__ == "__main__":
    run_app()
