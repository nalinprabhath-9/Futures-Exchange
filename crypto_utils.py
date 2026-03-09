import hashlib
from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError
import coincurve


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def get_signing_key_from_hex(priv_hex: str) -> SigningKey:
    return SigningKey.from_string(bytes.fromhex(priv_hex), curve=SECP256k1)


def get_verifying_key_from_bytes(pub_bytes: bytes) -> VerifyingKey:
    """
    Accepts a compressed (33-byte) or uncompressed (64/65-byte) secp256k1 public key.
    Returns an ecdsa.VerifyingKey object.
    """
    if len(pub_bytes) == 33:
        # Decompress using coincurve
        pubkey = coincurve.PublicKey(pub_bytes)
        uncompressed = pubkey.format(compressed=False)[1:]  # Remove 0x04 prefix
        return VerifyingKey.from_string(uncompressed, curve=SECP256k1)
    elif len(pub_bytes) == 64:
        return VerifyingKey.from_string(pub_bytes, curve=SECP256k1)
    elif len(pub_bytes) == 65 and pub_bytes[0] == 0x04:
        return VerifyingKey.from_string(pub_bytes[1:], curve=SECP256k1)
    else:
        raise ValueError("Invalid public key length for secp256k1")


def get_compressed_pubkey(vk: VerifyingKey) -> bytes:
    x = vk.pubkey.point.x()
    y = vk.pubkey.point.y()
    prefix = b'\x02' if y % 2 == 0 else b'\x03'
    return prefix + x.to_bytes(32, 'big')


def sign_message(sk: SigningKey, message: bytes) -> bytes:
    return sk.sign_deterministic(message, hashfunc=hashlib.sha256)


def verify_signature(pubkey_bytes: bytes, message: bytes, signature: bytes) -> bool:
    try:
        vk = get_verifying_key_from_bytes(pubkey_bytes)
        return vk.verify(signature, message, hashfunc=hashlib.sha256)
    except BadSignatureError:
        return False
    except Exception:
        return False
    
def verify_oracle_signature(pubkey_bytes: bytes, digest: bytes, signature: bytes) -> bool:
    try:
        # Use coincurve for direct secp256k1 signature verification (DER-encoded signature, compressed pubkey)
        # This matches the oracle's signing and verification logic exactly.
        pubkey = coincurve.PublicKey(pubkey_bytes)
        # coincurve expects bytes, signature is DER, digest is 32 bytes
        return pubkey.verify(signature, digest, hasher=None)
    except Exception:
        return False


# def _build_message(symbol: str, price: float, timestamp: int) -> bytes:
#     """
#     Canonical message bytes used for signing.

#     Format: SHA256( symbol_utf8 || price_str_utf8 || timestamp_str_utf8 )
#     Price is formatted with up to 8 decimal places, trailing zeros stripped.
#     """
#     price_str = f"{price:.8f}".rstrip("0").rstrip(".")
#     raw = symbol.encode() + price_str.encode() + str(timestamp).encode()
#     return hashlib.sha256(raw).digest()


# def sign_price(symbol: str, price: float, timestamp: int) -> tuple[str, str]:
#     """
#     Sign a price observation.

#     Returns:
#         (signature_hex, pubkey_hex)
#         signature_hex: DER-encoded secp256k1 ECDSA signature, lowercase hex
#         pubkey_hex:    compressed public key, lowercase hex
#     """
#     if _private_key is None:
#         raise RuntimeError("Keypair not initialised; call init_keypair() first.")
#     msg = _build_message(symbol, price, timestamp)
#     sig_der = _private_key.sign(msg, hasher=None)
#     return sig_der.hex(), get_pubkey_hex()
