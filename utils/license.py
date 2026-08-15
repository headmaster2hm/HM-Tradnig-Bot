"""One-time activation licensing for HM Bot Trader.

New users pay a one-time fee to activate the bot. After payment they
receive a license key which they paste into the dashboard once, together
with their MetaTrader 5 account number. The key is validated locally and
bound to that one MT5 account: the bot refuses to trade on any other MT5
account (paper/simulation mode "SIM" is allowed). The binding survives
reinstallation, so the same key can be re-entered after a fresh install
with no second payment.

Binding is enforced locally — the admin side (control panel) keeps the
seller's record of which key belongs to which MT5 account.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.paths import app_dir

# One-time activation fee.
PRICE = 20.0
CURRENCY = "USD"

# Developer: set this to your own payment page (Stripe, PayPal, Gumroad,
# etc.). When empty, the activation screen asks users to contact you for a
# key after paying.
PAYMENT_URL = ""

# Signing secret. KEEP THIS PRIVATE and stable across releases — changing
# it invalidates every license key you have already issued.
_SIGNING_KEY = base64.b64decode(
    "SE0tQk9ULURFTU8tU0VDUkVULUtFWS0yMDI2"
)

_KEY_VERSION = b"v1"
_KEY_LENGTH = 32  # payload (16 hex) + signature (16 hex)
LICENSE_FILENAME = "license.json"


# -- key format ---------------------------------------------------------
def _normalize(key: str) -> str:
    key = key.strip().upper()
    if key.startswith("HM"):
        key = key[2:]
    return key.replace("-", "").replace(" ", "")


def _sign(payload: bytes) -> bytes:
    digest = hmac.new(_SIGNING_KEY, _KEY_VERSION + payload, hashlib.sha256)
    return digest.digest()[:8]


def generate_key() -> str:
    """Create a new license key (developer side, e.g. after payment)."""
    payload = secrets.token_bytes(8)
    raw = (payload + _sign(payload)).hex().upper()
    groups = "-".join(raw[i : i + 4] for i in range(0, _KEY_LENGTH, 4))
    return f"HM-{groups}"


def validate_key(key: str) -> bool:
    """Return True if the key is a correctly signed license key."""
    if not key or not key.strip():
        return False
    raw = _normalize(key)
    if len(raw) != _KEY_LENGTH:
        return False
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return False
    payload, signature = data[:8], data[8:]
    return hmac.compare_digest(signature, _sign(payload))


# -- activation store ---------------------------------------------------
def license_path() -> Path:
    return app_dir() / LICENSE_FILENAME


def _read_license() -> dict[str, Any]:
    try:
        data = json.loads(license_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _normalize_account(account: Any) -> str | None:
    """Return a trimmed account login string, or None when absent/blank."""
    if account is None:
        return None
    text = str(account).strip()
    return text if text else None


def bound_mt5_account() -> str | None:
    """The MT5 account login the active license key is bound to, or None."""
    record = _read_license()
    key = str(record.get("key", "") or "")
    if not validate_key(key):
        return None
    return _normalize_account(record.get("mt5_account"))


def is_activated() -> bool:
    env_key = os.environ.get("HM_LICENSE_KEY", "").strip()
    if env_key and validate_key(env_key):
        return True
    record = _read_license()
    return validate_key(str(record.get("key", "") or ""))


def check_account(login: Any) -> tuple[bool, str]:
    """Return (ok, error) for connecting/trading on ``login``.

    A license bound to an MT5 account may only run on that account.
    Paper/simulation mode reports "SIM" and is always allowed; an
    unbound (legacy) license is always allowed.
    """
    bound = bound_mt5_account()
    if not bound:
        return True, ""
    if login is None:
        return True, ""
    current = str(login).strip()
    if current == "SIM":
        return True, ""
    if current == bound:
        return True, ""
    return (
        False,
        f"This license key is bound to MT5 account {bound}, but the bot is "
        f"connected to account {current}. Log into the licensed MT5 account "
        "or contact the seller to transfer the license.",
    )


def activate(key: str, mt5_account: Any = None) -> tuple[bool, str]:
    """Store, enable and bind a license key. Returns (ok, error_message).

    ``mt5_account`` is the MetaTrader 5 login the key is bound to. A key
    that was already activated for a different account cannot be reused
    for another one.
    """
    if not key or not key.strip():
        return False, "Please paste your license key."
    if not validate_key(key):
        return False, "That license key is not valid. Check for typos or contact the seller."

    account = _normalize_account(mt5_account)
    previous = _read_license()
    prev_key = str(previous.get("key", "") or "")
    prev_account = _normalize_account(previous.get("mt5_account"))
    if (
        prev_key
        and validate_key(prev_key)
        and _normalize(prev_key) == _normalize(key)
        and prev_account
        and account
        and prev_account != account
    ):
        return (
            False,
            f"This license key is already bound to MT5 account {prev_account} — "
            "it can only be used with that account. Enter the correct MT5 "
            "account number or contact the seller.",
        )

    record = {
        "key": key.strip(),
        "activated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if account:
        record["mt5_account"] = account
    try:
        license_path().parent.mkdir(parents=True, exist_ok=True)
        license_path().write_text(json.dumps(record, indent=2), encoding="utf-8")
    except OSError as exc:
        return False, f"Could not save license on this machine: {exc}"
    return True, ""


def status() -> dict[str, Any]:
    """Dashboard-facing activation status payload."""
    record = _read_license()
    key = str(record.get("key", "") or "")
    valid = validate_key(key)
    bound = bound_mt5_account() if valid else None
    return {
        "activated": is_activated(),
        "key_hint": (key[:7] + "…") if valid and key else "",
        "activated_at": record.get("activated_at") if valid else None,
        "mt5_account": bound,
        "account_bound": bool(bound),
        "price": PRICE,
        "currency": CURRENCY,
        "payment_url": PAYMENT_URL,
    }


# -- CLI for the developer ----------------------------------------------
def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m utils.license",
        description="Generate and validate HM Bot Trader license keys.",
    )
    parser.add_argument("--generate", action="store_true", help="Print a new license key")
    parser.add_argument("--count", type=int, default=1, help="Number of keys to print")
    parser.add_argument("--check", metavar="KEY", help="Validate a key and print the result")
    args = parser.parse_args(argv)

    if args.check:
        ok = validate_key(args.check)
        print(f"{args.check}  ->  {'VALID' if ok else 'INVALID'}")
        return 0 if ok else 1

    if not args.generate:
        parser.print_help()
        return 0

    for _ in range(max(1, args.count)):
        print(generate_key())
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
