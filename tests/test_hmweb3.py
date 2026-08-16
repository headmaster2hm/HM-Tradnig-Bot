"""Unit tests for the HMPyWeb3Kit payment helper (offline, no network)."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import hmweb3  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HM_WEB3_API_KEY", raising=False)
    monkeypatch.delenv("HM_WEB3_BASE_URL", raising=False)
    monkeypatch.delenv("HM_SELLER_URL", raising=False)
    yield
    hmweb3.clear_address_cache()


def _fake_response(payload: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


class TestRequest:
    def test_success_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hmweb3, "_urlopen", lambda req, timeout=None: _fake_response({"ok": True, "x": 1}))
        assert hmweb3._request("GET", "/health") == {"ok": True, "x": 1}

    def test_empty_body_returns_empty_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hmweb3, "_urlopen", lambda req, timeout=None: io.BytesIO(b""))
        assert hmweb3._request("GET", "/health") == {}

    def test_http_error_maps_detail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(req, timeout=None):
            raise urllib.error.HTTPError(
                url=req.full_url,
                code=400,
                msg="Bad Request",
                hdrs={},
                fp=io.BytesIO(json.dumps({"detail": "Bad chain"}).encode()),
            )

        monkeypatch.setattr(hmweb3, "_urlopen", boom)
        with pytest.raises(hmweb3.HmWeb3Error) as exc:
            hmweb3._request("POST", "/api/v1/wallet/generate", {"chain": "btc"})
        assert exc.value.status == 400
        assert "Bad chain" in str(exc.value)

    def test_connection_error_maps_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(req, timeout=None):
            raise urllib.error.URLError("timed out")

        monkeypatch.setattr(hmweb3, "_urlopen", boom)
        with pytest.raises(hmweb3.HmWeb3Error) as exc:
            hmweb3._request("GET", "/health")
        assert "timed out" in str(exc.value)


class TestApiKey:
    def test_empty_when_env_unset(self) -> None:
        assert hmweb3.api_key() == ""

    def test_env_key_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HM_WEB3_API_KEY", "my-secret")
        assert hmweb3.api_key() == "my-secret"


def _btc_wallet() -> dict:
    return {
        "ok": True,
        "chain": "btc",
        "address": "1LegacyAddress",
        "public_key": "pub",
        "bitcoin_addresses": {
            "legacy_p2pkh": "1LegacyAddress",
            "p2sh_wrapped_segwit": "3WrappedAddress",
            "native_segwit_p2wpkh": "bc1qNative",
            "native_segwit_bip84": "bc1pBip84",
        },
        "derivation_paths": {"main": "m/84'/0'/0'/0/0"},
    }


def _usdt_wallet() -> dict:
    return {
        "ok": True,
        "chain": "usdt",
        "address": "TMainTronAddress",
        "public_key": "pub",
        "usdt_addresses": {
            "tron_trc20": "TUsdtTronAddress",
            "tron_public_key": "0xPub",
        },
        "derivation_paths": {"main": "m/44'/195'/0'/0/0"},
    }


class TestGenerateWallet:
    def test_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict] = []

        def fake(req, timeout=None):
            body = json.loads(req.data.decode())
            calls.append(body)
            return _fake_response({"ok": True, "chain": body["chain"], "address": "abc"})

        monkeypatch.setattr(hmweb3, "_urlopen", fake)
        result = hmweb3.generate_wallet("btc")
        assert result["address"] == "abc"
        assert calls == [{"chain": "btc"}]

    def test_invalid_chain_rejected(self) -> None:
        with pytest.raises(hmweb3.HmWeb3Error):
            hmweb3.generate_wallet("not-a-chain")

    def test_ok_false_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            hmweb3, "_urlopen", lambda req, timeout=None: _fake_response({"ok": False, "detail": "nope"})
        )
        with pytest.raises(hmweb3.HmWeb3Error, match="nope"):
            hmweb3.generate_wallet("btc")


class TestCheckBalance:
    def test_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HM_WEB3_API_KEY", "test-key")
        monkeypatch.setattr(
            hmweb3,
            "_urlopen",
            lambda req, timeout=None: _fake_response(
                {"ok": True, "chain": "btc", "address": "abc123def456", "balance": "0.02", "unit": "BTC"}
            ),
        )
        result = hmweb3.check_balance("btc", "abc123def456")
        assert result["balance"] == "0.02"
        assert result["unit"] == "BTC"

    def test_short_address_rejected(self) -> None:
        with pytest.raises(hmweb3.HmWeb3Error, match="too short"):
            hmweb3.check_balance("btc", "short")

    def test_invalid_chain_rejected(self) -> None:
        with pytest.raises(hmweb3.HmWeb3Error):
            hmweb3.check_balance("cardano", "a" * 40)


class TestPaymentAddresses:
    def test_generates_btc_and_usdt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HM_WEB3_API_KEY", "test-key")
        seen: list[str] = []
        monkeypatch.setattr(hmweb3, "generate_wallet", lambda chain: (seen.append(chain), _btc_wallet() if chain == "btc" else _usdt_wallet())[1])

        payload = hmweb3.payment_addresses(force=True)
        assert payload["ok"] is True
        assert seen == ["btc", "usdt"]
        assert payload["btc"]["address"] == "bc1pBip84"
        assert payload["usdt"]["address"] == "TUsdtTronAddress"
        assert payload["btc"]["variants"]["legacy_p2pkh"] == "1LegacyAddress"

    def test_cached_until_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HM_WEB3_API_KEY", "test-key")
        count = {"n": 0}

        def fake_generate(chain: str) -> dict:
            count["n"] += 1
            return _btc_wallet() if chain == "btc" else _usdt_wallet()

        monkeypatch.setattr(hmweb3, "generate_wallet", fake_generate)
        first = hmweb3.payment_addresses()
        second = hmweb3.payment_addresses()
        assert first is second  # cached object
        assert count["n"] == 2  # one generate per chain, only on first call

    def test_force_regenerates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HM_WEB3_API_KEY", "test-key")
        count = {"n": 0}

        def fake_generate(chain: str) -> dict:
            count["n"] += 1
            return _btc_wallet() if chain == "btc" else _usdt_wallet()

        monkeypatch.setattr(hmweb3, "generate_wallet", fake_generate)
        hmweb3.payment_addresses()
        hmweb3.payment_addresses(force=True)
        assert count["n"] == 4

    def test_fallback_to_main_address(self) -> None:
        btc = _btc_wallet()
        btc.pop("bitcoin_addresses")
        address, variants = hmweb3._extract_btc(btc)
        assert address == "1LegacyAddress"
        assert variants == {}

        usdt = _usdt_wallet()
        usdt.pop("usdt_addresses")
        address, variants = hmweb3._extract_tron(usdt)
        assert address == "TMainTronAddress"
        assert variants == {}


class TestSellerProxy:
    """Customer builds have no API key: payment calls go to the seller."""

    def test_addresses_proxied_to_seller_when_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, str]] = []

        def fake(req, timeout=None):
            calls.append((req.full_url, req.method))
            return _fake_response(
                {
                    "ok": True,
                    "generated_at": "2026-01-01T00:00:00+00:00",
                    "btc": {"address": "bc1SellerAddress", "variants": {}},
                    "usdt": {"address": "TSellerAddress", "variants": {}},
                }
            )

        monkeypatch.setattr(hmweb3, "_urlopen", fake)
        payload = hmweb3.payment_addresses()
        assert payload["btc"]["address"] == "bc1SellerAddress"
        assert payload["usdt"]["address"] == "TSellerAddress"
        assert calls == [(hmweb3.DEFAULT_SELLER_URL + "/api/payment/addresses?source=app", "GET")]

    def test_addresses_proxy_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            hmweb3, "_urlopen", lambda req, timeout=None: _fake_response({"ok": False, "detail": "denied"})
        )
        with pytest.raises(hmweb3.HmWeb3Error, match="denied"):
            hmweb3.payment_addresses()

    def test_balance_proxied_to_seller_when_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, str, dict]] = []

        def fake(req, timeout=None):
            body = json.loads(req.data.decode())
            calls.append((req.full_url, req.method, body))
            return _fake_response(
                {"ok": True, "chain": "btc", "address": "abc123def456xyz", "balance": "0.5", "unit": "BTC"}
            )

        monkeypatch.setattr(hmweb3, "_urlopen", fake)
        result = hmweb3.check_balance("btc", "abc123def456xyz")
        assert result["balance"] == "0.5"
        assert calls == [
            (
                hmweb3.DEFAULT_SELLER_URL + "/api/payment/check",
                "POST",
                {"chain": "btc", "address": "abc123def456xyz"},
            )
        ]

    def test_seller_url_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HM_SELLER_URL", "https://pay.example.com/")
        assert hmweb3._seller_base_url() == "https://pay.example.com"

    def test_provider_used_when_key_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HM_WEB3_API_KEY", "k")
        count = {"n": 0}

        def fake_generate(chain: str) -> dict:
            count["n"] += 1
            return _btc_wallet() if chain == "btc" else _usdt_wallet()

        monkeypatch.setattr(hmweb3, "generate_wallet", fake_generate)
        payload = hmweb3.payment_addresses()
        assert count["n"] == 2
        assert payload["btc"]["address"] == "bc1pBip84"
