import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from node.blockchain import Blockchain, Block, Transaction, Output, FuturesTransaction
from node.transaction_enums import TransactionType
from node.tx_codec import futures_tx_to_wire, futures_tx_from_wire

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS users(
      user_id TEXT PRIMARY KEY,
      privkey_hex TEXT NOT NULL,
      pubkey_hex TEXT NOT NULL,
      address TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS mempool(
      tx_hash TEXT PRIMARY KEY,
      fee INTEGER NOT NULL,
      priority TEXT NOT NULL,
      tx_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS blocks(
      height INTEGER PRIMARY KEY,
      block_hash TEXT NOT NULL,
      prev_hash TEXT NOT NULL,
      ts INTEGER NOT NULL,
      bits INTEGER NOT NULL,
      nonce INTEGER NOT NULL,
      merkle_root TEXT NOT NULL,
      txs_json TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS snapshots(
      key TEXT PRIMARY KEY,
      json TEXT NOT NULL
    );
    """)
    conn.commit()

# ---------------- USERS ----------------

def upsert_user(conn: sqlite3.Connection, user_id: str, privkey_hex: str, pubkey_hex: str, address: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO users(user_id, privkey_hex, pubkey_hex, address) VALUES (?,?,?,?)",
        (user_id, privkey_hex, pubkey_hex, address),
    )
    conn.commit()

def list_users(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.execute("SELECT user_id, pubkey_hex, address FROM users ORDER BY user_id")
    return [dict(r) for r in cur.fetchall()]

def get_user(conn: sqlite3.Connection, user_id: str) -> Optional[Dict[str, Any]]:
    cur = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    r = cur.fetchone()
    return dict(r) if r else None

def import_users(conn: sqlite3.Connection, users: List[Dict[str, Any]]) -> None:
    for u in users:
        upsert_user(conn, u["user_id"], u["privkey_hex"], u["pubkey_hex"], u["address"])

# ---------------- MEMPOOL ----------------

def mempool_has(conn: sqlite3.Connection, tx_hash: str) -> bool:
    cur = conn.execute("SELECT 1 FROM mempool WHERE tx_hash=?", (tx_hash,))
    return cur.fetchone() is not None

def add_mempool_tx(conn: sqlite3.Connection, tx_hash: str, fee: int, priority: str, tx_json: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO mempool(tx_hash, fee, priority, tx_json) VALUES (?,?,?,?)",
        (tx_hash, fee, priority, tx_json),
    )
    conn.commit()

def remove_mempool_txs(conn: sqlite3.Connection, tx_hashes: List[str]) -> None:
    conn.executemany("DELETE FROM mempool WHERE tx_hash=?", [(h,) for h in tx_hashes])
    conn.commit()

def list_mempool(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.execute("SELECT tx_hash, fee, priority, tx_json FROM mempool ORDER BY fee DESC")
    out = []
    for r in cur.fetchall():
        out.append({"tx_hash": r["tx_hash"], "fee": r["fee"], "priority": r["priority"], "tx": json.loads(r["tx_json"])})
    return out

def restore_mempool_into_engine(conn: sqlite3.Connection, mempool_engine) -> None:
    from blockchain import FuturesTransaction
    rows = list_mempool(conn)
    # rebuild queues deterministically by fee ordering
    for row in rows:
        tx = futures_tx_from_wire(row["tx"])
        mempool_engine.add_transaction(tx)

# ---------------- BLOCKS ----------------

def serialize_tx(tx: Transaction) -> Dict[str, Any]:
    # Coinbase / normal Tx:
    if isinstance(tx, FuturesTransaction):
        d = futures_tx_to_wire(tx)
        d["_kind"] = "futures"
        return d
    else:
        outs = []
        if tx.ListOfOutputs and isinstance(tx.ListOfOutputs[0], Output):
            for o in tx.ListOfOutputs:
                outs.append({"value": o.Value, "index": o.Index, "script": o.Script})
        else:
            outs = tx.ListOfOutputs
        return {
            "_kind": "basic",
            "version": tx.VersionNumber,
            "inputs": tx.ListOfInputs,
            "outputs": outs,
            "fee": getattr(tx, "fee", 0),
            "tx_hash": tx.TransactionHash,
        }

def deserialize_tx(d: Dict[str, Any]) -> Transaction:
    kind = d.get("_kind")
    if kind == "futures":
        return futures_tx_from_wire(d)
    # basic tx (coinbase)
    outs = []
    for o in d["outputs"]:
        if isinstance(o, dict):
            outs.append(Output(value=o["value"], index=o["index"], script=o["script"]))
        else:
            outs.append(o)
    tx = Transaction(version_number=d["version"], list_of_inputs=d["inputs"], list_of_outputs=outs, fee=d.get("fee", 0))
    return tx

def persist_block(conn: sqlite3.Connection, height: int, block: Block) -> None:
    txs = [serialize_tx(tx) for tx in block.Transactions.values()]
    conn.execute(
        "INSERT OR REPLACE INTO blocks(height, block_hash, prev_hash, ts, bits, nonce, merkle_root, txs_json) VALUES (?,?,?,?,?,?,?,?)",
        (
            height,
            block.Blockhash,
            block.BlockHeader.hashPrevBlock,
            block.BlockHeader.Timestamp,
            block.BlockHeader.Bits,
            block.BlockHeader.Nonce,
            block.BlockHeader.hashMerkleRoot,
            json.dumps(txs, separators=(",", ":"), sort_keys=True),
        ),
    )
    conn.commit()

def load_blocks(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.execute("SELECT * FROM blocks ORDER BY height ASC")
    return [dict(r) for r in cur.fetchall()]

def rebuild_chain_from_db(conn: sqlite3.Connection, bc: Blockchain) -> None:
    rows = load_blocks(conn)
    for r in rows:
        txs = json.loads(r["txs_json"])
        # Rebuild a Block object with header fields
        b = Block(previous_block_hash=r["prev_hash"])
        b.BlockHeader.Timestamp = r["ts"]
        b.BlockHeader.Bits = r["bits"]
        b.BlockHeader.Nonce = r["nonce"]
        # inject txs
        for td in txs:
            tx = deserialize_tx(td)
            b.Transactions[tx.TransactionHash] = tx
        b.TransactionCounter = len(b.Transactions)
        b.BlockHeader.hashMerkleRoot = r["merkle_root"]
        b.Blockhash = r["block_hash"]
        # Apply to blockchain state (balances/trades)
        bc.add_block(b)

def load_chain_structure(conn: sqlite3.Connection, bc: Blockchain) -> None:
    """
    Restore persisted block headers and transaction indices without replaying
    state transitions. Runtime balances and trades come from snapshots.
    """
    rows = load_blocks(conn)
    bc.chain.clear()
    bc.block_height_index.clear()
    bc.block_hash_index.clear()
    bc.transaction_index.clear()

    for r in rows:
        txs = json.loads(r["txs_json"])
        b = Block(previous_block_hash=r["prev_hash"])
        b.BlockHeader.Timestamp = r["ts"]
        b.BlockHeader.Bits = r["bits"]
        b.BlockHeader.Nonce = r["nonce"]
        b.BlockHeader.hashMerkleRoot = r["merkle_root"]
        b.Blockhash = r["block_hash"]

        for td in txs:
            tx = deserialize_tx(td)
            b.Transactions[tx.TransactionHash] = tx
            bc.transaction_index[tx.TransactionHash] = (b, tx)

        b.TransactionCounter = len(b.Transactions)
        height = len(bc.chain)
        bc.chain.append(b)
        bc.block_height_index[height] = b
        bc.block_hash_index[b.Blockhash] = b

# ---------------- SNAPSHOTS ----------------

def save_snapshot(conn: sqlite3.Connection, key: str, obj: Any) -> None:
    conn.execute("INSERT OR REPLACE INTO snapshots(key,json) VALUES (?,?)", (key, json.dumps(obj)))
    conn.commit()

def load_snapshot(conn: sqlite3.Connection, key: str) -> Optional[Any]:
    cur = conn.execute("SELECT json FROM snapshots WHERE key=?", (key,))
    r = cur.fetchone()
    return json.loads(r["json"]) if r else None

def snapshot_state(conn: sqlite3.Connection, bc: Blockchain) -> None:
    # balances + locks
    save_snapshot(conn, "balances", bc.balances.balances)
    save_snapshot(conn, "locked", bc.balances.locked)

    # trades
    save_snapshot(conn, "proposed_trades", {k: futures_tx_to_wire(v) for k, v in bc.proposed_trades.items()})
    save_snapshot(conn, "active_trades", {k: futures_tx_to_wire(v) for k, v in bc.active_trades.items()})
    save_snapshot(conn, "settled_trades", {k: futures_tx_to_wire(v) for k, v in bc.settled_trades.items()})

def restore_state(conn: sqlite3.Connection, bc: Blockchain) -> None:
    bal = load_snapshot(conn, "balances") or {}
    locked = load_snapshot(conn, "locked") or {}
    bc.balances.balances.update({k: int(v) for k, v in bal.items()})
    bc.balances.locked.update({k: int(v) for k, v in locked.items()})

    for name, bucket in [("proposed_trades", bc.proposed_trades), ("active_trades", bc.active_trades), ("settled_trades", bc.settled_trades)]:
        d = load_snapshot(conn, name) or {}
        for tid, txw in d.items():
            bucket[tid] = futures_tx_from_wire(txw)
