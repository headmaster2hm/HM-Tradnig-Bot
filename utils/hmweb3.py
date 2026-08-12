"""Crypto payment wallet helper — HMPyWeb3Kit (https://hmweb3.simply-web.tech).

Generates BTC / USDT (TRC-20) deposit addresses and checks balances so
buyers can pay the one-time activation fee in crypto. Uses only the
Python standard library (urllib), so no extra dependency is needed.

Developer: the API key must come from the ``HM_WEB3_API_KEY``
environment variable — there is deliberately no key embedded in this
code, so the repo never leaks one. Do NOT hard-code a key into a
distributed .exe — anyone who can open the app could read it and drain
any funds sent to derived addresses. When the key is missing/unreachable
the dashboard simply falls back to the manual "contact the seller" flow.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

# --- API settings ------------------------------------------------------
BASE_URL = "https://hmweb3.simply-web.tech"
# No hard-coded key: set HM_WEB3_API_KEY in the environment (see module docstring).
DEFAULT_API_KEY = ""
_REQUEST_TIMEOUT = 30

CHAINS = ("btc", "eth", "doge", "ltc", "bnb", "sol", "tron", "usdt")
PAYMENT_CHAINS = ("btc", "usdt")

# TTL for a generated payment-address pair so the dashboard keeps one
# stable deposit address while the buyer completes the transfer.
_ADDRESS_CACHE_TTL = 600  # seconds

_address_cache: dict[str, Any] | None = None
_urlopen = urllib.request.urlopen


class HmWeb3Error(Exception):
    """Raised when the HMPyWeb3Kit API call fails."""

    def __init__(self, message: str, status: int | None = None, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


def api_key() -> str:
    return os.environ.get("HM_WEB3_API_KEY", DEFAULT_API_KEY).strip()


# --- HTTP layer --------------------------------------------------------
def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = BASE_URL.rstrip("/") + path
    headers = {"Accept": "application/json", "X-API-Key": api_key()}
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _urlopen(request, timeout=_REQUEST_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw.strip() else {}
            return parsed if isinstance(parsed, dict) else {"ok": True, "data": parsed}
    except urllib.error.HTTPError as exc:
        detail = None
        try:
            detail = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            detail = None
        raise HmWeb3Error(_error_detail(detail) or f"HTTP {exc.code}", status=exc.code, detail=detail) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or exc
        raise HmWeb3Error(f"Could not reach the payment API ({reason})") from exc
    except (OSError, ValueError) as exc:
        raise HmWeb3Error(f"Payment API error: {exc}") from exc


def _error_detail(detail: Any) -> str | None:
    if not isinstance(detail, dict):
        return None
    if isinstance(detail.get("detail"), str):
        return detail["detail"]
    if isinstance(detail.get("message"), str):
        return detail["message"]
    if isinstance(detail.get("error"), str):
        return detail["error"]
    if isinstance(detail.get("detail"), list):
        parts: list[str] = []
        for item in detail["detail"]:
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            loc = ".".join(str(p) for p in (item.get("loc") or []) if p and p != "body")
            msg = item.get("msg")
            parts.append(f"{loc}: {msg}" if loc and msg else str(msg or item))
        return "; ".join(p for p in parts if p) or None
    return None


# --- wallet API --------------------------------------------------------
def generate_wallet(chain: str) -> dict[str, Any]:
    """Generate a new wallet for a chain. Returns the WalletResponse dict."""
    chain = (chain or "").lower().strip()
    if chain not in CHAINS:
        raise HmWeb3Error(f"Unsupported chain '{chain}'. Choose one of: {', '.join(CHAINS)}.")
    response = _request("POST", "/api/v1/wallet/generate", {"chain": chain})
    if response.get("ok") is False:
        raise HmWeb3Error(_error_detail(response) or "Wallet generation failed", detail=response)
    return response


def check_balance(chain: str, address: str) -> dict[str, Any]:
    """Check the balance of an address. Returns the BalanceResponse dict."""
    chain = (chain or "").lower().strip()
    address = (address or "").strip()
    if chain not in CHAINS:
        raise HmWeb3Error(f"Unsupported chain '{chain}'.")
    if len(address) < 10:
        raise HmWeb3Error("Address is too short to check.")
    response = _request("POST", "/api/v1/balance/", {"chain": chain, "address": address})
    if response.get("ok") is False:
        raise HmWeb3Error(_error_detail(response) or "Balance check failed", detail=response)
    return response


def _extract_btc(wallet: dict[str, Any]) -> tuple[str, dict[str, str]]:
    variants = wallet.get("bitcoin_addresses")
    if isinstance(variants, dict):
        ordered = ("native_segwit_bip84", "native_segwit_p2wpkh", "p2sh_wrapped_segwit", "legacy_p2pkh")
        for key in ordered:
            if variants.get(key):
                return str(variants[key]), {str(k): str(v) for k, v in variants.items()}
    fallback = wallet.get("address")
    return (str(fallback) if fallback else ""), {
        str(k): str(v) for k, v in variants.items()
    } if isinstance(variants, dict) else {}


def _extract_tron(wallet: dict[str, Any]) -> tuple[str, dict[str, str]]:
    variants = wallet.get("usdt_addresses")
    if isinstance(variants, dict) and variants.get("tron_trc20"):
        return str(variants["tron_trc20"]), {str(k): str(v) for k, v in variants.items()}
    fallback = wallet.get("address")
    return (str(fallback) if fallback else ""), {
        str(k): str(v) for k, v in variants.items()
    } if isinstance(variants, dict) else {}


def _derivation_for(wallet: dict[str, Any]) -> dict[str, str]:
    paths = wallet.get("derivation_paths")
    return {str(k): str(v) for k, v in paths.items()} if isinstance(paths, dict) else {}


def payment_addresses(force: bool = False) -> dict[str, Any]:
    """Generate a fresh BTC + USDT (TRC-20) deposit-address pair.

    Results are cached briefly (see ``_ADDRESS_CACHE_TTL``) so the
    dashboard keeps one stable address while the buyer pays.
    """
    global _address_cache
    now = time.monotonic()
    if not force and _address_cache and now - _address_cache["at"] < _ADDRESS_CACHE_TTL:
        return _address_cache["payload"]

    btc_wallet = generate_wallet("btc")
    usdt_wallet = generate_wallet("usdt")
    btc_address, btc_variants = _extract_btc(btc_wallet)
    tron_address, tron_variants = _extract_tron(usdt_wallet)

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "btc": {"address": btc_address, "variants": btc_variants, "derivation": _derivation_for(btc_wallet)},
        "usdt": {"address": tron_address, "variants": tron_variants, "derivation": _derivation_for(usdt_wallet)},
    }
    _address_cache = {"at": now, "payload": payload}
    return payload


def clear_address_cache() -> None:
    """Forget the cached deposit-address pair (forces a fresh generate)."""
    global _address_cache
    _address_cache = None


# --- CLI ---------------------------------------------------------------
def _print_wallet(chain: str, wallet: dict[str, Any]) -> None:
    print(f"chain          : {chain}")
    print(f"address        : {wallet.get('address')}")
    if chain == "btc" and isinstance(wallet.get("bitcoin_addresses"), dict):
        print("bitcoin        : " + ", ".join(
            f"{k}={v}" for k, v in wallet["bitcoin_addresses"].items()
        ))
    if chain in ("usdt", "tron") and isinstance(wallet.get("usdt_addresses"), dict):
        print("usdt (trc-20)  : " + ", ".join(
            f"{k}={v}" for k, v in wallet["usdt_addresses"].items()
        ))
    paths = wallet.get("derivation_paths")
    if isinstance(paths, dict):
        print("derivation     : " + "; ".join(f"{k}: {v}" for k, v in paths.items()))


def _print_payment(payload: dict[str, Any]) -> None:
    print("generated_at   :", payload.get("generated_at"))
    print("BTC            :", payload["btc"]["address"])
    print("USDT (TRC-20)  :", payload["usdt"]["address"])
    print()
    print("Have the buyer send the one-time fee to one of these addresses,")
    print("then run:  python -m utils.hmweb3 balance --chain btc --address <addr>")


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m utils.hmweb3",
        description="HMPyWeb3Kit helper: generate crypto payment addresses and check balances.",
    )
    sub = parser.add_subparsers(dest="command")

    pay = sub.add_parser("pay", help="Generate a BTC + USDT (TRC-20) deposit-address pair")
    pay.set_defaults(handler=lambda args: _print_payment(payment_addresses(force=True)))

    gen = sub.add_parser("generate", help="Generate a new wallet for a chain")
    gen.add_argument("--chain", default="btc", choices=CHAINS, help="Blockchain (default: btc)")
    gen.add_argument("--count", type=int, default=1, help="Number of wallets to print")
    gen.set_defaults(handler=lambda args: [_print_wallet(args.chain, generate_wallet(args.chain)) for _ in range(max(1, args.count))])

    bal = sub.add_parser("balance", help="Check an address balance")
    bal.add_argument("--chain", default="btc", choices=CHAINS)
    bal.add_argument("--address", required=True)
    bal.set_defaults(handler=lambda args: _print_balance(check_balance(args.chain, args.address)))

    status = sub.add_parser("status", help="Check connectivity and API key")
    status.set_defaults(handler=lambda args: _print_status())

    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 0
    try:
        args.handler(args)
    except HmWeb3Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_balance(balance: dict[str, Any]) -> None:
    print(f"chain          : {balance.get('chain')}")
    print(f"address        : {balance.get('address')}")
    print(f"balance        : {balance.get('balance')} {balance.get('unit')}")
    if balance.get("balance_usd") is not None:
        print(f"usd value      : ≈ ${balance.get('balance_usd')}")


def _print_status() -> None:
    key = api_key()
    print(f"api key        : {key[:6]}…{key[-4:]} ({len(key)} chars)")
    try:
        health = _request("GET", "/health")
        print("connectivity   : OK", f"({health.get('status') or 'healthy'})")
    except HmWeb3Error as exc:
        print(f"connectivity   : FAILED — {exc}")
        print("Hint: the dashboard falls back to the manual flow when the API is unreachable.")


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
