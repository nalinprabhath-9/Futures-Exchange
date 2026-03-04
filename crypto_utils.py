import hashlib
from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def get_signing_key_from_hex(priv_hex: str) -> SigningKey:
    return SigningKey.from_string(bytes.fromhex(priv_hex), curve=SECP256k1)


def get_verifying_key_from_bytes(pub_bytes: bytes) -> VerifyingKey:
    return VerifyingKey.from_string(pub_bytes, curve=SECP256k1)


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
            vk = get_verifying_key_from_bytes(pubkey_bytes)
            return vk.verify_digest(signature, digest)
        except BadSignatureError:
            return False
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
