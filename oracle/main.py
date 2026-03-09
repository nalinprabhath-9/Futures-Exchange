"""
Oracle service entrypoint.

Startup sequence:
  1. Initialise SQLite database (create schema if absent).
  2. Load or generate the secp256k1 keypair.
  3. Start the FastAPI server with uvicorn.

Prices are fetched on demand when requested, not polled on a timer.
"""

import uvicorn
from fastapi import FastAPI

import crypto
import db
from api import router
from config import DB_PATH, PORT

app = FastAPI(
    title="Blockchain Futures Oracle",
    description=(
        "Signs real-time and historical asset prices with secp256k1 ECDSA. "
        "The oracle public key is the trust anchor used by blockchain nodes "
        "to validate trade settlement transactions."
    ),
    version="1.0.0",
)
app.include_router(router)


def startup() -> None:
    db.init_db(DB_PATH)
    crypto.init_keypair()


if __name__ == "__main__":
    startup()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
