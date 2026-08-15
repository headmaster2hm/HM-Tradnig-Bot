"""HM Bot Trader — native desktop window (no browser).

Starts the local dashboard HTTP server on a background thread and shows the
dashboard inside a native Windows window (Edge WebView2 via pywebview). The
window is resizable and themed to match the dashboard's dark UI.

Fallback: if pywebview is unavailable (e.g. missing WebView2 runtime) the
dashboard opens in the default browser instead, so the app never bricks.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from utils.logger import get_logger
from utils.paths import app_dir, install_dir

logger = get_logger("desktop")

DARK_BG = "#0e0f13"
MIN_WIDTH, MIN_HEIGHT = 1024, 680
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1360, 860


def _icon_path() -> str | None:
    """Path to the window/taskbar icon (bundled .ico), or None."""
    for base in (getattr(sys, "_MEIPASS", None), install_dir(), Path(__file__).resolve().parent):
        if not base:
            continue
        candidate = Path(base) / "assets" / "icon.ico"
        if candidate.is_file():
            return str(candidate)
    return None


def _open_fallback(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def run_desktop(host: str = "127.0.0.1", port: int = 0) -> None:
    from dashboard.webapp import create_server

    server, engine = create_server(host, port)
    bound_port = int(server.server_address[1])
    local_url = f"http://127.0.0.1:{bound_port}"
    logger.info("HM Bot Trader dashboard ready at %s", local_url)

    thread = threading.Thread(target=server.serve_forever, daemon=True, name="hm-http")
    thread.start()

    try:
        import webview  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        logger.warning("pywebview unavailable (%s) - opening dashboard in browser", exc)
        _open_fallback(local_url)
        server.shutdown()
        return

    window = webview.create_window(
        "HM Bot Trader",
        local_url,
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        resizable=True,
        background_color=DARK_BG,
        text_select=False,
        zoomable=True,
    )
    if window is None:
        logger.warning("failed to create native window - opening dashboard in browser")
        _open_fallback(local_url)
        server.shutdown()
        return

    icon = _icon_path()
    try:
        webview.start(icon=icon)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    run_desktop()
