import os

MOCK_MODE: bool = os.environ.get("MOCK_MODE", "false").lower() in ("1", "true", "yes")
MOCK_SEED: int | None = (
    int(os.environ["MOCK_SEED"]) if "MOCK_SEED" in os.environ else None
)

# How long a cached price is considered fresh (seconds)
CACHE_MAX_AGE: int = int(os.environ.get("CACHE_MAX_AGE", "30"))

DB_PATH: str = os.environ.get("DB_PATH", "oracle.db")
KEY_PATH: str = os.environ.get("KEY_PATH", "oracle_privkey.hex")
PORT: int = int(os.environ.get("PORT", "8080"))

# Mock base price used for any symbol (USD).
# In mock mode, prices start here and random-walk on each request.
MOCK_BASE_PRICE: float = float(os.environ.get("MOCK_BASE_PRICE", "1000.0"))
