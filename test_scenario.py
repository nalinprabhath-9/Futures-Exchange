from __future__ import annotations

import os
import sqlite3
import requests

from crypto_utils import generate_keypair, sign_payload
from templates import COIN_DECIMALS, DEFAULT_TEMPLATES, required_collateral_sats
from common import now_unix, new_nonce, stable_json, sha256_hex
from db import init_db


NODE = os.environ.get("NODE", "http://127.0.0.1:5001")


def post(path: str, body: dict):
    r = requests.post(f"{NODE}{path}", json=body, timeout=5)
    data = r.json()
    if r.status_code >= 400:
        raise RuntimeError(f"{path} failed {r.status_code}: {data}")
    return data


def get(path: str):
    r = requests.get(f"{NODE}{path}", timeout=5)
    r.raise_for_status()
    return r.json()


def seed_users_in_node_db(pubkeys_and_balances: list[tuple[str, str, int]]):
    # Default db path matches node.py default: node_<port>.db
    port = NODE.split(":")[-1]
    db_path = f"node_{port}.db"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=WAL;")
    init_db(conn)

    ts = now_unix()
    for pubkey, alias, bal_sats in pubkeys_and_balances:
        conn.execute(
            "INSERT OR IGNORE INTO users(pubkey, alias, created_at) VALUES (?, ?, ?)",
            (pubkey, alias, ts),
        )
        conn.execute(
            "INSERT OR IGNORE INTO wallets(pubkey, balance_sats, reserved_sats, created_at) VALUES (?, ?, 0, ?)",
            (pubkey, int(bal_sats), ts),
        )

    conn.commit()
    conn.close()


def main():
    # 5 users with 2000 ZPH
    kps = [generate_keypair() for _ in range(5)]
    users = [(kp.public_key_hex(), f"User{i+1}", int(2000 * COIN_DECIMALS)) for i, kp in enumerate(kps)]
    seed_users_in_node_db(users)

    proposer = kps[0]
    acceptor = kps[1]

    template_id = "BTCZPH-1"

    prop_payload = {
        "proposer_pubkey": proposer.public_key_hex(),
        "template_id": template_id,
        "side": "LONG",
        "quantity": 2,
        "entry_price": 60000.0,
        "expiry_unix": now_unix() + 3600,
        "created_at": now_unix(),
        "nonce": new_nonce(),
    }
    prop_sig = sign_payload(proposer.private_key, prop_payload)

    proposal_res = post("/propose", {
        "payload": prop_payload,
        "signer_pubkey": proposer.public_key_hex(),
        "signature_b64": prop_sig,
    })
    proposal_id = proposal_res["proposal_id"]
    print("proposal_id:", proposal_id)

    accept_payload = {
        "proposal_id": proposal_id,
        "accepted_at": now_unix(),
        "nonce": new_nonce(),
    }
    accept_sig = sign_payload(acceptor.private_key, accept_payload)

    accept_res = post("/accept", {
        "payload": accept_payload,
        "signer_pubkey": acceptor.public_key_hex(),
        "signature_b64": accept_sig,
    })
    trade_id = accept_res["trade_id"]
    print("trade_id:", trade_id)

    trades = get("/trades")
    trade = [t for t in trades if t["trade_id"] == trade_id][0]
    req = required_collateral_sats(DEFAULT_TEMPLATES[template_id], trade["entry_price"], trade["quantity"])
    print("required collateral per side (sats):", req)

    dep1_payload = {
        "trade_id": trade_id,
        "amount_sats": req,
        "created_at": now_unix(),
        "nonce": new_nonce(),
    }
    dep1_sig = sign_payload(proposer.private_key, dep1_payload)
    post("/deposit", {
        "payload": dep1_payload,
        "signer_pubkey": proposer.public_key_hex(),
        "signature_b64": dep1_sig,
    })
    print("proposer deposited")

    dep2_payload = {
        "trade_id": trade_id,
        "amount_sats": req,
        "created_at": now_unix(),
        "nonce": new_nonce(),
    }
    dep2_sig = sign_payload(acceptor.private_key, dep2_payload)
    post("/deposit", {
        "payload": dep2_payload,
        "signer_pubkey": acceptor.public_key_hex(),
        "signature_b64": dep2_sig,
    })
    print("acceptor deposited")

    trades2 = get("/trades")
    trade2 = [t for t in trades2 if t["trade_id"] == trade_id][0]
    print("final trade state:", trade2["state"])

    print("proposer wallet:", get(f"/wallet/{proposer.public_key_hex()}"))
    print("acceptor wallet:", get(f"/wallet/{acceptor.public_key_hex()}"))

    print("proposer notifications:", get(f"/notifications/{proposer.public_key_hex()}")[:5])
    print("acceptor notifications:", get(f"/notifications/{acceptor.public_key_hex()}")[:5])


if __name__ == "__main__":
    main()