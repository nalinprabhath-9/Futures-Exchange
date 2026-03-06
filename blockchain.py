import hashlib
import time
import random
from datetime import datetime
from typing import List, Dict, Optional

from transaction_enums import TransactionType, TradeState, TemplateType
from crypto_utils import sign_message, get_signing_key_from_hex, get_compressed_pubkey, verify_signature, verify_oracle_signature


CRYPTOCURRENCY_NAME = "FutureCoin"
MILLI_DENOMINATION = 1000
MAX_TXNS_PER_BLOCK = 10
COINBASE_REWARD = 50000

MINIMUM_FEES = {
    TransactionType.PROPOSE_TRADE: 1000,      # 1 FutureCoin
    TransactionType.ACCEPT_TRADE: 1000,       # 1 FutureCoin
    TransactionType.SETTLE_TRADE: 500,        # 0.5 FutureCoin
    TransactionType.CANCEL_PROPOSAL: 250,     # 0.25 FutureCoin
    TransactionType.CANCEL_TRADE: 500,        # 0.5 FutureCoin
    TransactionType.TRANSFER: 100,            # 0.1 FutureCoin (for regular transfers)
}

HIGH_PRIORITY_MULTIPLIER = 2


class Output:
    """
    Transaction Output class
    Represents a single output in a transaction
    """

    def __init__(self, value: int, index: int, script: str = ""):
        """
        Initialize an output

        Args:
            value: Amount in milli-coins (1/1000th of a coin)
            index: Output index in the transaction
            script: Script/address string (can be anything for now)
        """
        self.Value = value
        self.Index = index
        self.Script = script

    def to_string(self) -> str:
        """Serialize output for hashing"""
        return f"{self.Value}{self.Index}{self.Script}"

    def __repr__(self):
        coins = self.Value / MILLI_DENOMINATION
        return f"Output(value={coins} {CRYPTOCURRENCY_NAME}, index={self.Index}, script='{self.Script[:20]}...')"


class Transaction:
    """
    Transaction class representing a single transaction in the blockchain
    """

    def __init__(self, version_number: int = 1,
                 list_of_inputs: List[str] = None,
                 list_of_outputs=None,
                 fee: int = 0):
        """
        Initialize a transaction

        Args:
            version_number: Transaction version (default 1)
            list_of_inputs: List of input strings
            list_of_outputs: List of output strings OR Output objects
            fee: Transaction fee in milli-coins
        """
        self.VersionNumber = version_number
        self.ListOfInputs = list_of_inputs if list_of_inputs else []
        self.ListOfOutputs = list_of_outputs if list_of_outputs else []
        self.InCounter = len(self.ListOfInputs)
        self.OutCounter = len(self.ListOfOutputs)
        self.fee = fee
        self.TransactionHash = self._calculate_hash()

    def _calculate_hash(self) -> str:
        """
        Calculate the transaction hash using double SHA-256
        Hashes: VersionNumber + InCounter + ListOfInputs + OutCounter + ListOfOutputs + Fee
        """
        if self.ListOfOutputs and isinstance(self.ListOfOutputs[0], Output):
            outputs_str = ''.join([out.to_string() for out in self.ListOfOutputs])
        else:
            outputs_str = ''.join(self.ListOfOutputs)

        tx_data = (
            str(self.VersionNumber) +
            str(self.InCounter) +
            ''.join(self.ListOfInputs) +
            str(self.OutCounter) +
            outputs_str +
            str(self.fee)
        )

        first_hash = hashlib.sha256(tx_data.encode()).digest()
        second_hash = hashlib.sha256(first_hash).hexdigest()
        return second_hash

    def print_transaction(self):
        """Print transaction details"""
        print(f"\n{'='*60}")
        print(f"Transaction Hash: {self.TransactionHash}")
        print(f"{'='*60}")
        print(f"Version Number: {self.VersionNumber}")
        print(f"Input Counter: {self.InCounter}")
        print(f"Inputs: {self.ListOfInputs}")
        print(f"Output Counter: {self.OutCounter}")

        if self.ListOfOutputs and isinstance(self.ListOfOutputs[0], Output):
            print("Outputs:")
            for output in self.ListOfOutputs:
                coins = output.Value / MILLI_DENOMINATION
                print(f"  [{output.Index}] {coins:.3f} {CRYPTOCURRENCY_NAME} -> {output.Script[:30]}...")
        else:
            print(f"Outputs: {self.ListOfOutputs}")
        print(f"{'='*60}")


class Header:
    """
    Block header containing metadata about the block
    """

    def __init__(self, hash_prev_block: str = "0" * 64,
                 hash_merkle_root: str = "",
                 timestamp: int = None,
                 bits: int = 0,
                 nonce: int = 0,
                 version: int = 1):
        """
        Initialize block header

        Args:
            hash_prev_block: Hash of previous block's header (all zeros for genesis)
            hash_merkle_root: Merkle root of transactions
            timestamp: Block creation time (Unix timestamp)
            bits: Difficulty target
            nonce: Proof of work nonce
            version: Block version
        """
        self.Version = version
        self.hashPrevBlock = hash_prev_block
        self.hashMerkleRoot = hash_merkle_root
        self.Timestamp = timestamp if timestamp else int(datetime.now().timestamp())
        self.Bits = bits
        self.Nonce = nonce


