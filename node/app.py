import json
import os
import time
import threading
from typing import Dict, Any, List, Optional
from flask import Flask, request, jsonify

import requests

from node.blockchain import Blockchain, TxnMemoryPool, Miner, FuturesTransaction
from node.transaction_enums import TransactionType, TemplateType, TradeState
from node.crypto_utils import (
    get_signing_key_from_hex,
    get_compressed_pubkey,
    sign_message,
    verify_signature,
    pubkey_to_address,
)
from node.tx_codec import futures_tx_to_wire, futures_tx_from_wire
import node.state_store as store

APP = Flask(__name__)

NODE_ID = os.getenv("NODE_ID", "node1")
PORT = int(os.getenv("PORT", "5000"))
DB_PATH = os.getenv("DB_PATH", "/data/chain.db")
PEERS = [p.strip() for p in os.getenv("PEERS", "").split(",") if p.strip()]

conn = store.connect(DB_PATH)
store.init_schema(conn)

bc = Blockchain(proposal_timeout_seconds=int(os.getenv("PROPOSAL_TIMEOUT", "3600")))
mempool = TxnMemoryPool()
miner_address = os.getenv("MINER_ADDRESS", f"miner_{NODE_ID}")
miner = Miner(miner_address=miner_address)

# Restore chain + snapshots
try:
    rows = store.load_blocks(conn)
    if rows:
        # Load block headers/indices for chain height tracking only.
        # Balance/trade state comes from the snapshot (which includes faucet
        # credits that are never recorded in a block).
        store.load_chain_structure(conn, bc)

    # Always restore balance+trade state from snapshot regardless of blocks.
    store.restore_state(conn, bc)

    # Restore mempool items (if any)
    store.restore_mempool_into_engine(conn, mempool)
except Exception as e:
    print(f"[{NODE_ID}] restore failed: {e}")


def _json_ok(**kwargs):
    d = {"ok": True, "node": NODE_ID, "port": PORT}
    d.update(kwargs)
    return jsonify(d)


def _json_err(msg, code=400, **kwargs):
    d = {"ok": False, "error": msg, "node": NODE_ID, "port": PORT}
    d.update(kwargs)
    return jsonify(d), code


def gossip_futures_tx(txw: Dict[str, Any], origin: Optional[str] = None) -> None:
    headers = {}
    if origin:
        headers["X-Origin"] = origin
    for peer in PEERS:
        try:
            requests.post(f"{peer}/tx/gossip", json=txw, timeout=1.2, headers=headers)
        except Exception:
            pass


def _serialize_block_wire(height: int, block) -> Dict[str, Any]:
    txs = [store.serialize_tx(tx) for tx in block.Transactions.values()]
    return {
        "height": height,
        "block_hash": block.Blockhash,
        "prev_hash": block.BlockHeader.hashPrevBlock,
        "ts": block.BlockHeader.Timestamp,
        "bits": block.BlockHeader.Bits,
        "nonce": block.BlockHeader.Nonce,
        "merkle_root": block.BlockHeader.hashMerkleRoot,
        "txs": txs,
    }


def gossip_block(height: int, block, origin: Optional[str] = None) -> None:
    payload = _serialize_block_wire(height, block)
    if origin:
        payload["_origin"] = origin
    for peer in PEERS:
        try:
            requests.post(f"{peer}/block/gossip", json=payload, timeout=5)
        except Exception:
            pass


# ----------------- Health -----------------


@APP.get("/health")
def health():
    return _json_ok(
        peers=PEERS,
        tip_height=len(bc.chain) - 1 if bc.chain else -1,
        mempool=mempool.size(),
    )


# ----------------- Users -----------------


@APP.get("/users")
def users_list():
    return _json_ok(users=store.list_users(conn))


@APP.post("/admin/import_users")
def import_users():
    body = request.get_json(force=True)
    users = body.get("users", [])
    if not users:
        return _json_err("missing users list")
    store.import_users(conn, users)
    return _json_ok(imported=len(users))


@APP.post("/admin/flush_mempool")
def flush_mempool():
    """Remove all pending transactions from mempool (admin use / demo reset)."""
    conn.execute("DELETE FROM mempool")
    conn.commit()
    mempool.high_priority_txs.clear()
    mempool.normal_priority_txs.clear()
    return _json_ok(flushed=True)


