import os
import time
import requests
from crypto_utils import KeyPair, sign_payload
from common import now_unix, new_nonce

NODE = os.environ.get("NODE", "http://127.0.0.1:5002")
PROPOSAL_ID = os.environ["PROPOSAL_ID"]
PRIVATE_KEY_HEX = os.environ["PRIVATE_KEY_HEX"]

kp = KeyPair.from_private_key_hex(PRIVATE_KEY_HEX)
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