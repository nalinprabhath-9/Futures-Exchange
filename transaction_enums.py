"""
Transaction Enums for Futures Exchange
- Defines enums for transaction types, trade states, and template types used in the futures exchange blockchain
- Used to standardize transaction handling and state management across the blockchain implementation
"""

from enum import Enum

class TransactionType(Enum):
    """Types of transactions in our blockchain"""
    COINBASE = "coinbase"      # Mining reward
    TRANSFER = "transfer"      # Send coins between users
    PROPOSE_TRADE = "propose_trade"
    ACCEPT_TRADE = "accept_trade"
    DEPOSIT_COLLATERAL = "deposit_collateral"
    SETTLE_TRADE = "settle_trade"
    CANCEL_TRADE = "cancel_trade"

class TradeState(Enum):
    """States a futures trade can be in"""
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    COLLATERAL_LOCKED = "collateral_locked"
    ACTIVE = "active"
    SETTLED = "settled"
    CANCELLED = "cancelled"

class TemplateType(Enum):
    """Types of futures templates"""
    UP_DOWN = "up_down"           # Binary: price goes up or down
    LONG_SHORT = "long_short"     # Proportional payout based on price movement
    RANGE = "range"               # Price stays within range