@APP.post("/admin/sync_from")
def sync_from():
    """Fetch and apply all blocks this node is missing from a peer."""
    body = request.get_json(force=True)
    peer = body.get("peer")
    if not peer:
        return _json_err("missing peer URL")
    applied = _sync_from_peer(peer)
    return _json_ok(applied=applied, tip_height=len(bc.chain) - 1)


@APP.post("/admin/create_user")
def create_user():
    body = request.get_json(force=True)
    user_id = body.get("user_id")
    privkey_hex = body.get(
        "privkey_hex"
    )  # if not provided, we reject (we generate in bootstrap script)
    if not user_id or not privkey_hex:
        return _json_err("need user_id and privkey_hex")

    sk = get_signing_key_from_hex(privkey_hex)
    pub = get_compressed_pubkey(sk.public_key())
    addr = pubkey_to_address(pub)
    store.upsert_user(conn, user_id, privkey_hex, pub.hex(), addr)
    return _json_ok(user={"user_id": user_id, "address": addr, "pubkey_hex": pub.hex()})


# ----------------- Faucet / Balance -----------------


@APP.post("/faucet")
def faucet():
    body = request.get_json(force=True)
    user_id = body.get("user_id")
    amount = int(body.get("amount", 0))
    u = store.get_user(conn, user_id) if user_id else None
    if not u:
        return _json_err("unknown user")
    if amount <= 0:
        return _json_err("amount must be > 0")

    addr = u["address"]
    bc.balances.balances[addr] = bc.balances.balances.get(addr, 0) + amount
    store.snapshot_state(conn, bc)
    return _json_ok(address=addr, credited=amount)


@APP.get("/balance/<address>")
def get_balance(address: str):
    b = bc.get_user_balance(address)
    return _json_ok(balance=b["total"], locked=b["locked"], available=b["available"])


# ----------------- Proposals / Trades -----------------


@APP.get("/proposals")
def proposals():
    open_trades = [futures_tx_to_wire(t) for t in bc.get_proposed_trades()]
    return _json_ok(open=open_trades)


@APP.get("/trades")
def trades():
    return _json_ok(
        proposed=[futures_tx_to_wire(t) for t in bc.proposed_trades.values()],
        active=[futures_tx_to_wire(t) for t in bc.active_trades.values()],
        settled=[futures_tx_to_wire(t) for t in bc.settled_trades.values()],
    )


@APP.get("/trade/<trade_id>")
def trade(trade_id: str):
    t = bc.get_trade(trade_id)
    if not t:
        return _json_err("not found", 404)
    return _json_ok(trade=futures_tx_to_wire(t))


# ----------------- Mempool -----------------


@APP.get("/mempool")
def mempool_view():
    items = store.list_mempool(conn)
    # show minimal fields
    view = []
    for it in items:
        tx = it["tx"]
        view.append(
            {
                "tx_hash": it["tx_hash"],
                "fee": it["fee"],
                "priority": it["priority"],
                "tx_type": tx.get("tx_type"),
                "trade_id": tx.get("trade_id"),
            }
        )
    return _json_ok(mempool=view)


# ----------------- TX submit (signed) -----------------


def _ensure_sig_valid(tx) -> bool:
    if not getattr(tx, "signature", None) or not getattr(tx, "pubkey", None):
        return False
    return verify_signature(tx.pubkey, tx.get_signing_data(), tx.signature)


def _ensure_pubkey_matches_user(tx) -> bool:
    # for propose: party_a must match pubkey-derived address
    # for accept: party_b must match
    addr = pubkey_to_address(tx.pubkey)
    if tx.tx_type == TransactionType.PROPOSE_TRADE:
        return tx.party_a == addr
    if tx.tx_type == TransactionType.ACCEPT_TRADE:
        return tx.party_b == addr
    if tx.tx_type == TransactionType.SETTLE_TRADE:
        # Anyone may submit a settlement — the oracle signature on the
        # settlement price is the trust anchor, not the submitter's identity.
        return True
    if tx.tx_type in (TransactionType.CANCEL_PROPOSAL, TransactionType.CANCEL_TRADE):
        if tx.party_a and tx.party_a == addr:
            return True
        return False
    return True


