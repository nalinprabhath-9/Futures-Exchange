"""
Test suite for FutureCoin Futures Exchange blockchain
Covers mining, trading, settlement, and ECDSA signature verification.
"""
import os
import hashlib
import pytest
from ecdsa import SECP256k1, SigningKey
from ecdsa.util import sigencode_der
from blockchain import (
    Blockchain,
    Miner,
    TxnMemoryPool,
    CRYPTOCURRENCY_NAME,
    MILLI_DENOMINATION,
    create_propose_trade_transaction,
    create_accept_trade_transaction,
    create_settle_trade_transaction,
)
from transaction_enums import TradeState, TemplateType
from crypto_utils import get_signing_key_from_hex, get_compressed_pubkey

# Test keys (hex strings, for reproducibility)
ALICE_PRIV = '18e14a7b6a307f426a94f8114701e7c8e774e7f9a47e2c2035db29a206321725'
# 64 hex chars (32 bytes):
BOB_PRIV = 'b1e2d3c4f5a697887766554433221100ffeeddccbbaa99887766554433221100'

ALICE_ADDR = get_compressed_pubkey(get_signing_key_from_hex(ALICE_PRIV).verifying_key).hex()
BOB_ADDR = get_compressed_pubkey(get_signing_key_from_hex(BOB_PRIV).verifying_key).hex()


def make_oracle_settle_tx(blockchain, trade, oracle_price):
    oracle_sk = SigningKey.generate(curve=SECP256k1)
    oracle_pubkey = get_compressed_pubkey(oracle_sk.verifying_key).hex()
    blockchain.trusted_oracle_pubkey = oracle_pubkey

    oracle_timestamp = trade.expiry_timestamp
    price_str = f"{oracle_price:.8f}".rstrip("0").rstrip(".")
    digest = hashlib.sha256(
        trade.asset_pair.encode() +
        price_str.encode() +
        str(oracle_timestamp).encode()
    ).digest()
    oracle_signature = oracle_sk.sign_digest(digest, sigencode=sigencode_der).hex()

    return create_settle_trade_transaction(
        trade_id=trade.trade_id,
        oracle_price=oracle_price,
        oracle_timestamp=oracle_timestamp,
        oracle_signature=oracle_signature,
        oracle_pubkey=oracle_pubkey,
    )


def test_basic_mining():
    blockchain = Blockchain()
    mempool = TxnMemoryPool()
    alice = Miner(miner_address=ALICE_ADDR, difficulty_bits=0x207fffff)
    bob = Miner(miner_address=BOB_ADDR, difficulty_bits=0x207fffff)
    assert len(blockchain.chain) == 1
    # First mined block after genesis
    blockchain.add_block(alice.mine_block(blockchain, mempool, verbose=False))
    # Second mined block after genesis
    block_1 = bob.mine_block(blockchain, mempool, verbose=False)
    blockchain.add_block(block_1)
    assert blockchain.balances.get_total_balance(ALICE_ADDR) == 50000
    assert blockchain.balances.get_total_balance(BOB_ADDR) == 50000

def test_signed_trade_and_settlement():
    blockchain = Blockchain()
    mempool = TxnMemoryPool()
    alice = Miner(miner_address=ALICE_ADDR, difficulty_bits=0x207fffff)
    bob = Miner(miner_address=BOB_ADDR, difficulty_bits=0x207fffff)
    # Mining for initial balances
    blockchain.add_block(alice.mine_block(blockchain, mempool, verbose=False))
    blockchain.add_block(bob.mine_block(blockchain, mempool, verbose=False))
    # Alice proposes a trade (signed)
    trade_proposal = create_propose_trade_transaction(
        trade_id="TRADE_SIG1",
        party_a=ALICE_ADDR,
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=50000.0,
        expiry_hours=1,
        collateral_amount=10000,
        privkey_hex=ALICE_PRIV
    )
    mempool.add_transaction(trade_proposal)
    # Bob accepts (signed)
    trade_accept = create_accept_trade_transaction(
        trade_id="TRADE_SIG1",
        party_b=BOB_ADDR,
        privkey_hex=BOB_PRIV
    )
    mempool.add_transaction(trade_accept)
    # Mine block with proposal and acceptance
    blockchain.add_block(alice.mine_block(blockchain, mempool, verbose=False))
    # Check locked balances
    assert blockchain.balances.get_locked_balance(ALICE_ADDR) == 10000
    assert blockchain.balances.get_locked_balance(BOB_ADDR) == 10000

    trade = blockchain.get_trade("TRADE_SIG1")
    blockchain.chain[-1].BlockHeader.Timestamp = trade.expiry_timestamp + 1

    # Settlement uses oracle-signed price data.
    settle_tx = make_oracle_settle_tx(blockchain, trade, oracle_price=52000.0)
    mempool.add_transaction(settle_tx)
    blockchain.add_block(bob.mine_block(blockchain, mempool, verbose=False))
    # Final balances
    alice_total = blockchain.balances.get_total_balance(ALICE_ADDR)
    bob_total = blockchain.balances.get_total_balance(BOB_ADDR)
    assert alice_total == 111000
    assert bob_total == 89000
    # Check trade state
    trade = blockchain.get_trade("TRADE_SIG1")
    assert trade.state == TradeState.SETTLED
    assert trade.winner == ALICE_ADDR
    assert blockchain.balances.get_locked_balance(ALICE_ADDR) == 0
    assert blockchain.balances.get_locked_balance(BOB_ADDR) == 0
    # Signature fields present
    assert trade_proposal.signature is not None
    assert trade_proposal.pubkey is not None
    assert trade_accept.signature is not None
    assert trade_accept.pubkey is not None

