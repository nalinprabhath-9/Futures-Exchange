from __future__ import annotations
import base64
from dataclasses import dataclass
from typing import Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")

def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))

def generate_keypair() -> Tuple[str, str]:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    pub_raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    pub_b64 = b64e(pub_raw)

    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    return priv_pem, pub_b64

def load_private_key_from_pem(pem_text: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem_text.encode("utf-8"), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Not an Ed25519 private key")
    return key

def load_public_key_from_b64(pub_b64: str) -> Ed25519PublicKey:
    raw = b64d(pub_b64)
    return Ed25519PublicKey.from_public_bytes(raw)

def sign(priv_pem: str, message: bytes) -> str:
    priv = load_private_key_from_pem(priv_pem)
    sig = priv.sign(message)
    return b64e(sig)

def verify(pub_b64: str, message: bytes, sig_b64: str) -> bool:
    try:
        pub = load_public_key_from_b64(pub_b64)
        pub.verify(b64d(sig_b64), message)
        return True
    except Exception:
        return False

@dataclass(frozen=True)
class Identity:
    user_id: str
    address: str
    pubkey_b64: str