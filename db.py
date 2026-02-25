from __future__ import annotations
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  address TEXT NOT NULL UNIQUE,
  pubkey_b64 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS balances (
  address TEXT PRIMARY KEY,
  balance INTEGER NOT NULL,
  locked INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
  proposal_id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  maker_user_id TEXT NOT NULL,
  maker_address TEXT NOT NULL,
  maker_pubkey_b64 TEXT NOT NULL,
  terms_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  required_collateral INTEGER NOT NULL,
  payload_hash TEXT NOT NULL,
  maker_signature_b64 TEXT NOT NULL,
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS acceptances (
  proposal_id TEXT PRIMARY KEY,
  taker_user_id TEXT NOT NULL,
  taker_address TEXT NOT NULL,
  taker_pubkey_b64 TEXT NOT NULL,
  accepted_at INTEGER NOT NULL,
  payload_hash TEXT NOT NULL,
  taker_signature_b64 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mempool (
  tx_id TEXT PRIMARY KEY,
  tx_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS blocks (
  height INTEGER PRIMARY KEY,
  prev_hash TEXT NOT NULL,
  ts INTEGER NOT NULL,
  txs_json TEXT NOT NULL,
  nonce INTEGER NOT NULL,
  block_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
"""

def connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.commit()

# Users
def upsert_user(con: sqlite3.Connection, user: Dict[str, Any]) -> None:
    con.execute(
        "INSERT INTO users(user_id,name,address,pubkey_b64) VALUES(?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,address=excluded.address,pubkey_b64=excluded.pubkey_b64",
        (user["user_id"], user["name"], user["address"], user["pubkey_b64"])
    )
    con.execute(
        "INSERT INTO balances(address,balance,locked) VALUES(?,?,0) ON CONFLICT(address) DO NOTHING",
        (user["address"], int(user.get("balance", 0)))
    )
    con.commit()

def get_user(con: sqlite3.Connection, user_id: str) -> Optional[Dict[str, Any]]:
    r = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return dict(r) if r else None

def list_users(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT user_id,name,address,pubkey_b64 FROM users ORDER BY user_id").fetchall()
    return [dict(r) for r in rows]

# Balances
def get_balance(con: sqlite3.Connection, address: str) -> Dict[str, int]:
    r = con.execute("SELECT balance,locked FROM balances WHERE address=?", (address,)).fetchone()
    if not r:
        return {"balance": 0, "locked": 0}
    return {"balance": int(r["balance"]), "locked": int(r["locked"])}

def credit(con: sqlite3.Connection, address: str, amount: int) -> None:
    con.execute(
        "INSERT INTO balances(address,balance,locked) VALUES(?,?,0) "
        "ON CONFLICT(address) DO UPDATE SET balance=balance+excluded.balance",
        (address, int(amount))
    )
    con.commit()

def lock_collateral(con: sqlite3.Connection, address: str, amount: int) -> bool:
    r = con.execute("SELECT balance,locked FROM balances WHERE address=?", (address,)).fetchone()
    if not r:
        return False
    bal = int(r["balance"])
    locked = int(r["locked"])
    if (bal - locked) < int(amount):
        return False
    con.execute("UPDATE balances SET locked=locked+? WHERE address=?", (int(amount), address))
    con.commit()
    return True

# Proposals
def insert_proposal(con: sqlite3.Connection, p: Dict[str, Any]) -> bool:
    try:
        con.execute(
            "INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                p["proposal_id"], p["template_id"], int(p["version"]),
                p["maker_user_id"], p["maker_address"], p["maker_pubkey_b64"],
                p["terms_json"], int(p["created_at"]), int(p["expires_at"]),
                int(p["required_collateral"]), p["payload_hash"], p["maker_signature_b64"], p["status"]
            )
        )
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def get_proposal(con: sqlite3.Connection, proposal_id: str) -> Optional[Dict[str, Any]]:
    r = con.execute("SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    return dict(r) if r else None

def list_open_proposals(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT * FROM proposals WHERE status='OPEN' ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

def set_proposal_status(con: sqlite3.Connection, proposal_id: str, status: str) -> None:
    con.execute("UPDATE proposals SET status=? WHERE proposal_id=?", (status, proposal_id))
    con.commit()

# Acceptances
def insert_acceptance(con: sqlite3.Connection, a: Dict[str, Any]) -> bool:
    try:
        con.execute(
            "INSERT INTO acceptances VALUES(?,?,?,?,?,?,?)",
            (
                a["proposal_id"], a["taker_user_id"], a["taker_address"], a["taker_pubkey_b64"],
                int(a["accepted_at"]), a["payload_hash"], a["taker_signature_b64"]
            )
        )
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def get_acceptance(con: sqlite3.Connection, proposal_id: str) -> Optional[Dict[str, Any]]:
    r = con.execute("SELECT * FROM acceptances WHERE proposal_id=?", (proposal_id,)).fetchone()
    return dict(r) if r else None

# Mempool
def add_mempool_tx(con: sqlite3.Connection, tx: Dict[str, Any]) -> bool:
    try:
        con.execute(
            "INSERT INTO mempool VALUES(?,?,?,?)",
            (tx["tx_id"], tx["tx_type"], tx["payload_json"], int(tx["created_at"]))
        )
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def list_mempool(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT * FROM mempool ORDER BY created_at ASC").fetchall()
    return [dict(r) for r in rows]

def clear_mempool(con: sqlite3.Connection) -> None:
    con.execute("DELETE FROM mempool")
    con.commit()

def delete_mempool_txs(con: sqlite3.Connection, tx_ids: List[str]) -> None:
    if not tx_ids:
        return
    CHUNK = 500
    for i in range(0, len(tx_ids), CHUNK):
        chunk = tx_ids[i:i+CHUNK]
        placeholders = ",".join(["?"] * len(chunk))
        con.execute(f"DELETE FROM mempool WHERE tx_id IN ({placeholders})", chunk)
    con.commit()

# Chain
def get_tip(con: sqlite3.Connection) -> Tuple[int, str]:
    r = con.execute("SELECT height, block_hash FROM blocks ORDER BY height DESC LIMIT 1").fetchone()
    if not r:
        return (-1, "GENESIS")
    return (int(r["height"]), str(r["block_hash"]))

def add_block(con: sqlite3.Connection, b: Dict[str, Any]) -> None:
    con.execute(
        "INSERT INTO blocks VALUES(?,?,?,?,?,?)",
        (int(b["height"]), b["prev_hash"], int(b["ts"]), b["txs_json"], int(b["nonce"]), b["block_hash"])
    )
    con.commit()

def get_chain(con: sqlite3.Connection, limit: int = 50) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT * FROM blocks ORDER BY height DESC LIMIT ?", (int(limit),)).fetchall()
    return [dict(r) for r in rows]