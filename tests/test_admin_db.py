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
        uid = db.create_user("50014", "alice@example.com", "Alice", "first customer")
        users = db.list_users()
        assert len(users) == 1
        assert users[0]["id"] == uid
        assert users[0]["mt5_account"] == "50014"
        assert users[0]["email"] == "alice@example.com"
        assert users[0]["name"] == "Alice"
        assert users[0]["status"] == "active"

    def test_get_user(self, db: AdminDatabase) -> None:
        uid = db.create_user("50015")
        assert db.get_user(uid)["mt5_account"] == "50015"
        assert db.get_user(99999) is None

    def test_get_user_by_account(self, db: AdminDatabase) -> None:
        uid = db.create_user("50016", "bob@example.com")
        found = db.get_user_by_account("50016")
        assert found is not None
        assert found["id"] == uid
        assert db.get_user_by_account("99999") is None
        assert db.get_user_by_account("") is None

    def test_status_and_update(self, db: AdminDatabase) -> None:
        uid = db.create_user("50017")
        assert db.set_user_status(uid, "disabled") is True
        assert db.get_user(uid)["status"] == "disabled"
        assert db.update_user(uid, "50017", "carol@new.com", "Carol", "x") is True
        user = db.get_user(uid)
        assert user["mt5_account"] == "50017"
        assert user["email"] == "carol@new.com"
        assert user["notes"] == "x"

    def test_update_account_number(self, db: AdminDatabase) -> None:
        uid = db.create_user("50018")
        assert db.update_user(uid, "50019", "", "Moved", "") is True
        assert db.get_user(uid)["mt5_account"] == "50019"

    def test_delete(self, db: AdminDatabase) -> None:
        uid = db.create_user("50020")
        assert db.delete_user(uid) is True
        assert db.list_users() == []

    def test_mt5_account_required(self, db: AdminDatabase) -> None:
        with pytest.raises(ValueError):
            db.create_user("")
        with pytest.raises(ValueError):
            db.create_user("   ")

    def test_duplicate_account_rejected(self, db: AdminDatabase) -> None:
        db.create_user("50021")
        with pytest.raises(Exception):
            db.create_user("50021")

    def test_migration_adds_mt5_account(self, tmp_path: Path) -> None:
        path = tmp_path / "legacy.db"
        import sqlite3

        with sqlite3.connect(path) as conn:
            conn.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE,
                    name TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO users (email, name, status, notes, created_at, updated_at)"
                " VALUES ('legacy@example.com', 'Legacy', 'active', '', '2026-01-01', '2026-01-01')"
            )

        db = AdminDatabase(path)
        legacy = db.get_user(1)
        assert legacy is not None
        assert legacy["email"] == "legacy@example.com"
        assert legacy["mt5_account"] is None
        assert legacy["last_seen_at"] is None
        uid = db.create_user("50022", "new@example.com")
        assert db.get_user(uid)["mt5_account"] == "50022"

    def test_email_optional_and_blank_allowed(self, db: AdminDatabase) -> None:
        uid = db.create_user("50023")
        assert db.get_user(uid)["email"] is None
        db.create_user("50024", "")
        db.create_user("50025", "  ")
        assert len(db.list_users()) == 3

    def test_get_or_create_user_by_account(self, db: AdminDatabase) -> None:
        created = db.get_or_create_user_by_account("50026")
        assert created["mt5_account"] == "50026"
        assert created["status"] == "active"
        again = db.get_or_create_user_by_account("50026")
        assert again["id"] == created["id"]
        assert len(db.list_users()) == 1

    def test_get_or_create_requires_account(self, db: AdminDatabase) -> None:
        with pytest.raises(ValueError):
            db.get_or_create_user_by_account("")
        with pytest.raises(ValueError):
            db.get_or_create_user_by_account("   ")

    def test_touch_user_account(self, db: AdminDatabase) -> None:
        db.get_or_create_user_by_account("50027")
        assert db.get_user_by_account("50027")["last_seen_at"] is None
        assert db.touch_user_account("50027") is True
        assert db.get_user_by_account("50027")["last_seen_at"] is not None
        assert db.touch_user_account("99999") is False
        assert db.touch_user_account("") is False


class TestPayments:
    def test_create_and_list(self, db: AdminDatabase) -> None:
        uid = db.create_user("50101", "pay@example.com")
        pid = db.create_payment(uid, "btc", "bc1qabc123", 0.001, "BTC", "via email")
        payments = db.list_payments()
        assert len(payments) == 1
        assert payments[0]["user_account"] == "50101"
        assert payments[0]["user_email"] == "pay@example.com"
        assert payments[0]["address"] == "bc1qabc123"
        assert payments[0]["status"] == "pending"

    def test_filter_by_status(self, db: AdminDatabase) -> None:
        uid = db.create_user("50102")
        pid = db.create_payment(uid, "usdt", "TAddr123")
        db.set_payment_status(pid, "paid")
        assert len(db.list_payments("pending")) == 0
        paid = db.list_payments("paid")
        assert len(paid) == 1
        assert paid[0]["paid_at"] is not None

    def test_mark_paid_with_txid(self, db: AdminDatabase) -> None:
        uid = db.create_user("50103")
        pid = db.create_payment(uid, "btc", "bc1qxyz")
        db.set_payment_status(pid, "paid", txid="abc123hash")
        payment = db.get_payment(pid)
        assert payment["status"] == "paid"
        assert payment["txid"] == "abc123hash"
        assert payment["user_account"] == "50103"

    def test_delete_payment(self, db: AdminDatabase) -> None:
        uid = db.create_user("50104")
        pid = db.create_payment(uid, "btc", "bc1qdel")
        assert db.delete_payment(pid) is True
        assert db.list_payments() == []


class TestKeys:
    def test_add_and_list(self, db: AdminDatabase) -> None:
        uid = db.create_user("50105")
        assert db.add_key("HM-AAAA-AAAA-AAAA-AAAA", uid) is True
        keys = db.list_keys()
        assert len(keys) == 1
        assert keys[0]["user_account"] == "50105"
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
        uid = db.create_user("50106")
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
        uid = db.create_user("50107")
        db.create_payment(uid, "usdt", "TPendingAddr")
        overview = db.overview(price_usd=20.0)
        assert overview["pending_payments"] == 1
        assert overview["paid_payments"] == 0
        assert overview["revenue_usd"] == 0.0
