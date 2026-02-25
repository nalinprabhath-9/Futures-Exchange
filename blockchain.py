import hashlib
import time
import random
from datetime import datetime
from typing import List, Dict, Optional

from transaction_enums import TransactionType, TradeState, TemplateType


CRYPTOCURRENCY_NAME = "FutureCoin"
MILLI_DENOMINATION = 1000
MAX_TXNS_PER_BLOCK = 10
COINBASE_REWARD = 50000

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
                 list_of_outputs = None):
        """
        Initialize a transaction
        
        Args:
            version_number: Transaction version (default 1)
            list_of_inputs: List of input strings
            list_of_outputs: List of output strings OR Output objects
        """
        self.VersionNumber = version_number
        self.ListOfInputs = list_of_inputs if list_of_inputs else []
        self.ListOfOutputs = list_of_outputs if list_of_outputs else []
        self.InCounter = len(self.ListOfInputs)
        self.OutCounter = len(self.ListOfOutputs)
        
        self.TransactionHash = self._calculate_hash()
    
    def _calculate_hash(self) -> str:
        """
        Calculate the transaction hash using double SHA-256
        Hashes: VersionNumber + InCounter + ListOfInputs + OutCounter + ListOfOutputs
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
            outputs_str
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
        Calculate the Merkle root from all transactions
        For simplicity, we'll hash all transaction hashes together
        (A full Merkle tree implementation would pair and hash recursively)
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
        Calculate the block hash from header fields
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
    Manages FutureCoin balances and locked collateral
    """
    
    def __init__(self):
        """Initialize balance tracking"""
        self.balances = {}        # address -> total milli-coins
        self.locked = {}          # address -> locked milli-coins
        self.trade_locks = {}     # trade_id -> {party_a: amount, party_b: amount}
    
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
        total = self.get_total_balance(address)
        locked = self.get_locked_balance(address)
        return total - locked
    
    def lock_collateral(self, trade_id: str, party_a: str, party_b: str, amount: int) -> bool:
        """
        Lock collateral for both parties in a trade
        
        Returns:
            True if successful, False if insufficient balance
        """
        # Check both parties have sufficient available balance
        if self.get_available_balance(party_a) < amount:
            print(f"Insufficient balance for {party_a[:20]}...")
            return False
        
        if self.get_available_balance(party_b) < amount:
            print(f"Insufficient balance for {party_b[:20]}...")
            return False
        
        # Lock collateral
        if party_a not in self.locked:
            self.locked[party_a] = 0
        if party_b not in self.locked:
            self.locked[party_b] = 0
        
        self.locked[party_a] += amount
        self.locked[party_b] += amount
        
        # Track which trade locked this collateral
        self.trade_locks[trade_id] = {
            'party_a': party_a,
            'party_b': party_b,
            'amount': amount
        }
        
        coins = amount / MILLI_DENOMINATION
        print(f"Locked {coins} {CRYPTOCURRENCY_NAME} for {party_a[:20]}... in trade {trade_id}")
        print(f"Locked {coins} {CRYPTOCURRENCY_NAME} for {party_b[:20]}... in trade {trade_id}")
        
        return True
    
    def settle_trade(self, trade_id: str, winner: str, loser: str, 
                    winner_payout: int, loser_payout: int) -> bool:
        """
        Settle a trade by unlocking and transferring collateral
        
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
        loser_loss = amount - loser_payout  # How much loser loses
        self.balances[loser] -= loser_loss
        self.balances[winner] += loser_loss
        
        # Remove lock tracking
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
        Cancel a trade and unlock collateral (returns to original owners)
        """
        if trade_id not in self.trade_locks:
            return False
        
        lock_info = self.trade_locks[trade_id]
        amount = lock_info['amount']
        
        # Unlock collateral for both parties
        self.locked[lock_info['party_a']] -= amount
        self.locked[lock_info['party_b']] -= amount
        
        # Remove lock tracking
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
    Blockchain class managing a chain of blocks
    NOW SUPPORTS: Mining + Futures Trading
    """
    
    def __init__(self):
        """Initialize blockchain with balance management"""
        self.chain = []
        self.block_height_index = {}
        self.block_hash_index = {}
        self.transaction_index = {}
        
        # NEW: Track futures trades
        self.active_trades = {}    # trade_id -> FuturesTransaction
        self.settled_trades = {}   # trade_id -> FuturesTransaction
        
        # NEW: Balance manager
        self.balances = BalanceManager()
        
        print("Blockchain initialized (genesis block will be mined)")
        print("Futures trading enabled!")
    
    def add_block(self, block: Block):
        """
        Add a block to the blockchain and process all transactions
        """
        height = len(self.chain)
        self.chain.append(block)
        self.block_height_index[height] = block
        self.block_hash_index[block.Blockhash] = block
        
        # Process all transactions in the block
        for tx_hash, tx in block.Transactions.items():
            self.transaction_index[tx_hash] = (block, tx)
            self._process_transaction(tx)
        
        print(f"Block #{height} added to blockchain")
    
    def _process_transaction(self, tx: Transaction):
        """
        Process a transaction based on its type
        """
        # Check if it's a coinbase transaction (mining reward)
        if len(tx.ListOfInputs) > 0 and "Coinbase" in tx.ListOfInputs[0]:
            # Extract miner address from outputs
            if tx.ListOfOutputs and isinstance(tx.ListOfOutputs[0], Output):
                miner_address = tx.ListOfOutputs[0].Script
                reward = tx.ListOfOutputs[0].Value
                self.balances.add_mining_reward(miner_address, reward)
        
        # Check if it's a futures transaction
        elif isinstance(tx, FuturesTransaction):
            self._process_futures_transaction(tx)
    
    def _process_futures_transaction(self, tx):
        """Process futures-specific transactions"""
        
        if tx.tx_type == TransactionType.PROPOSE_TRADE:
            # Store proposed trade
            self.active_trades[tx.trade_id] = tx
            print(f"Trade {tx.trade_id} proposed by {tx.party_a[:20]}...")
        
        elif tx.tx_type == TransactionType.ACCEPT_TRADE:
            # Update trade with party B
            if tx.trade_id in self.active_trades:
                self.active_trades[tx.trade_id].party_b = tx.party_b
                self.active_trades[tx.trade_id].state = TradeState.ACCEPTED
                print(f"Trade {tx.trade_id} accepted by {tx.party_b[:20]}...")
        
        elif tx.tx_type == TransactionType.DEPOSIT_COLLATERAL:
            # Lock collateral when both parties deposit
            if tx.trade_id in self.active_trades:
                trade = self.active_trades[tx.trade_id]
                
                # Check if both parties have accepted
                if trade.party_a and trade.party_b:
                    success = self.balances.lock_collateral(
                        tx.trade_id,
                        trade.party_a,
                        trade.party_b,
                        trade.collateral_amount
                    )
                    
                    if success:
                        trade.state = TradeState.ACTIVE
                        print(f"Trade {tx.trade_id} is now ACTIVE")
        
        elif tx.tx_type == TransactionType.SETTLE_TRADE:
            # Settle the trade
            if tx.trade_id in self.active_trades:
                trade = self.active_trades[tx.trade_id]
                
                self.balances.settle_trade(
                    tx.trade_id,
                    tx.winner,
                    trade.party_a if tx.winner == trade.party_b else trade.party_b,
                    tx.winner_payout,
                    tx.loser_payout or 0
                )
                
                # Move to settled trades
                trade.state = TradeState.SETTLED
                trade.settlement_price = tx.settlement_price
                trade.winner = tx.winner
                self.settled_trades[tx.trade_id] = trade
                del self.active_trades[tx.trade_id]
        
        elif tx.tx_type == TransactionType.CANCEL_TRADE:
            # Cancel the trade
            if tx.trade_id in self.active_trades:
                self.balances.cancel_trade(tx.trade_id)
                trade = self.active_trades[tx.trade_id]
                trade.state = TradeState.CANCELLED
                del self.active_trades[tx.trade_id]
    
    def get_active_trades(self) -> List['FuturesTransaction']:
        """Get all active futures trades"""
        return list(self.active_trades.values())
    
    def get_trade(self, trade_id: str) -> Optional['FuturesTransaction']:
        """Get a specific trade by ID"""
        if trade_id in self.active_trades:
            return self.active_trades[trade_id]
        if trade_id in self.settled_trades:
            return self.settled_trades[trade_id]
        return None
    
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
        if result:
            block, transaction = result
            return transaction
        return None
    
    def print_blockchain(self):
        """Print the entire blockchain with futures info"""
        print(f"\n{'*'*70}")
        print(f"BLOCKCHAIN SUMMARY - {CRYPTOCURRENCY_NAME} FUTURES EXCHANGE")
        print(f"{'*'*70}")
        print(f"Total Blocks: {len(self.chain)}")
        print(f"Total Transactions: {len(self.transaction_index)}")
        print(f"Active Trades: {len(self.active_trades)}")
        print(f"Settled Trades: {len(self.settled_trades)}")
        print(f"{'*'*70}\n")
        
        for i, block in enumerate(self.chain):
            print(f"Block Height: {i}")
            block.print_block()

class TxnMemoryPool:
    """
    Transaction Memory Pool (Mempool)
    Stores pending transactions before they are added to blocks
    """
    
    def __init__(self):
        """Initialize an empty memory pool"""
        self.transactions = []
    
    def add_transaction(self, transaction: Transaction):
        """Add a transaction to the memory pool"""
        self.transactions.append(transaction)
        print(f"Added transaction {transaction.TransactionHash[:16]}... to mempool (size: {len(self.transactions)})")
    
    def get_transactions(self, count: int) -> List[Transaction]:
        """
        Get up to 'count' transactions from the mempool
        Removes them from the pool (simulating adding to block)
        
        Args:
            count: Maximum number of transactions to retrieve
            
        Returns:
            List of transactions (up to count)
        """
        result = self.transactions[:count]
        self.transactions = self.transactions[count:]
        return result
    
    def size(self) -> int:
        """Return the number of transactions in the mempool"""
        return len(self.transactions)
    
    def clear(self):
        """Clear all transactions from the mempool"""
        self.transactions = []

class Miner:
    """
    Miner class that creates blocks from transactions in the mempool
    Implements proof-of-work mining with difficulty target
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
        Calculate target from compact difficulty bits format
        Target = coefficient * 2^(8 * (exponent - 3))
        
        Args:
            bits: Difficulty bits in compact format (e.g., 0x207fffff)
            
        Returns:
            Target as an integer
        """
        exponent = bits >> 24
        coefficient = bits & 0xffffff
        target = coefficient * (2 ** (8 * (exponent - 3)))
        
        return target
    
    def create_coinbase_transaction(self, block_height: int) -> Transaction:
        """
        Create a coinbase transaction (mining reward)
        
        Args:
            block_height: Height of the block being mined
            
        Returns:
            Coinbase transaction
        """
        coinbase_input = f"Coinbase for block {block_height} - {int(time.time())}"
        coinbase_output = Output(
            value=COINBASE_REWARD,
            index=0,
            script=self.miner_address
        )
        coinbase_tx = Transaction(
            version_number=1,
            list_of_inputs=[coinbase_input],
            list_of_outputs=[coinbase_output]
        )
        
        return coinbase_tx
    
    def _hash_meets_target(self, block_hash: str) -> bool:
        """
        Check if a block hash meets the difficulty target
        
        Args:
            block_hash: Block hash as hex string
            
        Returns:
            True if hash < target, False otherwise
        """
        hash_int = int(block_hash, 16)
        return hash_int < self.target
    
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
        max_regular_txns = MAX_TXNS_PER_BLOCK - 1
        transactions = mempool.get_transactions(max_regular_txns)
        
        if verbose:
            print(f"Retrieved {len(transactions)} transactions from mempool")
            print(f"Mempool remaining: {mempool.size()} transactions")
        
        if block_height == 0:
            previous_hash = "0" * 64
        else:
            previous_hash = blockchain.chain[-1].Blockhash
        
        new_block = Block(previous_block_hash=previous_hash)
        new_block.BlockHeader.Bits = self.difficulty_bits
        new_block.add_transaction(coinbase_tx)
        
        for tx in transactions:
            new_block.add_transaction(tx)
        
        if verbose:
            print(f"Starting proof-of-work mining...")
            print(f"Target: {hex(self.target)}")
        
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
        
        end_time = time.time()
        elapsed = end_time - start_time
        hash_rate = hashes_this_block / elapsed if elapsed > 0 else 0
        
        self.blocks_mined += 1
        
        if verbose:
            print(f"\n{'='*70}")
            print(f"BLOCK MINED SUCCESSFULLY!")
            print(f"{'='*70}")
            print(f"Block height: {block_height}")
            print(f"Block hash: {new_block.Blockhash}")
            print(f"Nonce found: {nonce}")
            print(f"Total hashes: {hashes_this_block:,}")
            print(f"Time elapsed: {elapsed:.2f} seconds")
            print(f"Hash rate: {hash_rate:,.0f} H/s")
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
    
    num_outputs = random.randint(1, 3)
    outputs = []
    
    for i in range(num_outputs):
        value = random.randint(100, 5000)
        
        script_data = f"address_{random.randint(1000, 9999)}"
        script = hashlib.sha256(script_data.encode()).hexdigest()
        
        output = Output(value=value, index=i, script=script)
        outputs.append(output)
    
    tx = Transaction(
        version_number=1,
        list_of_inputs=[input_hash],
        list_of_outputs=outputs
    )
    
    return tx

class FuturesTransaction(Transaction):
    """
    Futures trade transaction - extends base Transaction class
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
                 loser_payout: int = None):
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
        
        # Use base Transaction for hash calculation
        # Serialize futures data as inputs/outputs
        inputs = [self._serialize_to_input()]
        outputs = [self._serialize_to_output()]
        
        super().__init__(
            version_number=2,  # Version 2 for futures transactions
            list_of_inputs=inputs,
            list_of_outputs=outputs
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
        print(f"Party A: {self.party_a[:20] if self.party_a else 'N/A'}...")
        print(f"Party B: {self.party_b[:20] if self.party_b else 'N/A'}...")
        
        if self.template_type:
            print(f"Template: {self.template_type.value}")
            print(f"Asset Pair: {self.asset_pair}")
            print(f"Strike Price: ${self.strike_price:,.2f}")
            
            if self.expiry_timestamp:
                expiry_dt = datetime.fromtimestamp(self.expiry_timestamp)
                print(f"Expiry: {expiry_dt}")
            
            if self.collateral_amount:
                coins = self.collateral_amount / MILLI_DENOMINATION
                print(f"Collateral: {coins:.3f} {CRYPTOCURRENCY_NAME} (each party)")
        
        if self.settlement_price:
            print(f"\n--- SETTLEMENT ---")
            print(f"Settlement Price: ${self.settlement_price:,.2f}")
            print(f"Winner: {self.winner[:20] if self.winner else 'N/A'}...")
            if self.winner_payout:
                winner_coins = self.winner_payout / MILLI_DENOMINATION
                print(f"Winner Payout: {winner_coins:.3f} {CRYPTOCURRENCY_NAME}")
        
        print(f"Timestamp: {datetime.fromtimestamp(self.timestamp)}")
        print(f"{'='*60}")



def create_propose_trade_transaction(trade_id: str,
                                    party_a: str,
                                    template_type: TemplateType,
                                    asset_pair: str,
                                    strike_price: float,
                                    expiry_hours: int,
                                    collateral_amount: int) -> FuturesTransaction:
    """
    Helper to create a trade proposal transaction
    
    Args:
        trade_id: Unique identifier
        party_a: Proposer's address
        template_type: UP_DOWN, LONG_SHORT, etc.
        asset_pair: e.g., "BTC/USD"
        strike_price: Reference price
        expiry_hours: Hours until expiry
        collateral_amount: Milli-coins each party stakes
    
    Returns:
        FuturesTransaction
    """
    expiry_timestamp = int(time.time()) + (expiry_hours * 3600)
    
    return FuturesTransaction(
        trade_id=trade_id,
        tx_type=TransactionType.PROPOSE_TRADE,
        party_a=party_a,
        template_type=template_type,
        asset_pair=asset_pair,
        strike_price=strike_price,
        expiry_timestamp=expiry_timestamp,
        collateral_amount=collateral_amount,
        state=TradeState.PROPOSED
    )

def create_accept_trade_transaction(trade_id: str, party_b: str) -> FuturesTransaction:
    """Helper to create a trade acceptance transaction"""
    return FuturesTransaction(
        trade_id=trade_id,
        tx_type=TransactionType.ACCEPT_TRADE,
        party_b=party_b,
        state=TradeState.ACCEPTED
    )

def create_deposit_collateral_transaction(trade_id: str) -> FuturesTransaction:
    """Helper to create a collateral deposit transaction"""
    return FuturesTransaction(
        trade_id=trade_id,
        tx_type=TransactionType.DEPOSIT_COLLATERAL,
        state=TradeState.COLLATERAL_LOCKED
    )

def create_settle_trade_transaction(trade_id: str,
                                   settlement_price: float,
                                   winner: str,
                                   winner_payout: int,
                                   loser_payout: int = 0) -> FuturesTransaction:
    """Helper to create a settlement transaction"""
    return FuturesTransaction(
        trade_id=trade_id,
        tx_type=TransactionType.SETTLE_TRADE,
        settlement_price=settlement_price,
        winner=winner,
        winner_payout=winner_payout,
        loser_payout=loser_payout,
        state=TradeState.SETTLED
    )