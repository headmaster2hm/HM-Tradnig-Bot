"""Regression tests for the hidden control page over HTTP."""

from __future__ import annotations

import sys
import threading
import types
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
