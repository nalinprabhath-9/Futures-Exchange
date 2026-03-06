"""
Oracle Integration Test
End-to-end deterministic settlement using signed oracle price.
"""

import time
import requests

from blockchain import (
    Blockchain,
    Miner,
    TxnMemoryPool,
    create_propose_trade_transaction,
    create_accept_trade_transaction,
    create_settle_trade_transaction,
    MILLI_DENOMINATION,
)
from transaction_enums import TemplateType, TradeState


ORACLE_URL = "http://localhost:8080"


def fetch_oracle_price(symbol: str):
    response = requests.get(f"{ORACLE_URL}/price/{symbol}")
    if response.status_code != 200:
        raise Exception(f"Oracle error: {response.status_code}")

    data = response.json()

    return {
        "price": data["price"],
        "timestamp": data["timestamp"],
        "signature": data["signature"],
        "pubkey": data["oracle_pubkey"],
    }


def print_balances(blockchain, *miners):
    for m in miners:
        total = blockchain.balances.get_total_balance(m.miner_address)
        locked = blockchain.balances.get_locked_balance(m.miner_address)
        available = blockchain.balances.get_available_balance(m.miner_address)
        print(
            f"{m.miner_address}: "
            f"Total={total / MILLI_DENOMINATION:.3f}, "
            f"Locked={locked / MILLI_DENOMINATION:.3f}, "
            f"Available={available / MILLI_DENOMINATION:.3f}"
        )


def main():
    print("\n=== ORACLE INTEGRATION TEST ===\n")

    # ------------------------------------------------------------------
    # 1️⃣ Initialize chain and participants
    # ------------------------------------------------------------------
    blockchain = Blockchain()
    mempool = TxnMemoryPool()

    alice = Miner("Alice_oracle", difficulty_bits=0x207fffff)
    bob = Miner("Bob_oracle", difficulty_bits=0x207fffff)

    # Mine initial capital
    blockchain.add_block(alice.mine_block(blockchain, mempool, verbose=False))
    blockchain.add_block(bob.mine_block(blockchain, mempool, verbose=False))

    print("Initial balances:")
    print_balances(blockchain, alice, bob)

    # ------------------------------------------------------------------
    # 2️⃣ Create futures trade
    # ------------------------------------------------------------------
    strike_price = 50000.0
    collateral = 10000

    mempool.add_transaction(
        create_propose_trade_transaction(
            trade_id="ORACLE_TRADE_1",
            party_a=alice.miner_address,
            template_type=TemplateType.UP_DOWN,
            asset_pair="BTC",
            strike_price=strike_price,
            expiry_hours=0.001,  # expire in ~3.6 seconds for fast testing
            collateral_amount=collateral,
        )
    )

    mempool.add_transaction(
        create_accept_trade_transaction(
            trade_id="ORACLE_TRADE_1",
            party_b=bob.miner_address,
        )
    )

    blockchain.add_block(alice.mine_block(blockchain, mempool, verbose=False))

    trade = blockchain.get_trade("ORACLE_TRADE_1")
    assert trade.state == TradeState.ACTIVE
    print("\nTrade ACTIVE ✓")
    print_balances(blockchain, alice, bob)

    # Advance blockchain time past expiry before settlement
    trade = blockchain.get_trade("ORACLE_TRADE_1")
    # Sleep until after expiry (plus a small buffer)
    if trade and hasattr(trade, 'expiry_timestamp'):
        now = int(time.time())
        wait = trade.expiry_timestamp - now + 1
        if wait > 0:
            print(f"Sleeping {wait} seconds to allow trade to expire...")
            time.sleep(wait)
        # Set the next block's timestamp to just after expiry
        blockchain.chain[-1].BlockHeader.Timestamp = trade.expiry_timestamp + 1

    # ------------------------------------------------------------------
    # 3️⃣ Fetch real oracle price
    # ------------------------------------------------------------------
    print("\nFetching oracle price...")
    oracle_data = fetch_oracle_price("BTC")

    print("Oracle returned:")
    print(oracle_data)

    # ------------------------------------------------------------------
    # 4️⃣ Submit settlement transaction
    # ------------------------------------------------------------------
    mempool.add_transaction(
        create_settle_trade_transaction(
            trade_id="ORACLE_TRADE_1",
            oracle_price=oracle_data["price"],
            oracle_timestamp=oracle_data["timestamp"],
            oracle_signature=oracle_data["signature"],
            oracle_pubkey=oracle_data["pubkey"],
        )
    )

    blockchain.add_block(bob.mine_block(blockchain, mempool, verbose=False))

    # ------------------------------------------------------------------
    # 5️⃣ Validate results
    # ------------------------------------------------------------------
    settled_trade = blockchain.get_trade("ORACLE_TRADE_1")

    print("\nPost-settlement trade state:", settled_trade.state.value)
    print("Settlement price:", settled_trade.settlement_price)
    print("Winner:", settled_trade.winner)

    assert settled_trade.state == TradeState.SETTLED
    assert settled_trade.settlement_price == oracle_data["price"]

    print("\nFinal balances:")
    print_balances(blockchain, alice, bob)

    print("\nOracle integration SUCCESS ✓")


if __name__ == "__main__":
    main()