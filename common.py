from __future__ import annotations
import json
import time
import hashlib
from typing import Any, Dict

def now_ts() -> int:
    return int(time.time())

def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def hash_obj(obj: Any) -> str:
    return sha256_hex(stable_json(obj).encode("utf-8"))

def ok(data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {"ok": True, **(data or {})}

def err(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"ok": False, "error": code, "message": message, **extra}