class Block:
    """
    Block class representing a single block in the blockchain
    """

    def __init__(self, magic_number: int = 0xf9beb4d9,
                 block_size: int = 0,
                 previous_block_hash: str = "0" * 64,
                 transaction_counter: int = 0):
        """
        Initialize a block

        Args:
            magic_number: Magic number (default 0xf9beb4d9)
            block_size: Size of block in bytes
            previous_block_hash: Hash of previous block
            transaction_counter: Number of transactions
        """
        self.MagicNumber = magic_number
        self.Blocksize = block_size
        self.TransactionCounter = transaction_counter
        self.Transactions = {}
        self.BlockHeader = Header(hash_prev_block=previous_block_hash)
        self.Blockhash = ""

    def add_transaction(self, transaction: Transaction):
        """
        Add a transaction to the block
        """
        self.Transactions[transaction.TransactionHash] = transaction
        self.TransactionCounter = len(self.Transactions)
        self._update_merkle_root()
        self._calculate_block_hash()

    def _update_merkle_root(self):
        """
        Calculate the Merkle root from all transactions.
        For simplicity, hashes all transaction hashes together
        (a full Merkle tree implementation would pair and hash recursively).
        """
        if not self.Transactions:
            self.BlockHeader.hashMerkleRoot = "0" * 64
            return

        tx_hashes = list(self.Transactions.keys())
        merkle_data = ''.join(tx_hashes)
        first_hash = hashlib.sha256(merkle_data.encode()).digest()
        merkle_root = hashlib.sha256(first_hash).hexdigest()
        self.BlockHeader.hashMerkleRoot = merkle_root

    def _calculate_block_hash(self):
        """
        Calculate the block hash from header fields.
        Hash: Timestamp + hashMerkleRoot + Bits + Nonce + hashPrevBlock
        """
        header_data = (
            str(self.BlockHeader.Timestamp) +
            self.BlockHeader.hashMerkleRoot +
            str(self.BlockHeader.Bits) +
            str(self.BlockHeader.Nonce) +
            self.BlockHeader.hashPrevBlock
        )

        first_hash = hashlib.sha256(header_data.encode()).digest()
        block_hash = hashlib.sha256(first_hash).hexdigest()
        self.Blockhash = block_hash

    def print_block(self):
        """Print block details"""
        print(f"\n{'#'*70}")
        print(f"BLOCK INFORMATION")
        print(f"{'#'*70}")
        print(f"Block Hash: {self.Blockhash}")
        print(f"Magic Number: {hex(self.MagicNumber)}")
        print(f"Block Size: {self.Blocksize}")
        print(f"Transaction Counter: {self.TransactionCounter}")
        print(f"\n{'='*70}")
        print(f"BLOCK HEADER")
        print(f"{'='*70}")
        print(f"Version: {self.BlockHeader.Version}")
        print(f"Previous Block Hash: {self.BlockHeader.hashPrevBlock}")
        print(f"Merkle Root: {self.BlockHeader.hashMerkleRoot}")
        print(f"Timestamp: {self.BlockHeader.Timestamp} ({datetime.fromtimestamp(self.BlockHeader.Timestamp)})")
        print(f"Bits: {self.BlockHeader.Bits}")
        print(f"Nonce: {self.BlockHeader.Nonce}")
        print(f"\n{'='*70}")
        print(f"TRANSACTIONS ({self.TransactionCounter} total)")
        print(f"{'='*70}")
        for i, (tx_hash, tx) in enumerate(self.Transactions.items(), 1):
            print(f"\nTransaction {i}:")
            print(f"  Hash: {tx_hash[:32]}...")
            if tx.ListOfOutputs and isinstance(tx.ListOfOutputs[0], Output):
                print(f"  Inputs ({len(tx.ListOfInputs)}): {[inp[:16] + '...' for inp in tx.ListOfInputs[:2]]}")
                print(f"  Outputs ({len(tx.ListOfOutputs)}):")
                for out in tx.ListOfOutputs[:3]:
                    coins = out.Value / MILLI_DENOMINATION
                    print(f"    [{out.Index}] {coins:.3f} {CRYPTOCURRENCY_NAME} -> {out.Script[:20]}...")
            else:
                print(f"  Inputs: {tx.ListOfInputs}")
                print(f"  Outputs: {tx.ListOfOutputs}")
        print(f"{'#'*70}\n")


class BalanceManager:
    """
    Manages FutureCoin balances and locked collateral.
    Collateral is locked per-party: party_a locks on proposal, party_b on acceptance.
    """

    def __init__(self):
        """Initialize balance tracking"""
        self.balances = {}      # address -> total milli-coins
        self.locked = {}        # address -> locked milli-coins
        self.trade_locks = {}   # trade_id -> {party_a, party_b, amount}

    def add_mining_reward(self, address: str, amount: int):
        """Add coins from mining reward"""
        if address not in self.balances:
            self.balances[address] = 0
        self.balances[address] += amount
        print(f"Added {amount / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME} to {address[:20]}... (Mining)")

    def get_total_balance(self, address: str) -> int:
        """Get total balance for address"""
        return self.balances.get(address, 0)

    def get_locked_balance(self, address: str) -> int:
        """Get locked balance for address"""
        return self.locked.get(address, 0)

    def get_available_balance(self, address: str) -> int:
        """Get available balance (total - locked)"""
        return self.get_total_balance(address) - self.get_locked_balance(address)

    def lock_collateral_party(self, trade_id: str, party: str, amount: int, role: str) -> bool:
        """
        Lock collateral for a single party in a trade.

        Args:
            trade_id: The trade identifier
            party: Address of the party locking collateral
            amount: Amount in milli-coins to lock
            role: 'party_a' or 'party_b'

        Returns:
            True if successful, False if insufficient balance
        """
        if self.get_available_balance(party) < amount:
            print(f"Insufficient balance for {party[:20]}... (need {amount / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME})")
            return False

        if party not in self.locked:
            self.locked[party] = 0
        self.locked[party] += amount

        # Initialise or update the trade_locks entry
        if trade_id not in self.trade_locks:
            self.trade_locks[trade_id] = {'party_a': None, 'party_b': None, 'amount': amount}
        self.trade_locks[trade_id][role] = party

        coins = amount / MILLI_DENOMINATION
        print(f"Locked {coins} {CRYPTOCURRENCY_NAME} for {party[:20]}... ({role}) in trade {trade_id}")
        return True

    def settle_trade(self, trade_id: str, winner: str, loser: str,
                     winner_payout: int, loser_payout: int) -> bool:
        """
        Settle a trade by unlocking and transferring collateral.

        Args:
            trade_id: ID of the trade to settle
            winner: Address of winning party
            loser: Address of losing party
            winner_payout: Amount winner receives (usually 2x collateral)
            loser_payout: Amount loser receives (usually 0)

        Returns:
            True if successful
        """
        if trade_id not in self.trade_locks:
            print(f"Trade {trade_id} not found in locks")
            return False

        lock_info = self.trade_locks[trade_id]
        amount = lock_info['amount']

        # Unlock collateral for both parties
        self.locked[lock_info['party_a']] -= amount
        self.locked[lock_info['party_b']] -= amount

        # Transfer from loser to winner
        loser_loss = amount - loser_payout
        self.balances[loser] -= loser_loss
        self.balances[winner] += loser_loss

        del self.trade_locks[trade_id]

        winner_coins = winner_payout / MILLI_DENOMINATION
        loser_coins = loser_payout / MILLI_DENOMINATION

        print(f"\n{'='*60}")
        print(f"TRADE SETTLED: {trade_id}")
        print(f"Winner: {winner[:20]}... receives {winner_coins} {CRYPTOCURRENCY_NAME}")
        print(f"Loser: {loser[:20]}... receives {loser_coins} {CRYPTOCURRENCY_NAME}")
        print(f"{'='*60}\n")

        return True

    def cancel_trade(self, trade_id: str) -> bool:
        """
        Cancel a trade and unlock collateral for whichever parties have already deposited.
        Handles partial locks (e.g. party_a deposited but party_b never accepted).
        """
        if trade_id not in self.trade_locks:
            return False

        lock_info = self.trade_locks[trade_id]
        amount = lock_info['amount']

        for role in ('party_a', 'party_b'):
            party = lock_info[role]
            if party is not None:
                self.locked[party] -= amount
                print(f"Unlocked {amount / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME} for {party[:20]}... ({role})")

        del self.trade_locks[trade_id]
        print(f"Trade {trade_id} cancelled, collateral unlocked")
        return True

    def print_balance(self, address: str):
        """Print balance information for an address"""
        total = self.get_total_balance(address)
        locked = self.get_locked_balance(address)
        available = self.get_available_balance(address)

        print(f"\n{'='*60}")
        print(f"BALANCE: {address[:30]}...")
        print(f"{'='*60}")
        print(f"Total:     {total / MILLI_DENOMINATION:.3f} {CRYPTOCURRENCY_NAME}")
        print(f"Locked:    {locked / MILLI_DENOMINATION:.3f} {CRYPTOCURRENCY_NAME}")
        print(f"Available: {available / MILLI_DENOMINATION:.3f} {CRYPTOCURRENCY_NAME}")
        print(f"{'='*60}\n")


