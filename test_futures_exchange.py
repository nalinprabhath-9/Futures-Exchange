"""
Comprehensive tests and examples for the FutureCoin Futures Exchange blockchain
Demonstrates mining, trading, and settlement workflows
"""

from blockchain import (
    Blockchain, 
    Miner, 
    TxnMemoryPool, 
    CRYPTOCURRENCY_NAME,
    MILLI_DENOMINATION,
    create_propose_trade_transaction,
    create_accept_trade_transaction,
    create_deposit_collateral_transaction,
    create_settle_trade_transaction
)
from transaction_enums import TradeState, TemplateType


def print_separator(title=""):
    """Print a visual separator"""
    print("\n" + "="*80)
    if title:
        print(f"  {title}")
        print("="*80)
    print()


def test_basic_mining():
    """Test 1: Basic mining functionality"""
    print_separator("TEST 1: BASIC MINING")
    
    blockchain = Blockchain()
    mempool = TxnMemoryPool()
    
    # Create miners
    alice = Miner(miner_address="Alice_0x1234abcd", difficulty_bits=0x207fffff)
    bob = Miner(miner_address="Bob_0x5678efgh", difficulty_bits=0x207fffff)
    
    # Mine genesis block
    print("Alice mining genesis block...")
    genesis = alice.mine_block(blockchain, mempool, verbose=True)
    blockchain.add_block(genesis)
    
    # Mine second block
    print("\nBob mining block 1...")
    block_1 = bob.mine_block(blockchain, mempool, verbose=True)
    blockchain.add_block(block_1)
    
    # Check balances
    print("\n--- BALANCES AFTER MINING ---")
    blockchain.balances.print_balance("Alice_0x1234abcd")
    blockchain.balances.print_balance("Bob_0x5678efgh")
    
    assert blockchain.balances.get_total_balance("Alice_0x1234abcd") == 50000
    assert blockchain.balances.get_total_balance("Bob_0x5678efgh") == 50000
    
    print("TEST 1 PASSED: Basic mining works correctly")
    return blockchain, mempool, alice, bob


def test_simple_futures_trade(blockchain, mempool, alice, bob):
    """Test 2: Simple UP/DOWN futures trade"""
    print_separator("TEST 2: SIMPLE FUTURES TRADE (UP/DOWN)")
    
    alice_addr = alice.miner_address
    bob_addr = bob.miner_address
    
    # Step 1: Alice proposes trade
    print("STEP 1: Alice proposes BTC will go UP")
    trade_proposal = create_propose_trade_transaction(
        trade_id="TRADE_001",
        party_a=alice_addr,
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=50000.00,
        expiry_hours=1,
        collateral_amount=10000  # 10 FutureCoins
    )
    trade_proposal.print_transaction()
    mempool.add_transaction(trade_proposal)
    
    # Step 2: Bob accepts (takes opposite side - DOWN)
    print("\nSTEP 2: Bob accepts trade (betting DOWN)")
    trade_accept = create_accept_trade_transaction(
        trade_id="TRADE_001",
        party_b=bob_addr
    )
    trade_accept.print_transaction()
    mempool.add_transaction(trade_accept)
    
    # Mine block with proposal and acceptance
    print("\nMining block with trade transactions...")
    block_2 = alice.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block_2)
    
    # Step 3: Deposit collateral
    print("\nSTEP 3: Both parties deposit collateral")
    deposit_tx = create_deposit_collateral_transaction("TRADE_001")
    mempool.add_transaction(deposit_tx)
    
    # Mine block with deposit
    block_3 = bob.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block_3)
    
    # Check balances after locking
    print("\n--- BALANCES AFTER COLLATERAL LOCK ---")
    blockchain.balances.print_balance(alice_addr)
    blockchain.balances.print_balance(bob_addr)
    
    # Verify collateral is locked
    assert blockchain.balances.get_locked_balance(alice_addr) == 10000
    assert blockchain.balances.get_locked_balance(bob_addr) == 10000
    assert blockchain.balances.get_available_balance(alice_addr) == 90000  # 50k initial + 50k from mining block_2 - 10k locked
    assert blockchain.balances.get_available_balance(bob_addr) == 90000   # 50k initial + 50k from mining block_3 - 10k locked
    
    # Step 4: Simulate expiry and settlement (Alice wins)
    print("\nSTEP 4: Trade expires - Oracle reports BTC went UP to $52,000")
    print("Result: Alice WINS!")
    
    settle_tx = create_settle_trade_transaction(
        trade_id="TRADE_001",
        settlement_price=52000.00,
        winner=alice_addr,
        winner_payout=20000,  # Gets both collaterals
        loser_payout=0
    )
    settle_tx.print_transaction()
    mempool.add_transaction(settle_tx)
    
    # Mine settlement block
    block_4 = alice.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block_4)
    
    # Final balances
    print("\n--- FINAL BALANCES ---")
    blockchain.balances.print_balance(alice_addr)
    blockchain.balances.print_balance(bob_addr)
    
    # Verify settlement
    alice_total = blockchain.balances.get_total_balance(alice_addr)
    bob_total = blockchain.balances.get_total_balance(bob_addr)
    
    # Alice: 50k (genesis) + 50k (block_2) + 50k (block_4) + 10k (won from Bob) = 160k
    # Bob: 50k (initial) + 50k (block_3) - 10k (lost to Alice) = 90k
    assert alice_total == 160000, f"Alice should have 160k, has {alice_total}"
    assert bob_total == 90000, f"Bob should have 90k, has {bob_total}"
    
    print("TEST 2 PASSED: Simple futures trade completed successfully")
    return blockchain, mempool


