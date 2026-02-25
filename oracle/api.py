"""
FastAPI routes for the price oracle.

Endpoints
---------
GET /health
    Liveness check; also returns the oracle public key.

GET /oracle/pubkey
    Returns the oracle's compressed secp256k1 public key (hex).
    Nodes hardcode this as the trust anchor for settlement verification.

GET /price/{symbol}
    Current signed price for any valid asset (fetched on demand).

GET /price/{symbol}/at/{timestamp}
    Signed price payload closest in time to the requested Unix timestamp.

Signed payload schema
---------------------
{
  "symbol":       "BTC",
  "price":        50123.45,
  "timestamp":    1700000000,
  "signature":    "3045...",   // DER-encoded secp256k1 ECDSA, hex
  "oracle_pubkey":"02abc..."   // compressed public key, hex
}
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import crypto
import db
import price_fetcher

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PricePayload(BaseModel):
    symbol: str
    price: float
    timestamp: int
    signature: str
    oracle_pubkey: str


class HealthResponse(BaseModel):
    status: str
    oracle_pubkey: str


class PubkeyResponse(BaseModel):
    pubkey: str
    curve: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_payload(symbol: str, price: float, timestamp: int) -> PricePayload:
    sig_hex, pubkey_hex = crypto.sign_price(symbol, price, timestamp)
    return PricePayload(
        symbol=symbol,
        price=price,
        timestamp=timestamp,
        signature=sig_hex,
        oracle_pubkey=pubkey_hex,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", oracle_pubkey=crypto.get_pubkey_hex())


@router.get("/oracle/pubkey", response_model=PubkeyResponse)
def oracle_pubkey() -> PubkeyResponse:
    return PubkeyResponse(pubkey=crypto.get_pubkey_hex(), curve="secp256k1")


@router.get("/price/{symbol}", response_model=PricePayload)
def latest_price(symbol: str) -> PricePayload:
    sym = symbol.upper()
    try:
        price, timestamp = price_fetcher.get_price(sym)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return _build_payload(sym, price, timestamp)


@router.get("/price/{symbol}/at/{timestamp}", response_model=PricePayload)
def price_at(symbol: str, timestamp: int) -> PricePayload:
    sym = symbol.upper()
    row = db.get_at_timestamp(sym, timestamp)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No historical price data available for {sym}.",
        )
    return _build_payload(sym, row["price"], row["timestamp"])