class Blockchain:
    """
    Blockchain managing a chain of blocks.
    Supports mining + futures trading.

    Trade lifecycle:
        PROPOSED  -> party_a's collateral locked on proposal
        ACTIVE    -> party_b's collateral locked on acceptance (no intermediate state)
        SETTLED / CANCELLED / EXPIRED

    Proposal timeout:
        If a PROPOSED trade is not accepted within `proposal_timeout_seconds`,
        it is automatically expired by the next call to `add_block`, unlocking
        party_a's collateral and moving the trade to EXPIRED.
    """

    def __init__(self, proposal_timeout_seconds: int = 3600):
        """
        Initialize blockchain with balance management.

        Args:
            proposal_timeout_seconds: How long (in seconds) a PROPOSED trade
                waits for acceptance before being automatically expired and
                party_a's collateral returned. Defaults to 3600 (1 hour).
        """
        self.chain = []
        self.block_height_index = {}
        self.block_hash_index = {}
        self.transaction_index = {}

        self.proposed_trades = {}  # trade_id -> FuturesTransaction (PROPOSED only)
        self.active_trades = {}    # trade_id -> FuturesTransaction (ACTIVE only)
        self.settled_trades = {}   # trade_id -> FuturesTransaction (terminal states)
        self.proposal_timeout_seconds = proposal_timeout_seconds
        self.balances = BalanceManager()

        # hardcoded
        self.trusted_oracle_pubkey = "02755042abfad8bc9c08e5184360e43d32108c1aafd2324f946eec3bdfd4950553"

        print("Blockchain initialized (genesis block will be mined)")
        print(f"Futures trading enabled! Proposal timeout: {proposal_timeout_seconds}s")

    

    def add_block(self, block: Block):
        """
        Add a block to the blockchain and process all transactions.
        Collects fees and awards them to the miner.
        """
        height = len(self.chain)
        self.chain.append(block)
        self.block_height_index[height] = block
        self.block_hash_index[block.Blockhash] = block

        # Track fees collected in this block
        total_fees_collected = 0
        miner_address = None

        # First, find miner address from coinbase transaction
        for tx_hash, tx in block.Transactions.items():
            if len(tx.ListOfInputs) > 0 and "Coinbase" in tx.ListOfInputs[0]:
                if tx.ListOfOutputs and isinstance(tx.ListOfOutputs[0], Output):
                    miner_address = tx.ListOfOutputs[0].Script
                    break

        # Process all transactions (except coinbase, which is processed last)
        coinbase_txs = []
        for tx_hash, tx in block.Transactions.items():
            self.transaction_index[tx_hash] = (block, tx)

            if len(tx.ListOfInputs) > 0 and "Coinbase" in tx.ListOfInputs[0]:
                coinbase_txs.append(tx)
                continue

            # Collect fee from non-coinbase transactions
            fee = getattr(tx, 'fee', 0)
            if fee > 0:
                fee_payer = None
                if isinstance(tx, FuturesTransaction):
                    if tx.tx_type == TransactionType.PROPOSE_TRADE:
                        fee_payer = tx.party_a
                    elif tx.tx_type == TransactionType.ACCEPT_TRADE:
                        fee_payer = tx.party_b
                    elif tx.tx_type == TransactionType.CANCEL_PROPOSAL:
                        fee_payer = tx.party_a
                        if fee_payer is None and tx.trade_id in self.proposed_trades:
                            fee_payer = self.proposed_trades[tx.trade_id].party_a
                    elif tx.tx_type == TransactionType.CANCEL_TRADE:
                        fee_payer = tx.party_a
                        if fee_payer is None and tx.trade_id in self.active_trades:
                            fee_payer = self.active_trades[tx.trade_id].party_a
                    elif tx.tx_type == TransactionType.SETTLE_TRADE:
                        fee_payer = tx.party_a or tx.winner

                if fee_payer:
                    if self.balances.get_available_balance(fee_payer) >= fee:
                        self.balances.balances[fee_payer] -= fee
                        total_fees_collected += fee
                        print(f"  Collected fee: {fee / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME} from {fee_payer[:20]}...")
                    else:
                        print(f"  WARNING: Insufficient balance for fee from {fee_payer[:20]}... (skipping transaction)")
                        continue

            self._process_transaction(tx)

        # Process coinbase transactions last (after fee collection)
        for tx in coinbase_txs:
            self._process_transaction(tx)

        # Award collected fees to miner
        if miner_address and total_fees_collected > 0:
            self.balances.balances[miner_address] = self.balances.balances.get(miner_address, 0) + total_fees_collected
            print(f"  Miner {miner_address[:20]}... earned {total_fees_collected / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME} in fees")

        # Expire stale proposals
        self._expire_stale_proposals(block.BlockHeader.Timestamp)

        print(f"Block #{height} added to blockchain (Total fees: {total_fees_collected / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME})")

    def _process_transaction(self, tx: Transaction):
        """
        Process a transaction based on its type
        """
        if len(tx.ListOfInputs) > 0 and "Coinbase" in tx.ListOfInputs[0]:
            if tx.ListOfOutputs and isinstance(tx.ListOfOutputs[0], Output):
                miner_address = tx.ListOfOutputs[0].Script
                reward = tx.ListOfOutputs[0].Value
                self.balances.add_mining_reward(miner_address, reward)

        elif isinstance(tx, FuturesTransaction):
            self._process_futures_transaction(tx)

    def _process_futures_transaction(self, tx: 'FuturesTransaction'):
        """Process futures-specific transactions"""
        if tx.tx_type == TransactionType.PROPOSE_TRADE:
            # Lock party_a's collateral immediately on proposal
            success = self.balances.lock_collateral_party(
                tx.trade_id, tx.party_a, tx.collateral_amount, 'party_a'
            )
            if not success:
                print(f"Trade {tx.trade_id} rejected: party_a cannot cover collateral")
                return

            self.proposed_trades[tx.trade_id] = tx
            print(f"Trade {tx.trade_id} proposed by {tx.party_a[:20]}... (collateral locked, fee paid)")

        elif tx.tx_type == TransactionType.ACCEPT_TRADE:
            if tx.trade_id not in self.proposed_trades:
                print(f"Trade {tx.trade_id} not found in proposed trades")
                return

            trade = self.proposed_trades[tx.trade_id]

            # Lock party_b's collateral; if it fails the acceptance is rejected
            success = self.balances.lock_collateral_party(
                tx.trade_id, tx.party_b, trade.collateral_amount, 'party_b'
            )
            if not success:
                print(f"Trade {tx.trade_id} acceptance rejected: party_b cannot cover collateral")
                return

            trade.party_b = tx.party_b
            trade.state = TradeState.ACTIVE
            self.active_trades[tx.trade_id] = trade
            del self.proposed_trades[tx.trade_id]
            print(f"Trade {tx.trade_id} accepted by {tx.party_b[:20]}... — now ACTIVE (fee paid)")

        elif tx.tx_type == TransactionType.CANCEL_PROPOSAL:
            # party_a voluntarily withdraws a PROPOSED (not yet accepted) trade
            if tx.trade_id not in self.proposed_trades:
                print(f"Trade {tx.trade_id} not found in proposed trades or already accepted")
                return

            self.balances.cancel_trade(tx.trade_id)
            trade = self.proposed_trades[tx.trade_id]
            trade.state = TradeState.CANCELLED
            self.settled_trades[tx.trade_id] = trade
            del self.proposed_trades[tx.trade_id]
            print(f"Trade {tx.trade_id} proposal cancelled by party_a, collateral unlocked")

        elif tx.tx_type == TransactionType.SETTLE_TRADE:
            # Ensure trade exists and is active
            if tx.trade_id not in self.active_trades:
                print(f"Trade {tx.trade_id} not found or already settled")
                return

            trade = self.active_trades[tx.trade_id]

            # Verify oracle pubkey matches trusted anchor
            if tx.oracle_pubkey != self.trusted_oracle_pubkey:
                print("Invalid oracle pubkey")
                return

            # Rebuild oracle message EXACTLY like oracle does
            # Oracle format:
            # SHA256( symbol || formatted_price || timestamp )

            price_str = f"{tx.oracle_price:.8f}".rstrip("0").rstrip(".")
            raw = (
                trade.asset_pair.encode() +
                price_str.encode() +
                str(tx.oracle_timestamp).encode()
            )

            digest = hashlib.sha256(raw).digest()

            # Verify oracle signature (digest already hashed once)
            if not verify_oracle_signature(
                bytes.fromhex(tx.oracle_pubkey),
                digest,
                bytes.fromhex(tx.oracle_signature)
            ):
                print("Invalid oracle signature")
                return

            # Enforce expiry using TRADE expiry, not tx expiry
            current_block_time = self.chain[-1].BlockHeader.Timestamp
            print(f"[DEBUG] SETTLE_TRADE: current_block_time={current_block_time}, trade.expiry_timestamp={trade.expiry_timestamp}, diff={current_block_time - trade.expiry_timestamp}")

            if current_block_time < trade.expiry_timestamp:
                print("Trade not yet expired")
                return

            # Optional: enforce oracle timestamp close to expiry
            print(f"[DEBUG] SETTLE_TRADE: oracle_timestamp={tx.oracle_timestamp}, expiry_timestamp={trade.expiry_timestamp}, diff={tx.oracle_timestamp - trade.expiry_timestamp}")
            if abs(tx.oracle_timestamp - trade.expiry_timestamp) > 300:
                print("Oracle timestamp too far from expiry")
                return

            # Compute winner deterministically (IGNORE tx.winner)
            if tx.oracle_price > trade.strike_price:
                winner = trade.party_a
                loser = trade.party_b
            else:
                winner = trade.party_b
                loser = trade.party_a

            total_collateral = trade.collateral_amount * 2

            # Perform settlement using balance manager
            self.balances.settle_trade(
                tx.trade_id,
                winner,
                loser,
                total_collateral,
                0
            )

            # Update trade state
            trade.state = TradeState.SETTLED
            trade.settlement_price = tx.oracle_price
            trade.winner = winner

            self.settled_trades[tx.trade_id] = trade
            del self.active_trades[tx.trade_id]

            print(f"Trade {tx.trade_id} settled. Winner: {winner}")
            # if tx.trade_id not in self.active_trades:
            #     print(f"Trade {tx.trade_id} not found or already settled")
            #     return

            # trade = self.active_trades[tx.trade_id]
            # loser = trade.party_a if tx.winner == trade.party_b else trade.party_b

            # self.balances.settle_trade(
            #     tx.trade_id,
            #     tx.winner,
            #     loser,
            #     tx.winner_payout,
            #     tx.loser_payout or 0
            # )

            # trade.state = TradeState.SETTLED
            # trade.settlement_price = tx.settlement_price
            # trade.winner = tx.winner
            # self.settled_trades[tx.trade_id] = trade
            # del self.active_trades[tx.trade_id]

        elif tx.tx_type == TransactionType.CANCEL_TRADE:
            if tx.trade_id not in self.active_trades:
                return
            self.balances.cancel_trade(tx.trade_id)
            trade = self.active_trades[tx.trade_id]
            trade.state = TradeState.CANCELLED
            self.settled_trades[tx.trade_id] = trade
            del self.active_trades[tx.trade_id]

    def get_active_trades(self) -> List['FuturesTransaction']:
        """Get all active futures trades"""
        return list(self.active_trades.values())

    def get_trade(self, trade_id: str) -> Optional['FuturesTransaction']:
        """Get a specific trade by ID"""
        return (
            self.proposed_trades.get(trade_id) or
            self.active_trades.get(trade_id) or
            self.settled_trades.get(trade_id)
        )

    def get_proposed_trades(self) -> List['FuturesTransaction']:
        """Get all open (not yet accepted) trade proposals"""
        return list(self.proposed_trades.values())

    def _expire_stale_proposals(self, current_time: int):
        """
        Expire all PROPOSED trades whose proposal_timeout has elapsed.

        Called automatically by add_block using the block's own timestamp so
        that expiry is deterministic across all nodes: every node processing
        the same block will expire exactly the same set of proposals.

        Party_a's locked collateral is returned upon expiry.

        Args:
            current_time: Unix timestamp to compare against each trade's
                expiry_timestamp (set at proposal_timeout_seconds after creation).
        """
        expired = [
            trade_id for trade_id, trade in self.proposed_trades.items()
            if trade.expiry_timestamp is not None and current_time > trade.expiry_timestamp
        ]
        for trade_id in expired:
            trade = self.proposed_trades[trade_id]
            self.balances.cancel_trade(trade_id)
            trade.state = TradeState.EXPIRED
            self.settled_trades[trade_id] = trade
            del self.proposed_trades[trade_id]
            print(f"Trade {trade_id} EXPIRED (no acceptance by {datetime.fromtimestamp(trade.expiry_timestamp)}), collateral returned")

    def get_user_balance(self, address: str) -> dict:
        """Get balance information for a user"""
        return {
            'total': self.balances.get_total_balance(address),
            'locked': self.balances.get_locked_balance(address),
            'available': self.balances.get_available_balance(address)
        }

    def create_block(self, transactions: List[Transaction]) -> Block:
        """Create a new block with given transactions"""
        previous_block = self.chain[-1]
        new_block = Block(previous_block_hash=previous_block.Blockhash)
        for tx in transactions:
            new_block.add_transaction(tx)
        self.add_block(new_block)
        return new_block

    def get_block_by_height(self, height: int) -> Optional[Block]:
        """Get a block by its height"""
        return self.block_height_index.get(height)

    def get_block_by_hash(self, block_hash: str) -> Optional[Block]:
        """Get a block by its hash"""
        return self.block_hash_index.get(block_hash)

    def find_transaction(self, transaction_hash: str) -> Optional[Transaction]:
        """Search for a transaction by its hash"""
        result = self.transaction_index.get(transaction_hash)
        return result[1] if result else None

    def print_blockchain(self):
        """Print the entire blockchain with futures info"""
        print(f"\n{'*'*70}")
        print(f"BLOCKCHAIN SUMMARY - {CRYPTOCURRENCY_NAME} FUTURES EXCHANGE")
        print(f"{'*'*70}")
        print(f"Total Blocks: {len(self.chain)}")
        print(f"Total Transactions: {len(self.transaction_index)}")
        print(f"Proposed Trades: {len(self.proposed_trades)}")
        print(f"Active Trades: {len(self.active_trades)}")
        print(f"Settled Trades: {len(self.settled_trades)}")
        print(f"{'*'*70}\n")

        for i, block in enumerate(self.chain):
            print(f"Block Height: {i}")
            block.print_block()


