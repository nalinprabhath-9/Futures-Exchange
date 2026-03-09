import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from flask import Flask, Response, jsonify, request, send_file

BASE_DIR = Path(__file__).resolve().parent
INDEX_HTML = BASE_DIR / "ui/index.html"
USERS_JSON = BASE_DIR / "users.json"

app = Flask(__name__)

DEFAULT_TIMEOUT = 20


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def ok(**kwargs):
    payload = {"ok": True}
    payload.update(kwargs)
    return jsonify(payload)


def err(message: str, code: int = 400, **kwargs):
    payload = {"ok": False, "error": message}
    payload.update(kwargs)
    return jsonify(payload), code


def read_users() -> list[dict[str, Any]]:
    if not USERS_JSON.exists():
        return []
    return json.loads(USERS_JSON.read_text())


def get_user(user_id: str) -> Optional[dict[str, Any]]:
    for u in read_users():
        if u.get("user_id") == user_id:
            return u
    return None


def normalize_node_url(node: str) -> str:
    node = node.strip()
    if not node.startswith("http://") and not node.startswith("https://"):
        node = f"http://{node}"
    return node.rstrip("/")


def proxy_request(method: str, url: str, *, json_body: Optional[dict] = None):
    return requests.request(method, url, json=json_body, timeout=DEFAULT_TIMEOUT)


def run_python_snippet(code: str, env: Optional[dict[str, str]] = None) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["python", "-c", code],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        env=merged_env,
    )


# ---------------------------------------------------------
# UI page
# ---------------------------------------------------------

@app.get("/")
def index():
    if not INDEX_HTML.exists():
        return err(f"index.html not found at {INDEX_HTML}", 404)
    return send_file(INDEX_HTML)


# ---------------------------------------------------------
# Generic API proxy
# UI calls /api/<port>/<path> and we forward to node
# Example: /api/5001/health -> http://127.0.0.1:5001/health
# ---------------------------------------------------------

@app.route("/api/<port>/<path:subpath>", methods=["GET", "POST"])
def api_proxy(port: str, subpath: str):
    target = f"http://127.0.0.1:{port}/{subpath}"
    if request.query_string:
        target += f"?{request.query_string.decode()}"

    try:
        if request.method == "GET":
            r = requests.get(target, timeout=DEFAULT_TIMEOUT)
        else:
            body = request.get_json(silent=True)
            r = requests.post(target, json=body, timeout=DEFAULT_TIMEOUT)

        return Response(
            r.content,
            status=r.status_code,
            content_type=r.headers.get("Content-Type", "application/json"),
        )
    except requests.RequestException as e:
        return err(f"proxy failed to {target}: {e}", 502)


# ---------------------------------------------------------
# Action endpoints used by the UI
# These are convenience wrappers around your existing code.
# ---------------------------------------------------------

@app.post("/action/propose")
def action_propose():
    """
    UI sends:
    {
      node: "http://127.0.0.1:5001",
      maker: "user1",
      template: "FUTURES_V1",
      underlying: "BTC",
      side: "LONG",
      qty: 1,
      price: 45000,
      expiry: 3600,
      collateral: 200
    }

    This endpoint:
    - finds maker in users.json
    - builds signed propose tx using node.blockchain.create_propose_trade_transaction()
    - submits it to /tx/submit on the target node
    """
    body = request.get_json(force=True)

    node = normalize_node_url(body.get("node", ""))
    maker_id = body.get("maker")
    underlying = body.get("underlying", "BTC")
    side = body.get("side", "LONG")
    qty = body.get("qty", 1)
    price = body.get("price", 45000)
    expiry_seconds = int(body.get("expiry", 3600))
    collateral = int(body.get("collateral", 200))

    if not node or not maker_id:
        return err("missing node or maker")

    maker = get_user(maker_id)
    if not maker:
        return err(f"user not found in users.json: {maker_id}", 404)

    # UI collateral is often entered in whole coins; backend tx helper expects milli
    collateral_milli = collateral * 1000

    code = f"""
import json, time, requests
from node.blockchain import create_propose_trade_transaction
from node.transaction_enums import TemplateType
from node.tx_codec import futures_tx_to_wire

trade_id = f"P{{int(time.time())}}"
template_type = TemplateType.UP_DOWN

tx = create_propose_trade_transaction(
    trade_id=trade_id,
    party_a={maker["address"]!r},
    template_type=template_type,
    asset_pair={f"{underlying}/USD"!r},
    strike_price={price},
    expiry_hours={expiry_seconds}/3600,
    collateral_amount={collateral_milli},
    privkey_hex={maker["privkey_hex"]!r},
    high_priority=True,
)

wire = futures_tx_to_wire(tx)
resp = requests.post({node + "/tx/submit"!r}, json={{"tx": wire}}, timeout=20)

print(json.dumps({{
    "proposal_id": trade_id,
    "tx_dict": tx.to_dict(),
    "submit_status": resp.status_code,
    "submit_json": resp.json()
}}))
"""
    cp = run_python_snippet(code)
    if cp.returncode != 0:
        return jsonify({
            "ok": False,
            "stdout": cp.stdout,
            "stderr": cp.stderr
        }), 500

    try:
        parsed = json.loads(cp.stdout.strip())
    except Exception:
        return jsonify({
            "ok": False,
            "stdout": cp.stdout,
            "stderr": cp.stderr,
            "error": "failed to parse propose result"
        }), 500

    submit_json = parsed.get("submit_json", {})
    if not submit_json.get("ok"):
        return jsonify({
            "ok": False,
            "parsed": parsed,
            "stdout": cp.stdout,
            "stderr": cp.stderr
        }), 400

    return jsonify({
        "ok": True,
        "parsed": parsed,
        "stdout": cp.stdout,
        "stderr": cp.stderr
    })


