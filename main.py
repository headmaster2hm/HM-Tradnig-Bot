"""HM Bot Trader — entry point.

Default mode opens the dashboard in a native Windows window (no browser).
Pass ``--browser`` to fall back to the classic browser-tab behaviour.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python main.py` from TradingBot/
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.logger import setup_logging
from utils.paths import ensure_user_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="HM Bot Trader dashboard")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address. Use 0.0.0.0 to also allow your phone on the same Wi-Fi.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to listen on (0 = pick a random free port).",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Open the dashboard in your default browser instead of a native window.",
    )
    args = parser.parse_args()

    ensure_user_settings()
    setup_logging()
    from mailadmin import start_watcher

    start_watcher()

    if args.browser:
        from dashboard import run_app

        run_app(host=args.host, port=args.port)
        return

    from desktop import run_desktop

    run_desktop(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
