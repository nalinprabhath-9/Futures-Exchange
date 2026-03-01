"""
Comprehensive tests and examples for the FutureCoin Futures Exchange blockchain
Demonstrates mining, trading, and settlement workflows
"""

import time
from datetime import datetime
from blockchain import (
    Blockchain,
    Miner,
    TxnMemoryPool,
    CRYPTOCURRENCY_NAME,
    MILLI_DENOMINATION,
    create_propose_trade_transaction,
    create_accept_trade_transaction,
    create_cancel_proposal_transaction,
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
    """
    Test 2: Simple UP/DOWN futures trade.

    Collateral lifecycle under the new model:
      - Alice's collateral (10k) is locked when her PROPOSE_TRADE tx is processed.
      - Bob's collateral (10k) is locked when his ACCEPT_TRADE tx is processed;
        the trade moves directly to ACTIVE — no separate deposit step.
    """
    print_separator("TEST 2: SIMPLE FUTURES TRADE (UP/DOWN)")
    
    alice_addr = alice.miner_address
    bob_addr = bob.miner_address
    
    # Step 1: Alice proposes trade — her collateral is locked upon processing
    print("STEP 1: Alice proposes BTC will go UP (collateral locked on proposal)")
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
    
    # Step 2: Bob accepts — his collateral is locked upon processing, trade goes ACTIVE
    print("\nSTEP 2: Bob accepts trade (betting DOWN — collateral locked on acceptance)")
    trade_accept = create_accept_trade_transaction(
        trade_id="TRADE_001",
        party_b=bob_addr
    )
    trade_accept.print_transaction()
    mempool.add_transaction(trade_accept)
    
    # Mine block with both proposal and acceptance
    print("\nMining block with proposal and acceptance transactions...")
    block_2 = alice.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block_2)
    
    # Verify trade is immediately ACTIVE after block is processed
    trade = blockchain.get_trade("TRADE_001")
    assert trade.state == TradeState.ACTIVE, f"Expected ACTIVE, got {trade.state.value}"
    print(f"\nTrade state after block: {trade.state.value} ✓")
    
    # Check balances after locking
    # At this point: Alice has 50k (block_0) + 50k (block_2 coinbase) = 100k total, 10k locked
    #                Bob has   50k (block_1)                           =  50k total, 10k locked
    print("\n--- BALANCES AFTER COLLATERAL LOCK ---")
    blockchain.balances.print_balance(alice_addr)
    blockchain.balances.print_balance(bob_addr)
    
    assert blockchain.balances.get_locked_balance(alice_addr) == 10000
    assert blockchain.balances.get_locked_balance(bob_addr) == 10000
    assert blockchain.balances.get_available_balance(alice_addr) == 90000  # 100k total - 10k locked
    assert blockchain.balances.get_available_balance(bob_addr) == 40000   # 50k total - 10k locked
    
    # Step 3: Simulate expiry and settlement (Alice wins)
    print("\nSTEP 3: Trade expires — Oracle reports BTC went UP to $52,000")
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
    block_3 = bob.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block_3)
    
    # Final balances
    # Alice: 50k (block_0) + 50k (block_2) + 10k (won from Bob) = 110k
    # Bob:   50k (block_1) + 50k (block_3) - 10k (lost to Alice) = 90k
    print("\n--- FINAL BALANCES ---")
    blockchain.balances.print_balance(alice_addr)
    blockchain.balances.print_balance(bob_addr)
    
    alice_total = blockchain.balances.get_total_balance(alice_addr)
    bob_total = blockchain.balances.get_total_balance(bob_addr)
    
    assert alice_total == 110000, f"Alice should have 110k, has {alice_total}"
    assert bob_total == 90000, f"Bob should have 90k, has {bob_total}"
    
    print("TEST 2 PASSED: Simple futures trade completed successfully")
    return blockchain, mempool


