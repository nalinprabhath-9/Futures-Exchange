from __future__ import annotations

import os
import sqlite3
from typing import Dict, Any, List, Tuple

import requests
from flask import Flask, request, jsonify

from common import stable_json, sha256_hex, now_unix
from crypto_utils import verify_signature
from templates import DEFAULT_TEMPLATES, required_collateral_sats, COIN_SYMBOL, COIN_DECIMALS
import db as dbmod


def compute_msg_id(kind: str, payload: Dict[str, Any], signer_pubkey: str, signature_b64: str) -> str:
    base = stable_json({
        "kind": kind,
        "payload": payload,
        "signer_pubkey": signer_pubkey,
        "signature_b64": signature_b64,
    }).encode("utf-8")
    return sha256_hex(base)


def ok(data: Dict[str, Any], status: int = 200) -> Tuple[Dict[str, Any], int]:
    return data, status


def err(message: str, status: int) -> Tuple[Dict[str, Any], int]:
    return {"ok": False, "error": message}, status


def create_app(db_path: str, peers: List[str]) -> Flask:
    app = Flask(__name__)
    conn = dbmod.connect(db_path)
    dbmod.init_db(conn)

    def broadcast(msg: Dict[str, Any]) -> None:
        for peer in peers:
            try:
                requests.post(f"{peer}/ingest", json=msg, timeout=1.5)
            except Exception:
                pass

    def require_fields(obj: Dict[str, Any], fields: List[str]) -> None:
        for f in fields:
            if f not in obj:
                raise ValueError(f"missing field: {f}")

    def ensure_user(pubkey: str) -> None:
        if not dbmod.user_exists(conn, pubkey):
            raise LookupError("unknown user pubkey (seed users first)")

    def process_message(msg: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        try:
            require_fields(msg, ["kind", "payload", "signer_pubkey", "signature_b64"])
            kind = msg["kind"]
            payload = msg["payload"]
            signer = msg["signer_pubkey"]
            sig = msg["signature_b64"]

            if kind not in ("PROPOSAL", "ACCEPT", "DEPOSIT"):
                return err("invalid kind", 400)
            if not isinstance(payload, dict):
                return err("payload must be an object", 400)

            if not verify_signature(signer, payload, sig):
                return err("bad signature", 401)

            msg_id = compute_msg_id(kind, payload, signer, sig)

            with conn:
                if dbmod.has_seen_msg(conn, msg_id):
                    return ok({"ok": True, "duplicate": True, "msg_id": msg_id})
                dbmod.mark_seen_msg(conn, msg_id)

            if kind == "PROPOSAL":
                return handle_proposal(payload, signer, sig, msg_id)
            if kind == "ACCEPT":
                return handle_accept(payload, signer, sig, msg_id)
            return handle_deposit(payload, signer, sig, msg_id)

        except ValueError as e:
            return err(str(e), 400)
        except LookupError as e:
            return err(str(e), 404)
        except PermissionError as e:
            return err(str(e), 409)
        except Exception as e:
            return err(f"internal error: {e}", 500)

    def handle_proposal(payload: Dict[str, Any], signer: str, sig: str, msg_id: str) -> Tuple[Dict[str, Any], int]:
        require_fields(payload, [
            "proposer_pubkey", "template_id", "side", "quantity",
            "entry_price", "expiry_unix", "created_at", "nonce"
        ])

        proposer = str(payload["proposer_pubkey"])
        ensure_user(proposer)
        if proposer != signer:
            return err("signer does not match proposer_pubkey", 401)

        template_id = str(payload["template_id"])
        if template_id not in DEFAULT_TEMPLATES:
            return err("unknown template_id", 400)

        side = str(payload["side"])
        if side not in ("LONG", "SHORT"):
            return err("side must be LONG or SHORT", 400)

        quantity = int(payload["quantity"])
        if quantity <= 0:
            return err("quantity must be > 0", 400)

        entry_price = float(payload["entry_price"])
        if entry_price <= 0:
            return err("entry_price must be > 0", 400)

        expiry_unix = int(payload["expiry_unix"])
        if expiry_unix <= now_unix():
            return err("proposal already expired", 409)

        proposal_id = sha256_hex(stable_json(payload).encode("utf-8"))

        row = dict(payload)
        row["proposal_id"] = proposal_id
        row["signature_b64"] = sig

        try:
            dbmod.insert_proposal(conn, row)
        except sqlite3.IntegrityError:
            # idempotent duplicates: same proposal_id or (proposer, nonce)
            pass

        dbmod.add_notification(conn, proposer, "PROPOSED", f"Proposal created: {proposal_id}")
        broadcast({
            "kind": "PROPOSAL",
            "payload": payload,
            "signer_pubkey": signer,
            "signature_b64": sig,
        })
        return ok({"ok": True, "msg_id": msg_id, "proposal_id": proposal_id})

    def handle_accept(payload: Dict[str, Any], signer: str, sig: str, msg_id: str) -> Tuple[Dict[str, Any], int]:
        require_fields(payload, ["proposal_id", "accepted_at", "nonce"])
        ensure_user(signer)

        proposal_id = str(payload["proposal_id"])
        prop = dbmod.get_proposal(conn, proposal_id)
        if not prop:
            return err("proposal not found", 404)

        if prop["status"] != "OPEN":
            return err(f"proposal not OPEN (status={prop['status']})", 409)

        if int(prop["expiry_unix"]) <= now_unix():
            with conn:
                dbmod.mark_proposal_status(conn, proposal_id, "EXPIRED")
            return err("proposal expired", 409)

        proposer = str(prop["proposer_pubkey"])
        if signer == proposer:
            return err("cannot accept your own proposal", 409)

        template_id = str(prop["template_id"])
        template = DEFAULT_TEMPLATES[template_id]
        req_sats = required_collateral_sats(template, float(prop["entry_price"]), int(prop["quantity"]))

        # Reserve for acceptor
        try:
            with conn:
                dbmod.reserve_sats(conn, signer, req_sats)
        except PermissionError:
            with conn:
                dbmod.add_notification(conn, signer, "ACCEPT_REJECTED",
                                       f"Insufficient collateral to accept. Need {req_sats} sats.")
            return err("insufficient collateral to accept", 409)

        # Reserve for proposer too (prevents stuck trades)
        try:
            with conn:
                dbmod.reserve_sats(conn, proposer, req_sats)
        except PermissionError:
            with conn:
                dbmod.release_reserve_sats(conn, signer, req_sats)
                dbmod.add_notification(conn, signer, "ACCEPT_REJECTED",
                                       "Proposer lacks collateral; cannot match trade.")
                dbmod.add_notification(conn, proposer, "ACCEPT_FAILED",
                                       "Someone tried to accept, but you lack collateral.")
            return err("proposer insufficient collateral", 409)

        acceptance_id = sha256_hex(stable_json({
            "proposal_id": proposal_id,
            "acceptor": signer,
            "nonce": str(payload["nonce"]),
        }).encode("utf-8"))

        # Determine long/short
        if str(prop["side"]) == "LONG":
            long_pk, short_pk = proposer, signer
        else:
            long_pk, short_pk = signer, proposer

        trade_id = sha256_hex(stable_json({
            "proposal_id": proposal_id,
            "long_pk": long_pk,
            "short_pk": short_pk,
            "template_id": template_id,
            "proposal_nonce": str(prop["nonce"]),
        }).encode("utf-8"))

        try:
            with conn:
                dbmod.insert_acceptance(conn, {
                    "acceptance_id": acceptance_id,
                    "proposal_id": proposal_id,
                    "acceptor_pubkey": signer,
                    "accepted_at": int(payload["accepted_at"]),
                    "nonce": str(payload["nonce"]),
                    "signature_b64": sig,
                })
                dbmod.mark_proposal_status(conn, proposal_id, "ACCEPTED")
                dbmod.insert_trade(conn, {
                    "trade_id": trade_id,
                    "proposal_id": proposal_id,
                    "template_id": template_id,
                    "long_pubkey": long_pk,
                    "short_pubkey": short_pk,
                    "quantity": int(prop["quantity"]),
                    "entry_price": float(prop["entry_price"]),
                    "expiry_unix": int(prop["expiry_unix"]),
                    "required_collateral_sats": req_sats,
                    "state": "AWAITING_DEPOSIT",
                })
                dbmod.add_notification(conn, proposer, "PROPOSAL_ACCEPTED",
                                       f"Proposal {proposal_id} accepted. Trade {trade_id} created.")
                dbmod.add_notification(conn, signer, "ACCEPTED",
                                       f"You accepted proposal {proposal_id}. Trade {trade_id} created.")
        except sqlite3.IntegrityError:
            # idempotent if already accepted/created
            pass

        broadcast({
            "kind": "ACCEPT",
            "payload": payload,
            "signer_pubkey": signer,
            "signature_b64": sig,
        })
        return ok({"ok": True, "msg_id": msg_id, "trade_id": trade_id})

    def handle_deposit(payload: Dict[str, Any], signer: str, sig: str, msg_id: str) -> Tuple[Dict[str, Any], int]:
        require_fields(payload, ["trade_id", "amount_sats", "nonce", "created_at"])
        ensure_user(signer)

        trade_id = str(payload["trade_id"])
        amount = int(payload["amount_sats"])
        if amount <= 0:
            return err("amount_sats must be > 0", 400)

        trade = dbmod.get_trade(conn, trade_id)
        if not trade:
            return err("trade not found", 404)

        if int(trade["expiry_unix"]) <= now_unix():
            return err("trade expired; cannot deposit", 409)

        if trade["state"] not in ("AWAITING_DEPOSIT", "PARTIALLY_DEPOSITED"):
            return err(f"cannot deposit in state {trade['state']}", 409)

        if signer not in (trade["long_pubkey"], trade["short_pubkey"]):
            return err("only trade participants can deposit", 403)

        required = int(trade["required_collateral_sats"])
        already = dbmod.get_escrow(conn, trade_id, signer)
        remaining = max(required - already, 0)

        if remaining == 0:
            return err("already fully deposited", 409)

        # avoid over-deposit
        if amount > remaining:
            return err(f"deposit exceeds remaining (remaining={remaining})", 409)

        deposit_id = sha256_hex(stable_json({
            "trade_id": trade_id,
            "depositor": signer,
            "nonce": str(payload["nonce"]),
        }).encode("utf-8"))

        try:
            with conn:
                dbmod.deduct_balance_and_reduce_reserve(conn, signer, amount)
                conn.execute(
                    """
                    INSERT INTO deposits(deposit_id, trade_id, depositor_pubkey, amount_sats, created_at, nonce, signature_b64)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (deposit_id, trade_id, signer, amount, int(payload["created_at"]), str(payload["nonce"]), sig),
                )
                dbmod.add_escrow(conn, trade_id, signer, amount)

                long_dep = dbmod.get_escrow(conn, trade_id, str(trade["long_pubkey"]))
                short_dep = dbmod.get_escrow(conn, trade_id, str(trade["short_pubkey"]))

                if long_dep >= required and short_dep >= required:
                    dbmod.set_trade_state(conn, trade_id, "BOTH_DEPOSITED", "both_sides_deposited")
                    dbmod.add_notification(conn, str(trade["long_pubkey"]), "DEPOSIT_OK", f"Trade {trade_id}: BOTH_DEPOSITED.")
                    dbmod.add_notification(conn, str(trade["short_pubkey"]), "DEPOSIT_OK", f"Trade {trade_id}: BOTH_DEPOSITED.")
                else:
                    dbmod.set_trade_state(conn, trade_id, "PARTIALLY_DEPOSITED", "one_side_deposited")
                    dbmod.add_notification(conn, signer, "DEPOSIT_OK", f"Trade {trade_id}: deposit recorded ({amount} sats).")

        except sqlite3.IntegrityError:
            dbmod.add_notification(conn, signer, "DEPOSIT_REJECTED", "Duplicate deposit (nonce reuse).")
            return err("duplicate deposit (nonce reuse)", 409)
        except PermissionError as e:
            dbmod.add_notification(conn, signer, "DEPOSIT_REJECTED", str(e))
            return err(str(e), 409)

        broadcast({
            "kind": "DEPOSIT",
            "payload": payload,
            "signer_pubkey": signer,
            "signature_b64": sig,
        })
        return ok({"ok": True, "msg_id": msg_id, "deposit_id": deposit_id})

    # -------------------- routes --------------------

    @app.get("/templates")
    def templates():
        return jsonify(DEFAULT_TEMPLATES)

    @app.get("/users")
    def users():
        rows = conn.execute("SELECT pubkey, alias, created_at FROM users ORDER BY created_at ASC").fetchall()
        return jsonify([dict(r) for r in rows])

    @app.get("/wallet/<pubkey>")
    def wallet(pubkey: str):
        if not dbmod.user_exists(conn, pubkey):
            return jsonify({"ok": False, "error": "unknown user"}), 404
        bal, res = dbmod.get_wallet(conn, pubkey)
        return jsonify({
            "coin": COIN_SYMBOL,
            "decimals": COIN_DECIMALS,
            "balance_sats": bal,
            "reserved_sats": res,
            "available_sats": bal - res,
        })

    @app.get("/notifications/<pubkey>")
    def notifications(pubkey: str):
        if not dbmod.user_exists(conn, pubkey):
            return jsonify({"ok": False, "error": "unknown user"}), 404
        return jsonify(dbmod.list_notifications(conn, pubkey))

    @app.get("/proposals")
    def proposals():
        return jsonify(dbmod.list_proposals(conn))

    @app.get("/trades")
    def trades():
        return jsonify(dbmod.list_trades(conn))

    @app.post("/ingest")
    def ingest():
        msg = request.get_json(force=True)
        data, status = process_message(msg)
        return jsonify(data), status

    # convenience: these just set kind and run process_message
    @app.post("/propose")
    def propose():
        msg = request.get_json(force=True)
        msg["kind"] = "PROPOSAL"
        data, status = process_message(msg)
        return jsonify(data), status

    @app.post("/accept")
    def accept():
        msg = request.get_json(force=True)
        msg["kind"] = "ACCEPT"
        data, status = process_message(msg)
        return jsonify(data), status

    @app.post("/deposit")
    def deposit():
        msg = request.get_json(force=True)
        msg["kind"] = "DEPOSIT"
        data, status = process_message(msg)
        return jsonify(data), status

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    peers_raw = os.environ.get("PEERS", "")
    peers = [p.strip() for p in peers_raw.split(",") if p.strip()]
    db_path = os.environ.get("DB_PATH", f"node_{port}.db")

    app = create_app(db_path=db_path, peers=peers)
    app.run(host="0.0.0.0", port=port, debug=True)