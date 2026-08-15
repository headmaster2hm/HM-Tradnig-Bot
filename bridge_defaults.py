"""Compiled-in defaults for the HM Bridge Windows agent.

``build_win.bat`` rewrites these from ``HM_BRIDGE_URL`` / ``HM_BRIDGE_TOKEN``
environment variables when present, so the installer ships with the correct
server link pre-filled — end users never have to type anything.
"""

APP_NAME = "HM Bridge Agent"
APP_ID = "HMBotBridgeAgent"

DEFAULT_URL = "wss://tradebot.headmaster.fun/bridge/ws"
DEFAULT_TOKEN = "M5YEzYrFGfFFIbpIg12Sjp-CL6LLiY80PGhzl0DtZWU"