def test_invalid_signature_rejected():
    blockchain = Blockchain()
    mempool = TxnMemoryPool()
    # Create a trade proposal with Alice's key, but tamper with the signature
    tx = create_propose_trade_transaction(
        trade_id="TRADE_BADSIG",
        party_a=ALICE_ADDR,
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=50000.0,
        expiry_hours=1,
        collateral_amount=10000,
        privkey_hex=ALICE_PRIV
    )
    # Tamper with signature
    tx.signature = b'bad_signature'
    mempool.add_transaction(tx)
    # Should not be added to mempool
    assert all(t.trade_id != "TRADE_BADSIG" for t in mempool.transactions if hasattr(t, 'trade_id'))

def test_insufficient_balance():
    blockchain = Blockchain()
    mempool = TxnMemoryPool()
    alice = Miner(miner_address=ALICE_ADDR, difficulty_bits=0x207fffff)
    bob = Miner(miner_address=BOB_ADDR, difficulty_bits=0x207fffff)
    blockchain.add_block(alice.mine_block(blockchain, mempool, verbose=False))
    blockchain.add_block(bob.mine_block(blockchain, mempool, verbose=False))
    # Set collateral to more than both Alice and Bob have available
    excessive_collateral = (
        blockchain.balances.get_available_balance(ALICE_ADDR) +
        blockchain.balances.get_available_balance(BOB_ADDR) + 10000
    )
    tx = create_propose_trade_transaction(
        trade_id="TRADE_EXCESSIVE",
        party_a=ALICE_ADDR,
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=50000.0,
        expiry_hours=1,
        collateral_amount=excessive_collateral,
        privkey_hex=ALICE_PRIV
    )
    mempool.add_transaction(tx)
    accept = create_accept_trade_transaction("TRADE_EXCESSIVE", BOB_ADDR, privkey_hex=BOB_PRIV)
    mempool.add_transaction(accept)
    blockchain.add_block(alice.mine_block(blockchain, mempool, verbose=False))
    trade = blockchain.get_trade("TRADE_EXCESSIVE")
    assert trade.state != TradeState.ACTIVE

def test_blockchain_state_tracking():
    blockchain = Blockchain()
    mempool = TxnMemoryPool()
    miner = Miner(miner_address=ALICE_ADDR, difficulty_bits=0x207fffff)
    for _ in range(5):
        blockchain.add_block(miner.mine_block(blockchain, mempool, verbose=False))
    assert len(blockchain.chain) == 6
    assert blockchain.get_block_by_height(0) is not None
    assert blockchain.get_block_by_height(5) is not None
    # Chain integrity
    for i in range(1, len(blockchain.chain)):
        assert blockchain.chain[i].BlockHeader.hashPrevBlock == blockchain.chain[i-1].Blockhash

def test_multiple_trades():
    blockchain = Blockchain()
    mempool = TxnMemoryPool()
    alice = Miner(miner_address=ALICE_ADDR, difficulty_bits=0x207fffff)
    bob = Miner(miner_address=BOB_ADDR, difficulty_bits=0x207fffff)
    blockchain.add_block(alice.mine_block(blockchain, mempool, verbose=False))
    blockchain.add_block(bob.mine_block(blockchain, mempool, verbose=False))
    # Trade 1
    t1 = create_propose_trade_transaction(
        trade_id="T1",
        party_a=ALICE_ADDR,
        template_type=TemplateType.UP_DOWN,
        asset_pair="ETH/USD",
        strike_price=3000.0,
        expiry_hours=2,
        collateral_amount=5000,
        privkey_hex=ALICE_PRIV
    )
    mempool.add_transaction(t1)
    a1 = create_accept_trade_transaction("T1", BOB_ADDR, privkey_hex=BOB_PRIV)
    mempool.add_transaction(a1)
    # Trade 2
    t2 = create_propose_trade_transaction(
        trade_id="T2",
        party_a=ALICE_ADDR,
        template_type=TemplateType.UP_DOWN,
        asset_pair="SOL/USD",
        strike_price=100.0,
        expiry_hours=3,
        collateral_amount=8000,
        privkey_hex=ALICE_PRIV
    )
    mempool.add_transaction(t2)
    a2 = create_accept_trade_transaction("T2", BOB_ADDR, privkey_hex=BOB_PRIV)
    mempool.add_transaction(a2)
    blockchain.add_block(alice.mine_block(blockchain, mempool, verbose=False))
    # Check locked balances
    assert blockchain.balances.get_locked_balance(ALICE_ADDR) == 13000
    assert blockchain.balances.get_locked_balance(BOB_ADDR) == 13000
    # Check active trades
    active_trades = blockchain.get_active_trades()
    assert len(active_trades) == 2

if __name__ == "__main__":
    pytest.main([os.path.abspath(__file__)])
