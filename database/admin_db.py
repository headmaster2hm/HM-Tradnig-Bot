"""Owner-side SQLite store: customers, crypto payments, issued license keys.

Lives in its own database (``control.db``) so the seller's business data
never mixes with a buyer's local trade history.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.paths import admin_db_path

USER_ACTIVE = "active"
USER_DISABLED = "disabled"
PAYMENT_PENDING = "pending"
PAYMENT_PAID = "paid"
PAYMENT_REFUNDED = "refunded"
KEY_UNUSED = "unused"
KEY_ACTIVE = "active"
KEY_REVOKED = "revoked"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AdminDatabase:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else admin_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
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
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    chain TEXT NOT NULL,
                    address TEXT NOT NULL,
                    amount_expected REAL,
                    unit TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    txid TEXT,
                    created_at TEXT NOT NULL,
                    paid_at TEXT,
                    notes TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS license_keys (
                    key TEXT PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'unused',
                    issued_at TEXT NOT NULL,
                    activated_at TEXT
                )
                """
            )
            conn.commit()

    # --- users --------------------------------------------------------
    def create_user(self, email: str, name: str = "", notes: str = "") -> int:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO users (email, name, status, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (email.strip(), name.strip(), USER_ACTIVE, notes.strip(), now, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT u.*,
                       (SELECT COUNT(*) FROM payments p WHERE p.user_id = u.id) AS payment_count,
                       (SELECT COUNT(*) FROM payments p WHERE p.user_id = u.id AND p.status = 'paid') AS paid_count,
                       (SELECT COUNT(*) FROM license_keys k WHERE k.user_id = u.id) AS key_count
                FROM users u ORDER BY u.id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def set_user_status(self, user_id: int, status: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE users SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_user(self, user_id: int, email: str, name: str, notes: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE users SET email = ?, name = ?, notes = ?, updated_at = ? WHERE id = ?",
                (email.strip(), name.strip(), notes.strip(), _now(), user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    # --- payments -----------------------------------------------------
    def create_payment(
        self,
        user_id: int,
        chain: str,
        address: str,
        amount_expected: float | None = None,
        unit: str = "",
        notes: str = "",
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO payments (user_id, chain, address, amount_expected, unit, status, created_at, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, chain, address, amount_expected, unit, PAYMENT_PENDING, _now(), notes.strip()),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_payments(self, status: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT p.*, u.email AS user_email, u.name AS user_name
            FROM payments p LEFT JOIN users u ON u.id = p.user_id
        """
        params: tuple[Any, ...] = ()
        if status:
            query += " WHERE p.status = ?"
            params = (status,)
        query += " ORDER BY p.id DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_payment(self, payment_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT p.*, u.email AS user_email, u.name AS user_name
                FROM payments p LEFT JOIN users u ON u.id = p.user_id
                WHERE p.id = ?
                """,
                (payment_id,),
            ).fetchone()
        return dict(row) if row else None

    def set_payment_status(
        self,
        payment_id: int,
        status: str,
        txid: str = "",
        paid_at: str | None = None,
    ) -> bool:
        stamp = paid_at or _now()
        with self._connect() as conn:
            if status == PAYMENT_PAID:
                cursor = conn.execute(
                    "UPDATE payments SET status = ?, txid = ?, paid_at = ? WHERE id = ?",
                    (status, txid.strip(), stamp, payment_id),
                )
            else:
                cursor = conn.execute(
                    "UPDATE payments SET status = ?, txid = ? WHERE id = ?",
                    (status, txid.strip(), payment_id),
                )
            conn.commit()
            return cursor.rowcount > 0

    def delete_payment(self, payment_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM payments WHERE id = ?", (payment_id,))
            conn.commit()
            return cursor.rowcount > 0

    # --- license keys -------------------------------------------------
    def add_key(self, key: str, user_id: int | None = None) -> bool:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO license_keys (key, user_id, status, issued_at) VALUES (?, ?, ?, ?)",
                    (key, user_id, KEY_UNUSED, _now()),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def list_keys(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT k.*, u.email AS user_email, u.name AS user_name
                FROM license_keys k LEFT JOIN users u ON u.id = k.user_id
                ORDER BY k.issued_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_key(self, key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM license_keys WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None

    def set_key_status(self, key: str, status: str, activated_at: str | None = None) -> bool:
        stamp = activated_at or _now()
        with self._connect() as conn:
            if status == KEY_ACTIVE:
                cursor = conn.execute(
                    "UPDATE license_keys SET status = ?, activated_at = ? WHERE key = ?",
                    (status, stamp, key),
                )
            else:
                cursor = conn.execute("UPDATE license_keys SET status = ? WHERE key = ?", (status, key))
            conn.commit()
            return cursor.rowcount > 0

    # --- overview -----------------------------------------------------
    def overview(self, price_usd: float) -> dict[str, Any]:
        with self._connect() as conn:
            users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
            active_users = conn.execute("SELECT COUNT(*) AS c FROM users WHERE status = 'active'").fetchone()
            keys = conn.execute("SELECT COUNT(*) AS c FROM license_keys").fetchone()
            keys_active = conn.execute(
                "SELECT COUNT(*) AS c FROM license_keys WHERE status = 'active'"
            ).fetchone()
            pending = conn.execute(
                "SELECT COUNT(*) AS c FROM payments WHERE status = 'pending'"
            ).fetchone()
            paid = conn.execute("SELECT COUNT(*) AS c FROM payments WHERE status = 'paid'").fetchone()
            paid_this_month = conn.execute(
                "SELECT COUNT(*) AS c FROM payments WHERE status = 'paid' AND paid_at >= ?",
                (datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(),),
            ).fetchone()
        return {
            "total_users": int(users["c"]),
            "active_users": int(active_users["c"]),
            "total_keys": int(keys["c"]),
            "active_keys": int(keys_active["c"]),
            "pending_payments": int(pending["c"]),
            "paid_payments": int(paid["c"]),
            "paid_this_month": int(paid_this_month["c"]),
            "revenue_usd": round(int(paid["c"]) * price_usd, 2),
            "revenue_this_month_usd": round(int(paid_this_month["c"]) * price_usd, 2),
        }
