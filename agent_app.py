"""HM Bridge Agent — Windows desktop app.

Discovers a local MetaTrader 5 terminal, opens a secure outbound link to the
hosted HM Bot Trader, and answers its trading calls locally. No Python needed
by end users (ships as a frozen windowed exe built by ``build_win.bat``).

Run from source:  python agent_app.py [--autostart]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import threading

import bridge_defaults
import mt5_detect
from bridge_agent import BridgeAgent

# ---------------------------------------------------------------- constants
APP_NAME = bridge_defaults.APP_NAME
APP_ID = bridge_defaults.APP_ID
DEFAULT_URL = bridge_defaults.DEFAULT_URL
DEFAULT_TOKEN = bridge_defaults.DEFAULT_TOKEN

FONT = "Segoe UI"
ACCENT = "#5b66ff"
BG = "#0e0f13"
CARD = "#16181e"
INK = "#eef0f4"
MUTED = "#7d818d"
GOOD = "#22c55e"
BAD = "#ef4444"
LINE = "#23242c"

POLL_MS = 500


def _app_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, APP_ID)
    os.makedirs(folder, exist_ok=True)
    return folder


def resource_path(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _single_instance() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import ctypes  # type: ignore[import-untyped]

        handle = ctypes.windll.kernel32.CreateMutexW(None, False, APP_ID)
        return bool(handle and ctypes.windll.kernel32.GetLastError() != 183)
    except Exception:  # noqa: BLE001
        return True


# ---------------------------------------------------------------- settings
CONFIG_PATH = os.path.join(_app_dir(), "config.json")


def _load_config() -> dict:
    defaults = {"url": DEFAULT_URL, "token": DEFAULT_TOKEN, "mt5_path": "", "autostart": False}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        defaults.update({k: v for k, v in saved.items() if v not in ("", None)})
    except Exception:  # noqa: BLE001
        pass
    return defaults


def _save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception:  # noqa: BLE001
        pass


def _autostart_set(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import winreg  # type: ignore[import-untyped]

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        if enabled:
            exe = f'"{sys.executable}" --autostart'
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, exe)
        else:
            try:
                winreg.DeleteValue(key, APP_ID)
            except OSError:
                pass
        winreg.CloseKey(key)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- logging
class TextHandler(logging.Handler):
    def __init__(self, widget) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.widget = widget

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.widget.insert("end", self.format(record) + "\n")
            self.widget.see("end")
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- app
class Splash:
    def __init__(self, root) -> None:  # type: ignore[no-untyped-def]
        self.root = root
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError:  # pragma: no cover
            self.win = None
            return

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        width, height = 480, 300
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self.win.geometry(f"{width}x{height}+{x}+{y}")

        canvas = tk.Canvas(self.win, width=width, height=height, bg=BG, highlightthickness=0)
        canvas.pack()
        try:
            from PIL import Image, ImageTk

            image = Image.open(resource_path(os.path.join("assets", "splash.png"))).resize(
                (width, height)
            )
            self._photo = ImageTk.PhotoImage(image)
            canvas.create_image(0, 0, anchor="nw", image=self._photo)
        except Exception:  # noqa: BLE001
            canvas.create_rectangle(0, 0, width, height, fill=BG)
            canvas.create_text(
                width // 2, height // 2 - 30, text="HM\u258c", fill=ACCENT,
                font=(FONT, 34, "bold"),
            )
            canvas.create_text(
                width // 2, height // 2 + 6, text=APP_NAME, fill=INK,
                font=(FONT, 18, "bold"),
            )
            canvas.create_text(
                width // 2, height // 2 + 34, text="Starting\u2026", fill=MUTED,
                font=(FONT, 10),
            )

        self._bar = ttk.Progressbar(
            canvas, length=width - 120, mode="determinate", maximum=24
        )
        canvas.create_window(width // 2, height - 28, window=self._bar)
        self._n = 0
        self._tick()

    def _tick(self) -> None:
        if self.win is None:
            return
        self._n += 1
        try:
            self._bar["value"] = self._n
        except Exception:  # noqa: BLE001
            return
        if self._n < 24:
            self.root.after(70, self._tick)

    def close(self) -> None:
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:  # noqa: BLE001
                pass


class AgentApp:
    def __init__(self, autostart: bool) -> None:
        if sys.platform == "win32":
            try:
                import ctypes  # type: ignore[import-untyped]

                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:  # noqa: BLE001
                pass

        self.autostart = autostart
        self.cfg = _load_config()
        self.agent: BridgeAgent | None = None
        self.agent_thread: threading.Thread | None = None
        self._tasks: queue.Queue = queue.Queue()

        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk

        root = tk.Tk()
        root.withdraw()
        self.root = root
        try:
            root.iconbitmap(resource_path(os.path.join("assets", "icon.ico")))
        except Exception:  # noqa: BLE001
            pass
        root.title(APP_NAME)
        root.configure(bg=BG)
        root.geometry("560x620")
        root.minsize(520, 560)

        self._build_ui()
        self._splash = Splash(root)
        root.after(2500, self._show_main)
        self._poll_status()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- UI --------------------------------------------------------------
    def _build_ui(self) -> None:
        tk, ttk = self.tk, self.ttk
        root = self.root

        card = ttk.Frame(root, padding=18)
        card.pack(fill="both", expand=True, padx=16, pady=14)

        # header
        head = tk.Frame(card, bg=BG)
        head.pack(fill="x", pady=(0, 12))
        tk.Label(head, text="HM\u258c", bg=BG, fg=ACCENT, font=(FONT, 26, "bold")).pack(side="left")
        tk.Label(head, text="  " + APP_NAME, bg=BG, fg=INK, font=(FONT, 16, "bold")).pack(
            side="left", anchor="s", pady=(0, 4)
        )
        self.dot = tk.Canvas(head, width=16, height=16, bg=BG, highlightthickness=0)
        self.dot.pack(side="right")
        self.dot_id = self.dot.create_oval(2, 2, 14, 14, fill=MUTED, outline="")

        # status
        self.status_label = tk.Label(
            card, text="Ready", bg=BG, fg=MUTED, font=(FONT, 12), anchor="w"
        )
        self.status_label.pack(fill="x", pady=(0, 4))
        self.account_label = tk.Label(
            card, text="MetaTrader 5: detecting\u2026", bg=BG, fg=MUTED, font=(FONT, 10),
            anchor="w",
        )
        self.account_label.pack(fill="x", pady=(0, 14))

        # settings box
        box = tk.Frame(card, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        box.pack(fill="x", pady=(0, 12))

        def field(label_text: str, key: str, *, secret: bool = False, row: int) -> None:
            tk.Label(box, text=label_text, bg=CARD, fg=MUTED, font=(FONT, 9)).grid(
                row=row, column=0, sticky="w", padx=(14, 0), pady=(12, 2)
            )
            var = self.tk.StringVar(value=str(self.cfg.get(key, "")))
            widget = tk.Entry(box, textvariable=var, bg=BG, fg=INK, insertbackground=INK,
                              relief="flat", font=(FONT, 10), show="\u2022" if secret else "")
            widget.grid(row=row, column=1, sticky="ew", padx=(10, 14), pady=(6, 6))
            box.columnconfigure(1, weight=1)
            setattr(self, f"var_{key}", var)

        field("Server URL", "url", row=0)
        field("Bridge token", "token", secret=True, row=1)
        field("MetaTrader 5 terminal", "mt5_path", row=2)

        detect = tk.Button(box, text="Auto-detect MT5", command=self._detect,
                           bg=ACCENT, fg="white", relief="flat", padx=10, font=(FONT, 9, "bold"))
        detect.grid(row=2, column=2, sticky="e", padx=(0, 14), pady=(6, 6))

        self._var_autostart = self.tk.BooleanVar(value=bool(self.cfg.get("autostart")))
        tk.Checkbutton(
            box, text="Start automatically with Windows", variable=self._var_autostart,
            bg=CARD, fg=INK, activebackground=CARD, activeforeground=INK,
            selectcolor=BG, font=(FONT, 10), command=self._toggle_autostart,
        ).grid(row=3, column=0, columnspan=3, sticky="w", padx=(14, 0), pady=(8, 12))

        # buttons
        btns = tk.Frame(card, bg=BG)
        btns.pack(fill="x", pady=(0, 12))
        self.start_btn = tk.Button(
            btns, text="Start agent", command=self._toggle_agent, bg=GOOD, fg="#04120a",
            relief="flat", padx=18, pady=6, font=(FONT, 11, "bold"), cursor="hand2",
        )
        self.start_btn.pack(side="left")
        tk.Button(
            btns, text="Open log folder", command=self._open_log_folder, bg=CARD, fg=INK,
            relief="flat", padx=12, pady=6, font=(FONT, 9), cursor="hand2",
        ).pack(side="right")

        # log
        tk.Label(card, text="Activity log", bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w", pady=(0, 4))
        log_frame = tk.Frame(card, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            log_frame, bg=CARD, fg=MUTED, insertbackground=MUTED, relief="flat",
            font=("Consolas", 9), height=12, wrap="none",
        )
        self.log_text.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        scroll = tk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

        self._setup_logging()

    def _setup_logging(self) -> None:
        handler = TextHandler(self.log_text)
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
        logging.getLogger("agent").addHandler(handler)
        logging.getLogger("agent").setLevel(logging.INFO)

    # -- actions ----------------------------------------------------------
    def _detect(self) -> None:
        self.status_label.config(text="Looking for MetaTrader 5\u2026")
        threading.Thread(target=self._detect_worker, daemon=True).start()

    def _detect_worker(self) -> None:
        try:
            path = mt5_detect.detect_primary()
        except Exception as exc:  # noqa: BLE001
            path = ""
            self._log(f"detection error: {exc}")
        self._tasks.put(("detect_done", path))

    def _on_detect_done(self, path: str) -> None:
        if path:
            self.var_mt5_path.set(path)
            self.status_label.config(text=f"Found MetaTrader 5: {path}")
            self._log(f"auto-detected terminal: {path}")
        else:
            self.status_label.config(
                text="No MetaTrader 5 found \u2014 open MT5 and log in, then press Auto-detect."
            )
            self._log("no MetaTrader 5 terminal found")

    def _toggle_autostart(self) -> None:
        enabled = bool(self._var_autostart.get())
        self.cfg["autostart"] = enabled
        _save_config(self.cfg)
        _autostart_set(enabled)
        self._log("start with Windows " + ("enabled" if enabled else "disabled"))

    def _toggle_agent(self) -> None:
        if self.agent is not None:
            self.agent.stop()
            self.agent = None
            self.agent_thread = None
            self.start_btn.config(text="Start agent", bg=GOOD, fg="#04120a")
            self._set_dot(MUTED)
            self.status_label.config(text="Stopped")
            self._log("agent stopped")
            return

        token = self.var_token.get().strip()
        if not token:
            self.status_label.config(text="Bridge token is missing.")
            return

        mt5_path = self.var_mt5_path.get().strip()
        if mt5_path:
            self._start_agent(token, {"path": mt5_path})
            return

        # No terminal given — detect it in a background thread so the UI never
        # freezes while PowerShell/registry detection runs.
        self.start_btn.config(state="disabled")
        self.status_label.config(text="Detecting MetaTrader 5\u2026")
        self._log("detecting MetaTrader 5\u2026")

        def _worker() -> None:
            try:
                found = mt5_detect.detect_primary()
            except Exception as exc:  # noqa: BLE001
                found = ""
                self._log(f"detection error: {exc}")
            self._tasks.put(("start_after_detect", token, found))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_start_after_detect(self, token: str, path: str) -> None:
        self.start_btn.config(state="normal")
        if path:
            self.var_mt5_path.set(path)
            self._log(f"auto-detected terminal: {path}")
            self._start_agent(token, {"path": path})
        else:
            self.status_label.config(
                text="MetaTrader 5 not found \u2014 open MT5 and press Auto-detect first."
            )
            self._log("no MetaTrader 5 terminal found")

    def _start_agent(self, token: str, kwargs: dict) -> None:
        url = self.var_url.get().strip() or DEFAULT_URL
        self.cfg.update({"url": url, "token": token, "mt5_path": kwargs.get("path", "")})
        _save_config(self.cfg)

        self.agent = BridgeAgent(url, token, kwargs)
        self.agent_thread = threading.Thread(target=self.agent.run, daemon=True)
        self.agent_thread.start()
        self.start_btn.config(text="Stop agent", bg=BAD, fg="white")
        self.status_label.config(text="Connecting\u2026")
        self._log(f"starting agent \u2192 {url}")

    # -- status loop ------------------------------------------------------
    def _set_dot(self, color: str) -> None:
        self.dot.itemconfig(self.dot_id, fill=color)

    def _poll_status(self) -> None:
        try:
            while True:
                task = self._tasks.get_nowait()
                kind = task[0]
                if kind == "detect_done":
                    self._on_detect_done(task[1])
                elif kind == "start_after_detect":
                    self._on_start_after_detect(task[1], task[2])
        except queue.Empty:
            pass
        try:
            agent = self.agent
            if agent is None:
                self._set_dot(MUTED)
            elif agent.connected:
                self._set_dot(GOOD)
                self.status_label.config(text="Connected \u2014 trading through your MetaTrader 5")
            elif agent.status_text == "connecting":
                self._set_dot("#eab308")
                self.status_label.config(text="Connecting to server\u2026")
            elif agent.status_text.startswith("error"):
                self._set_dot(BAD)
                self.status_label.config(text=f"Reconnecting \u2014 {agent.last_error_text}")
            else:
                self._set_dot(MUTED)

            if agent is not None and agent.account:
                acct = agent.account
                login = acct.get("login")
                server = acct.get("server")
                balance = acct.get("balance")
                currency = acct.get("currency") or ""
                name = acct.get("name") or ""
                self.account_label.config(
                    text=f"Account {login} \u00b7 {server or ''} \u00b7 "
                         f"{balance:,.2f} {currency} \u00b7 {name}".strip()
                )
        except Exception:  # noqa: BLE001
            pass
        self.root.after(POLL_MS, self._poll_status)

    def _log(self, message: str) -> None:
        try:
            logging.getLogger("agent").info("%s", message)
        except Exception:  # noqa: BLE001
            pass

    def _open_log_folder(self) -> None:
        if sys.platform != "win32":
            return
        try:
            os.startfile(_app_dir())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    # -- lifecycle --------------------------------------------------------
    def _on_close(self) -> None:
        if self.agent is not None:
            self.agent.stop()
        self.cfg["autostart"] = bool(self._var_autostart.get())
        _save_config(self.cfg)
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _show_main(self) -> None:
        self._splash.close()
        self.root.deiconify()
        if self.autostart and self.agent is None:
            self.root.after(400, self._toggle_agent)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--autostart", action="store_true", help="auto-connect on launch")
    args = parser.parse_args()

    if not _single_instance():
        return 0

    app = AgentApp(autostart=args.autostart)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
