"""Unit tests for the owner/admin auth module (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import admin as admin_util  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(admin_util, "admin_config_path", lambda: tmp_path / "admin.json")
    yield
    admin_util._failures.clear()


class TestPassword:
    def test_short_password_rejected(self) -> None:
        assert admin_util.set_password("owner", "short") != ""

    def test_set_and_verify(self) -> None:
        assert admin_util.set_password("owner", "hunter2hunter") == ""
        assert admin_util.is_configured() is True
        assert admin_util.verify_password("owner", "hunter2hunter") is True

    def test_wrong_password_fails(self) -> None:
        admin_util.set_password("owner", "correcthorse")
        assert admin_util.verify_password("owner", "wrongpass") is False

    def test_wrong_username_fails(self) -> None:
        admin_util.set_password("owner", "batterystaple")
        assert admin_util.verify_password("other", "batterystaple") is False

    def test_not_configured_by_default(self) -> None:
        assert admin_util.is_configured() is False
        assert admin_util.verify_password("owner", "x") is False

    def test_change_password(self) -> None:
        admin_util.set_password("owner", "firstpassword")
        assert admin_util.verify_password("owner", "firstpassword") is True
        admin_util.set_password("owner", "secondpassword")
        assert admin_util.verify_password("owner", "secondpassword") is True
        assert admin_util.verify_password("owner", "firstpassword") is False


class TestPathToken:
    def test_stable_and_urlsafe(self) -> None:
        first = admin_util.get_path_token()
        second = admin_util.get_path_token()
        assert first == second
        assert first.isalnum()
        assert len(first) >= 8

    def test_no_admin_like_segment(self) -> None:
        token = admin_util.get_path_token()
        lowered = token.lower()
        for word in ("admin", "control", "manage", "panel", "auth", "login"):
            assert word not in lowered


class TestSession:
    def test_issue_and_verify(self) -> None:
        token = admin_util.issue_session()
        assert admin_util.session_verify(token) is True

    def test_tampered_token_rejected(self) -> None:
        token = admin_util.issue_session()
        assert admin_util.session_verify(token[:-2] + "00") is False

    def test_garbage_rejected(self) -> None:
        for bad in (None, "", "not-a-token", "a" * 50):
            assert admin_util.session_verify(bad) is False

    def test_expired_token_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        token = admin_util.issue_session()
        monkeypatch.setattr(admin_util.time, "time", lambda: 10**18)
        assert admin_util.session_verify(token) is False


class TestLockout:
    def test_locks_after_threshold(self) -> None:
        assert admin_util.is_locked("1.2.3.4") is False
        for _ in range(admin_util.LOCKOUT_THRESHOLD):
            admin_util.record_failure("1.2.3.4")
        assert admin_util.is_locked("1.2.3.4") is True

    def test_reset_clears(self) -> None:
        for _ in range(admin_util.LOCKOUT_THRESHOLD):
            admin_util.record_failure("9.9.9.9")
        assert admin_util.is_locked("9.9.9.9") is True
        admin_util.reset_failures("9.9.9.9")
        assert admin_util.is_locked("9.9.9.9") is False

    def test_different_ips_do_not_share_lockout(self) -> None:
        for _ in range(admin_util.LOCKOUT_THRESHOLD):
            admin_util.record_failure("1.1.1.1")
        assert admin_util.is_locked("2.2.2.2") is False