@APP.post("/tx/submit")
def submit_tx():
    body = request.get_json(force=True)
    try:
        tx = futures_tx_from_wire(body["tx"])
    except Exception as e:
        return _json_err(f"bad tx: {e}")

    # dedupe
    if store.mempool_has(conn, tx.TransactionHash):
        return _json_ok(accepted=False, dedup=True, tx_hash=tx.TransactionHash)

    # verify signature + identity binding
    if not _ensure_sig_valid(tx):
        return _json_err("invalid signature", 400)
    if not _ensure_pubkey_matches_user(tx):
        return _json_err("pubkey does not match party address", 400)

    # balance pre-check: reject before mempool if the sender can't cover collateral + fee
    if tx.tx_type == TransactionType.PROPOSE_TRADE:
        needed = (tx.collateral_amount or 0) + (tx.fee or 0)
        available = bc.balances.get_available_balance(tx.party_a)
        if available < needed:
            return _json_err(
                f"insufficient balance: need {needed} milli-coins "
                f"(collateral {tx.collateral_amount} + fee {tx.fee}), "
                f"have {available}",
                400,
            )
    elif tx.tx_type == TransactionType.ACCEPT_TRADE:
        # Look for the proposal in mined state first, then in the mempool
        # (proposer and acceptor can both submit before the block is mined)
        proposal = bc.proposed_trades.get(tx.trade_id)
        if proposal is None:
            for mp_entry in mempool.transactions:
                if (
                    isinstance(mp_entry, FuturesTransaction)
                    and mp_entry.tx_type == TransactionType.PROPOSE_TRADE
                    and mp_entry.trade_id == tx.trade_id
                ):
                    proposal = mp_entry
                    break
        if proposal is None:
            return _json_err(
                f"trade {tx.trade_id} not found — propose it first", 404
            )
        needed = (proposal.collateral_amount or 0) + (tx.fee or 0)
        available = bc.balances.get_available_balance(tx.party_b)
        if available < needed:
            return _json_err(
                f"insufficient balance: need {needed} milli-coins "
                f"(collateral {proposal.collateral_amount} + fee {tx.fee}), "
                f"have {available}",
                400,
            )

    elif tx.tx_type == TransactionType.CANCEL_TRADE:
        # Only PROPOSED trades (not yet accepted) can be cancelled.
        # If the trade is already ACTIVE, reject immediately.
        if tx.trade_id in bc.active_trades:
            return _json_err(
                f"trade {tx.trade_id} is already ACTIVE and cannot be cancelled — "
                "only proposed (unaccepted) trades can be cancelled",
                400,
            )

    # add to mempool engine (fee + min fee enforced here)
    ok = mempool.add_transaction(tx)
    if not ok:
        return _json_err("mempool rejected tx (fee/signature)", 409)

    # persist mempool tx
    priority = "HIGH" if tx.fee >= 2 * tx.fee / 2 else "NORMAL"
    store.add_mempool_tx(
        conn,
        tx.TransactionHash,
        int(tx.fee),
        priority,
        json.dumps(futures_tx_to_wire(tx)),
    )
    # gossip
    gossip_futures_tx(futures_tx_to_wire(tx), origin=f"http://{NODE_ID}:{PORT}")
    return _json_ok(accepted=True, tx_hash=tx.TransactionHash)


@APP.post("/tx/gossip")
def gossip_rx():
    body = request.get_json(force=True)
    try:
        tx = futures_tx_from_wire(body)
    except Exception:
        return _json_err("bad gossip tx", 400)

    if store.mempool_has(conn, tx.TransactionHash):
        return _json_ok(accepted=False, dedup=True)

    if not _ensure_sig_valid(tx):
        return _json_err("invalid signature", 400)

    ok = mempool.add_transaction(tx)
    if not ok:
        return _json_err("mempool rejected", 409)

    store.add_mempool_tx(
        conn,
        tx.TransactionHash,
        int(tx.fee),
        "NORMAL",
        json.dumps(futures_tx_to_wire(tx)),
    )
    return _json_ok(accepted=True)


# ----------------- Mine -----------------


