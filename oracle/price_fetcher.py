"""
On-demand price fetching module.

When a price is requested, the oracle checks its DB cache first. If the cached
entry is fresh enough (< CACHE_MAX_AGE seconds old), it's returned immediately.
Otherwise, the oracle fetches a live price from CryptoCompare (primary) or
Coinbase (fallback), stores it, and returns it.

Mock mode (MOCK_MODE=true):
  - Every symbol starts at MOCK_BASE_PRICE and random-walks on each fetch.
  - Set MOCK_SEED for deterministic sequences (useful in tests).
"""

import random
import time
from typing import Optional

import httpx

import db
from config import CACHE_MAX_AGE, MOCK_BASE_PRICE, MOCK_MODE, MOCK_SEED

# Mutable mock state: per-symbol prices that drift on each request
_mock_prices: dict[str, float] = {}
_rng: random.Random = random.Random(MOCK_SEED)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fetch_cryptocompare(symbol: str) -> Optional[float]:
    """Fetch a single symbol's USD price from CryptoCompare, or None on failure."""
    url = (
        f"https://min-api.cryptocompare.com/data/price?fsym={symbol.upper()}&tsyms=USD"
    )
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        if "USD" in data:
            return float(data["USD"])
        if "Response" in data and data["Response"] == "Error":
            print(
                f"[price_fetcher] CryptoCompare error for {symbol}: {data.get('Message')}"
            )
    except Exception as exc:
        print(f"[price_fetcher] CryptoCompare error for {symbol}: {exc}")
    return None


def _fetch_coinbase(symbol: str) -> Optional[float]:
    """Fetch a single symbol's USD price from Coinbase, or None on failure."""
    url = f"https://api.coinbase.com/v2/prices/{symbol.upper()}-USD/spot"
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        if "amount" in data:
            return float(data["amount"])
    except Exception as exc:
        print(f"[price_fetcher] Coinbase error for {symbol}: {exc}")
    return None


def _fetch_mock(symbol: str) -> float:
    """Return a random-walking mock price for *symbol*."""
    sym = symbol.upper()
    if sym not in _mock_prices:
        _mock_prices[sym] = MOCK_BASE_PRICE
    delta = _mock_prices[sym] * _rng.uniform(-0.005, 0.005)
    _mock_prices[sym] = round(_mock_prices[sym] + delta, 2)
    return _mock_prices[sym]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def get_price(symbol: str) -> tuple[float, int]:
    """
    Return (price, timestamp) for *symbol*.

    Uses a cached DB value if it's less than CACHE_MAX_AGE seconds old,
    otherwise fetches live.
    """
    sym = symbol.upper()
    now = int(time.time())

    # Check cache
    row = db.get_latest(sym)
    if row and (now - row["timestamp"]) < CACHE_MAX_AGE:
        return row["price"], row["timestamp"]

    # Fetch fresh price
    if MOCK_MODE:
        price = _fetch_mock(sym)
        source = "mock"
    else:
        price = _fetch_cryptocompare(sym)
        source = "cryptocompare"
        if price is None:
            print(
                f"[price_fetcher] CryptoCompare unavailable for {sym}, trying Coinbase..."
            )
            price = _fetch_coinbase(sym)
            source = "coinbase"
        if price is None:
            raise RuntimeError(f"All price sources failed for {sym}")

    db.insert_price(sym, price, now, source)
    print(f"[price_fetcher] {sym} = ${price} from {source} at {now}")
    return price, now
