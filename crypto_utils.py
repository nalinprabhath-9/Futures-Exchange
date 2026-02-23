from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

from common import stable_json, b64e, b64d


@dataclass(frozen=True)
class KeyPair:
    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey

    def public_key_hex(self) -> str:
        pk_bytes = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return pk_bytes.hex()

    def private_key_hex(self) -> str:
        sk_bytes = self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return sk_bytes.hex()

    @staticmethod
    def from_private_key_hex(sk_hex: str) -> "KeyPair":
        sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(sk_hex))
        return KeyPair(private_key=sk, public_key=sk.public_key())


def generate_keypair() -> KeyPair:
    sk = Ed25519PrivateKey.generate()
    return KeyPair(private_key=sk, public_key=sk.public_key())


def sign_payload(private_key: Ed25519PrivateKey, payload: Dict[str, Any]) -> str:
    msg = stable_json(payload).encode("utf-8")
    sig = private_key.sign(msg)
    return b64e(sig)


def verify_signature(public_key_hex: str, payload: Dict[str, Any], signature_b64: str) -> bool:
    try:
        pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        msg = stable_json(payload).encode("utf-8")
        pk.verify(b64d(signature_b64), msg)
        return True
    except Exception:
        return False