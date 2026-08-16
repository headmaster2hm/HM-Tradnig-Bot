"""Regression tests for the hidden control page over HTTP."""

from __future__ import annotations

import sys
import threading
import types
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import admin as admin_util  # noqa: E402


class _FakeEngine:
    paused = False
    dry_run = True

    def __init__(self) -> None:
        self.config = types.SimpleNamespace(to_dict=lambda: {}, mt5=types.SimpleNamespace(password=""), telegram=types.SimpleNamespace(bot_token=""))
        self.executor = types.SimpleNamespace(db=types.SimpleNamespace(history=lambda limit=1000: []))


@pytest.fixture()
def server(tmp_path: Path):
    from dashboard.webapp import make_handler

    admin_util.admin_config_path = lambda: tmp_path / "admin.json"
    assert admin_util.set_password("owner", "hunter2hunter") == ""
    token = admin_util.get_path_token()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(_FakeEngine()))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, token
    finally:
        httpd.shutdown()
        httpd.server_close()
        admin_util._failures.clear()


def _get(url: str) -> tuple[int, str, str]:
    with urllib.request.urlopen(url, timeout=10) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return resp.status, resp.headers.get("Content-Type", ""), body


class TestControlPage:
    def test_page_uses_token_prefixed_assets(self, server) -> None:
        base, token = server
        status, ctype, body = _get(f"{base}/{token}")
        assert status == 200
        assert "text/html" in ctype
        assert f'href="/{token}/ui.css"' in body
        assert f'src="/{token}/ui.js"' in body

    def test_css_served_under_token_path(self, server) -> None:
        base, token = server
        status, ctype, body = _get(f"{base}/{token}/ui.css")
        assert status == 200
        assert "text/css" in ctype
        assert ":root" in body

    def test_js_served_under_token_path(self, server) -> None:
        base, token = server
        status, ctype, body = _get(f"{base}/{token}/ui.js")
        assert status == 200
        assert "javascript" in ctype
        assert "function boot" in body

    def test_root_assets_do_not_leak_control_files(self, server) -> None:
        base, _token = server
        status, ctype, body = _get(f"{base}/ui.css")
        assert status == 200
        assert "text/css" not in ctype
        assert ":root" not in body


class TestPaymentAddresses:
    def test_plain_request_uses_cache_and_no_db_write(
        self, server, tmp_path: Path, monkeypatch
    ) -> None:
        from dashboard import webapp
        from database.admin_db import AdminDatabase

        webapp.hmweb3.clear_address_cache()
        db = AdminDatabase(tmp_path / "control.db")
        monkeypatch.setattr(webapp, "_get_admin_db", lambda: db)
        monkeypatch.setenv("HM_WEB3_API_KEY", "test-key")
        monkeypatch.setattr(webapp.hmweb3, "generate_wallet", lambda chain: _wallet(chain))

        base, _token = server
        status, _ctype, body = _get(f"{base}/api/payment/addresses")
        assert status == 200
        assert "bc1AppBtc" in body
        assert db.list_payments() == []

    def test_app_source_records_pending_payments_and_rate_limits(
        self, server, tmp_path: Path, monkeypatch
    ) -> None:
        from dashboard import webapp
        from database.admin_db import AdminDatabase

        webapp.hmweb3.clear_address_cache()
        webapp._proxy_gen_times.clear()
        monkeypatch.setattr(webapp, "_PROXY_GEN_LIMIT", 1)
        db = AdminDatabase(tmp_path / "control.db")
        monkeypatch.setattr(webapp, "_get_admin_db", lambda: db)
        monkeypatch.setenv("HM_WEB3_API_KEY", "test-key")
        monkeypatch.setattr(webapp.hmweb3, "generate_wallet", lambda chain: _wallet(chain))

        base, _token = server
        status, _ctype, body = _get(f"{base}/api/payment/addresses?source=app")
        assert status == 200
        assert "bc1AppBtc" in body

        payments = db.list_payments(status="pending")
        chains = {(p["chain"], p["address"]) for p in payments}
        assert ("btc", "bc1AppBtc") in chains
        assert ("usdt", "TAppUsdt") in chains

        try:
            _get(f"{base}/api/payment/addresses?source=app")
            second_status = 200
        except urllib.error.HTTPError as exc:
            second_status = exc.code
        assert second_status == 429  # rate limited


def _wallet(chain: str) -> dict:
    if chain == "btc":
        return {
            "ok": True,
            "bitcoin_addresses": {"native_segwit_bip84": "bc1AppBtc"},
            "derivation_paths": {},
        }
    return {
        "ok": True,
        "usdt_addresses": {"tron_trc20": "TAppUsdt"},
        "derivation_paths": {},
    }
