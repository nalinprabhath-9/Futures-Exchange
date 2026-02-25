from __future__ import annotations
from typing import Any, Dict, Tuple
from common import now_ts

class TemplateError(Exception):
    pass

TEMPLATES: Dict[str, Dict[str, Any]] = {
    "FUTURES_V1": {
        "version": 1,
        "required_fields": ["underlying", "side", "qty", "price", "expiry_seconds", "collateral"],
        "side_values": ["LONG", "SHORT"],
        "min_qty": 1,
        "min_price": 1,
        "min_collateral": 1,
        "max_expiry_seconds": 7 * 24 * 3600,
    }
}

def list_templates() -> Dict[str, Any]:
    return {k: {"version": v["version"], "required_fields": v["required_fields"]} for k, v in TEMPLATES.items()}

def validate_and_build(template_id: str, terms: Dict[str, Any]) -> Tuple[int, Dict[str, Any], int]:
    if template_id not in TEMPLATES:
        raise TemplateError(f"unknown_template:{template_id}")

    spec = TEMPLATES[template_id]
    for f in spec["required_fields"]:
        if f not in terms:
            raise TemplateError(f"missing_field:{f}")

    underlying = str(terms["underlying"]).upper()
    side = str(terms["side"]).upper()
    qty = int(terms["qty"])
    price = int(terms["price"])
    expiry_seconds = int(terms["expiry_seconds"])
    collateral = int(terms["collateral"])

    if side not in spec["side_values"]:
        raise TemplateError("invalid_side")
    if qty < spec["min_qty"]:
        raise TemplateError("qty_too_small")
    if price < spec["min_price"]:
        raise TemplateError("price_too_small")
    if collateral < spec["min_collateral"]:
        raise TemplateError("collateral_too_small")
    if expiry_seconds <= 0 or expiry_seconds > spec["max_expiry_seconds"]:
        raise TemplateError("invalid_expiry_seconds")

    created_at = now_ts()
    expires_at = created_at + expiry_seconds

    built = {
        "underlying": underlying,
        "side": side,
        "qty": qty,
        "price": price,
        "collateral": collateral,
        "created_at": created_at,
        "expires_at": expires_at,
    }
    required_collateral = collateral
    return spec["version"], built, required_collateral