def test_multiple_trades(blockchain, mempool, alice, bob):
    """Test 3: Multiple concurrent trades"""
    print_separator("TEST 3: MULTIPLE CONCURRENT TRADES")
    
    alice_addr = alice.miner_address
    bob_addr = bob.miner_address
    
    # Create third miner
    charlie = Miner(miner_address="Charlie_0x9999zzzz", difficulty_bits=0x207fffff)
    
    # Charlie mines to get initial balance
    print("Charlie mining to get initial balance...")
    block = charlie.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    print("\n--- INITIAL BALANCES ---")
    blockchain.balances.print_balance(alice_addr)
    blockchain.balances.print_balance(bob_addr)
    blockchain.balances.print_balance(charlie.miner_address)
    
    # Trade 1: Alice vs Bob on ETH/USD
    print("\nTRADE 2: Alice proposes ETH will go UP")
    trade_2 = create_propose_trade_transaction(
        trade_id="TRADE_002",
        party_a=alice_addr,
        template_type=TemplateType.UP_DOWN,
        asset_pair="ETH/USD",
        strike_price=3000.00,
        expiry_hours=2,
        collateral_amount=5000
    )
    mempool.add_transaction(trade_2)
    
    accept_2 = create_accept_trade_transaction("TRADE_002", bob_addr)
    mempool.add_transaction(accept_2)
    
    # Trade 2: Alice vs Charlie on SOL/USD
    print("\nTRADE 3: Alice proposes SOL will go DOWN")
    trade_3 = create_propose_trade_transaction(
        trade_id="TRADE_003",
        party_a=alice_addr,
        template_type=TemplateType.UP_DOWN,
        asset_pair="SOL/USD",
        strike_price=100.00,
        expiry_hours=3,
        collateral_amount=8000
    )
    mempool.add_transaction(trade_3)
    
    accept_3 = create_accept_trade_transaction("TRADE_003", charlie.miner_address)
    mempool.add_transaction(accept_3)
    
    # Mine block with both trades
    print("\nMining block with multiple trades...")
    block = alice.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    # Deposit collateral for both trades
    print("\nDepositing collateral for both trades...")
    deposit_2 = create_deposit_collateral_transaction("TRADE_002")
    deposit_3 = create_deposit_collateral_transaction("TRADE_003")
    mempool.add_transaction(deposit_2)
    mempool.add_transaction(deposit_3)
    
    block = bob.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    # Check active trades
    active_trades = blockchain.get_active_trades()
    print(f"\n--- ACTIVE TRADES: {len(active_trades)} ---")
    for trade in active_trades:
        print(f"  - {trade.trade_id}: {trade.asset_pair} ({trade.state.value})")
    
    # Check locked balances
    print("\n--- BALANCES WITH MULTIPLE LOCKED TRADES ---")
    blockchain.balances.print_balance(alice_addr)
    
    # Alice has 13k locked (5k + 8k from both trades)
    assert blockchain.balances.get_locked_balance(alice_addr) == 13000
    
    print("TEST 3 PASSED: Multiple concurrent trades work correctly")
    return blockchain, mempool, charlie


