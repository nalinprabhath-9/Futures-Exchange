from typing import Dict, Any
from node.transaction_enums import TransactionType, TemplateType, TradeState
from node.blockchain import FuturesTransaction

def futures_tx_to_wire(tx: FuturesTransaction) -> Dict[str, Any]:
    d = tx.to_dict()
    # signature/pubkey are bytes in your object; store as hex for JSON transport
    d["signature_hex"] = tx.signature.hex() if getattr(tx, "signature", None) else None
    d["pubkey_hex"] = tx.pubkey.hex() if getattr(tx, "pubkey", None) else None
    return d

def futures_tx_from_wire(d: Dict[str, Any]) -> FuturesTransaction:
    sig_hex = d.get("signature_hex")
    pub_hex = d.get("pubkey_hex")

    tx = FuturesTransaction(
        trade_id=d["trade_id"],
        tx_type=TransactionType(d["tx_type"]),
        party_a=d.get("party_a"),
        party_b=d.get("party_b"),
        template_type=TemplateType(d["template_type"]) if d.get("template_type") else None,
        asset_pair=d.get("asset_pair"),
        strike_price=d.get("strike_price"),
        expiry_timestamp=d.get("expiry_timestamp"),
        collateral_amount=d.get("collateral_amount"),
        state=TradeState(d.get("state", TradeState.PROPOSED.value)),
        settlement_price=d.get("settlement_price"),
        winner=d.get("winner"),
        winner_payout=d.get("winner_payout"),
        loser_payout=d.get("loser_payout"),
        fee=d.get("fee"),
        signature=bytes.fromhex(sig_hex) if sig_hex else None,
        pubkey=bytes.fromhex(pub_hex) if pub_hex else None,
    )
    return tx