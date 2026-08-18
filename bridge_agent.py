"""HM Bridge agent — exposes your desktop MetaTrader 5 to the hosted bot.

Run this on the SAME Windows machine where MetaTrader 5 is installed and
logged in. It opens a secure outbound WebSocket to the bot's dashboard and
answers its trading calls locally. No port forwarding needed.

Requirements (Windows):

    pip install MetaTrader5 websocket-client numpy

Usage:

    python bridge_agent.py --token YOUR_BRIDGE_TOKEN
    python bridge_agent.py --url wss://tradebot.headmaster.fun/bridge/ws --token ... --login 12345 --password ... --server Broker-Server

Optional login/server/password attach MT5 to an account if it is not
already logged in. Leave them out if the terminal is already signed in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import date, datetime
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

__version__ = "1.1.0"

TELEMETRY_INTERVAL = 1.0
MAX_PAYLOAD = 4 * 1024 * 1024


def _to_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if np is not None:
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, np.ndarray):
            return [_to_json(item) for item in value.tolist()]
        if isinstance(value, np.void):
            return _to_json(dict(zip(value.dtype.names, value.tolist())))
    if isinstance(value, dict):
        return {str(key): _to_json(item) for key, item in value.items()}
    if hasattr(value, "_asdict"):  # namedtuple (MT5 info/position/deal objects)
        return _to_json(value._asdict())
    if isinstance(value, (list, tuple)):
        return [_to_json(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return _to_json(vars(value))
    return str(value)


def _rates_json(rates: Any) -> list[dict[str, Any]] | None:
    if rates is None:
        return None
    try:
        names = rates.dtype.names
        return [{name: _to_json(row[name]) for name in names} for row in rates]
    except Exception:  # noqa: BLE001
        return None


class BridgeAgent:
    def __init__(self, url: str, token: str, kwargs: dict[str, Any]) -> None:
        self.url = url
        self.token = token
        self.init_kwargs = kwargs
        self._stop = threading.Event()
        self._last_init_error = ""
        self._mt5 = None
        self._mt5_ready = False
        self._mt5_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self.connected = False
        self.account: Any = None
        self.status_text = "idle"
        self.last_error_text = ""

    # -- thread-safe WebSocket send ---------------------------------------
    def _ws_send(self, ws: Any, data: str) -> None:
        """Serialize all outgoing WebSocket frames to prevent corruption."""
        with self._send_lock:
            ws.send(data)

    # -- MT5 wrappers ----------------------------------------------------
    def _import_mt5(self) -> bool:
        if self._mt5 is not None:
            return True
        try:
            import MetaTrader5 as mt5  # type: ignore[import-untyped]

            self._mt5 = mt5
            return True
        except ImportError:
            self._last_init_error = "MetaTrader5 package not installed on this machine"
            return False

    def _ensure_mt5_ready(self) -> bool:
        """Initialize the local MT5 terminal once so telemetry carries a login.

        Initialization happens lazily from the telemetry loop (and never blocks
        the websocket reply path): the terminal launches/attaches on first use
        and we retry each second until it succeeds.
        """
        if self._mt5_ready:
            return True
        if not self._import_mt5():
            return False
        with self._mt5_lock:
            if self._mt5_ready:
                return True
            try:
                ok = bool(self._mt5.initialize(**self.init_kwargs))
            except Exception as exc:  # noqa: BLE001
                ok = False
                self._last_init_error = str(exc)
            if ok:
                self._mt5_ready = True
            else:
                self._last_init_error = str(self._mt5.last_error())
                logging.getLogger("agent").warning(
                    "MT5 initialize failed: %s", self._last_init_error
                )
            return ok

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        log = logging.getLogger("agent")

        if method == "update":
            return self._handle_update(params, log)
        if method == "version":
            return __version__

        if not self._import_mt5():
            return {"_hm_error": self._last_init_error}
        if method != "initialize" and not self._ensure_mt5_ready():
            return {"_hm_error": self._last_init_error or "MT5 not initialized"}

        if method == "initialize":
            return self._ensure_mt5_ready()

        mt5 = self._mt5
        with self._mt5_lock:
            try:
                if method == "shutdown":
                    return bool(mt5.shutdown())
                if method == "terminal_info":
                    return _to_json(mt5.terminal_info())
                if method == "account_info":
                    return _to_json(mt5.account_info())
                if method == "symbol_info":
                    return _to_json(mt5.symbol_info(params.get("symbol")))
                if method == "symbol_select":
                    return bool(mt5.symbol_select(params.get("symbol"), bool(params.get("enable", True))))
                if method == "symbol_info_tick":
                    return _to_json(mt5.symbol_info_tick(params.get("symbol")))
                if method == "copy_rates_from_pos":
                    rates = mt5.copy_rates_from_pos(
                        params.get("symbol"),
                        int(params.get("timeframe", 1)),
                        int(params.get("start", 0)),
                        int(params.get("count", 100)),
                    )
                    return _rates_json(rates)
                if method == "copy_rates_range":
                    rates = mt5.copy_rates_range(
                        params.get("symbol"),
                        int(params.get("timeframe", 1)),
                        int(params.get("start", 0)),
                        int(params.get("stop", 0)),
                    )
                    return _rates_json(rates)
                if method == "positions_get":
                    symbol = params.get("symbol") or None
                    return _to_json(mt5.positions_get(symbol=symbol))
                if method == "orders_get":
                    symbol = params.get("symbol") or None
                    return _to_json(mt5.orders_get(symbol=symbol))
                if method == "order_send":
                    request = dict(params.get("request") or {})
                    return _to_json(mt5.order_send(**request))
                if method == "position_modify":
                    ticket = int(params.get("ticket", 0))
                    sl = float(params.get("sl", 0))
                    tp = float(params.get("tp", 0))
                    request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": ticket,
                        "sl": sl,
                        "tp": tp,
                    }
                    return _to_json(mt5.order_send(request))
                if method == "history_deals_get":
                    return _to_json(
                        mt5.history_deals_get(
                            int(params.get("date_from", 0)), int(params.get("date_to", 0))
                        )
                    )
                if method == "last_error":
                    return mt5.last_error()
            except Exception as exc:  # noqa: BLE001
                log.error("mt5.%s failed: %s", method, exc)
                raise
        return {"_hm_error": f"unknown method {method}"}

    # -- auto-update -----------------------------------------------------
    def _handle_update(self, params: dict[str, Any], log: logging.Logger) -> bool:
        url = params.get("url", "")
        expected_sha256 = params.get("sha256", "")
        if not url:
            return False
        log.info("downloading update from %s", url)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"HMBridgeAgent/{__version__}"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if expected_sha256:
                actual = hashlib.sha256(data).hexdigest()
                if actual != expected_sha256:
                    log.error("update hash mismatch: expected %s got %s", expected_sha256, actual)
                    return False
            if getattr(sys, "frozen", False):
                app_dir = os.path.dirname(sys.executable)
                update_dir = os.path.join(
                    os.environ.get("LOCALAPPDATA", app_dir), "HMBotBridgeAgent", "updates"
                )
                os.makedirs(update_dir, exist_ok=True)
                new_path = os.path.join(update_dir, os.path.basename(sys.executable))
                with open(new_path, "wb") as fh:
                    fh.write(data)
                log.info("launching update from %s", new_path)
                subprocess.Popen([new_path, "--autostart"])  # noqa: S603
                os._exit(0)
            else:
                my_path = os.path.abspath(__file__)
                tmp_path = my_path + ".tmp"
                with open(tmp_path, "wb") as fh:
                    fh.write(data)
                os.replace(tmp_path, my_path)
                log.info("updated, restarting...")
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as exc:  # noqa: BLE001
            log.error("update failed: %s", exc)
            return False
        return True

    # -- connection ------------------------------------------------------
    def _run_once(self) -> None:
        import websocket  # type: ignore[import-untyped]

        log = logging.getLogger("agent")
        ws = websocket.create_connection(self.url, timeout=20, max_size=MAX_PAYLOAD)
        try:
            self._ws_send(ws, json.dumps({"type": "auth", "token": self.token}))
            welcome = json.loads(ws.recv())
            if welcome.get("type") == "error":
                raise RuntimeError(f"server rejected auth: {welcome.get('error')}")
            self.connected = True
            self.status_text = "connected"
            self.last_error_text = ""
            log.info("authenticated with server")

            threading.Thread(
                target=self._telemetry_loop, args=(ws,), daemon=True, name="telemetry"
            ).start()

            while not self._stop.is_set():
                try:
                    raw = ws.recv()
                except Exception:  # noqa: BLE001  (timeout)
                    try:
                        ws.ping("hm")
                        continue
                    except Exception:  # noqa: BLE001
                        raise
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                reply = self._handle_request(msg)
                if reply is not None:
                    self._ws_send(ws, json.dumps(reply))
        finally:
            self.connected = False
            self.status_text = "disconnected"
            ws.close()

    def _handle_request(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        msg_id = msg.get("id")
        method = str(msg.get("method") or "").split(".", 1)[-1]
        if msg_id is None or not method:
            return None
        params = msg.get("params") or {}
        try:
            result = self._dispatch(method, params)
            error = None
            if isinstance(result, dict) and result.pop("_hm_error", None):
                error = result.pop("_hm_error", None)
        except Exception as exc:  # noqa: BLE001
            result, error = None, str(exc)
        reply = {"id": msg_id}
        if error:
            reply["error"] = error
        else:
            reply["result"] = result
        return reply

    def _telemetry_loop(self, ws: Any) -> None:
        log = logging.getLogger("agent")
        last_ping = time.time()
        while not self._stop.is_set():
            try:
                if self._ensure_mt5_ready():
                    with self._mt5_lock:
                        mt5 = self._mt5
                        account = _to_json(mt5.account_info())
                        terminal = _to_json(mt5.terminal_info())
                        positions = _to_json(mt5.positions_get())
                        last_error = mt5.last_error()
                    self.account = account
                    data = {
                        "account": account,
                        "terminal": terminal,
                        "positions": positions,
                        "last_error": last_error,
                        "version": __version__,
                    }
                    self._ws_send(ws, json.dumps({"type": "telemetry", "data": data}))
                    if time.time() - last_ping > 30:
                        try:
                            ws.ping("hm")
                            last_ping = time.time()
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as exc:  # noqa: BLE001
                log.debug("telemetry push failed: %s", exc)
            self._stop.wait(TELEMETRY_INTERVAL)

    def run(self) -> None:
        log = logging.getLogger("agent")
        backoff = 2.0
        while not self._stop.is_set():
            try:
                self.status_text = "connecting"
                log.info("connecting to %s", self.url)
                self._run_once()
                backoff = 2.0
            except KeyboardInterrupt:
                break
            except Exception as exc:  # noqa: BLE001
                self.last_error_text = str(exc)
                self.status_text = f"error: {exc}"
                log.error("connection lost: %s — retrying in %.0fs", exc, backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 1.6, 30.0)

    def stop(self) -> None:
        self._stop.set()
        self.status_text = "stopped"


def main() -> int:
    parser = argparse.ArgumentParser(description="HM Bridge agent — expose desktop MT5 to the hosted bot")
    parser.add_argument("--url", default=os.environ.get("HM_BRIDGE_URL", "wss://tradebot.headmaster.fun/bridge/ws"))
    parser.add_argument("--token", default=os.environ.get("HM_BRIDGE_TOKEN", ""))
    parser.add_argument("--mt5-path", default="", help="terminal64.exe path")
    parser.add_argument("--login", type=int, default=0)
    parser.add_argument("--password", default=os.environ.get("HM_MT5_PASSWORD", ""))
    parser.add_argument("--server", default="")
    parser.add_argument("--log", default="bridge_agent.log")
    parser.add_argument("--autostart", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(args.log, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    if not args.token:
        logging.getLogger("agent").error("No --token given (or HM_BRIDGE_TOKEN env). Refusing to start.")
        return 1

    kwargs: dict[str, Any] = {}
    if args.mt5_path:
        kwargs["path"] = args.mt5_path
    if args.login:
        kwargs["login"] = args.login
        kwargs["password"] = args.password
        kwargs["server"] = args.server

    agent = BridgeAgent(args.url, args.token, kwargs)
    agent.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
