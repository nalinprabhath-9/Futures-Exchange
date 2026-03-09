from enum import Enum

class TransactionType(Enum):
    COINBASE = "coinbase"
    TRANSFER = "transfer"

    PROPOSE_TRADE = "propose_trade"
    ACCEPT_TRADE = "accept_trade"
    DEPOSIT_COLLATERAL = "deposit_collateral"  
    SETTLE_TRADE = "settle_trade"

    CANCEL_PROPOSAL = "cancel_proposal"
    CANCEL_TRADE = "cancel_trade"

class TradeState(Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    COLLATERAL_LOCKED = "collateral_locked"
    ACTIVE = "active"
    SETTLED = "settled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

class TemplateType(Enum):
    UP_DOWN = "up_down"
    LONG_SHORT = "long_short"
    RANGE = "range"