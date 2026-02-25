from __future__ import annotations
import argparse, json, urllib.request, uuid
from common import stable_json, hash_obj
from crypto_utils import sign
from client_keys import read_pem
from templates import validate_and_build

def post(url: str, payload: dict) -> dict:
    data = stable_json(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=4) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", required=True)
    ap.add_argument("--maker", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--template", default="FUTURES_V1")
    ap.add_argument("--underlying", default="BTC")
    ap.add_argument("--side", required=True, choices=["LONG","SHORT"])
    ap.add_argument("--qty", type=int, required=True)
    ap.add_argument("--price", type=int, required=True)
    ap.add_argument("--expiry", type=int, default=3600)
    ap.add_argument("--collateral", type=int, required=True)
    args = ap.parse_args()

    base = args.node.rstrip("/")

    with urllib.request.urlopen(base + "/users", timeout=4) as r:
        users = json.loads(r.read().decode("utf-8"))["users"]
    maker = next((u for u in users if u["user_id"] == args.maker), None)
    if not maker:
        raise SystemExit(f"maker {args.maker} not registered on node (import users first)")

    terms = {
        "underlying": args.underlying,
        "side": args.side,
        "qty": args.qty,
        "price": args.price,
        "expiry_seconds": args.expiry,
        "collateral": args.collateral
    }

    version, built_terms, required = validate_and_build(args.template, terms)
    proposal_id = uuid.uuid4().hex

    canonical = {
        "proposal_id": proposal_id,
        "template_id": args.template,
        "version": version,
        "maker_user_id": args.maker,
        "maker_address": maker["address"],
        "maker_pubkey_b64": maker["pubkey_b64"],
        "terms": built_terms,
        "created_at": built_terms["created_at"],
        "expires_at": built_terms["expires_at"],
        "required_collateral": required,
    }
    payload_hash = hash_obj(canonical)

    sig = sign(read_pem(args.key), payload_hash.encode("utf-8"))

    req = {
        "proposal_id": proposal_id,
        "maker_user_id": args.maker,
        "template_id": args.template,
        "terms": terms,
        "payload_hash": payload_hash,
        "maker_signature_b64": sig,
    }

    res = post(base + "/propose", req)
    print(json.dumps(res))

if __name__ == "__main__":
    main()