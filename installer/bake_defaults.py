"""Rewrite ``bridge_defaults.py`` with the URL/token baked in at build time.

Reads ``HM_BRIDGE_URL`` and ``HM_BRIDGE_TOKEN`` from the environment. When
they are unset (typical local build), the existing committed defaults are
kept unchanged. Used by ``build_win.bat`` and the GitHub Actions workflow so
every shipped agent points at the right server automatically.
"""

from __future__ import annotations

import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bridge_defaults.py")

DEFAULT_URL = os.environ.get("HM_BRIDGE_URL") or "wss://tradebot.headmaster.fun/bridge/ws"
DEFAULT_TOKEN = os.environ.get("HM_BRIDGE_TOKEN") or "M5YEzYrFGfFFIbpIg12Sjp-CL6LLiY80PGhzl0DtZWU"

content = (
    '"""Compiled-in defaults for the HM Bridge Windows agent.\n\n'
    "``build_win.bat`` rewrites these from ``HM_BRIDGE_URL`` / ``HM_BRIDGE_TOKEN``\n"
    "environment variables when present, so the installer ships with the correct\n"
    "server link pre-filled \u2014 end users never have to type anything.\n"
    '"""\n\n'
    'APP_NAME = "HM Bridge Agent"\n'
    'APP_ID = "HMBotBridgeAgent"\n\n'
    f'DEFAULT_URL = "{DEFAULT_URL}"\n'
    f'DEFAULT_TOKEN = "{DEFAULT_TOKEN}"\n'
)

with open(PATH, "w", encoding="utf-8") as fh:
    fh.write(content)

print(f"baked bridge_defaults.py  url={DEFAULT_URL}  token={'set' if DEFAULT_TOKEN else 'EMPTY'}")