class TxnMemoryPool:
    """
    Transaction Memory Pool (Mempool) with fee-based prioritization.
    High-fee transactions are selected before normal-fee transactions.
    """

    def __init__(self):
        """Initialize mempool with priority queues"""
        self.high_priority_txs = []    # fee >= HIGH_PRIORITY_MULTIPLIER * minimum
        self.normal_priority_txs = []  # fee >= minimum but below high-priority threshold

    @property
    def transactions(self) -> List[Transaction]:
        """Compatibility view of all queued transactions (high first)."""
        return self.high_priority_txs + self.normal_priority_txs

    def add_transaction(self, transaction: Transaction):
        """
        Add a transaction to mempool with fee-based priority.
        Returns:
            True if added, False if rejected.
        """
        if hasattr(transaction, 'signature') and hasattr(transaction, 'pubkey'):
            if transaction.signature and transaction.pubkey:
                if not verify_signature(transaction.pubkey, transaction.get_signing_data(), transaction.signature):
                    print(f"Rejected transaction {transaction.TransactionHash[:16]}...: invalid signature!")
                    return False

        fee = getattr(transaction, 'fee', 0)
        if isinstance(transaction, FuturesTransaction):
            min_fee = MINIMUM_FEES.get(transaction.tx_type, 500)
        else:
            min_fee = MINIMUM_FEES.get(TransactionType.TRANSFER, 100)

        if fee < min_fee:
            print(f"Rejected transaction {transaction.TransactionHash[:16]}...: fee {fee} below minimum {min_fee}")
            return False

        if fee >= min_fee * HIGH_PRIORITY_MULTIPLIER:
            self.high_priority_txs.append(transaction)
            priority = "HIGH"
        else:
            self.normal_priority_txs.append(transaction)
            priority = "NORMAL"

        print(
            f"Added transaction {transaction.TransactionHash[:16]}... to mempool "
            f"[{priority} priority, fee: {fee / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}] "
            f"(size: {self.size()})"
        )
        return True

    def get_transactions(self, count: int) -> List[Transaction]:
        """
        Get up to 'count' transactions from mempool.
        High-priority transactions are selected first, then normal priority.

        Args:
            count: Maximum number of transactions to retrieve

        Returns:
            List of transactions (up to count)
        """
        result = []
        while self.high_priority_txs and len(result) < count:
            result.append(self.high_priority_txs.pop(0))
        while self.normal_priority_txs and len(result) < count:
            result.append(self.normal_priority_txs.pop(0))

        if result:
            high_count = sum(
                1 for tx in result
                if getattr(tx, 'fee', 0) >= MINIMUM_FEES.get(
                    tx.tx_type if isinstance(tx, FuturesTransaction) else TransactionType.TRANSFER, 100
                ) * HIGH_PRIORITY_MULTIPLIER
            )
            print(f"Mempool: Selected {len(result)} transactions ({high_count} high-priority, {len(result) - high_count} normal)")
        return result

    def size(self) -> int:
        """Return total number of transactions in mempool"""
        return len(self.high_priority_txs) + len(self.normal_priority_txs)

    def clear(self):
        """Clear all transactions from the mempool"""
        self.high_priority_txs = []
        self.normal_priority_txs = []


