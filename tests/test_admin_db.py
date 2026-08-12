"""Unit tests for the owner-side admin database (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.admin_db import AdminDatabase  # noqa: E402


@pytest.fixture()
def db(tmp_path: Path) -> AdminDatabase:
    return AdminDatabase(tmp_path / "control.db")


class TestUsers:
    def test_create_and_list(self, db: AdminDatabase) -> None:
        uid = db.create_user("alice@example.com", "Alice", "first customer")
        users = db.list_users()
        assert len(users) == 1
        assert users[0]["id"] == uid
        assert users[0]["email"] == "alice@example.com"
        assert users[0]["name"] == "Alice"
        assert users[0]["status"] == "active"

    def test_get_user(self, db: AdminDatabase) -> None:
        uid = db.create_user("bob@example.com")
        assert db.get_user(uid)["email"] == "bob@example.com"
        assert db.get_user(99999) is None

    def test_status_and_update(self, db: AdminDatabase) -> None:
        uid = db.create_user("carol@example.com")
        assert db.set_user_status(uid, "disabled") is True
        assert db.get_user(uid)["status"] == "disabled"
        assert db.update_user(uid, "carol@new.com", "Carol", "x") is True
        user = db.get_user(uid)
        assert user["email"] == "carol@new.com"
        assert user["notes"] == "x"

    def test_delete(self, db: AdminDatabase) -> None:
        uid = db.create_user("dave@example.com")
        assert db.delete_user(uid) is True
        assert db.list_users() == []

    def test_duplicate_email_rejected(self, db: AdminDatabase) -> None:
        db.create_user("eve@example.com")
        with pytest.raises(Exception):
            db.create_user("eve@example.com")


class TestPayments:
    def test_create_and_list(self, db: AdminDatabase) -> None:
        uid = db.create_user("pay@example.com")
        pid = db.create_payment(uid, "btc", "bc1qabc123", 0.001, "BTC", "via email")
        payments = db.list_payments()
        assert len(payments) == 1
        assert payments[0]["user_email"] == "pay@example.com"
        assert payments[0]["address"] == "bc1qabc123"
        assert payments[0]["status"] == "pending"

    def test_filter_by_status(self, db: AdminDatabase) -> None:
        uid = db.create_user("pay2@example.com")
        pid = db.create_payment(uid, "usdt", "TAddr123")
        db.set_payment_status(pid, "paid")
        assert len(db.list_payments("pending")) == 0
        paid = db.list_payments("paid")
        assert len(paid) == 1
        assert paid[0]["paid_at"] is not None

    def test_mark_paid_with_txid(self, db: AdminDatabase) -> None:
        uid = db.create_user("pay3@example.com")
        pid = db.create_payment(uid, "btc", "bc1qxyz")
        db.set_payment_status(pid, "paid", txid="abc123hash")
        payment = db.get_payment(pid)
        assert payment["status"] == "paid"
        assert payment["txid"] == "abc123hash"

    def test_delete_payment(self, db: AdminDatabase) -> None:
        uid = db.create_user("pay4@example.com")
        pid = db.create_payment(uid, "btc", "bc1qdel")
        assert db.delete_payment(pid) is True
        assert db.list_payments() == []


class TestKeys:
    def test_add_and_list(self, db: AdminDatabase) -> None:
        uid = db.create_user("key@example.com")
        assert db.add_key("HM-AAAA-AAAA-AAAA-AAAA", uid) is True
        keys = db.list_keys()
        assert len(keys) == 1
        assert keys[0]["user_email"] == "key@example.com"
        assert keys[0]["status"] == "unused"

    def test_duplicate_key_rejected(self, db: AdminDatabase) -> None:
        assert db.add_key("HM-AAAA-AAAA-AAAA-AAAA") is True
        assert db.add_key("HM-AAAA-AAAA-AAAA-AAAA") is False

    def test_set_key_status(self, db: AdminDatabase) -> None:
        db.add_key("HM-BBBB-BBBB-BBBB-BBBB")
        assert db.set_key_status("HM-BBBB-BBBB-BBBB-BBBB", "revoked") is True
        assert db.get_key("HM-BBBB-BBBB-BBBB-BBBB")["status"] == "revoked"


class TestOverview:
    def test_counts_and_revenue(self, db: AdminDatabase) -> None:
        uid = db.create_user("sum@example.com")
        pid = db.create_payment(uid, "btc", "bc1qsum")
        db.set_payment_status(pid, "paid")
        db.add_key("HM-CCCC-CCCC-CCCC-CCCC", uid)

        overview = db.overview(price_usd=20.0)
        assert overview["total_users"] == 1
        assert overview["active_users"] == 1
        assert overview["paid_payments"] == 1
        assert overview["pending_payments"] == 0
        assert overview["revenue_usd"] == 20.0
        assert overview["total_keys"] == 1

    def test_pending_counts(self, db: AdminDatabase) -> None:
        uid = db.create_user("pend@example.com")
        db.create_payment(uid, "usdt", "TPendingAddr")
        overview = db.overview(price_usd=20.0)
        assert overview["pending_payments"] == 1
        assert overview["paid_payments"] == 0
        assert overview["revenue_usd"] == 0.0
