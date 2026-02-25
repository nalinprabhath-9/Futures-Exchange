"""
SQLite persistence for oracle price observations.

Schema:
    prices(id, symbol, price, timestamp, source)
    index on (symbol, timestamp) for fast lookups.
"""

import sqlite3
from typing import Optional

from config import DB_PATH

_db_path: str = DB_PATH


def init_db(path: str = DB_PATH) -> None:
    """Create schema if not present. Safe to call on every startup."""
    global _db_path
    _db_path = path
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS prices (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol    TEXT    NOT NULL,
                price     REAL    NOT NULL,
                timestamp INTEGER NOT NULL,
                source    TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_symbol_ts
                ON prices (symbol, timestamp);
        """
        )
    print(f"[db] Initialised database at {path}")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def insert_price(symbol: str, price: float, timestamp: int, source: str) -> None:
    """Persist one price observation."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO prices (symbol, price, timestamp, source) VALUES (?, ?, ?, ?)",
            (symbol, price, timestamp, source),
        )


def get_latest(symbol: str) -> Optional[sqlite3.Row]:
    """Return the most recently recorded price row for *symbol*, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM prices WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    return row


def get_at_timestamp(symbol: str, target_ts: int) -> Optional[sqlite3.Row]:
    """
    Return the price row whose timestamp is closest to *target_ts*.
    Prefers the row just before or at the target when equidistant.
    """
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM prices
            WHERE symbol = ?
            ORDER BY ABS(timestamp - ?) ASC, timestamp DESC
            LIMIT 1
            """,
            (symbol, target_ts),
        ).fetchone()
    return row