class Miner:
    """
    Miner class that creates blocks from transactions in the mempool.
    Implements proof-of-work mining with difficulty target.
    """

    def __init__(self, miner_address: str, difficulty_bits: int = 0x207fffff):
        """
        Initialize a miner

        Args:
            miner_address: Address where mining rewards are sent
            difficulty_bits: Difficulty target in compact format (default: Regtest)
        """
        self.miner_address = miner_address
        self.difficulty_bits = difficulty_bits
        self.blocks_mined = 0
        self.total_hashes = 0
        self.target = self._calculate_target(difficulty_bits)

        print(f"Miner initialized:")
        print(f"  Address: {miner_address}")
        print(f"  Difficulty bits: {hex(difficulty_bits)}")
        print(f"  Target: {hex(self.target)}")

    def _calculate_target(self, bits: int) -> int:
        """
        Calculate target from compact difficulty bits format.
        Target = coefficient * 2^(8 * (exponent - 3))

        Args:
            bits: Difficulty bits in compact format (e.g., 0x207fffff)

        Returns:
            Target as an integer
        """
        exponent = bits >> 24
        coefficient = bits & 0xffffff
        return coefficient * (2 ** (8 * (exponent - 3)))

    def create_coinbase_transaction(self, block_height: int) -> Transaction:
        """
        Create a coinbase transaction (mining reward)

        Args:
            block_height: Height of the block being mined

        Returns:
            Coinbase transaction
        """
        coinbase_input = f"Coinbase for block {block_height} - {int(time.time())}"
        coinbase_output = Output(value=COINBASE_REWARD, index=0, script=self.miner_address)
        return Transaction(version_number=1, list_of_inputs=[coinbase_input], list_of_outputs=[coinbase_output])

    def _hash_meets_target(self, block_hash: str) -> bool:
        """
        Check if a block hash meets the difficulty target

        Args:
            block_hash: Block hash as hex string

        Returns:
            True if hash < target, False otherwise
        """
        return int(block_hash, 16) < self.target

    def mine_block(self, blockchain: Blockchain, mempool: TxnMemoryPool, verbose: bool = True) -> Block:
        """
        Mine a new block from transactions in the mempool using proof-of-work

        Args:
            blockchain: The blockchain to add the block to
            mempool: Transaction memory pool
            verbose: Whether to print mining progress

        Returns:
            The newly mined block
        """
        block_height = len(blockchain.chain)

        if verbose:
            print(f"\n{'*'*70}")
            print(f"MINING BLOCK #{block_height}")
            print(f"{'*'*70}")

        coinbase_tx = self.create_coinbase_transaction(block_height)

        if verbose:
            print(f"Created coinbase: {COINBASE_REWARD / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME} -> {self.miner_address[:20]}...")

        transactions = mempool.get_transactions(MAX_TXNS_PER_BLOCK - 1)

        if verbose:
            print(f"Retrieved {len(transactions)} transactions from mempool")

        previous_hash = "0" * 64 if block_height == 0 else blockchain.chain[-1].Blockhash
        new_block = Block(previous_block_hash=previous_hash)
        new_block.BlockHeader.Bits = self.difficulty_bits
        new_block.add_transaction(coinbase_tx)

        for tx in transactions:
            new_block.add_transaction(tx)

        if verbose:
            print(f"Starting proof-of-work mining...")

        start_time = time.time()
        nonce = 0
        hashes_this_block = 0

        while True:
            new_block.BlockHeader.Nonce = nonce
            new_block._calculate_block_hash()
            hashes_this_block += 1
            self.total_hashes += 1

            if self._hash_meets_target(new_block.Blockhash):
                break

            nonce += 1

            if verbose and hashes_this_block % 100000 == 0:
                elapsed = time.time() - start_time
                hash_rate = hashes_this_block / elapsed if elapsed > 0 else 0
                print(f"  Hashes: {hashes_this_block:,} | Hash rate: {hash_rate:,.0f} H/s | Nonce: {nonce}")

        elapsed = time.time() - start_time
        hash_rate = hashes_this_block / elapsed if elapsed > 0 else 0
        self.blocks_mined += 1

        if verbose:
            print(f"\n{'='*70}")
            print(f"BLOCK MINED SUCCESSFULLY!")
            print(f"{'='*70}")
            print(f"Block height: {block_height} | Hash: {new_block.Blockhash}")
            print(f"Nonce: {nonce} | Hashes: {hashes_this_block:,} | Time: {elapsed:.2f}s | Rate: {hash_rate:,.0f} H/s")
            print(f"Transactions: {new_block.TransactionCounter}")
            print(f"{'='*70}\n")

        return new_block


