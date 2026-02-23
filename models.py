from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Literal

from common import now_unix, new_nonce, sha256_hex, stable_json


CoinSymbol = Literal["ZPH"]


@dataclass(frozen=True)
class Wallet:
    balances: Dict[CoinSymbol, int] = field(default_factory=lambda: {"ZPH": 0})

    def get(self, sym: CoinSymbol) -> int:
        return int(self.balances.get(sym, 0))


@dataclass(frozen=True)
class User:
    user_id: str
    public_key_hex: str
    # private key stays local (not stored here)


@dataclass(frozen=True)
class FuturesTemplate:
    template_id: str
    name: str
    # standardized fields for your futures contract
    underlying: str            # e.g. "BTC-USD"
    contract_size: float       # e.g. 1.0 BTC
    margin_rate: float         # e.g. 0.10 for 10%
    settlement: str            # "cash" (oracle) or "physical" (usually not in projects)
    oracle_symbol: str         # e.g. "BTCUSD"


@dataclass(frozen=True)
class TradeProposal:
    proposer_pubkey: str
    template_id: str
    side: Literal["LONG", "SHORT"]     # proposer’s side
    quantity: int                      # number of contracts
    entry_price: float                 # agreed entry price (or limit)
    expiry_unix: int                   # contract expiry timestamp

    created_at: int = field(default_factory=now_unix)
    nonce: str = field(default_factory=new_nonce)

    def id(self) -> str:
        payload = {
            "proposer_pubkey": self.proposer_pubkey,
            "template_id": self.template_id,
            "side": self.side,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "expiry_unix": self.expiry_unix,
            "created_at": self.created_at,
            "nonce": self.nonce,
        }
        return sha256_hex(stable_json(payload).encode("utf-8"))


@dataclass(frozen=True)
class SignedMessage:
    kind: Literal["PROPOSAL", "ACCEPT"]
    payload: Dict
    signer_pubkey: str
    signature_b64: str
    msg_id: str


@dataclass
class ProposalState:
    proposal: TradeProposal
    status: Literal["OPEN", "ACCEPTED", "CANCELLED", "EXPIRED"] = "OPEN"
    accepted_by_pubkey: Optional[str] = None
    accepted_at: Optional[int] = None


@dataclass(frozen=True)
class MatchedTrade:
    trade_id: str
    proposal_id: str
    long_pubkey: str
    short_pubkey: str
    template_id: str
    quantity: int
    entry_price: float
    expiry_unix: int
    state: Literal["AWAITING_DEPOSIT"] = "AWAITING_DEPOSIT"

    def required_collateral(self, template_margin_rate: float, contract_size: float) -> float:
        # Notional = entry_price * contract_size * quantity
        notional = self.entry_price * contract_size * self.quantity
        # Each side posts margin_rate * notional (simple model; you can change later)
        return template_margin_rate * notional