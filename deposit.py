import json, os, requests
from crypto_utils import KeyPair, sign_payload
from common import now_unix, new_nonce

NODE = os.environ.get("NODE", "http://127.0.0.1:5001")
USERS_FILE = os.environ.get("USERS_FILE", "users_5001.json")
ALIAS = os.environ.get("ALIAS", "User1")

TRADE_ID = os.environ["TRADE_ID"]
AMOUNT_SATS = int(os.environ["AMOUNT_SATS"])

users = json.load(open(USERS_FILE))
u = next(x for x in users if x["alias"] == ALIAS)
kp = KeyPair.from_private_key_hex(u["private_key_hex"])
pub = kp.public_key_hex()

payload = {
    "trade_id": TRADE_ID,
    "amount_sats": AMOUNT_SATS,
    "created_at": now_unix(),
    "nonce": new_nonce(),
}
sig = sign_payload(kp.private_key, payload)

r = requests.post(f"{NODE}/deposit", json={
    "payload": payload,
    "signer_pubkey": pub,
    "signature_b64": sig,
}, timeout=5)

print(r.status_code, r.json())