def generate_random_transaction() -> Transaction:
    """
    Generate a random transaction with hashed inputs and Output objects

    Returns:
        A new Transaction object
    """
    input_data = f"{int(time.time())}{random.randint(1000, 9999)}"
    input_hash = hashlib.sha256(input_data.encode()).hexdigest()

    outputs = [
        Output(
            value=random.randint(100, 5000),
            index=i,
            script=hashlib.sha256(f"address_{random.randint(1000,9999)}".encode()).hexdigest()
        )
        for i in range(random.randint(1, 3))
    ]

    return Transaction(version_number=1, list_of_inputs=[input_hash], list_of_outputs=outputs)


class FuturesTransaction(Transaction):
    """
    Futures trade transaction with fee support.
    """

    def __init__(self,
                 trade_id: str,
                 tx_type: TransactionType,
                 party_a: str = None,
                 party_b: str = None,
                 template_type: TemplateType = None,
                 asset_pair: str = None,
                 strike_price: float = None,
                 expiry_timestamp: int = None,
                 collateral_amount: int = None,
                 state: TradeState = TradeState.PROPOSED,
                 settlement_price: float = None,
                 winner: str = None,
                 winner_payout: int = None,
                 loser_payout: int = None,
                 fee: int = None,
                 signature: bytes = None,
                 pubkey: bytes = None,
                 oracle_price: float = None,
                 oracle_timestamp: int = None,
                 oracle_signature: str = None,
                 oracle_pubkey: str = None):
        """
        Initialize a futures transaction

        Args:
            trade_id: Unique identifier for the trade
            tx_type: Type of futures transaction (propose, accept, settle, etc.)
            party_a: First party's address
            party_b: Second party's address (None until accepted)
            template_type: Which futures template to use
            asset_pair: Asset being traded (e.g., "BTC/USD")
            strike_price: Reference price for settlement
            expiry_timestamp: When the trade expires
            collateral_amount: Amount each party stakes (in milli-FutureCoin)
            state: Current state of the trade
            settlement_price: Final price from oracle (filled at settlement)
            winner: Address of winner (filled at settlement)
            winner_payout: Amount winner receives
            loser_payout: Amount loser receives (usually 0)
            signature: ECDSA signature (bytes)
            pubkey: Compressed public key (bytes)
            fee: Transaction fee in milli-coins. If None, uses minimum for tx_type.
        """
        self.trade_id = trade_id
        self.tx_type = tx_type
        self.party_a = party_a
        self.party_b = party_b
        self.template_type = template_type
        self.asset_pair = asset_pair
        self.strike_price = strike_price
        self.expiry_timestamp = expiry_timestamp
        self.collateral_amount = collateral_amount
        self.state = state
        self.settlement_price = settlement_price
        self.winner = winner
        self.winner_payout = winner_payout
        self.loser_payout = loser_payout
        self.timestamp = int(time.time())
        self.signature = signature
        self.pubkey = pubkey
        self.oracle_price = oracle_price
        self.oracle_timestamp = oracle_timestamp
        self.oracle_signature = oracle_signature
        self.oracle_pubkey = oracle_pubkey

        # hardcoded
        self.trusted_oracle_pubkey = "02755042abfad8bc9c08e5184360e43d32108c1aafd2324f946eec3bdfd4950553"
        
        if fee is None:
            fee = MINIMUM_FEES.get(tx_type, 500)
        else:
            min_fee = MINIMUM_FEES.get(tx_type, 0)
            if fee < min_fee:
                raise ValueError(
                    f"Fee {fee} ({fee/MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}) "
                    f"below minimum {min_fee} ({min_fee/MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}) "
                    f"for {tx_type.value}"
                )

        super().__init__(
            version_number=2,
            list_of_inputs=[self._serialize_to_input()],
            list_of_outputs=[self._serialize_to_output()],
            fee=fee
        )

    def _serialize_to_input(self) -> str:
        """Serialize futures data for hashing (input side)"""
        return (
            f"{self.trade_id}"
            f"{self.tx_type.value}"
            f"{self.party_a or ''}"
            f"{self.party_b or ''}"
            f"{self.timestamp}"
        )

    def _serialize_to_output(self) -> str:
        """Serialize futures data for hashing (output side)"""
        return (
            f"{self.template_type.value if self.template_type else ''}"
            f"{self.asset_pair or ''}"
            f"{self.strike_price or 0}"
            f"{self.expiry_timestamp or 0}"
            f"{self.collateral_amount or 0}"
            f"{self.state.value}"
        )

    def get_signing_data(self) -> bytes:
        """Return the canonical bytes to be signed for this transaction."""
        data = (
            str(self.trade_id) +
            str(self.tx_type.value) +
            str(self.party_a or '') +
            str(self.party_b or '') +
            str(self.template_type.value if self.template_type else '') +
            str(self.asset_pair or '') +
            str(self.strike_price or 0) +
            str(self.expiry_timestamp or 0) +
            str(self.collateral_amount or 0) +
            str(self.state.value) +
            str(self.settlement_price or 0) +
            str(self.winner or '') +
            str(self.winner_payout or 0) +
            str(self.loser_payout or 0) +
            str(self.fee or 0) +
            str(self.timestamp) +
            str(self.oracle_price or 0) +
            str(self.oracle_timestamp or 0) +
            str(self.oracle_signature or '') +
            str(self.oracle_pubkey or '')
        )
        return data.encode('utf-8')

    def to_dict(self) -> dict:
        """Convert to dictionary for storage/transmission"""
        return {
            'transaction_hash': self.TransactionHash,
            'trade_id': self.trade_id,
            'tx_type': self.tx_type.value,
            'party_a': self.party_a,
            'party_b': self.party_b,
            'template_type': self.template_type.value if self.template_type else None,
            'asset_pair': self.asset_pair,
            'strike_price': self.strike_price,
            'expiry_timestamp': self.expiry_timestamp,
            'collateral_amount': self.collateral_amount,
            'state': self.state.value,
            'settlement_price': self.settlement_price,
            'winner': self.winner,
            'winner_payout': self.winner_payout,
            'loser_payout': self.loser_payout,
            'fee': self.fee,
            'timestamp': self.timestamp
        }

    def print_transaction(self):
        """Print futures transaction details"""
        print(f"\n{'='*60}")
        print(f"FUTURES TRANSACTION: {self.tx_type.value.upper()}")
        print(f"{'='*60}")
        print(f"Transaction Hash: {self.TransactionHash}")
        print(f"Trade ID: {self.trade_id}")
        print(f"State: {self.state.value}")
        print(f"Fee: {self.fee / MILLI_DENOMINATION:.3f} {CRYPTOCURRENCY_NAME}")
        print(f"Party A: {self.party_a[:20] if self.party_a else 'N/A'}...")
        print(f"Party B: {self.party_b[:20] if self.party_b else 'N/A'}...")

        if self.template_type:
            print(f"Template: {self.template_type.value}")
            print(f"Asset Pair: {self.asset_pair}")
            print(f"Strike Price: ${self.strike_price:,.2f}")

            if self.expiry_timestamp:
                print(f"Expiry: {datetime.fromtimestamp(self.expiry_timestamp)}")

            if self.collateral_amount:
                coins = self.collateral_amount / MILLI_DENOMINATION
                print(f"Collateral: {coins:.3f} {CRYPTOCURRENCY_NAME} (each party)")

        if self.settlement_price:
            print(f"\n--- SETTLEMENT ---")
            print(f"Settlement Price: ${self.settlement_price:,.2f}")
            print(f"Winner: {self.winner[:20] if self.winner else 'N/A'}...")
            if self.winner_payout:
                print(f"Winner Payout: {self.winner_payout / MILLI_DENOMINATION:.3f} {CRYPTOCURRENCY_NAME}")

        print(f"Timestamp: {datetime.fromtimestamp(self.timestamp)}")
        print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Transaction helper factories
