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
