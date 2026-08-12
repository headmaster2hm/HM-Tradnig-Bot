"""SQLite trade persistence."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.paths import default_db_path


@dataclass
class TradeRecord:
    ticket: int
    time_open: str
    time_close: str | None
    trade_type: str
    entry_price: float
    exit_price: float | None
    profit: float | None
    lot_size: float
    duration_seconds: int | None
    signal: str
    reason_closed: str | None
    confidence: float | None = None
    dry_run: bool = False


class TradeDatabase:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket INTEGER NOT NULL,
                    time_open TEXT NOT NULL,
                    time_close TEXT,
                    trade_type TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    profit REAL,
                    lot_size REAL NOT NULL,
                    duration_seconds INTEGER,
                    signal TEXT,
                    reason_closed TEXT,
                    confidence REAL,
                    dry_run INTEGER DEFAULT 0
                )
                """
            )
            conn.commit()

    def insert_open(
        self,
        ticket: int,
        trade_type: str,
        entry_price: float,
        lot_size: float,
        signal: str,
        confidence: float | None = None,
        dry_run: bool = False,
        time_open: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trades (
                    ticket, time_open, trade_type, entry_price, lot_size,
                    signal, confidence, dry_run
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket,
                    time_open or datetime.utcnow().isoformat(timespec="seconds"),
                    trade_type,
                    entry_price,
                    lot_size,
                    signal,
                    confidence,
                    int(dry_run),
                ),
            )
            conn.commit()

    def close_trade(
        self,
        ticket: int,
        exit_price: float,
        profit: float,
        reason_closed: str,
        time_close: str | None = None,
    ) -> None:
        closed_at = time_close or datetime.utcnow().isoformat(timespec="seconds")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT time_open FROM trades WHERE ticket = ? AND time_close IS NULL ORDER BY id DESC LIMIT 1",
                (ticket,),
            ).fetchone()
            duration = None
            if row:
                try:
                    opened = datetime.fromisoformat(row["time_open"])
                    duration = int((datetime.fromisoformat(closed_at) - opened).total_seconds())
                except ValueError:
                    duration = None
            conn.execute(
                """
                UPDATE trades
                SET time_close = ?, exit_price = ?, profit = ?,
                    duration_seconds = ?, reason_closed = ?
                WHERE ticket = ? AND time_close IS NULL
                """,
                (closed_at, exit_price, profit, duration, reason_closed, ticket),
            )
            conn.commit()

    def open_tickets(self, dry_run: bool | None = None) -> list[int]:
        with self._connect() as conn:
            if dry_run is None:
                rows = conn.execute(
                    "SELECT ticket FROM trades WHERE time_close IS NULL"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT ticket FROM trades WHERE time_close IS NULL AND dry_run = ?",
                    (int(dry_run),),
                ).fetchall()
        return [int(r["ticket"]) for r in rows]

    def history(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self, dry_run: bool | None = None) -> dict[str, Any]:
        """Aggregate closed-trade stats.

        dry_run=True  → paper only
        dry_run=False → live only
        dry_run=None  → all trades
        """
        with self._connect() as conn:
            if dry_run is None:
                closed = conn.execute(
                    "SELECT profit FROM trades WHERE time_close IS NOT NULL AND profit IS NOT NULL"
                ).fetchall()
            else:
                closed = conn.execute(
                    """
                    SELECT profit FROM trades
                    WHERE time_close IS NOT NULL AND profit IS NOT NULL AND dry_run = ?
                    """,
                    (int(dry_run),),
                ).fetchall()
        profits = [float(r["profit"]) for r in closed]
        wins = [p for p in profits if p > 0]
        return {
            "total_trades": len(profits),
            "wins": len(wins),
            "win_rate": (len(wins) / len(profits) * 100.0) if profits else 0.0,
            "net_profit": sum(profits) if profits else 0.0,
            "dry_run_filter": dry_run,
        }

    def export_csv(self, path: Path | str) -> Path:
        import csv

        out = Path(path)
        rows = self.history(limit=10_000)
        fieldnames = [
            "ticket",
            "time_open",
            "time_close",
            "trade_type",
            "entry_price",
            "exit_price",
            "profit",
            "lot_size",
            "duration_seconds",
            "signal",
            "reason_closed",
            "confidence",
            "dry_run",
        ]
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return out
