"""
Oracle keypair management and price signing.

Signing protocol (for node verification):
  message = SHA256(symbol_bytes + price_str_bytes + timestamp_str_bytes)
  signature = secp256k1 ECDSA sign(message), DER-encoded

Both signature and public key are returned as lowercase hex strings.
The oracle public key (compressed, 33 bytes) is the trust anchor hardcoded into nodes.
"""

import hashlib
import os

import coincurve

from config import KEY_PATH

_private_key: coincurve.PrivateKey | None = None


def _load_or_generate_key() -> coincurve.PrivateKey:
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "r") as f:
            raw_hex = f.read().strip()
        key = coincurve.PrivateKey(bytes.fromhex(raw_hex))
        print(f"[crypto] Loaded existing private key from {KEY_PATH}")
    else:
        key = coincurve.PrivateKey()
        with open(KEY_PATH, "w") as f:
            f.write(key.secret.hex())
        print(f"[crypto] Generated new private key, saved to {KEY_PATH}")
    return key


def init_keypair() -> None:
    """Load or generate the oracle keypair. Must be called before signing."""
    global _private_key
    _private_key = _load_or_generate_key()
    pubkey_hex = get_pubkey_hex()
    print(f"[crypto] Oracle public key (trust anchor): {pubkey_hex}")


def get_pubkey_hex() -> str:
    """Return the compressed 33-byte public key as a lowercase hex string."""
    if _private_key is None:
        raise RuntimeError("Keypair not initialised; call init_keypair() first.")
    return _private_key.public_key.format(compressed=True).hex()


def _build_message(symbol: str, price: float, timestamp: int) -> bytes:
    """
    Canonical message bytes used for signing.

    Format: SHA256( symbol_utf8 || price_str_utf8 || timestamp_str_utf8 )
    Price is formatted with up to 8 decimal places, trailing zeros stripped.
    """
    price_str = f"{price:.8f}".rstrip("0").rstrip(".")
    raw = symbol.encode() + price_str.encode() + str(timestamp).encode()
    return hashlib.sha256(raw).digest()


def sign_price(symbol: str, price: float, timestamp: int) -> tuple[str, str]:
    """
    Sign a price observation.

    Returns:
        (signature_hex, pubkey_hex)
        signature_hex: DER-encoded secp256k1 ECDSA signature, lowercase hex
        pubkey_hex:    compressed public key, lowercase hex
    """
    if _private_key is None:
        raise RuntimeError("Keypair not initialised; call init_keypair() first.")
    msg = _build_message(symbol, price, timestamp)
    sig_der = _private_key.sign(msg, hasher=None)
    return sig_der.hex(), get_pubkey_hex()


def verify_price(
    symbol: str,
    price: float,
    timestamp: int,
    signature_hex: str,
    pubkey_hex: str,
) -> bool:
    """
    Verify a signed price payload.  Useful for testing and CLI tools.
    """
    msg = _build_message(symbol, price, timestamp)
    pub = coincurve.PublicKey(bytes.fromhex(pubkey_hex))
    sig = bytes.fromhex(signature_hex)
    return pub.verify(sig, msg, hasher=None)