# ---------------------------------------------------------------------------

def create_propose_trade_transaction(trade_id: str,
                                     party_a: str,
                                     template_type: TemplateType,
                                     asset_pair: str,
                                     strike_price: float,
                                     expiry_hours: int,
                                     collateral_amount: int,
                                     fee: int = None,
                                     high_priority: bool = False,
                                     privkey_hex: str = None) -> FuturesTransaction:
    """
    Create a trade proposal transaction.
    Party A's collateral will be locked when this tx is processed.
    """
    expiry_timestamp = int(time.time()) + (expiry_hours * 3600)
    if fee is None:
        min_fee = MINIMUM_FEES[TransactionType.PROPOSE_TRADE]
        fee = min_fee * HIGH_PRIORITY_MULTIPLIER if high_priority else min_fee

    tx = FuturesTransaction(
        trade_id=trade_id,
        tx_type=TransactionType.PROPOSE_TRADE,
        party_a=party_a,
        template_type=template_type,
        asset_pair=asset_pair,
        strike_price=strike_price,
        expiry_timestamp=expiry_timestamp,
        collateral_amount=collateral_amount,
        state=TradeState.PROPOSED,
        fee=fee
    )
    if privkey_hex:
        sk = get_signing_key_from_hex(privkey_hex)
        tx.signature = sign_message(sk, tx.get_signing_data())
        tx.pubkey = get_compressed_pubkey(sk.verifying_key)
    return tx