def test_insufficient_balance(blockchain, mempool, alice, bob):
    """Test 4: Handle insufficient balance for collateral"""
    print_separator("TEST 4: INSUFFICIENT BALANCE HANDLING")
    
    alice_addr = alice.miner_address
    bob_addr = bob.miner_address
    
    # Try to create trade with more collateral than available
    alice_available = blockchain.balances.get_available_balance(alice_addr)
    print(f"Alice's available balance: {alice_available / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}")
    
    excessive_collateral = alice_available + 10000
    print(f"\nAttempting to create trade requiring {excessive_collateral / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}...")
    
    trade_excessive = create_propose_trade_transaction(
        trade_id="TRADE_EXCESSIVE",
        party_a=alice_addr,
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=50000.00,
        expiry_hours=1,
        collateral_amount=excessive_collateral
    )
    mempool.add_transaction(trade_excessive)
    
    accept_excessive = create_accept_trade_transaction("TRADE_EXCESSIVE", bob_addr)
    mempool.add_transaction(accept_excessive)
    
    # Mine block
    block = alice.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    # Try to deposit (should fail)
    print("\nAttempting to deposit collateral...")
    deposit_excessive = create_deposit_collateral_transaction("TRADE_EXCESSIVE")
    mempool.add_transaction(deposit_excessive)
    
    block = bob.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    # Trade should still be in ACCEPTED state, not ACTIVE
    trade = blockchain.get_trade("TRADE_EXCESSIVE")
    print(f"\nTrade state after deposit attempt: {trade.state.value}")
    assert trade.state != TradeState.ACTIVE
    
    print("TEST 4 PASSED: Insufficient balance handled correctly")


def test_settlement_scenarios():
    """Test 5: Different settlement scenarios"""
    print_separator("TEST 5: SETTLEMENT SCENARIOS")
    
    # Fresh blockchain for clean test
    blockchain = Blockchain()
    mempool = TxnMemoryPool()
    
    trader_a = Miner(miner_address="TraderA_addr", difficulty_bits=0x207fffff)
    trader_b = Miner(miner_address="TraderB_addr", difficulty_bits=0x207fffff)
    
    # Mine initial blocks
    for i in range(2):
        if i % 2 == 0:
            block = trader_a.mine_block(blockchain, mempool, verbose=False)
        else:
            block = trader_b.mine_block(blockchain, mempool, verbose=False)
        blockchain.add_block(block)
    
    print("Initial balances:")
    blockchain.balances.print_balance(trader_a.miner_address)
    blockchain.balances.print_balance(trader_b.miner_address)
    
    # Scenario 1: Trader A wins (price goes UP)
    print("\n--- SCENARIO 1: Price goes UP (Trader A wins) ---")
    
    trade = create_propose_trade_transaction(
        trade_id="SCENARIO_1",
        party_a=trader_a.miner_address,
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=50000.00,
        expiry_hours=1,
        collateral_amount=10000
    )
    mempool.add_transaction(trade)
    mempool.add_transaction(create_accept_trade_transaction("SCENARIO_1", trader_b.miner_address))
    
    block = trader_a.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    mempool.add_transaction(create_deposit_collateral_transaction("SCENARIO_1"))
    block = trader_b.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    # Settlement: Price went UP to 55,000
    settle = create_settle_trade_transaction(
        trade_id="SCENARIO_1",
        settlement_price=55000.00,
        winner=trader_a.miner_address,
        winner_payout=20000,
        loser_payout=0
    )
    mempool.add_transaction(settle)
    block = trader_a.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    print("\nFinal balances:")
    blockchain.balances.print_balance(trader_a.miner_address)
    blockchain.balances.print_balance(trader_b.miner_address)
    
    # Verify
    settled_trade = blockchain.get_trade("SCENARIO_1")
    assert settled_trade.state == TradeState.SETTLED
    assert settled_trade.winner == trader_a.miner_address
    assert settled_trade.settlement_price == 55000.00
    
    print("TEST 5 PASSED: Settlement scenarios work correctly")


