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
    CANCEL_PROPOSAL = "cancel_proposal"        # party_a withdraws an unaccepted proposal
    SETTLE_TRADE = "settle_trade"
    CANCEL_TRADE = "cancel_trade"              # Mutual cancellation of an active trade (requires both signatures)

class TradeState(Enum):
    """States a futures trade can be in"""
    PROPOSED = "proposed"
    ACTIVE = "active"
    SETTLED = "settled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"                        # Proposal timed out before acceptance

class TemplateType(Enum):
    """Types of futures templates"""
    UP_DOWN = "up_down"           # Binary: price goes up or down
    LONG_SHORT = "long_short"     # Proportional payout based on price movement
    RANGE = "range"               # Price stays within range