def create_accept_trade_transaction(trade_id: str,
                                    party_b: str,
                                    fee: int = None,
                                    high_priority: bool = False,
                                    privkey_hex: str = None) -> FuturesTransaction:
    """
    Create a trade acceptance transaction.
    Party B's collateral will be locked when this tx is processed,
    and the trade transitions directly to ACTIVE.
    """
    if fee is None:
        min_fee = MINIMUM_FEES[TransactionType.ACCEPT_TRADE]
        fee = min_fee * HIGH_PRIORITY_MULTIPLIER if high_priority else min_fee

    tx = FuturesTransaction(
        trade_id=trade_id,
        tx_type=TransactionType.ACCEPT_TRADE,
        party_b=party_b,
        state=TradeState.ACTIVE,   # skips ACCEPTED; goes straight to ACTIVE
        fee=fee
    )
    if privkey_hex:
        sk = get_signing_key_from_hex(privkey_hex)
        tx.signature = sign_message(sk, tx.get_signing_data())
        tx.pubkey = get_compressed_pubkey(sk.verifying_key)
    return tx


def create_cancel_proposal_transaction(trade_id: str,
                                       fee: int = None,
                                       high_priority: bool = False,
                                       privkey_hex: str = None) -> 'FuturesTransaction':
    """
    Create a transaction that cancels a PROPOSED (not yet accepted) trade.

    Only valid while the trade is in PROPOSED state. Processing this tx
    returns party_a's locked collateral and moves the trade to CANCELLED.
    Has no effect if the trade has already been accepted (ACTIVE).

    Args:
        trade_id: ID of the proposed trade to cancel
        privkey_hex: Optional hex private key for signing

    Returns:
        A signed or unsigned FuturesTransaction of type CANCEL_PROPOSAL
    """
    if fee is None:
        min_fee = MINIMUM_FEES[TransactionType.CANCEL_PROPOSAL]
        fee = min_fee * HIGH_PRIORITY_MULTIPLIER if high_priority else min_fee

    tx = FuturesTransaction(
        trade_id=trade_id,
        tx_type=TransactionType.CANCEL_PROPOSAL,
        state=TradeState.CANCELLED,
        fee=fee
    )
    if privkey_hex:
        sk = get_signing_key_from_hex(privkey_hex)
        tx.signature = sign_message(sk, tx.get_signing_data())
        tx.pubkey = get_compressed_pubkey(sk.verifying_key)
    return tx

def create_settle_trade_transaction(trade_id: str,
                                    oracle_price: float,
                                    oracle_timestamp: int,
                                    oracle_signature: str,
                                    oracle_pubkey: str,
                                    fee: int = None,
                                    high_priority: bool = False,
                                    privkey_hex: str = None) -> FuturesTransaction:

    if fee is None:
        min_fee = MINIMUM_FEES[TransactionType.SETTLE_TRADE]
        fee = min_fee * HIGH_PRIORITY_MULTIPLIER if high_priority else min_fee

    tx = FuturesTransaction(
        trade_id=trade_id,
        tx_type=TransactionType.SETTLE_TRADE,
        oracle_price=oracle_price,
        oracle_timestamp=oracle_timestamp,
        oracle_signature=oracle_signature,
        oracle_pubkey=oracle_pubkey,
        state=TradeState.SETTLED,
        fee=fee
    )

    if privkey_hex:
        sk = get_signing_key_from_hex(privkey_hex)
        tx.signature = sign_message(sk, tx.get_signing_data())
        tx.pubkey = get_compressed_pubkey(sk.verifying_key)

    return tx

# def create_settle_trade_transaction(trade_id: str,
#                                     settlement_price: float,
#                                     winner: str,
#                                     winner_payout: int,
#                                     loser_payout: int = 0,
#                                     fee: int = None,
#                                     high_priority: bool = False,
#                                     privkey_hex: str = None) -> FuturesTransaction:
#     """
#     Create a settlement transaction.
#     """
#     if fee is None:
#         min_fee = MINIMUM_FEES[TransactionType.SETTLE_TRADE]
#         fee = min_fee * HIGH_PRIORITY_MULTIPLIER if high_priority else min_fee

#     tx = FuturesTransaction(
#         trade_id=trade_id,
#         tx_type=TransactionType.SETTLE_TRADE,
#         settlement_price=settlement_price,
#         winner=winner,
#         winner_payout=winner_payout,
#         loser_payout=loser_payout,
#         state=TradeState.SETTLED,
#         fee=fee
#     )
#     if privkey_hex:
#         sk = get_signing_key_from_hex(privkey_hex)
#         tx.signature = sign_message(sk, tx.get_signing_data())
#         tx.pubkey = get_compressed_pubkey(sk.verifying_key)
#     return tx


def create_cancel_trade_transaction(trade_id: str,
                                    party_a: str,
                                    fee: int = None,
                                    high_priority: bool = False,
                                    privkey_hex: str = None) -> FuturesTransaction:
    """
    Create a cancellation transaction for an ACTIVE trade.
    """
    if fee is None:
        min_fee = MINIMUM_FEES[TransactionType.CANCEL_TRADE]
        fee = min_fee * HIGH_PRIORITY_MULTIPLIER if high_priority else min_fee

    tx = FuturesTransaction(
        trade_id=trade_id,
        tx_type=TransactionType.CANCEL_TRADE,
        party_a=party_a,
        state=TradeState.CANCELLED,
        fee=fee
    )
    if privkey_hex:
        sk = get_signing_key_from_hex(privkey_hex)
        tx.signature = sign_message(sk, tx.get_signing_data())
        tx.pubkey = get_compressed_pubkey(sk.verifying_key)
    return tx