def test_blockchain_state():
    """Test 6: Blockchain state tracking"""
    print_separator("TEST 6: BLOCKCHAIN STATE TRACKING")
    
    blockchain = Blockchain()
    mempool = TxnMemoryPool()
    
    miner = Miner(miner_address="Miner_addr", difficulty_bits=0x207fffff)
    
    # Mine multiple blocks
    print("Mining 5 blocks...")
    for i in range(5):
        block = miner.mine_block(blockchain, mempool, verbose=False)
        blockchain.add_block(block)
        print(f"  Block {i} mined")
    
    # Check blockchain state
    print(f"\n--- BLOCKCHAIN STATE ---")
    print(f"Chain length: {len(blockchain.chain)}")
    print(f"Total transactions: {len(blockchain.transaction_index)}")
    print(f"Active trades: {len(blockchain.active_trades)}")
    print(f"Settled trades: {len(blockchain.settled_trades)}")
    
    # Test block retrieval
    genesis = blockchain.get_block_by_height(0)
    print(f"\nGenesis block hash: {genesis.Blockhash}")
    
    latest = blockchain.get_block_by_height(4)
    print(f"Latest block hash: {latest.Blockhash}")
    
    # Verify chain integrity
    print("\nVerifying chain integrity...")
    for i in range(1, len(blockchain.chain)):
        current_block = blockchain.chain[i]
        previous_block = blockchain.chain[i-1]
        
        assert current_block.BlockHeader.hashPrevBlock == previous_block.Blockhash
        print(f"  Block {i} links correctly to Block {i-1} ✓")
    
    print("TEST 6 PASSED: Blockchain state tracking works correctly")


