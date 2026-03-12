import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import os, secrets, json, requests
from ecdsa import SigningKey, SECP256k1
from node.crypto_utils import get_compressed_pubkey, pubkey_to_address

def gen_priv_hex() -> str:
    return secrets.token_hex(32)

def make_user(user_id: str):
    priv = gen_priv_hex()
    sk = SigningKey.from_string(bytes.fromhex(priv), curve=SECP256k1)
    pub = get_compressed_pubkey(sk.verifying_key)
    addr = pubkey_to_address(pub)
    return {"user_id": user_id, "privkey_hex": priv, "pubkey_hex": pub.hex(), "address": addr}

def main():
    nodes = os.environ.get("NODES", "http://localhost:5001,http://localhost:5002,http://localhost:5003").split(",")
    k = int(os.environ.get("USERS", "3"))
    users = [make_user(f"user{i}") for i in range(1, k+1)]

    for n in nodes:
        r = requests.post(f"{n}/admin/import_users", json={"users": users}, timeout=20)
        r.raise_for_status()
        print(n, r.json())

    with open("users.json", "w") as f:
        json.dump(users, f, indent=2)
    print("Wrote users.json")

if __name__ == "__main__":
    main()