@APP.post("/mine")
def mine():
    try:
        before = mempool.size()
        block = miner.mine_block(bc, mempool, verbose=False)
        bc.add_block(block)

        height = len(bc.chain) - 1
        store.persist_block(conn, height, block)
        store.snapshot_state(conn, bc)

        included = [
            h
            for h in block.Transactions.keys()
            if "Coinbase"
            not in (
                block.Transactions[h].ListOfInputs[0]
                if block.Transactions[h].ListOfInputs
                else ""
            )
        ]
        store.remove_mempool_txs(conn, included)

        after = mempool.size()

        # Propagate block to all peers
        gossip_block(height, block, origin=f"http://{NODE_ID}:{PORT}")

        return _json_ok(
            mined_height=height,
            included_txs=len(included),
            mempool_before=before,
            mempool_after=after,
            block_hash=block.Blockhash,
        )
    except Exception as e:
        return _json_err(f"mine failed: {e}", 500)


def _apply_block_row(row: Dict[str, Any]) -> bool:
    """Deserialize a raw DB/wire block row and apply it to the chain.
    Returns True if applied, False if skipped (already have it or wrong height)."""
    from node.blockchain import Block as _Block

    block_hash = row["block_hash"]
    height = row["height"]

    if block_hash in bc.block_hash_index:
        return False
    if height != len(bc.chain):
        return False

    b = _Block(previous_block_hash=row["prev_hash"])
    b.BlockHeader.Timestamp = row["ts"]
    b.BlockHeader.Bits = row["bits"]
    b.BlockHeader.Nonce = row["nonce"]
    b.BlockHeader.hashMerkleRoot = row["merkle_root"]
    b.Blockhash = block_hash

    txs_data = row["txs"] if "txs" in row else json.loads(row.get("txs_json", "[]"))
    for td in txs_data:
        tx = store.deserialize_tx(td)
        b.Transactions[tx.TransactionHash] = tx
    b.TransactionCounter = len(b.Transactions)

    bc.add_block(b)
    store.persist_block(conn, height, b)
    store.snapshot_state(conn, bc)

    included = [
        h
        for h in b.Transactions.keys()
        if "Coinbase"
        not in (
            b.Transactions[h].ListOfInputs[0] if b.Transactions[h].ListOfInputs else ""
        )
    ]
    store.remove_mempool_txs(conn, included)
    return True


def _sync_from_peer(peer_url: str) -> int:
    """Fetch and apply all blocks this node is missing from peer_url.
    Returns number of blocks applied."""
    our_height = len(bc.chain) - 1
    try:
        r = requests.get(f"{peer_url}/chain/from/{our_height + 1}", timeout=15)
        rows = r.json().get("blocks", [])
    except Exception:
        return 0
    applied = 0
    for row in rows:
        if _apply_block_row(row):
            applied += 1
    return applied


@APP.post("/block/gossip")
def block_gossip_rx():
    body = request.get_json(force=True)
    try:
        height = body["height"]
        block_hash = body["block_hash"]

        if block_hash in bc.block_hash_index:
            return _json_ok(accepted=False, dedup=True)

        expected_height = len(bc.chain)

        # If we're behind, sync missing blocks from the sender first
        if height > expected_height:
            origin = body.get("_origin")
            if origin:
                threading.Thread(
                    target=_sync_from_peer, args=(origin,), daemon=True
                ).start()
            return _json_ok(accepted=False, reason="behind peer, syncing")

        if height != expected_height:
            return _json_ok(
                accepted=False,
                reason=f"height mismatch: have {expected_height-1}, got {height}",
            )

        _apply_block_row(body)

        # Forward to peers
        origin = body.get("_origin")
        gossip_block(height, bc.chain[height], origin=origin)

        return _json_ok(accepted=True, height=height)
    except Exception as e:
        return _json_err(f"block gossip failed: {e}", 400)


# ----------------- Chain view -----------------


@APP.get("/chain")
def chain():
    limit = int(request.args.get("limit", "20"))
    rows = store.load_blocks(conn)
    rows = rows[-limit:]
    return _json_ok(blocks=rows)


@APP.get("/chain/from/<int:from_height>")
def chain_from(from_height: int):
    """Return all stored blocks starting from from_height (for peer sync)."""
    rows = store.load_blocks(conn)
    result = []
    for r in rows:
        if r["height"] >= from_height:
            txs = json.loads(r["txs_json"])
            result.append(
                {
                    "height": r["height"],
                    "block_hash": r["block_hash"],
                    "prev_hash": r["prev_hash"],
                    "ts": r["ts"],
                    "bits": r["bits"],
                    "nonce": r["nonce"],
                    "merkle_root": r["merkle_root"],
                    "txs": txs,
                }
            )
    return _json_ok(blocks=result)


if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=PORT)