@app.post("/action/accept")
def action_accept():
    """
    UI sends:
    {
      node: "http://127.0.0.1:5002",
      proposal_id: "P123...",
      taker: "user2"
    }

    This creates and signs ACCEPT_TRADE and submits it.
    """
    body = request.get_json(force=True)

    node = normalize_node_url(body.get("node", ""))
    proposal_id = body.get("proposal_id")
    taker_id = body.get("taker")

    if not node or not proposal_id or not taker_id:
        return err("missing node, proposal_id, or taker")

    taker = get_user(taker_id)
    if not taker:
        return err(f"user not found in users.json: {taker_id}", 404)

    code = f"""
import json, requests
from node.blockchain import create_accept_trade_transaction
from node.tx_codec import futures_tx_to_wire

tx = create_accept_trade_transaction(
    trade_id={proposal_id!r},
    party_b={taker["address"]!r},
    privkey_hex={taker["privkey_hex"]!r},
    high_priority=True,
)

wire = futures_tx_to_wire(tx)
resp = requests.post({node + "/tx/submit"!r}, json={{"tx": wire}}, timeout=20)

print(json.dumps({{
    "agreement_tx_id": tx.TransactionHash,
    "tx_dict": tx.to_dict(),
    "submit_status": resp.status_code,
    "submit_json": resp.json()
}}))
"""
    cp = run_python_snippet(code)
    if cp.returncode != 0:
        return jsonify({
            "ok": False,
            "stdout": cp.stdout,
            "stderr": cp.stderr
        }), 500

    try:
        parsed = json.loads(cp.stdout.strip())
    except Exception:
        return jsonify({
            "ok": False,
            "stdout": cp.stdout,
            "stderr": cp.stderr,
            "error": "failed to parse accept result"
        }), 500

    submit_json = parsed.get("submit_json", {})
    if not submit_json.get("ok"):
        return jsonify({
            "ok": False,
            "parsed": parsed,
            "stdout": cp.stdout,
            "stderr": cp.stderr
        }), 400

    return jsonify({
        "ok": True,
        "parsed": parsed,
        "stdout": cp.stdout,
        "stderr": cp.stderr
    })


@app.post("/action/mine")
def action_mine():
    """
    UI sends:
    {
      node: "http://127.0.0.1:5001"
    }

    This just forwards to /mine on that node.
    """
    body = request.get_json(force=True)
    node = normalize_node_url(body.get("node", ""))

    if not node:
        return err("missing node")

    try:
        r = requests.post(f"{node}/mine", json={}, timeout=DEFAULT_TIMEOUT)
        data = r.json()
        return jsonify({
            "ok": bool(data.get("ok", False)),
            "parsed": data,
            "stdout": "",
            "stderr": ""
        }), (200 if data.get("ok") else 400)
    except requests.RequestException as e:
        return err(f"mine request failed: {e}", 502)


@app.post("/action/deposit")
def action_deposit():
    """
    UI sends:
    {
      node: "http://127.0.0.1:5001",
      user: "user1",
      amount: 500
    }

    Amount is treated as whole coins from the UI.
    This forwards to your node funding endpoint.

    Adjust this if your backend uses /faucet instead of /admin/fund.
    """
    body = request.get_json(force=True)

    node = normalize_node_url(body.get("node", ""))
    user_id = body.get("user")
    amount = int(body.get("amount", 0))

    if not node or not user_id:
      return err("missing node or user")

    user = get_user(user_id)
    if not user:
        return err(f"user not found in users.json: {user_id}", 404)

    amount_milli = amount * 1000

    # Try /admin/fund first, then /faucet fallback
    endpoints = [
        (f"{node}/admin/fund", {"address": user["address"], "amount_milli": amount_milli}),
        (f"{node}/faucet", {"user_id": user_id, "amount": amount_milli}),
    ]

    last_error = None
    for url, payload in endpoints:
        try:
            r = requests.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
            try:
                data = r.json()
            except Exception:
                data = {"raw": r.text}

            if r.ok and data.get("ok", True):
                return jsonify({"ok": True, "parsed": data})
            last_error = {"status": r.status_code, "data": data, "url": url}
        except requests.RequestException as e:
            last_error = {"error": str(e), "url": url}

    return jsonify({"ok": False, "parsed": last_error}), 400


@app.post("/action/lock")
def action_lock():
    """
    Optional helper.
    If your backend has no explicit lock endpoint, this returns a friendly message.
    """
    body = request.get_json(force=True)
    node = normalize_node_url(body.get("node", ""))
    user_id = body.get("user")
    amount = int(body.get("amount", 0))

    if not node or not user_id:
        return err("missing node or user")

    user = get_user(user_id)
    if not user:
        return err(f"user not found in users.json: {user_id}", 404)

    amount_milli = amount * 1000

    # If you later implement /admin/lock, this will work.
    try:
        r = requests.post(
            f"{node}/admin/lock",
            json={"address": user["address"], "amount_milli": amount_milli},
            timeout=DEFAULT_TIMEOUT
        )
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}

        if r.ok and data.get("ok", True):
            return jsonify({"ok": True, "parsed": data})

        return jsonify({
            "ok": False,
            "parsed": data,
            "error": "lock endpoint returned failure"
        }), 400
    except requests.RequestException:
        return jsonify({
            "ok": False,
            "error": "lock endpoint not implemented in backend"
        }), 400


# ---------------------------------------------------------
# Startup
# ---------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)