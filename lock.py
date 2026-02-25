from __future__ import annotations
import argparse, json, urllib.request
from common import stable_json

def post(url: str, payload: dict) -> dict:
    data = stable_json(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=4) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--amount", type=int, required=True)
    args = ap.parse_args()
    print(post(args.node.rstrip("/") + "/lock", {"user_id": args.user, "amount": args.amount}))

if __name__ == "__main__":
    main()