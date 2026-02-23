import json, os, requests
from crypto_utils import KeyPair, sign_payload
from common import now_unix, new_nonce

NODE = os.environ.get("NODE", "http://127.0.0.1:5001")
USERS_FILE = os.environ.get("USERS_FILE", "users_5001.json")
ALIAS = os.environ.get("ALIAS", "User1")

TEMPLATE_ID = os.environ.get("TEMPLATE_ID", "BTCZPH-1")
SIDE = os.environ.get("SIDE", "LONG")
QTY = int(os.environ.get("QTY", "2"))
ENTRY_PRICE = float(os.environ.get("ENTRY_PRICE", "60000"))
EXPIRY_SECS = int(os.environ.get("EXPIRY_SECS", "3600"))

users = json.load(open(USERS_FILE))
u = next(x for x in users if x["alias"] == ALIAS)
kp = KeyPair.from_private_key_hex(u["private_key_hex"])
pub = kp.public_key_hex()

payload = {
    "proposer_pubkey": pub,
    "template_id": TEMPLATE_ID,
    "side": SIDE,
    "quantity": QTY,
    "entry_price": ENTRY_PRICE,
    "expiry_unix": now_unix() + EXPIRY_SECS,
    "created_at": now_unix(),
    "nonce": new_nonce(),
}
sig = sign_payload(kp.private_key, payload)

r = requests.post(f"{NODE}/propose", json={
    "payload": payload,
    "signer_pubkey": pub,
    "signature_b64": sig,
}, timeout=5)

print(r.status_code, r.json())