"""Owner/admin authentication and the hidden control URL.

Everything the owner needs is behind a single random URL token that is
never part of the pages users see (and deliberately contains no word like
"admin"). The control panel itself requires a username + password.

Secrets are kept in ``admin.json`` under the app data folder:

- ``password_hash`` — PBKDF2-HMAC-SHA256 hash of the owner password
- ``path_token``   — the random segment of the control URL (``/<token>``)
- ``signing_key``  — key used to sign the session cookie

First-time setup (from the project folder):

    python -m utils.admin set-password --username owner
    python -m utils.admin url

The printed URL is the only entrance to the control panel.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from utils.paths import admin_config_path

ADMIN_CONFIG_FILENAME = "admin.json"
PBKDF2_ITERATIONS = 240_000
SESSION_TTL_SECONDS = 12 * 3600  # 12h
SESSION_COOKIE = "hm_admin"

# Brute-force protection: lock an IP for LOCKOUT_WINDOW after this many
# failed login attempts.
LOCKOUT_THRESHOLD = 10
LOCKOUT_WINDOW = 15 * 60  # seconds

_FORBIDDEN_SEGMENTS = ("admin", "control", "manage", "panel", "auth", "login")

_lock = threading.Lock()
_failures: dict[str, deque[float]] = {}


# --- config store ------------------------------------------------------
def _default_config() -> dict[str, Any]:
    return {
        "username": "",
        "salt": "",
        "password_hash": "",
        "pbkdf2_iterations": PBKDF2_ITERATIONS,
        "path_token": "",
        "signing_key": "",
    }


def load_config() -> dict[str, Any]:
    path = admin_config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = _default_config()
                merged.update(data)
                return merged
        except (OSError, ValueError):
            pass
    return _default_config()


def save_config(data: dict[str, Any]) -> None:
    path = admin_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def ensure_config() -> dict[str, Any]:
    """Create the config file with path token + signing key if missing."""
    data = load_config()
    changed = False
    if not data.get("path_token"):
        data["path_token"] = _new_path_token()
        changed = True
    if not data.get("signing_key"):
        data["signing_key"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        changed = True
    if changed:
        save_config(data)
    return data


def _new_path_token() -> str:
    """Random URL-safe token with no obvious admin-like segment."""
    while True:
        token = secrets.token_urlsafe(12).replace("-", "").replace("_", "")
        if not any(word in token.lower() for word in _FORBIDDEN_SEGMENTS):
            return token


def get_path_token() -> str:
    """The secret segment that gates the control panel (``/<token>``)."""
    return ensure_config()["path_token"]


# --- password ----------------------------------------------------------
def set_password(username: str, password: str) -> str:
    """Hash and store the owner password. Returns an error string ("" = ok)."""
    username = (username or "").strip()
    if not username:
        return "A username is required."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    salt = secrets.token_bytes(16)
    iterations = PBKDF2_ITERATIONS
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    data = ensure_config()
    data["username"] = username
    data["salt"] = salt.hex()
    data["pbkdf2_iterations"] = iterations
    data["password_hash"] = digest.hex()
    save_config(data)
    return ""


def is_configured() -> bool:
    data = load_config()
    return bool(data.get("password_hash") and data.get("username"))


def _hash_password(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def verify_password(username: str, password: str) -> bool:
    data = load_config()
    if not data.get("password_hash"):
        return False
    try:
        salt = bytes.fromhex(data["salt"])
        expected = bytes.fromhex(data["password_hash"])
    except ValueError:
        return False
    if hmac.compare_digest(username, data.get("username", "")) is False:
        return False
    actual = _hash_password(password, salt, int(data.get("pbkdf2_iterations") or PBKDF2_ITERATIONS))
    return hmac.compare_digest(actual, expected)


# --- login rate limiting ----------------------------------------------
def is_locked(ip: str) -> bool:
    with _lock:
        stamps = _failures.get(ip)
        if not stamps:
            return False
        now = time.time()
        _failures[ip] = deque(s for s in stamps if now - s < LOCKOUT_WINDOW)
        return len(_failures[ip]) >= LOCKOUT_THRESHOLD


def record_failure(ip: str) -> None:
    with _lock:
        now = time.time()
        stamps = _failures.setdefault(ip, deque(maxlen=LOCKOUT_THRESHOLD))
        stamps.append(now)


def reset_failures(ip: str) -> None:
    with _lock:
        _failures.pop(ip, None)


# --- sessions ----------------------------------------------------------
def _signing_key() -> bytes:
    return ensure_config()["signing_key"].encode("ascii")


def issue_session() -> str:
    """Create a signed session cookie value (stateless, expires)."""
    exp = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{exp}:{secrets.token_urlsafe(18)}".encode("utf-8")
    sig = hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig


def session_verify(token: str | None) -> bool:
    if not token:
        return False
    try:
        body, sig = token.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (ValueError, TypeError):
        return False
    expected = hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        exp_str, _nonce = payload.decode("utf-8").split(":", 1)
        exp = int(exp_str)
    except ValueError:
        return False
    return time.time() < exp


# --- CLI ---------------------------------------------------------------
def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m utils.admin",
        description="Owner/admin setup for the HM Bot Trader control panel.",
    )
    sub = parser.add_subparsers(dest="command")

    pw = sub.add_parser("set-password", help="Create or change the owner password")
    pw.add_argument("--username", default="owner", help="Owner username (default: owner)")
    pw.add_argument("--password", default=None, help="Read password from argument (not recommended)")
    pw.set_defaults(handler=lambda args: _cmd_set_password(args.username, args.password))

    url = sub.add_parser("url", help="Print the hidden control panel URL path")
    url.set_defaults(handler=lambda args: _cmd_url())

    status = sub.add_parser("status", help="Show whether the control panel is secured")
    status.set_defaults(handler=lambda args: _cmd_status())

    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 0
    return args.handler(args)


def _cmd_set_password(username: str, password: str | None) -> int:
    if password is None:
        password = getpass.getpass("New password: ")
        confirm = getpass.getpass("Repeat password: ")
        if password != confirm:
            print("error: passwords do not match", file=sys.stderr)
            return 1
    error = set_password(username, password)
    if error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Password saved for user '{username}'.")
    print("Control panel: run  python -m utils.admin url  to get the link.")
    return 0


def _cmd_url() -> int:
    print(f"/{get_path_token()}")
    return 0


def _cmd_status() -> int:
    if is_configured():
        print(f"secured       : yes (user: {load_config().get('username') or '?'})")
    else:
        print("secured       : NO — run  python -m utils.admin set-password")
    print(f"control path  : /{get_path_token()}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
