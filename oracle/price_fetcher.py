"""
On-demand price fetching module.

When a price is requested, the oracle checks its DB cache first. If the cached
entry is fresh enough (< CACHE_MAX_AGE seconds old), it's returned immediately.
Otherwise, the oracle fetches a live price from CoinGecko (primary) or CoinCap
(fallback), stores it, and returns it.

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

# Maps ticker symbols (e.g. "BTC") to CoinGecko IDs (e.g. "bitcoin").
# Populated lazily on first use from CoinGecko's /coins/list endpoint.
_coingecko_id_map: dict[str, str] = {}
_coingecko_map_loaded: bool = False


# ---------------------------------------------------------------------------
# CoinGecko ID resolution
# ---------------------------------------------------------------------------


def _ensure_coingecko_map() -> None:
    """Fetch the full symbol→id mapping from CoinGecko once, then cache it."""
    global _coingecko_map_loaded
    if _coingecko_map_loaded:
        return
    url = "https://api.coingecko.com/api/v3/coins/list"
    try:
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
        for coin in resp.json():
            sym = coin.get("symbol", "").upper()
            cg_id = coin.get("id", "")
            # Keep the first mapping per symbol (CoinGecko lists the most
            # popular coins first in alphabetical order, but duplicates are
            # rare for major tickers like BTC/ETH/SOL).
            if sym and cg_id and sym not in _coingecko_id_map:
                _coingecko_id_map[sym] = cg_id
        _coingecko_map_loaded = True
        print(
            f"[price_fetcher] Loaded {len(_coingecko_id_map)} CoinGecko symbol mappings"
        )
    except Exception as exc:
        print(f"[price_fetcher] Failed to load CoinGecko coin list: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fetch_coingecko(symbol: str) -> Optional[float]:
    """Fetch a single symbol's USD price from CoinGecko, or None on failure."""
    _ensure_coingecko_map()
    cg_id = _coingecko_id_map.get(symbol.upper())
    if cg_id is None:
        print(f"[price_fetcher] No CoinGecko ID found for {symbol}")
        return None
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        if cg_id in data and "usd" in data[cg_id]:
            return float(data[cg_id]["usd"])
    except Exception as exc:
        print(f"[price_fetcher] CoinGecko error for {symbol}: {exc}")
    return None


def _fetch_coincap(symbol: str) -> Optional[float]:
    """Fetch a single symbol's USD price from CoinCap v2, or None on failure."""
    # CoinCap uses lowercase full names, but also supports searching by symbol.
    url = f"https://api.coincap.io/v2/assets?search={symbol.upper()}&limit=1"
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if data and data[0].get("symbol", "").upper() == symbol.upper():
            return float(data[0]["priceUsd"])
    except Exception as exc:
        print(f"[price_fetcher] CoinCap error for {symbol}: {exc}")
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
        price = _fetch_coingecko(sym)
        source = "coingecko"
        if price is None:
            print(f"[price_fetcher] CoinGecko unavailable for {sym}, trying CoinCap...")
            price = _fetch_coincap(sym)
            source = "coincap"
        if price is None:
            raise RuntimeError(f"All price sources failed for {sym}")

    db.insert_price(sym, price, now, source)
    print(f"[price_fetcher] {sym} = ${price} from {source} at {now}")
    return price, now