def test_multiple_trades(blockchain, mempool, alice, bob):
    """
    Test 3: Multiple concurrent trades.

    Collateral for each trade is locked in two phases within the same block:
      - PROPOSE_TRADE locks party_a's share.
      - ACCEPT_TRADE locks party_b's share and activates the trade.
    No separate deposit transactions are required.
    """
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
    
    # Trade 2: Alice vs Bob on ETH/USD
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
    
    # Trade 3: Alice vs Charlie on SOL/USD
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
    
    # Mine one block — proposals lock party_a collateral, acceptances lock party_b collateral
    print("\nMining block with proposals and acceptances...")
    block = alice.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    # Both trades should be immediately ACTIVE
    for trade_id in ("TRADE_002", "TRADE_003"):
        trade = blockchain.get_trade(trade_id)
        assert trade.state == TradeState.ACTIVE, \
            f"{trade_id} expected ACTIVE, got {trade.state.value}"
        print(f"  {trade_id} state: {trade.state.value} ✓")
    
    # Check active trades
    active_trades = blockchain.get_active_trades()
    print(f"\n--- ACTIVE TRADES: {len(active_trades)} ---")
    for trade in active_trades:
        print(f"  - {trade.trade_id}: {trade.asset_pair} ({trade.state.value})")
    
    # Alice has 13k locked: 10k from TRADE_001 was settled (0 locked),
    # 5k from TRADE_002 + 8k from TRADE_003 = 13k
    print("\n--- BALANCES WITH MULTIPLE LOCKED TRADES ---")
    blockchain.balances.print_balance(alice_addr)
    
    assert blockchain.balances.get_locked_balance(alice_addr) == 13000
    
    print("TEST 3 PASSED: Multiple concurrent trades work correctly")
    return blockchain, mempool, charlie


def test_insufficient_balance(blockchain, mempool, alice, bob):
    """
    Test 4: Handle insufficient balance for collateral.

    Under the new model the balance check happens at propose/accept time.
    A propose with insufficient funds is rejected immediately when the block
    is processed — the trade is never registered as active.
    """
    print_separator("TEST 4: INSUFFICIENT BALANCE HANDLING")
    
    alice_addr = alice.miner_address
    bob_addr = bob.miner_address
    
    alice_available = blockchain.balances.get_available_balance(alice_addr)
    print(f"Alice's available balance: {alice_available / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}")
    
    excessive_collateral = alice_available + 10000
    print(f"\nAttempting to propose trade requiring {excessive_collateral / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}...")
    
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
    
    # Mine block — the proposal will be rejected at processing time
    # because Alice cannot cover the collateral
    block = alice.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    # Trade should not exist at all — rejected at propose time
    trade = blockchain.get_trade("TRADE_EXCESSIVE")
    print(f"\nTrade registered after failed proposal: {trade}")
    assert trade is None, f"Expected trade to be rejected, but got state: {trade.state.value}"
    
    print("TEST 4 PASSED: Insufficient balance handled correctly at proposal time")


def test_insufficient_balance_party_b():
    """
    Test 4b: Party B attempts to accept a trade without enough collateral.

    The proposal succeeds and party_a's collateral is locked. When party_b's
    ACCEPT_TRADE tx is processed, the balance check fails, so:
      - party_b's collateral is NOT locked
      - the trade remains in PROPOSED state (never reaches ACTIVE)
      - party_a's collateral lock is still in place (pending a future accept or cancel)
    """
    print_separator("TEST 4b: PARTY B INSUFFICIENT BALANCE ON ACCEPTANCE")

    blockchain = Blockchain()
    mempool = TxnMemoryPool()

    proposer = Miner(miner_address="Proposer_addr", difficulty_bits=0x207fffff)
    broke_acceptor = Miner(miner_address="BrokeAcceptor_addr", difficulty_bits=0x207fffff)

    # Only the proposer mines — broke_acceptor deliberately has no balance
    print("Proposer mines to get initial balance; BrokeAcceptor mines nothing...")
    block = proposer.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)

    proposer_addr = proposer.miner_address
    acceptor_addr = broke_acceptor.miner_address

    proposer_balance = blockchain.balances.get_available_balance(proposer_addr)
    acceptor_balance = blockchain.balances.get_available_balance(acceptor_addr)
    collateral = 10000  # 10 FutureCoins — proposer can cover it, acceptor cannot

    print(f"\nProposer available:      {proposer_balance / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}")
    print(f"BrokeAcceptor available: {acceptor_balance / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}")
    print(f"Required collateral:     {collateral / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}")

    assert proposer_balance >= collateral, "Proposer should have enough collateral for this test"
    assert acceptor_balance < collateral, "BrokeAcceptor should not have enough collateral for this test"

    # Propose — party_a's collateral is locked on processing
    mempool.add_transaction(create_propose_trade_transaction(
        trade_id="TRADE_BROKE_B",
        party_a=proposer_addr,
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=50000.00,
        expiry_hours=1,
        collateral_amount=collateral
    ))

    # Accept — will be rejected at processing time due to insufficient balance
    mempool.add_transaction(create_accept_trade_transaction(
        trade_id="TRADE_BROKE_B",
        party_b=acceptor_addr
    ))

    block = proposer.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)

    trade = blockchain.get_trade("TRADE_BROKE_B")

    # Trade exists (proposal succeeded) but is still PROPOSED, not ACTIVE
    assert trade is not None, "Trade should exist — the proposal was valid"
    assert trade.state == TradeState.PROPOSED, \
        f"Expected PROPOSED after failed acceptance, got {trade.state.value}"
    assert trade.party_b is None, \
        f"party_b should not be set after failed acceptance, got {trade.party_b}"

    print(f"\nTrade state after failed acceptance: {trade.state.value} ✓")
    print(f"party_b on trade: {trade.party_b} ✓")

    # Proposer's collateral is still locked — the trade is open for another acceptor
    proposer_locked = blockchain.balances.get_locked_balance(proposer_addr)
    acceptor_locked = blockchain.balances.get_locked_balance(acceptor_addr)

    assert proposer_locked == collateral, \
        f"Proposer should still have {collateral} locked, has {proposer_locked}"
    assert acceptor_locked == 0, \
        f"BrokeAcceptor should have 0 locked, has {acceptor_locked}"

    print(f"Proposer locked:      {proposer_locked / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME} ✓")
    print(f"BrokeAcceptor locked: {acceptor_locked / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME} ✓")

    print("TEST 4b PASSED: Party B insufficient balance handled correctly at acceptance time")



