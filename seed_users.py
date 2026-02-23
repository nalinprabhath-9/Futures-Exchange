import json, os, sqlite3
from crypto_utils import generate_keypair
from templates import COIN_DECIMALS
from common import now_unix
from db import init_db

PORT = int(os.environ.get("PORT", "5001"))
DB_PATH = os.environ.get("DB_PATH", f"node_{PORT}.db")
OUTFILE = os.environ.get("OUTFILE", f"users_{PORT}.json")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys=ON;")
conn.execute("PRAGMA journal_mode=WAL;")
init_db(conn)

ts = now_unix()
users_out = []
for i in range(5):
    kp = generate_keypair()
    pub = kp.public_key_hex()
    priv = kp.private_key_hex()
    alias = f"User{i+1}"

    conn.execute(
        "INSERT OR IGNORE INTO users(pubkey, alias, created_at) VALUES (?, ?, ?)",
        (pub, alias, ts),
    )
    conn.execute(
        "INSERT OR IGNORE INTO wallets(pubkey, balance_sats, reserved_sats, created_at) VALUES (?, ?, 0, ?)",
        (pub, int(200000 * COIN_DECIMALS), ts),
    )

    users_out.append({"alias": alias, "pubkey": pub, "private_key_hex": priv})

conn.commit()
conn.close()

with open(OUTFILE, "w") as f:
    json.dump(users_out, f, indent=2)

print(f"Seeded 5 users into {DB_PATH} and wrote keys to {OUTFILE}")