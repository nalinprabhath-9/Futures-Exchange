from __future__ import annotations
import argparse
import json
import os
import uuid
from typing import Any, Dict, List

from crypto_utils import generate_keypair

def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

def make_user(name: str, initial_balance: int, keystore_dir: str) -> Dict[str, Any]:
    user_id = name.strip().lower()
    address = "addr_" + uuid.uuid4().hex[:16]

    priv_pem, pub_b64 = generate_keypair()

    ensure_dir(keystore_dir)
    key_path = os.path.join(keystore_dir, f"{user_id}.pem")
    with open(key_path, "w", encoding="utf-8") as f:
        f.write(priv_pem)

    return {
        "user_id": user_id,
        "name": name,
        "address": address,
        "pubkey_b64": pub_b64,
        "balance": int(initial_balance),
        "keystore_path": key_path,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--names", default="Alice,Bob,Carol")
    ap.add_argument("--balance", type=int, default=2000)
    ap.add_argument("--keystore", default="keystore")
    args = ap.parse_args()

    users: List[Dict[str, Any]] = []
    for n in [x.strip() for x in args.names.split(",") if x.strip()]:
        users.append(make_user(n, args.balance, args.keystore))

    public_users = [{k: u[k] for k in ("user_id","name","address","pubkey_b64","balance")} for u in users]

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"users": public_users}, f, indent=2)

    print(f"[seed] wrote {len(users)} users to {args.out}")
    print(f"[seed] private keys: {args.keystore}/<user>.pem")

if __name__ == "__main__":
    main()