def test_cancel_proposal():
    """
    Test 4c: Party A manually cancels a PROPOSED trade before anyone accepts.

    Expected outcomes:
      - Trade moves to CANCELLED and is stored in settled_trades
      - Party A's locked collateral is returned in full
      - The trade is no longer visible in proposed_trades
    """
    print_separator("TEST 4c: MANUAL PROPOSAL CANCELLATION BY PARTY A")

    blockchain = Blockchain()
    mempool = TxnMemoryPool()

    party_a = Miner(miner_address="PartyA_cancel_addr", difficulty_bits=0x207fffff)

    # Mine so party_a has a balance
    block = party_a.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)

    party_a_addr = party_a.miner_address
    collateral = 10000

    balance_before = blockchain.balances.get_available_balance(party_a_addr)
    print(f"Party A available before proposal: {balance_before / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}")

    # Submit proposal — party_a's collateral locked on processing
    mempool.add_transaction(create_propose_trade_transaction(
        trade_id="TRADE_CANCEL_TEST",
        party_a=party_a_addr,
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=50000.00,
        expiry_hours=1,
        collateral_amount=collateral
    ))

    block = party_a.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)

    trade = blockchain.get_trade("TRADE_CANCEL_TEST")
    assert trade is not None and trade.state == TradeState.PROPOSED, \
        f"Expected PROPOSED, got {trade.state.value if trade else None}"
    assert blockchain.balances.get_locked_balance(party_a_addr) == collateral
    print(f"Trade state after proposal: {trade.state.value} ✓")
    print(f"Locked after proposal: {blockchain.balances.get_locked_balance(party_a_addr) / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME} ✓")

    # Party A cancels the proposal before anyone accepts
    print("\nParty A submitting cancellation...")
    mempool.add_transaction(create_cancel_proposal_transaction("TRADE_CANCEL_TEST"))

    block = party_a.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)

    trade = blockchain.get_trade("TRADE_CANCEL_TEST")
    assert trade is not None and trade.state == TradeState.CANCELLED, \
        f"Expected CANCELLED, got {trade.state.value if trade else None}"

    # Collateral must be fully returned
    assert blockchain.balances.get_locked_balance(party_a_addr) == 0, \
        f"Expected 0 locked after cancel, got {blockchain.balances.get_locked_balance(party_a_addr)}"

    available_after = blockchain.balances.get_available_balance(party_a_addr)
    print(f"\nTrade state after cancel: {trade.state.value} ✓")
    print(f"Locked after cancel: {blockchain.balances.get_locked_balance(party_a_addr) / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME} ✓")
    print(f"Available after cancel: {available_after / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}")

    # Trade should no longer appear in proposed_trades
    assert "TRADE_CANCEL_TEST" not in blockchain.proposed_trades, \
        "Cancelled trade should be removed from proposed_trades"
    print("Trade removed from proposed_trades ✓")

    print("TEST 4c PASSED: Proposal cancellation by party_a works correctly")