def test_complete_workflow():
    """Test 7: Complete end-to-end workflow"""
    print_separator("TEST 7: COMPLETE END-TO-END WORKFLOW")
    
    print("Initializing blockchain and participants...")
    blockchain = Blockchain()
    mempool = TxnMemoryPool()
    
    # Create participants
    alice = Miner(miner_address="Alice_Wallet", difficulty_bits=0x207fffff)
    bob = Miner(miner_address="Bob_Wallet", difficulty_bits=0x207fffff)
    charlie = Miner(miner_address="Charlie_Wallet", difficulty_bits=0x207fffff)
    
    # Phase 1: Mining for initial capital
    print("\n--- PHASE 1: MINING FOR CAPITAL ---")
    for i in range(3):
        if i == 0:
            miner = alice
            name = "Alice"
        elif i == 1:
            miner = bob
            name = "Bob"
        else:
            miner = charlie
            name = "Charlie"
        
        print(f"{name} mining block {i}...")
        block = miner.mine_block(blockchain, mempool, verbose=False)
        blockchain.add_block(block)
    
    print("\nBalances after mining:")
    for name, miner in [("Alice", alice), ("Bob", bob), ("Charlie", charlie)]:
        balance = blockchain.balances.get_total_balance(miner.miner_address)
        print(f"  {name}: {balance / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}")
    
    # Phase 2: Create multiple trades
    print("\n--- PHASE 2: CREATING TRADES ---")
    
    trades_config = [
        ("TRADE_A", alice.miner_address, bob.miner_address, "BTC/USD", 50000, 5000),
        ("TRADE_B", bob.miner_address, charlie.miner_address, "ETH/USD", 3000, 8000),
        ("TRADE_C", alice.miner_address, charlie.miner_address, "SOL/USD", 100, 3000),
    ]
    
    for trade_id, party_a, party_b, asset, strike, collateral in trades_config:
        print(f"\nCreating {trade_id}: {asset}")
        
        # Propose
        proposal = create_propose_trade_transaction(
            trade_id=trade_id,
            party_a=party_a,
            template_type=TemplateType.UP_DOWN,
            asset_pair=asset,
            strike_price=float(strike),
            expiry_hours=1,
            collateral_amount=collateral
        )
        mempool.add_transaction(proposal)
        
        # Accept
        accept = create_accept_trade_transaction(trade_id, party_b)
        mempool.add_transaction(accept)
    
    # Mine block with all proposals/acceptances
    block = alice.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    print(f"\nActive trades: {len(blockchain.get_active_trades())}")
    
    # Phase 3: Deposit collateral
    print("\n--- PHASE 3: DEPOSITING COLLATERAL ---")
    
    for trade_id, _, _, _, _, _ in trades_config:
        deposit = create_deposit_collateral_transaction(trade_id)
        mempool.add_transaction(deposit)
    
    block = bob.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    print("\nBalances after locking collateral:")
    for name, miner in [("Alice", alice), ("Bob", bob), ("Charlie", charlie)]:
        total = blockchain.balances.get_total_balance(miner.miner_address)
        locked = blockchain.balances.get_locked_balance(miner.miner_address)
        available = blockchain.balances.get_available_balance(miner.miner_address)
        print(f"  {name}: Total={total/1000:.1f}, Locked={locked/1000:.1f}, Available={available/1000:.1f}")
    
    # Phase 4: Settle trades
    print("\n--- PHASE 4: SETTLING TRADES ---")
    
    settlements = [
        ("TRADE_A", 52000, alice.miner_address, 10000, 0),  # Alice wins
        ("TRADE_B", 2800, charlie.miner_address, 16000, 0),  # Charlie wins (price went DOWN)
        ("TRADE_C", 105, alice.miner_address, 6000, 0),     # Alice wins
    ]
    
    for trade_id, settlement_price, winner, winner_payout, loser_payout in settlements:
        print(f"\nSettling {trade_id} at ${settlement_price}")
        settle = create_settle_trade_transaction(
            trade_id=trade_id,
            settlement_price=float(settlement_price),
            winner=winner,
            winner_payout=winner_payout,
            loser_payout=loser_payout
        )
        mempool.add_transaction(settle)
    
    block = charlie.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    # Final summary
    print("\n--- FINAL SUMMARY ---")
    print(f"Total blocks mined: {len(blockchain.chain)}")
    print(f"Total transactions: {len(blockchain.transaction_index)}")
    print(f"Settled trades: {len(blockchain.settled_trades)}")
    print(f"Active trades: {len(blockchain.active_trades)}")
    
    print("\nFinal balances:")
    for name, miner in [("Alice", alice), ("Bob", bob), ("Charlie", charlie)]:
        total = blockchain.balances.get_total_balance(miner.miner_address)
        print(f"  {name}: {total / MILLI_DENOMINATION:.1f} {CRYPTOCURRENCY_NAME}")
    
    print("\nTEST 7 PASSED: Complete workflow executed successfully")


def run_all_tests():
    """Run all tests in sequence"""
    print("\n" + "|"*80)
    print("|" + " "*78 + "|")
    print("|" + "  FUTURECHAIN FUTURES EXCHANGE - COMPREHENSIVE TEST SUITE".center(78) + "|")
    print("|" + " "*78 + "|")
    print("|"*80 + "\n")
    
    try:
        # Test 1: Basic mining
        blockchain, mempool, alice, bob = test_basic_mining()
        
        # Test 2: Simple trade
        blockchain, mempool = test_simple_futures_trade(blockchain, mempool, alice, bob)
        
        # Test 3: Multiple trades
        blockchain, mempool, charlie = test_multiple_trades(blockchain, mempool, alice, bob)
        
        # Test 4: Insufficient balance
        test_insufficient_balance(blockchain, mempool, alice, bob)
        
        # Test 5: Settlement scenarios
        test_settlement_scenarios()
        
        # Test 6: Blockchain state
        test_blockchain_state()
        
        # Test 7: Complete workflow
        test_complete_workflow()
        
        # Final summary
        print("ALL TESTS PASSED!")
        
    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\nUNEXPECTED ERROR: {e}")
        raise


if __name__ == "__main__":
    run_all_tests()