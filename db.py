from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional, Tuple, List

from common import now_unix


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          pubkey TEXT PRIMARY KEY,
          alias TEXT,
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wallets (
          pubkey TEXT PRIMARY KEY REFERENCES users(pubkey) ON DELETE CASCADE,
          balance_sats INTEGER NOT NULL,
          reserved_sats INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS proposals (
          proposal_id TEXT PRIMARY KEY,
          proposer_pubkey TEXT NOT NULL REFERENCES users(pubkey),
          template_id TEXT NOT NULL,
          side TEXT NOT NULL,
          quantity INTEGER NOT NULL,
          entry_price REAL NOT NULL,
          expiry_unix INTEGER NOT NULL,
          created_at INTEGER NOT NULL,
          nonce TEXT NOT NULL,
          signature_b64 TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'OPEN'
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_proposals_nonce
          ON proposals(proposer_pubkey, nonce);

        CREATE TABLE IF NOT EXISTS acceptances (
          acceptance_id TEXT PRIMARY KEY,
          proposal_id TEXT NOT NULL REFERENCES proposals(proposal_id) ON DELETE CASCADE,
          acceptor_pubkey TEXT NOT NULL REFERENCES users(pubkey),
          accepted_at INTEGER NOT NULL,
          nonce TEXT NOT NULL,
          signature_b64 TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_accept_nonce
          ON acceptances(acceptor_pubkey, nonce);

        CREATE TABLE IF NOT EXISTS trades (
          trade_id TEXT PRIMARY KEY,
          proposal_id TEXT NOT NULL UNIQUE REFERENCES proposals(proposal_id),
          template_id TEXT NOT NULL,
          long_pubkey TEXT NOT NULL REFERENCES users(pubkey),
          short_pubkey TEXT NOT NULL REFERENCES users(pubkey),
          quantity INTEGER NOT NULL,
          entry_price REAL NOT NULL,
          expiry_unix INTEGER NOT NULL,
          required_collateral_sats INTEGER NOT NULL,
          state TEXT NOT NULL DEFAULT 'AWAITING_DEPOSIT',
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS escrow (
          trade_id TEXT NOT NULL REFERENCES trades(trade_id) ON DELETE CASCADE,
          pubkey TEXT NOT NULL REFERENCES users(pubkey),
          deposited_sats INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(trade_id, pubkey)
        );

        CREATE TABLE IF NOT EXISTS deposits (
          deposit_id TEXT PRIMARY KEY,
          trade_id TEXT NOT NULL REFERENCES trades(trade_id) ON DELETE CASCADE,
          depositor_pubkey TEXT NOT NULL REFERENCES users(pubkey),
          amount_sats INTEGER NOT NULL,
          created_at INTEGER NOT NULL,
          nonce TEXT NOT NULL,
          signature_b64 TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_deposit_nonce
          ON deposits(depositor_pubkey, nonce);

        CREATE TABLE IF NOT EXISTS trade_state_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          trade_id TEXT NOT NULL REFERENCES trades(trade_id) ON DELETE CASCADE,
          from_state TEXT,
          to_state TEXT NOT NULL,
          reason TEXT,
          at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          to_pubkey TEXT NOT NULL REFERENCES users(pubkey),
          kind TEXT NOT NULL,
          message TEXT NOT NULL,
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS seen_msgs (
          msg_id TEXT PRIMARY KEY,
          seen_at INTEGER NOT NULL
        );
        """
    )
    conn.commit()


# ---------- Users / wallets ----------

def create_user(conn: sqlite3.Connection, pubkey: str, alias: str, initial_balance_sats: int) -> None:
    ts = now_unix()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(pubkey, alias, created_at) VALUES (?, ?, ?)",
            (pubkey, alias, ts),
        )
        conn.execute(
            "INSERT OR IGNORE INTO wallets(pubkey, balance_sats, reserved_sats, created_at) VALUES (?, ?, 0, ?)",
            (pubkey, int(initial_balance_sats), ts),
        )


def user_exists(conn: sqlite3.Connection, pubkey: str) -> bool:
    row = conn.execute("SELECT 1 FROM users WHERE pubkey = ?", (pubkey,)).fetchone()
    return row is not None


def get_wallet(conn: sqlite3.Connection, pubkey: str) -> Tuple[int, int]:
    row = conn.execute(
        "SELECT balance_sats, reserved_sats FROM wallets WHERE pubkey = ?",
        (pubkey,),
    ).fetchone()
    if not row:
        raise KeyError("wallet not found")
    return int(row["balance_sats"]), int(row["reserved_sats"])


def reserve_sats(conn: sqlite3.Connection, pubkey: str, amount: int) -> None:
    if amount <= 0:
        return
    cur = conn.execute(
        """
        UPDATE wallets
           SET reserved_sats = reserved_sats + ?
         WHERE pubkey = ?
           AND (balance_sats - reserved_sats) >= ?
        """,
        (int(amount), pubkey, int(amount)),
    )
    if cur.rowcount != 1:
        raise PermissionError("insufficient available funds to reserve")


def release_reserve_sats(conn: sqlite3.Connection, pubkey: str, amount: int) -> None:
    if amount <= 0:
        return
    conn.execute(
        """
        UPDATE wallets
           SET reserved_sats = CASE
                                 WHEN reserved_sats >= ? THEN reserved_sats - ?
                                 ELSE 0
                               END
         WHERE pubkey = ?
        """,
        (int(amount), int(amount), pubkey),
    )


def deduct_balance_and_reduce_reserve(conn: sqlite3.Connection, pubkey: str, amount: int) -> None:
    """
    Deduct from balance; reduce reserved by same amount (reserved was set at accept-time).
    """
    if amount <= 0:
        raise ValueError("amount must be > 0")
    cur = conn.execute(
        """
        UPDATE wallets
           SET balance_sats = balance_sats - ?,
               reserved_sats = CASE
                                WHEN reserved_sats >= ? THEN reserved_sats - ?
                                ELSE 0
                              END
         WHERE pubkey = ?
           AND balance_sats >= ?
        """,
        (int(amount), int(amount), int(amount), pubkey, int(amount)),
    )
    if cur.rowcount != 1:
        raise PermissionError("insufficient balance to deposit")


def add_notification(conn: sqlite3.Connection, to_pubkey: str, kind: str, message: str) -> None:
    conn.execute(
        "INSERT INTO notifications(to_pubkey, kind, message, created_at) VALUES (?, ?, ?, ?)",
        (to_pubkey, kind, message, now_unix()),
    )


def list_notifications(conn: sqlite3.Connection, to_pubkey: str, limit: int = 50) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT kind, message, created_at FROM notifications WHERE to_pubkey = ? ORDER BY id DESC LIMIT ?",
        (to_pubkey, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- Seen messages (idempotency) ----------

def has_seen_msg(conn: sqlite3.Connection, msg_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM seen_msgs WHERE msg_id = ?", (msg_id,)).fetchone()
    return row is not None


def mark_seen_msg(conn: sqlite3.Connection, msg_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO seen_msgs(msg_id, seen_at) VALUES (?, ?)",
        (msg_id, now_unix()),
    )


# ---------- Proposals / trades ----------

def insert_proposal(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO proposals(
              proposal_id, proposer_pubkey, template_id, side, quantity, entry_price,
              expiry_unix, created_at, nonce, signature_b64, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
            """,
            (
                row["proposal_id"],
                row["proposer_pubkey"],
                row["template_id"],
                row["side"],
                int(row["quantity"]),
                float(row["entry_price"]),
                int(row["expiry_unix"]),
                int(row["created_at"]),
                row["nonce"],
                row["signature_b64"],
            ),
        )


def get_proposal(conn: sqlite3.Connection, proposal_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()


def mark_proposal_status(conn: sqlite3.Connection, proposal_id: str, status: str) -> None:
    conn.execute("UPDATE proposals SET status = ? WHERE proposal_id = ?", (status, proposal_id))


def list_proposals(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM proposals ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def insert_acceptance(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO acceptances(
          acceptance_id, proposal_id, acceptor_pubkey, accepted_at, nonce, signature_b64
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            row["acceptance_id"],
            row["proposal_id"],
            row["acceptor_pubkey"],
            int(row["accepted_at"]),
            row["nonce"],
            row["signature_b64"],
        ),
    )


def insert_trade(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    ts = now_unix()
    conn.execute(
        """
        INSERT INTO trades(
          trade_id, proposal_id, template_id, long_pubkey, short_pubkey,
          quantity, entry_price, expiry_unix, required_collateral_sats, state, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["trade_id"],
            row["proposal_id"],
            row["template_id"],
            row["long_pubkey"],
            row["short_pubkey"],
            int(row["quantity"]),
            float(row["entry_price"]),
            int(row["expiry_unix"]),
            int(row["required_collateral_sats"]),
            row.get("state", "AWAITING_DEPOSIT"),
            ts,
        ),
    )
    # escrow rows
    conn.execute("INSERT OR IGNORE INTO escrow(trade_id, pubkey, deposited_sats) VALUES (?, ?, 0)", (row["trade_id"], row["long_pubkey"]))
    conn.execute("INSERT OR IGNORE INTO escrow(trade_id, pubkey, deposited_sats) VALUES (?, ?, 0)", (row["trade_id"], row["short_pubkey"]))
    # history
    conn.execute(
        "INSERT INTO trade_state_history(trade_id, from_state, to_state, reason, at) VALUES (?, ?, ?, ?, ?)",
        (row["trade_id"], None, row.get("state", "AWAITING_DEPOSIT"), "trade_created", now_unix()),
    )


def get_trade(conn: sqlite3.Connection, trade_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,)).fetchone()


def list_trades(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT * FROM trades ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_escrow(conn: sqlite3.Connection, trade_id: str, pubkey: str) -> int:
    row = conn.execute(
        "SELECT deposited_sats FROM escrow WHERE trade_id = ? AND pubkey = ?",
        (trade_id, pubkey),
    ).fetchone()
    return int(row["deposited_sats"]) if row else 0


def add_escrow(conn: sqlite3.Connection, trade_id: str, pubkey: str, amount: int) -> None:
    conn.execute(
        "UPDATE escrow SET deposited_sats = deposited_sats + ? WHERE trade_id = ? AND pubkey = ?",
        (int(amount), trade_id, pubkey),
    )


def set_trade_state(conn: sqlite3.Connection, trade_id: str, to_state: str, reason: str) -> None:
    row = conn.execute("SELECT state FROM trades WHERE trade_id = ?", (trade_id,)).fetchone()
    from_state = row["state"] if row else None
    conn.execute("UPDATE trades SET state = ? WHERE trade_id = ?", (to_state, trade_id))
    conn.execute(
        "INSERT INTO trade_state_history(trade_id, from_state, to_state, reason, at) VALUES (?, ?, ?, ?, ?)",
        (trade_id, from_state, to_state, reason, now_unix()),
    )