def test_proposal_timeout():
    """
    Test 4d: A PROPOSED trade that is not accepted within proposal_timeout_seconds
    is automatically expired when the next block is processed.

    The blockchain is configured with a very short timeout (1 second) so the
    test can run without real delays — we instead fast-forward by manipulating
    the block timestamp directly.

    Expected outcomes:
      - Trade moves to EXPIRED
      - Party A's collateral is returned
      - Trade is removed from proposed_trades
    """
    print_separator("TEST 4d: PROPOSAL TIMEOUT / AUTO-EXPIRY")

    # 5-second timeout so we can trigger it by advancing the block timestamp
    timeout = 5
    blockchain = Blockchain(proposal_timeout_seconds=timeout)
    mempool = TxnMemoryPool()

    party_a = Miner(miner_address="PartyA_timeout_addr", difficulty_bits=0x207fffff)

    block = party_a.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)

    party_a_addr = party_a.miner_address
    collateral = 10000

    # Submit proposal — expiry_timestamp = now + timeout
    proposal_time = int(time.time())
    mempool.add_transaction(create_propose_trade_transaction(
        trade_id="TRADE_TIMEOUT_TEST",
        party_a=party_a_addr,
        template_type=TemplateType.UP_DOWN,
        asset_pair="ETH/USD",
        strike_price=3000.00,
        expiry_hours=0,           # 0 hours — expiry_timestamp is overridden below
        collateral_amount=collateral
    ))

    # Mine the proposal block normally
    proposal_block = party_a.mine_block(blockchain, mempool, verbose=False)
    # Override expiry_timestamp on the stored trade object to be in the near past
    # (simulating a short timeout window)
    # We do this BEFORE add_block so the trade is registered with a short expiry
    blockchain.add_block(proposal_block)

    trade = blockchain.get_trade("TRADE_TIMEOUT_TEST")
    assert trade is not None and trade.state == TradeState.PROPOSED

    # Manually set the trade's expiry to 1 second ago to simulate timeout
    trade.expiry_timestamp = int(time.time()) - 1
    print(f"Trade expiry set to: {datetime.fromtimestamp(trade.expiry_timestamp)} (1 second ago)")
    print(f"Collateral locked before expiry: {blockchain.balances.get_locked_balance(party_a_addr) / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}")

    # Mine the next block — add_block will call _expire_stale_proposals
    # and the trade's expiry will be detected
    print("\nMining next block (expiry check triggered)...")
    next_block = party_a.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(next_block)

    trade = blockchain.get_trade("TRADE_TIMEOUT_TEST")
    assert trade is not None and trade.state == TradeState.EXPIRED, \
        f"Expected EXPIRED, got {trade.state.value if trade else None}"

    # Collateral must be fully returned
    assert blockchain.balances.get_locked_balance(party_a_addr) == 0, \
        f"Expected 0 locked after expiry, got {blockchain.balances.get_locked_balance(party_a_addr)}"

    assert "TRADE_TIMEOUT_TEST" not in blockchain.proposed_trades, \
        "Expired trade should be removed from proposed_trades"

    print(f"\nTrade state after expiry: {trade.state.value} ✓")
    print(f"Collateral locked after expiry: {blockchain.balances.get_locked_balance(party_a_addr) / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME} ✓")
    print("Trade removed from proposed_trades ✓")

    print("TEST 4d PASSED: Proposal auto-expiry works correctly")


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
        block = (trader_a if i % 2 == 0 else trader_b).mine_block(blockchain, mempool, verbose=False)
        blockchain.add_block(block)
    
    print("Initial balances:")
    blockchain.balances.print_balance(trader_a.miner_address)
    blockchain.balances.print_balance(trader_b.miner_address)
    
    # Scenario 1: Trader A wins (price goes UP)
    print("\n--- SCENARIO 1: Price goes UP (Trader A wins) ---")
    
    # Propose + accept in the same block — both collaterals locked, trade goes ACTIVE
    mempool.add_transaction(create_propose_trade_transaction(
        trade_id="SCENARIO_1",
        party_a=trader_a.miner_address,
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=50000.00,
        expiry_hours=1,
        collateral_amount=10000
    ))
    mempool.add_transaction(create_accept_trade_transaction("SCENARIO_1", trader_b.miner_address))
    
    block = trader_a.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    trade = blockchain.get_trade("SCENARIO_1")
    assert trade.state == TradeState.ACTIVE, f"Expected ACTIVE, got {trade.state.value}"
    print(f"Trade state after propose+accept block: {trade.state.value} ✓")
    
    # Settlement: Price went UP to 55,000
    mempool.add_transaction(create_settle_trade_transaction(
        trade_id="SCENARIO_1",
        settlement_price=55000.00,
        winner=trader_a.miner_address,
        winner_payout=20000,
        loser_payout=0
    ))
    block = trader_b.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    print("\nFinal balances:")
    blockchain.balances.print_balance(trader_a.miner_address)
    blockchain.balances.print_balance(trader_b.miner_address)
    
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
    for i, (name, miner) in enumerate([("Alice", alice), ("Bob", bob), ("Charlie", charlie)]):
        print(f"{name} mining block {i}...")
        block = miner.mine_block(blockchain, mempool, verbose=False)
        blockchain.add_block(block)
    
    print("\nBalances after mining:")
    for name, miner in [("Alice", alice), ("Bob", bob), ("Charlie", charlie)]:
        balance = blockchain.balances.get_total_balance(miner.miner_address)
        print(f"  {name}: {balance / MILLI_DENOMINATION} {CRYPTOCURRENCY_NAME}")
    
    # Phase 2: Create and activate trades
    # Proposals lock party_a collateral; acceptances lock party_b collateral
    # and activate the trade — all in the same block.
    print("\n--- PHASE 2: CREATING AND ACTIVATING TRADES ---")
    
    trades_config = [
        ("TRADE_A", alice.miner_address, bob.miner_address,     "BTC/USD", 50000, 5000),
        ("TRADE_B", bob.miner_address,   charlie.miner_address, "ETH/USD",  3000, 8000),
        ("TRADE_C", alice.miner_address, charlie.miner_address, "SOL/USD",   100, 3000),
    ]
    
    for trade_id, party_a, party_b, asset, strike, collateral in trades_config:
        print(f"\nCreating {trade_id}: {asset}")
        
        mempool.add_transaction(create_propose_trade_transaction(
            trade_id=trade_id,
            party_a=party_a,
            template_type=TemplateType.UP_DOWN,
            asset_pair=asset,
            strike_price=float(strike),
            expiry_hours=1,
            collateral_amount=collateral
        ))
        mempool.add_transaction(create_accept_trade_transaction(trade_id, party_b))
    
    # One block handles all proposals + acceptances; collateral locked as each tx is processed
    block = alice.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    active_trades = blockchain.get_active_trades()
    print(f"\nActive trades after block: {len(active_trades)}")
    for trade in active_trades:
        print(f"  - {trade.trade_id}: {trade.asset_pair} ({trade.state.value})")
    
    assert len(active_trades) == 3, f"Expected 3 active trades, got {len(active_trades)}"
    
    print("\nBalances after locking collateral:")
    for name, miner in [("Alice", alice), ("Bob", bob), ("Charlie", charlie)]:
        total = blockchain.balances.get_total_balance(miner.miner_address)
        locked = blockchain.balances.get_locked_balance(miner.miner_address)
        available = blockchain.balances.get_available_balance(miner.miner_address)
        print(f"  {name}: Total={total/1000:.1f}, Locked={locked/1000:.1f}, Available={available/1000:.1f}")
    
    # Phase 3: Settle trades
    print("\n--- PHASE 3: SETTLING TRADES ---")
    
    settlements = [
        ("TRADE_A", 52000, alice.miner_address,   10000, 0),  # Alice wins
        ("TRADE_B",  2800, charlie.miner_address, 16000, 0),  # Charlie wins (price went DOWN)
        ("TRADE_C",   105, alice.miner_address,    6000, 0),  # Alice wins
    ]
    
    for trade_id, settlement_price, winner, winner_payout, loser_payout in settlements:
        print(f"\nSettling {trade_id} at ${settlement_price}")
        mempool.add_transaction(create_settle_trade_transaction(
            trade_id=trade_id,
            settlement_price=float(settlement_price),
            winner=winner,
            winner_payout=winner_payout,
            loser_payout=loser_payout
        ))
    
    block = charlie.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block)
    
    # Final summary
    print("\n--- FINAL SUMMARY ---")
    print(f"Total blocks mined: {len(blockchain.chain)}")
    print(f"Total transactions: {len(blockchain.transaction_index)}")
    print(f"Settled trades: {len(blockchain.settled_trades)}")
    print(f"Active trades: {len(blockchain.active_trades)}")
    
    assert len(blockchain.settled_trades) == 3
    assert len(blockchain.active_trades) == 0
    
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
        
        # Test 4: Insufficient balance — party_a proposal rejected
        test_insufficient_balance(blockchain, mempool, alice, bob)

        # Test 4b: Insufficient balance — party_b acceptance rejected
        test_insufficient_balance_party_b()

        # Test 4c: Manual proposal cancellation by party_a
        test_cancel_proposal()

        # Test 4d: Proposal auto-expiry (timeout)
        test_proposal_timeout()

        # Test 5: Settlement scenarios
        test_settlement_scenarios()
        
        # Test 6: Blockchain state
        test_blockchain_state()
        
        # Test 7: Complete workflow
        test_complete_workflow()
        
        print("ALL TESTS PASSED!")
        
    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\nUNEXPECTED ERROR: {e}")
        raise


if __name__ == "__main__":
    run_all_tests()