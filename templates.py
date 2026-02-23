from __future__ import annotations

COIN_SYMBOL = "ZPH"       # Zephyr
COIN_DECIMALS = 10**8     # integer smallest units

DEFAULT_TEMPLATES = {
    "BTCZPH-1": {
        "template_id": "BTCZPH-1",
        "name": "BTC Cash-Settled Futures (10% margin)",
        "underlying": "BTC-USD",
        "contract_size": 1.0,
        "margin_rate": 0.10,
        "settlement": "cash",
        "oracle_symbol": "BTCUSD",
    },
    "ETHZPH-1": {
        "template_id": "ETHZPH-1",
        "name": "ETH Cash-Settled Futures (12% margin)",
        "underlying": "ETH-USD",
        "contract_size": 1.0,
        "margin_rate": 0.12,
        "settlement": "cash",
        "oracle_symbol": "ETHUSD",
    },
}


def required_collateral_sats(template: dict, entry_price: float, quantity: int) -> int:
    """
    notional = entry_price * contract_size * quantity
    required = margin_rate * notional
    return in sats (int)
    """
    notional = float(entry_price) * float(template["contract_size"]) * int(quantity)
    required = float(template["margin_rate"]) * notional
    sats = int(round(required * COIN_DECIMALS))
    return max(sats, 0)