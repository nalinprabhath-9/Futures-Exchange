#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "ui"
INDEX_HTML = UI_DIR / "index.html"

# Assumes your python scripts live in the same folder as ui_server.py
SCRIPTS = {
    "deposit": str(ROOT / "deposit.py"),
    "lock": str(ROOT / "lock.py"),
    "propose": str(ROOT / "propose.py"),
    "accept": str(ROOT / "accept.py"),
    "mine": str(ROOT / "mine.py"),
}

DEFAULT_KEYSTORE = str(ROOT / "keystore")

def read_json_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    n = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(n) if n else b"{}"
    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return {}

def send_json(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    out = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(out)))
    handler.end_headers()
    handler.wfile.write(out)

def send_html(handler: BaseHTTPRequestHandler, status: int, html: str) -> None:
    out = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(out)))
    handler.end_headers()
    handler.wfile.write(out)

def http_forward(method: str, url: str, body: Optional[Dict[str, Any]] = None, timeout: float = 3.0) -> Tuple[int, Dict[str, Any]]:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            raw = resp.read().decode("utf-8") or "{}"
            try:
                return status, json.loads(raw)
            except Exception:
                return status, {"ok": True, "raw": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else ""
        try:
            return e.code, json.loads(raw) if raw else {"ok": False, "error": "http_error", "message": str(e)}
        except Exception:
            return e.code, {"ok": False, "error": "http_error", "message": str(e), "raw": raw}
    except Exception as e:
        return 502, {"ok": False, "error": "proxy_error", "message": str(e)}

def run_cli(args: list[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(
            [sys.executable] + args,
            cwd=cwd or str(ROOT),
            capture_output=True,
            text=True,
            check=False
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", f"failed_to_run: {e}"

class UIHandler(BaseHTTPRequestHandler):
    # ---- Static ----
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            if not INDEX_HTML.exists():
                send_html(self, 500, "<h1>Missing ui/index.html</h1>")
                return
            send_html(self, 200, INDEX_HTML.read_text(encoding="utf-8"))
            return

        # ---- Proxy: /api/<port>/<path...> ----
        if self.path.startswith("/api/"):
            # /api/5001/health  -> http://127.0.0.1:5001/health
            parts = self.path.split("/")
            if len(parts) < 4:
                send_json(self, 400, {"ok": False, "error": "bad_api_path"})
                return
            port = parts[2]
            rest = "/" + "/".join(parts[3:])
            target = f"http://127.0.0.1:{port}{rest}"
            status, payload = http_forward("GET", target, None)
            send_json(self, status, payload)
            return

        send_json(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        # ---- Proxy: /api/<port>/<path...> (POST) ----
        if self.path.startswith("/api/"):
            body = read_json_body(self)
            parts = self.path.split("/")
            if len(parts) < 4:
                send_json(self, 400, {"ok": False, "error": "bad_api_path"})
                return
            port = parts[2]
            rest = "/" + "/".join(parts[3:])
            target = f"http://127.0.0.1:{port}{rest}"
            status, payload = http_forward("POST", target, body)
            send_json(self, status, payload)
            return

        # ---- Actions: /action/<name> ----
        if self.path.startswith("/action/"):
            body = read_json_body(self)
            action = self.path.split("/action/")[1].split("?")[0]

            keystore = body.get("keystore") or DEFAULT_KEYSTORE
            node = body.get("node")  # e.g. http://127.0.0.1:5001
            if not node:
                send_json(self, 400, {"ok": False, "error": "missing_node"})
                return

            if action not in SCRIPTS:
                send_json(self, 404, {"ok": False, "error": "unknown_action"})
                return

            # Build CLI args
            if action == "deposit":
                user = body.get("user")
                amount = int(body.get("amount", 0))
                argv = [SCRIPTS["deposit"], "--node", node, "--user", user, "--amount", str(amount)]

            elif action == "lock":
                user = body.get("user")
                amount = int(body.get("amount", 0))
                argv = [SCRIPTS["lock"], "--node", node, "--user", user, "--amount", str(amount)]

            elif action == "propose":
                maker = body.get("maker")
                key = body.get("key") or str(Path(keystore) / f"{maker}.pem")
                template_id = body.get("template") or "FUTURES_V1"
                underlying = body.get("underlying") or "BTC"
                side = body.get("side")
                qty = int(body.get("qty", 0))
                price = int(body.get("price", 0))
                expiry = int(body.get("expiry", 3600))
                collateral = int(body.get("collateral", 0))
                argv = [
                    SCRIPTS["propose"],
                    "--node", node,
                    "--maker", maker,
                    "--key", key,
                    "--template", template_id,
                    "--underlying", underlying,
                    "--side", side,
                    "--qty", str(qty),
                    "--price", str(price),
                    "--expiry", str(expiry),
                    "--collateral", str(collateral),
                ]

            elif action == "accept":
                taker = body.get("taker")
                proposal_id = body.get("proposal_id")
                key = body.get("key") or str(Path(keystore) / f"{taker}.pem")
                argv = [
                    SCRIPTS["accept"],
                    "--node", node,
                    "--taker", taker,
                    "--key", key,
                    "--proposal", proposal_id,
                ]

            elif action == "mine":
                argv = [SCRIPTS["mine"], "--node", node]

            else:
                send_json(self, 400, {"ok": False, "error": "unsupported_action"})
                return

            rc, out, err = run_cli(argv)

            # out may be python-dict or json; try parse
            parsed = None
            if out:
                try:
                    parsed = json.loads(out)
                except Exception:
                    try:
                        import ast
                        parsed = ast.literal_eval(out)
                    except Exception:
                        parsed = {"raw": out}

            send_json(self, 200 if rc == 0 else 500, {
                "ok": (rc == 0),
                "returncode": rc,
                "stdout": out,
                "stderr": err,
                "parsed": parsed
            })
            return

        send_json(self, 404, {"ok": False, "error": "not_found"})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    if not INDEX_HTML.exists():
        print(f"[ui] Missing {INDEX_HTML}. Create ui/index.html first.")
        sys.exit(1)

    server = HTTPServer(("127.0.0.1", args.port), UIHandler)
    print(f"[ui] http://127.0.0.1:{args.port} (proxy + actions)")
    server.serve_forever()

if __name__ == "__main__":
    main()