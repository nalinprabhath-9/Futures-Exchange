import json, os, requests
from crypto_utils import KeyPair, sign_payload
from common import now_unix, new_nonce

NODE = os.environ.get("NODE", "http://127.0.0.1:5002")
USERS_FILE = os.environ.get("USERS_FILE", "users_5002.json")
ALIAS = os.environ.get("ALIAS", "User2")
PROPOSAL_ID = os.environ["PROPOSAL_ID"]

users = json.load(open(USERS_FILE))
u = next(x for x in users if x["alias"] == ALIAS)
kp = KeyPair.from_private_key_hex(u["private_key_hex"])
pub = kp.public_key_hex()

payload = {
    "proposal_id": PROPOSAL_ID,
    "accepted_at": now_unix(),
    "nonce": new_nonce(),
}
sig = sign_payload(kp.private_key, payload)

r = requests.post(f"{NODE}/accept", json={
    "payload": payload,
    "signer_pubkey": pub,
    "signature_b64": sig,
}, timeout=5)

print(r.status_code, r.json())