import hashlib
from ecdsa import SigningKey, VerifyingKey, SECP256k1
from ecdsa.util import sigencode_der, sigdecode_der


def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def ripemd160(b: bytes) -> bytes:
    h = hashlib.new("ripemd160")
    h.update(b)
    return h.digest()


def hash160(b: bytes) -> bytes:
    return ripemd160(sha256(b))


def get_signing_key_from_hex(priv_hex: str) -> SigningKey:
    """Create an ecdsa.SigningKey from 32-byte hex string."""
    raw = bytes.fromhex(priv_hex)
    if len(raw) != 32:
        raise ValueError("privkey_hex must be 32 bytes (64 hex chars)")
    return SigningKey.from_string(raw, curve=SECP256k1)


def get_compressed_pubkey(vk: VerifyingKey) -> bytes:
    """Compressed SEC format: 33 bytes (02/03 + x)."""
    point = vk.pubkey.point
    x = point.x()
    y = point.y()
    prefix = b"\x02" if (y % 2 == 0) else b"\x03"
    return prefix + x.to_bytes(32, "big")


def pubkey_to_address(compressed_pubkey: bytes) -> str:
    """
    Simple address for class project:
    use HASH160(pubkey) as hex string (40 chars).
    """
    return hash160(compressed_pubkey).hex()


def sign_message(sk: SigningKey, msg: bytes) -> bytes:
    """DER-encoded ECDSA signature over SHA256(msg)."""
    digest = sha256(msg)
    return sk.sign_digest(digest, sigencode=sigencode_der)


def verify_signature(pubkey_bytes: bytes, msg: bytes, signature: bytes) -> bool:
    """
    Verify signature given COMPRESSED pubkey bytes (33 bytes).
    """
    try:
        vk = VerifyingKey.from_string(_decompress_pubkey(pubkey_bytes), curve=SECP256k1)
        digest = sha256(msg)
        return vk.verify_digest(signature, digest, sigdecode=sigdecode_der)
    except Exception:
        return False


def _decompress_pubkey(comp: bytes) -> bytes:
    """
    Convert compressed SEC pubkey (33 bytes) to raw uncompressed point bytes (64 bytes: x||y).
    This is needed for VerifyingKey.from_string().
    """
    if len(comp) != 33 or comp[0] not in (2, 3):
        raise ValueError("invalid compressed pubkey")

    prefix = comp[0]
    x = int.from_bytes(comp[1:], "big")

    # secp256k1 field prime
    p = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
    # curve equation: y^2 = x^3 + 7 (mod p)
    y_sq = (pow(x, 3, p) + 7) % p
    y = pow(y_sq, (p + 1) // 4, p)  # since p % 4 == 3

    # choose the y with correct parity
    if (y % 2 == 0 and prefix == 3) or (y % 2 == 1 and prefix == 2):
        y = p - y

    return x.to_bytes(32, "big") + y.to_bytes(32, "big")