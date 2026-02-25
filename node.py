from __future__ import annotations
import argparse
import json
import uuid
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

from common import stable_json, hash_obj, now_ts, ok, err
from crypto_utils import verify
import templates
import db as dbm

MAX_TX_PER_BLOCK = 2  # set low for testing; change to 100+ for normal use

def http_post_json(url: str, payload: Dict[str, Any], timeout: float = 1.5) -> Optional[Dict[str, Any]]:
    data = stable_json(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return None

class NodeState:
    def __init__(self, db_path: str, peers: List[str]):
        self.con = dbm.connect(db_path)
        dbm.init_db(self.con)
        self.peers = [p.rstrip("/") for p in peers if p.strip()]

        height, _ = dbm.get_tip(self.con)
        if height == -1:
            genesis = self._make_block("GENESIS", [{
                "tx_id": "GENESIS",
                "tx_type": "GENESIS",
                "payload": {"note": "genesis"},
                "created_at": now_ts()
            }])
            dbm.add_block(self.con, genesis)

    def _make_block(self, prev_hash: str, txs: List[Dict[str, Any]]) -> Dict[str, Any]:
        height, tip_hash = dbm.get_tip(self.con)
        if prev_hash != tip_hash and prev_hash != "GENESIS":
            prev_hash = tip_hash
        b = {"height": height + 1, "prev_hash": prev_hash, "ts": now_ts(), "txs": txs, "nonce": 0}
        b["block_hash"] = hash_obj({"height": b["height"], "prev_hash": b["prev_hash"], "ts": b["ts"], "txs": b["txs"], "nonce": b["nonce"]})
        b["txs_json"] = stable_json(b["txs"])
        return b

    # Setup
    def import_users_from_json(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for u in data["users"]:
            dbm.upsert_user(self.con, u)
        return ok({"imported": len(data["users"])})

    def health(self) -> Dict[str, Any]:
        h, tip = dbm.get_tip(self.con)
        return ok({"tip_height": h, "tip_hash": tip, "peers": self.peers})

    def list_templates(self) -> Dict[str, Any]:
        return ok({"templates": templates.list_templates()})

    def list_users(self) -> Dict[str, Any]:
        return ok({"users": dbm.list_users(self.con)})

    # Wallet
    def balance(self, address: str) -> Dict[str, Any]:
        b = dbm.get_balance(self.con, address)
        return ok({"address": address, **b, "available": b["balance"] - b["locked"]})

    def faucet_deposit(self, user_id: str, amount: int) -> Dict[str, Any]:
        if amount <= 0:
            return err("invalid_amount", "amount must be > 0")
        u = dbm.get_user(self.con, user_id)
        if not u:
            return err("unknown_user", f"user {user_id} not found")
        dbm.credit(self.con, u["address"], amount)
        return ok({"credited": amount, "address": u["address"], "balance": dbm.get_balance(self.con, u["address"])})

    def lock(self, user_id: str, amount: int) -> Dict[str, Any]:
        if amount <= 0:
            return err("invalid_amount", "amount must be > 0")
        u = dbm.get_user(self.con, user_id)
        if not u:
            return err("unknown_user", f"user {user_id} not found")
        if not dbm.lock_collateral(self.con, u["address"], amount):
            b = dbm.get_balance(self.con, u["address"])
            return err("insufficient_funds", "not enough available funds", balance=b, available=b["balance"] - b["locked"])
        return ok({"locked": amount, "address": u["address"], "balance": dbm.get_balance(self.con, u["address"])})

    # Canonical payloads
    def _canonical_proposal_payload(self, maker: Dict[str, Any], proposal_id: str, template_id: str, version: int,
                                   built_terms: Dict[str, Any], required_collateral: int) -> Dict[str, Any]:
        return {
            "proposal_id": proposal_id,
            "template_id": template_id,
            "version": int(version),
            "maker_user_id": maker["user_id"],
            "maker_address": maker["address"],
            "maker_pubkey_b64": maker["pubkey_b64"],
            "terms": built_terms,
            "created_at": int(built_terms["created_at"]),
            "expires_at": int(built_terms["expires_at"]),
            "required_collateral": int(required_collateral),
        }

    def _canonical_accept_payload(self, taker: Dict[str, Any], proposal_id: str, accepted_at: int) -> Dict[str, Any]:
        return {
            "proposal_id": proposal_id,
            "taker_user_id": taker["user_id"],
            "taker_address": taker["address"],
            "taker_pubkey_b64": taker["pubkey_b64"],
            "accepted_at": int(accepted_at),
        }

    # Proposal
    def propose(self, req: Dict[str, Any]) -> Dict[str, Any]:
        maker_user_id = req.get("maker_user_id", "")
        template_id = req.get("template_id", "")
        terms = req.get("terms", {})
        maker_sig = req.get("maker_signature_b64", "")
        payload_hash = req.get("payload_hash", "")
        proposal_id = req.get("proposal_id") or uuid.uuid4().hex

        maker = dbm.get_user(self.con, maker_user_id)
        if not maker:
            return err("unknown_user", f"maker {maker_user_id} not found")

        try:
            version, built_terms, required_collateral = templates.validate_and_build(template_id, terms)
        except templates.TemplateError as e:
            return err("invalid_template", str(e))

        canonical = self._canonical_proposal_payload(maker, proposal_id, template_id, version, built_terms, required_collateral)
        expected_hash = hash_obj(canonical)

        if expected_hash != payload_hash:
            return err("bad_hash", "payload_hash mismatch", expected=expected_hash)

        if not verify(maker["pubkey_b64"], expected_hash.encode("utf-8"), maker_sig):
            return err("bad_signature", "maker signature invalid")

        row = {
            "proposal_id": proposal_id,
            "template_id": template_id,
            "version": int(version),
            "maker_user_id": maker_user_id,
            "maker_address": maker["address"],
            "maker_pubkey_b64": maker["pubkey_b64"],
            "terms_json": stable_json(built_terms),
            "created_at": int(built_terms["created_at"]),
            "expires_at": int(built_terms["expires_at"]),
            "required_collateral": int(required_collateral),
            "payload_hash": expected_hash,
            "maker_signature_b64": maker_sig,
            "status": "OPEN",
        }

        if not dbm.insert_proposal(self.con, row):
            return err("duplicate", "proposal already exists")

        for peer in self.peers:
            http_post_json(f"{peer}/gossip/proposal", row)

        return ok({"proposal_id": proposal_id, "payload_hash": expected_hash})

    def receive_proposal(self, row: Dict[str, Any]) -> Dict[str, Any]:
        maker = dbm.get_user(self.con, row.get("maker_user_id", ""))
        if not maker:
            return err("unknown_maker", "maker not registered on this node")
        if maker["pubkey_b64"] != row.get("maker_pubkey_b64", ""):
            return err("pubkey_mismatch", "maker pubkey mismatch")

        built_terms = json.loads(row["terms_json"]) if isinstance(row.get("terms_json"), str) else row.get("terms", {})
        canonical = self._canonical_proposal_payload(
            maker=maker,
            proposal_id=row["proposal_id"],
            template_id=row["template_id"],
            version=int(row["version"]),
            built_terms=built_terms,
            required_collateral=int(row["required_collateral"])
        )
        expected_hash = hash_obj(canonical)
        if expected_hash != row.get("payload_hash", ""):
            return err("bad_hash", "proposal hash mismatch")

        if not verify(maker["pubkey_b64"], expected_hash.encode("utf-8"), row.get("maker_signature_b64", "")):
            return err("bad_signature", "proposal signature invalid")

        if now_ts() >= int(row["expires_at"]):
            row["status"] = "EXPIRED"

        dbm.insert_proposal(self.con, row)
        return ok({"stored": True})

    # Acceptance
    def accept(self, req: Dict[str, Any]) -> Dict[str, Any]:
        taker_user_id = req.get("taker_user_id", "")
        proposal_id = req.get("proposal_id", "")
        taker_sig = req.get("taker_signature_b64", "")
        payload_hash = req.get("payload_hash", "")
        accepted_at = int(req.get("accepted_at") or now_ts())

        taker = dbm.get_user(self.con, taker_user_id)
        if not taker:
            return err("unknown_user", f"taker {taker_user_id} not found")

        p = dbm.get_proposal(self.con, proposal_id)
        if not p:
            return err("unknown_proposal", "proposal not found")

        if p["status"] != "OPEN":
            return err("not_open", f"status={p['status']}")

        if now_ts() >= int(p["expires_at"]):
            dbm.set_proposal_status(self.con, proposal_id, "EXPIRED")
            return err("expired", "proposal expired")

        if dbm.get_acceptance(self.con, proposal_id):
            return err("already_accepted", "proposal already accepted")

        required = int(p["required_collateral"])
        bal = dbm.get_balance(self.con, taker["address"])
        if bal["locked"] < required:
            return err("insufficient_collateral", "lock more collateral before accepting", locked=bal["locked"], required=required)

        canonical_accept = self._canonical_accept_payload(taker, proposal_id, accepted_at)
        expected_hash = hash_obj(canonical_accept)
        if expected_hash != payload_hash:
            return err("bad_hash", "accept payload hash mismatch", expected=expected_hash)

        if not verify(taker["pubkey_b64"], expected_hash.encode("utf-8"), taker_sig):
            return err("bad_signature", "taker signature invalid")

        arow = {**canonical_accept, "payload_hash": expected_hash, "taker_signature_b64": taker_sig}
        if not dbm.insert_acceptance(self.con, arow):
            return err("already_accepted", "acceptance exists")

        dbm.set_proposal_status(self.con, proposal_id, "ACCEPTED")

        # Build AGREEMENT tx and store in local mempool
        terms = json.loads(p["terms_json"])
        tx_id = uuid.uuid4().hex
        tx_payload = {
            "proposal_id": proposal_id,

            "template_id": p["template_id"],
            "version": int(p["version"]),
            "terms": terms,
            "created_at": int(p["created_at"]),
            "expires_at": int(p["expires_at"]),
            "required_collateral": int(p["required_collateral"]),

            "maker_user_id": p["maker_user_id"],
            "maker_address": p["maker_address"],
            "maker_pubkey_b64": p["maker_pubkey_b64"],
            "maker_signature_b64": p["maker_signature_b64"],
            "proposal_payload_hash": p["payload_hash"],

            "taker_user_id": taker_user_id,
            "taker_address": taker["address"],
            "taker_pubkey_b64": taker["pubkey_b64"],
            "accepted_at": accepted_at,
            "taker_signature_b64": taker_sig,
            "accept_payload_hash": expected_hash,
        }

        dbm.add_mempool_tx(self.con, {
            "tx_id": tx_id,
            "tx_type": "AGREEMENT",
            "payload_json": stable_json(tx_payload),
            "created_at": accepted_at
        })

        # Gossip acceptance/status + tx to peers (Option B)
        for peer in self.peers:
            http_post_json(f"{peer}/gossip/acceptance", arow)
            http_post_json(f"{peer}/gossip/proposal_status", {"proposal_id": proposal_id, "status": "ACCEPTED"})
            http_post_json(f"{peer}/gossip/tx", {"tx_id": tx_id, "tx_type": "AGREEMENT", "payload": tx_payload, "created_at": accepted_at})

        return ok({"proposal_id": proposal_id, "agreement_tx_id": tx_id})

    def receive_acceptance(self, row: Dict[str, Any]) -> Dict[str, Any]:
        taker = dbm.get_user(self.con, row.get("taker_user_id", ""))
        if not taker:
            return err("unknown_taker", "taker not registered")
        if taker["pubkey_b64"] != row.get("taker_pubkey_b64", ""):
            return err("pubkey_mismatch", "taker pubkey mismatch")

        canonical = self._canonical_accept_payload(taker, row["proposal_id"], int(row["accepted_at"]))
        expected_hash = hash_obj(canonical)
        if expected_hash != row.get("payload_hash", ""):
            return err("bad_hash", "acceptance hash mismatch")
        if not verify(taker["pubkey_b64"], expected_hash.encode("utf-8"), row.get("taker_signature_b64", "")):
            return err("bad_signature", "acceptance signature invalid")

        dbm.insert_acceptance(self.con, row)
        if dbm.get_proposal(self.con, row["proposal_id"]):
            dbm.set_proposal_status(self.con, row["proposal_id"], "ACCEPTED")
        return ok({"stored": True})

    def update_proposal_status(self, proposal_id: str, status: str) -> Dict[str, Any]:
        p = dbm.get_proposal(self.con, proposal_id)
        if not p:
            return ok({"ignored": True})
        cur = p["status"]
        if cur == "OPEN" and status in ("ACCEPTED", "EXPIRED", "CANCELLED"):
            dbm.set_proposal_status(self.con, proposal_id, status)
        return ok({"updated": True})

    # TX gossip validation
    def _validate_agreement_tx(self, tx_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        required_fields = [
            "proposal_id","template_id","version","terms","created_at","expires_at","required_collateral",
            "maker_user_id","maker_address","maker_pubkey_b64","maker_signature_b64","proposal_payload_hash",
            "taker_user_id","taker_address","taker_pubkey_b64","accepted_at","taker_signature_b64","accept_payload_hash"
        ]
        for f in required_fields:
            if f not in tx_payload:
                return {"code": "missing_field", "message": f"tx missing {f}"}

        maker = dbm.get_user(self.con, tx_payload["maker_user_id"])
        if not maker:
            return {"code": "unknown_maker", "message": "maker not registered"}
        if maker["pubkey_b64"] != tx_payload["maker_pubkey_b64"]:
            return {"code": "pubkey_mismatch", "message": "maker pubkey mismatch"}

        canonical_proposal = {
            "proposal_id": tx_payload["proposal_id"],
            "template_id": tx_payload["template_id"],
            "version": int(tx_payload["version"]),
            "maker_user_id": tx_payload["maker_user_id"],
            "maker_address": tx_payload["maker_address"],
            "maker_pubkey_b64": tx_payload["maker_pubkey_b64"],
            "terms": tx_payload["terms"],
            "created_at": int(tx_payload["created_at"]),
            "expires_at": int(tx_payload["expires_at"]),
            "required_collateral": int(tx_payload["required_collateral"]),
        }
        proposal_hash = hash_obj(canonical_proposal)
        if proposal_hash != tx_payload["proposal_payload_hash"]:
            return {"code": "bad_proposal_hash", "message": "proposal hash mismatch"}
        if not verify(maker["pubkey_b64"], proposal_hash.encode("utf-8"), tx_payload["maker_signature_b64"]):
            return {"code": "bad_maker_sig", "message": "maker signature invalid"}

        taker = dbm.get_user(self.con, tx_payload["taker_user_id"])
        if not taker:
            return {"code": "unknown_taker", "message": "taker not registered"}
        if taker["pubkey_b64"] != tx_payload["taker_pubkey_b64"]:
            return {"code": "pubkey_mismatch", "message": "taker pubkey mismatch"}

        canonical_accept = {
            "proposal_id": tx_payload["proposal_id"],
            "taker_user_id": tx_payload["taker_user_id"],
            "taker_address": tx_payload["taker_address"],
            "taker_pubkey_b64": tx_payload["taker_pubkey_b64"],
            "accepted_at": int(tx_payload["accepted_at"]),
        }
        accept_hash = hash_obj(canonical_accept)
        if accept_hash != tx_payload["accept_payload_hash"]:
            return {"code": "bad_accept_hash", "message": "acceptance hash mismatch"}
        if not verify(taker["pubkey_b64"], accept_hash.encode("utf-8"), tx_payload["taker_signature_b64"]):
            return {"code": "bad_taker_sig", "message": "taker signature invalid"}

        if int(tx_payload["accepted_at"]) >= int(tx_payload["expires_at"]):
            return {"code": "expired", "message": "accepted after expiry"}

        if int(tx_payload["required_collateral"]) != int(tx_payload["terms"].get("collateral", -1)):
            return {"code": "bad_collateral", "message": "required_collateral != terms.collateral"}

        return None

    def receive_tx(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        tx_id = tx.get("tx_id", "")
        tx_type = tx.get("tx_type", "")
        created_at = int(tx.get("created_at", 0))
        payload = tx.get("payload", {})

        if not tx_id or tx_type != "AGREEMENT" or not isinstance(payload, dict):
            return err("bad_tx", "invalid tx format")

        v = self._validate_agreement_tx(payload)
        if v is not None:
            return err(v["code"], v["message"])

        added = dbm.add_mempool_tx(self.con, {
            "tx_id": tx_id,
            "tx_type": tx_type,
            "payload_json": stable_json(payload),
            "created_at": created_at or int(payload["accepted_at"]),
        })

        return ok({"stored": True, "already_present": (not added)})

    # Mining (capacity enforced at mining time)
    def mine(self) -> Dict[str, Any]:
        mp = dbm.list_mempool(self.con)
        if not mp:
            return err("empty_mempool", "no transactions to mine")

        selected = mp[:MAX_TX_PER_BLOCK]
        selected_ids: List[str] = []
        txs: List[Dict[str, Any]] = []

        for r in selected:
            selected_ids.append(r["tx_id"])
            txs.append({
                "tx_id": r["tx_id"],
                "tx_type": r["tx_type"],
                "payload": json.loads(r["payload_json"]),
                "created_at": int(r["created_at"])
            })

        _, tip = dbm.get_tip(self.con)
        b = self._make_block(tip, txs)
        dbm.add_block(self.con, b)

        dbm.delete_mempool_txs(self.con, selected_ids)

        remaining = len(mp) - len(selected)
        return ok({
            "mined_height": b["height"],
            "block_hash": b["block_hash"],
            "included_txs": len(selected),
            "remaining_in_mempool": remaining,
            "capacity": MAX_TX_PER_BLOCK
        })

    # Views
    def proposals(self) -> Dict[str, Any]:
        return ok({"open": dbm.list_open_proposals(self.con)})

    def mempool(self) -> Dict[str, Any]:
        return ok({"mempool": dbm.list_mempool(self.con)})

    def chain(self, limit: int) -> Dict[str, Any]:
        return ok({"blocks": dbm.get_chain(self.con, limit=limit)})

class Handler(BaseHTTPRequestHandler):
    state: NodeState

    def _read_json(self) -> Dict[str, Any]:
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _send(self, status: int, payload: Dict[str, Any]) -> None:
        out = stable_json(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self._send(200, self.state.health()); return
        if path == "/templates":
            self._send(200, self.state.list_templates()); return
        if path == "/users":
            self._send(200, self.state.list_users()); return
        if path.startswith("/balance/"):
            addr = path.split("/balance/")[1]
            self._send(200, self.state.balance(addr)); return
        if path == "/proposals":
            self._send(200, self.state.proposals()); return
        if path == "/mempool":
            self._send(200, self.state.mempool()); return
        if path.startswith("/chain"):
            limit = 50
            if "?" in self.path and "limit=" in self.path:
                try: limit = int(self.path.split("limit=")[1].split("&")[0])
                except: pass
            self._send(200, self.state.chain(limit)); return
        self._send(404, err("not_found", "unknown route"))

    def do_POST(self):
        path = self.path
        body = self._read_json()

        if path == "/import_users":
            try:
                res = self.state.import_users_from_json(body["path"])
                self._send(200, res)
            except Exception as e:
                self._send(400, err("bad_request", str(e)))
            return

        if path == "/deposit":
            res = self.state.faucet_deposit(body.get("user_id",""), int(body.get("amount",0)))
            self._send(200 if res["ok"] else 409, res); return

        if path == "/lock":
            res = self.state.lock(body.get("user_id",""), int(body.get("amount",0)))
            self._send(200 if res["ok"] else 409, res); return

        if path == "/propose":
            res = self.state.propose(body)
            self._send(200 if res["ok"] else 400, res); return

        if path == "/accept":
            res = self.state.accept(body)
            self._send(200 if res["ok"] else 409, res); return

        if path == "/mine":
            res = self.state.mine()
            self._send(200 if res["ok"] else 409, res); return

        if path == "/gossip/proposal":
            res = self.state.receive_proposal(body)
            self._send(200 if res["ok"] else 400, res); return

        if path == "/gossip/acceptance":
            res = self.state.receive_acceptance(body)
            self._send(200 if res["ok"] else 400, res); return

        if path == "/gossip/proposal_status":
            res = self.state.update_proposal_status(body.get("proposal_id",""), body.get("status",""))
            self._send(200, res); return

        if path == "/gossip/tx":
            res = self.state.receive_tx(body)
            self._send(200 if res["ok"] else 400, res); return

        self._send(404, err("not_found", "unknown route"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--db", type=str, required=True)
    ap.add_argument("--peers", type=str, default="")
    args = ap.parse_args()

    peers = [p.strip() for p in args.peers.split(",") if p.strip()]
    state = NodeState(args.db, peers)

    Handler.state = state
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[node] http://127.0.0.1:{args.port} db={args.db} peers={peers}")
    server.serve_forever()

if __name__ == "__main__":
    main()