from __future__ import annotations
import argparse, json, urllib.request, time
from common import stable_json, hash_obj
from crypto_utils import sign
from client_keys import read_pem

def post(url: str, payload: dict) -> dict:
    data = stable_json(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=4) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", required=True)
    ap.add_argument("--taker", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--proposal", required=True)
    args = ap.parse_args()

    base = args.node.rstrip("/")

    with urllib.request.urlopen(base + "/users", timeout=4) as r:
        users = json.loads(r.read().decode("utf-8"))["users"]
    taker = next((u for u in users if u["user_id"] == args.taker), None)
    if not taker:
        raise SystemExit(f"taker {args.taker} not registered on node")

    accepted_at = int(time.time())
    canonical = {
        "proposal_id": args.proposal,
        "taker_user_id": args.taker,
        "taker_address": taker["address"],
        "taker_pubkey_b64": taker["pubkey_b64"],
        "accepted_at": accepted_at,
    }
    payload_hash = hash_obj(canonical)
    sig = sign(read_pem(args.key), payload_hash.encode("utf-8"))

    req = {
        "proposal_id": args.proposal,
        "taker_user_id": args.taker,
        "accepted_at": accepted_at,
        "payload_hash": payload_hash,
        "taker_signature_b64": sig,
    }

    res = post(base + "/accept", req)
    print(json.dumps(res))

if __name__ == "__main__":
    main()