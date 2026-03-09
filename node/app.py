import json
import os
import time
import threading
from typing import Dict, Any, List, Optional
from flask import Flask, request, jsonify

import requests

from node.blockchain import Blockchain, TxnMemoryPool, Miner
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
    # If you persisted blocks, replay them:
    rows = store.load_blocks(conn)
    if rows:
        store.rebuild_chain_from_db(conn, bc)
    else:
        # Or just restore snapshots (balances/trades) if no blocks exist:
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
    # fire-and-forget
    headers = {}
    if origin:
        headers["X-Origin"] = origin
    for peer in PEERS:
        try:
            requests.post(f"{peer}/tx/gossip", json=txw, timeout=1.2, headers=headers)
        except Exception:
            pass

# ----------------- Health -----------------

@APP.get("/health")
def health():
    return _json_ok(peers=PEERS, tip_height=len(bc.chain)-1 if bc.chain else -1, mempool=mempool.size())

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

@APP.post("/admin/create_user")
def create_user():
    body = request.get_json(force=True)
    user_id = body.get("user_id")
    privkey_hex = body.get("privkey_hex")  # if not provided, we reject (we generate in bootstrap script)
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
        view.append({
            "tx_hash": it["tx_hash"],
            "fee": it["fee"],
            "priority": it["priority"],
            "tx_type": tx.get("tx_type"),
            "trade_id": tx.get("trade_id"),
        })
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
        return (tx.party_a == addr)
    if tx.tx_type == TransactionType.ACCEPT_TRADE:
        return (tx.party_b == addr)
    if tx.tx_type in (TransactionType.CANCEL_PROPOSAL, TransactionType.CANCEL_TRADE, TransactionType.SETTLE_TRADE):
        # allow if party_a matches OR winner matches, depending on your later policy
        if tx.party_a and tx.party_a == addr:
            return True
        if getattr(tx, "winner", None) and tx.winner == addr:
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

    # add to mempool engine (fee + min fee enforced here)
    ok = mempool.add_transaction(tx)
    if not ok:
        return _json_err("mempool rejected tx (fee/signature)", 409)

    # persist mempool tx
    priority = "HIGH" if tx.fee >= 2 * tx.fee/2 else "NORMAL"
    store.add_mempool_tx(conn, tx.TransactionHash, int(tx.fee), priority, json.dumps(futures_tx_to_wire(tx)))
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

    store.add_mempool_tx(conn, tx.TransactionHash, int(tx.fee), "NORMAL", json.dumps(futures_tx_to_wire(tx)))
    return _json_ok(accepted=True)

# ----------------- Mine -----------------

@APP.post("/mine")
def mine():
    # mine a block from mempool, apply to bc, persist block + snapshots, remove mined txs from db mempool
    try:
        before = mempool.size()
        block = miner.mine_block(bc, mempool, verbose=False)
        # apply (this updates balances, locks, trades, expiry, fees)
        bc.add_block(block)

        height = len(bc.chain) - 1
        store.persist_block(conn, height, block)
        store.snapshot_state(conn, bc)

        # remove txs included in block from sqlite mempool
        included = [h for h in block.Transactions.keys() if "Coinbase" not in (block.Transactions[h].ListOfInputs[0] if block.Transactions[h].ListOfInputs else "")]
        store.remove_mempool_txs(conn, included)

        after = mempool.size()
        return _json_ok(mined_height=height, included_txs=len(included), mempool_before=before, mempool_after=after, block_hash=block.Blockhash)
    except Exception as e:
        return _json_err(f"mine failed: {e}", 500)

# ----------------- Simple chain view -----------------

@APP.get("/chain")
def chain():
    limit = int(request.args.get("limit", "20"))
    rows = store.load_blocks(conn)
    rows = rows[-limit:]
    return _json_ok(blocks=rows)

if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=PORT)