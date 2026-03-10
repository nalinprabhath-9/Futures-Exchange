import os
import sys
import json
import time
import argparse
import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from node.blockchain import (
    create_propose_trade_transaction,
    create_accept_trade_transaction,
    create_cancel_proposal_transaction,
    create_cancel_trade_transaction,
)
from node.transaction_enums import TemplateType


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------


def submit(node, tx):
    """
    Submit a signed transaction to a node.

    Triggers:
      - node/tx_codec.py -> futures_tx_to_wire()
      - node/app.py -> /tx/submit
      - node/blockchain.py -> TxnMemoryPool.add_transaction()
    """
    from node.tx_codec import futures_tx_to_wire

    return requests.post(
        f"{node}/tx/submit", json={"tx": futures_tx_to_wire(tx)}, timeout=10
    ).json()


def mine(node):
    """
    Trigger mining on a node.

    Triggers:
      - node/app.py -> /mine
      - node/blockchain.py -> Miner.mine_block()
      - node/blockchain.py -> Blockchain.add_block()
      - node/blockchain.py -> _process_futures_transaction()
    """
    return requests.post(f"{node}/mine", json={}, timeout=30).json()


def get_trade(node, trade_id):
    """Fetch trade state from node."""
    return requests.get(f"{node}/trade/{trade_id}", timeout=10).json()


def get_balance(node, address):
    """Fetch balance info from node."""
    return requests.get(f"{node}/balance/{address}", timeout=10).json()


def get_mempool(node):
    """Fetch mempool contents from node."""
    return requests.get(f"{node}/mempool", timeout=10).json()


def wait_for_mempool_tx(node, trade_id, timeout=8):
    """
    Wait until a tx related to trade_id appears in node mempool.
    Useful because gossip may take a short time.
    """
    start = time.time()
    while time.time() - start < timeout:
        mp = get_mempool(node)
        if mp.get("ok"):
            entries = mp.get("mempool", [])
            for entry in entries:
                payload = entry.get("payload_json", "")
                if trade_id in str(payload):
                    return True
        time.sleep(0.25)
    return False


def assert_ok(resp, label="response"):
    assert resp.get("ok"), f"{label} failed: {resp}"


def assert_not_ok(resp, label="response"):
    assert not resp.get("ok"), f"{label} unexpectedly succeeded: {resp}"


def print_case(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Run end-to-end and edge-case tests for Futures Exchange"
    )
    parser.add_argument("--users-file", default="users.json", help="Path to users.json")
    parser.add_argument("--node1", default="http://localhost:5001", help="Node 1 URL")
    parser.add_argument("--node2", default="http://localhost:5002", help="Node 2 URL")
    parser.add_argument("--node3", default="http://localhost:5003", help="Node 3 URL")
    args = parser.parse_args()

    N1 = args.node1
    N2 = args.node2
    N3 = args.node3

    users = json.load(open(args.users_file))

    if len(users) < 2:
        raise ValueError("Need at least 2 users in users.json to run tests")

    # We only require first 2 users for the main flow.
    # If more are present, that is fine.
    A = users[0]
    B = users[1]
    C = users[2] if len(users) > 2 else None

    print("Loaded users from:", args.users_file)
    print("User A:", A["user_id"], A["address"])
    print("User B:", B["user_id"], B["address"])
    if C:
        print("User C:", C["user_id"], C["address"])

    # --------------------------------------------------------
    # CASE 1: Happy path
    #
    # Scenario:
    #   Example:
    #     user1 = maker/proposer
    #     user2 = taker/accepter
    #
    # Flow:
    #   1) user1 proposes a trade on node1
    #   2) tx is signed using user1 private key
    #   3) proposal is added to mempool and gossiped
    #   4) user2 accepts the trade on node2
    #   5) tx is signed using user2 private key
    #   6) accept is added to mempool and gossiped
    #   7) mine block(s)
    #   8) trade should become ACTIVE
    #
    # Crypto involved:
    #   - ECDSA signature using secp256k1
    #   - public key compressed
    #   - node verifies signature and pubkey-derived address
    # --------------------------------------------------------
    print_case("CASE 1: Happy path — propose -> accept -> mine -> ACTIVE")

    trade_id = f"T{int(time.time())}"
    collateral = 50000  # milli
    expiry_hours = 1

    txp = create_propose_trade_transaction(
        trade_id=trade_id,
        party_a=A["address"],
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=45000,
        expiry_hours=expiry_hours,
        collateral_amount=collateral,
        privkey_hex=A["privkey_hex"],
        high_priority=True,
    )
    r = submit(N1, txp)
    print("propose:", r)
    assert_ok(r, "proposal submit")

    txa = create_accept_trade_transaction(
        trade_id=trade_id,
        party_b=B["address"],
        privkey_hex=B["privkey_hex"],
        high_priority=True,
    )
    r = submit(N2, txa)
    print("accept:", r)
    assert_ok(r, "accept submit")

    # Since gossip may take time, try waiting for node1 to see accept tx.
    wait_for_mempool_tx(N1, trade_id, timeout=5)

    # Mine on both nodes to make the flow robust even if block sync is not implemented.
    r = mine(N1)
    print("mine node1:", r)
    assert_ok(r, "mine node1")

    r = mine(N2)
    print("mine node2:", r)
    assert_ok(r, "mine node2")

    # Check trade on node2 first (since accept originated there), then node1.
    t = get_trade(N2, trade_id)
    print("trade @ node2:", t)
    if not t.get("ok"):
        t = get_trade(N1, trade_id)
        print("trade @ node1 fallback:", t)

    assert_ok(t, "trade lookup")
    assert t.get("trade", {}).get("state") in (
        "active",
        "ACTIVE",
        "TradeState.ACTIVE",
    ), t

    # --------------------------------------------------------
    # CASE 2: Low fee rejection
    #
    # Scenario:
    #   user1 tries to create a proposal with fee below minimum.
    #
    # Expected:
    #   - either constructor raises ValueError
    #   - or mempool / submit rejects it
    # --------------------------------------------------------
    print_case("CASE 2: Low fee rejection")

    bad_trade = f"BADFEE{int(time.time())}"
    try:
        tx_lowfee = create_propose_trade_transaction(
            trade_id=bad_trade,
            party_a=A["address"],
            template_type=TemplateType.UP_DOWN,
            asset_pair="BTC/USD",
            strike_price=45000,
            expiry_hours=1,
            collateral_amount=collateral,
            fee=1,  # intentionally too low
            privkey_hex=A["privkey_hex"],
        )
        r = submit(N1, tx_lowfee)
        print("low fee submit:", r)
        assert_not_ok(r, "low fee submit")
        print("✅ Rejected by submit/mempool")
    except ValueError as e:
        print("✅ Rejected at construction time:", str(e))

    # --------------------------------------------------------
    # CASE 3: Invalid signature rejection
    #
    # Scenario:
    #   user1 constructs a proposal but attaches a fake signature.
    #
    # Expected:
    #   node rejects tx due to invalid signature.
    # --------------------------------------------------------
    print_case("CASE 3: Invalid signature rejection")

    trade_sig = f"BADSIG{int(time.time())}"
    tx_bad_sig = create_propose_trade_transaction(
        trade_id=trade_sig,
        party_a=A["address"],
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=45000,
        expiry_hours=1,
        collateral_amount=collateral,
        privkey_hex=None,  # do not sign properly
    )
    tx_bad_sig.signature = b"\x30\x00"  # intentionally invalid
    tx_bad_sig.pubkey = bytes.fromhex(A["pubkey_hex"])

    r = submit(N1, tx_bad_sig)
    print("bad sig submit:", r)
    assert_not_ok(r, "bad signature submit")

    # --------------------------------------------------------
    # CASE 4: Cancel proposal before acceptance
    #
    # Scenario:
    #   user1 proposes a trade but cancels it before user2 accepts.
    #
    # Expected:
    #   after mining, trade becomes CANCELLED
    # --------------------------------------------------------
    print_case("CASE 4: Cancel proposal before acceptance")

    trade_cancel = f"CANCEL{int(time.time())}"
    txp4 = create_propose_trade_transaction(
        trade_id=trade_cancel,
        party_a=A["address"],
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=45000,
        expiry_hours=1,
        collateral_amount=collateral,
        privkey_hex=A["privkey_hex"],
    )
    r = submit(N1, txp4)
    print("propose cancel:", r)
    assert_ok(r, "cancel-case proposal submit")

    txc = create_cancel_proposal_transaction(
        trade_id=trade_cancel,
        party_a=A["address"],
        privkey_hex=A["privkey_hex"],
    )
    r = submit(N1, txc)
    print("cancel proposal tx:", r)
    assert_ok(r, "cancel proposal tx submit")

    r = mine(N1)
    print("mine cancel:", r)
    assert_ok(r, "mine cancel")

    t = get_trade(N1, trade_cancel)
    print("trade cancel state:", t)
    assert_ok(t, "cancelled trade lookup")
    assert t.get("trade", {}).get("state") in (
        "cancelled",
        "CANCELLED",
        "TradeState.CANCELLED",
    ), t

    # --------------------------------------------------------
    # CASE 5: Insufficient collateral
    #
    # Scenario:
    #   trade requires huge collateral so one side cannot cover it.
    #
    # Expected:
    #   proposal or acceptance should fail, or trade should never become ACTIVE
    # --------------------------------------------------------
    print_case("CASE 5: Insufficient collateral")

    trade_insuf = f"INSUF{int(time.time())}"
    huge_collateral = 10_000_000_000

    tx_insuf_prop = create_propose_trade_transaction(
        trade_id=trade_insuf,
        party_a=A["address"],
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=45000,
        expiry_hours=1,
        collateral_amount=huge_collateral,
        privkey_hex=A["privkey_hex"],
    )
    r = submit(N1, tx_insuf_prop)
    print("propose insuf:", r)

    if not r.get("ok"):
        print("✅ Proposal rejected as expected because collateral is too high")
    else:
        tx_insuf_acc = create_accept_trade_transaction(
            trade_id=trade_insuf,
            party_b=B["address"],
            privkey_hex=B["privkey_hex"],
        )
        r2 = submit(N2, tx_insuf_acc)
        print("accept insuf:", r2)

        if not r2.get("ok"):
            print("✅ Acceptance rejected due to insufficient collateral")
        else:
            r3 = mine(N1)
            print("mine insuf node1:", r3)
            assert_ok(r3, "mine insuf node1")

            r4 = mine(N2)
            print("mine insuf node2:", r4)
            assert_ok(r4, "mine insuf node2")

            t2 = get_trade(N2, trade_insuf)
            print("trade insuf state:", t2)

            if t2.get("ok"):
                assert t2.get("trade", {}).get("state") not in (
                    "active",
                    "ACTIVE",
                    "TradeState.ACTIVE",
                ), t2

    # --------------------------------------------------------
    # CASE 6: Cancel ACTIVE trade must be rejected
    #
    # Scenario:
    #   user1 proposes, user2 accepts, trade becomes ACTIVE.
    #   user1 then attempts to cancel the active trade.
    #
    # Expected:
    #   cancel submission is rejected — only PROPOSED trades can be cancelled.
    #   trade remains ACTIVE after the attempt.
    # --------------------------------------------------------
    print_case("CASE 6: Cancel ACTIVE trade must be rejected")

    trade_active_cancel = f"ACTCANCEL{int(time.time())}"
    collateral2 = 40000

    txp5 = create_propose_trade_transaction(
        trade_id=trade_active_cancel,
        party_a=A["address"],
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=45000,
        expiry_hours=1,
        collateral_amount=collateral2,
        privkey_hex=A["privkey_hex"],
    )
    r = submit(N1, txp5)
    print("propose active-cancel:", r)
    assert_ok(r, "active-cancel proposal submit")

    txa5 = create_accept_trade_transaction(
        trade_id=trade_active_cancel,
        party_b=B["address"],
        privkey_hex=B["privkey_hex"],
    )
    r = submit(N2, txa5)
    print("accept active-cancel:", r)
    assert_ok(r, "active-cancel accept submit")

    r = mine(N1)
    print("mine to activate node1:", r)
    assert_ok(r, "mine to activate node1")

    r = mine(N2)
    print("mine to activate node2:", r)
    assert_ok(r, "mine to activate node2")

    t = get_trade(N2, trade_active_cancel)
    if not t.get("ok"):
        t = get_trade(N1, trade_active_cancel)
    print("trade active:", t)
    assert_ok(t, "active trade lookup")
    assert t.get("trade", {}).get("state") in (
        "active",
        "ACTIVE",
        "TradeState.ACTIVE",
    ), t

    # Attempt to cancel — must be rejected since trade is ACTIVE
    tx_can_active = create_cancel_trade_transaction(
        trade_id=trade_active_cancel,
        party_a=A["address"],
        privkey_hex=A["privkey_hex"],
    )
    r = submit(N1, tx_can_active)
    print("cancel active tx (should be rejected):", r)
    assert_not_ok(r, "cancel of active trade should be rejected")
    print("✅ Cancel of ACTIVE trade correctly rejected")

    # Confirm trade is still ACTIVE
    t = get_trade(N1, trade_active_cancel)
    print("trade state after rejected cancel:", t)
    assert_ok(t, "trade still exists after rejected cancel")
    assert t.get("trade", {}).get("state") in (
        "active",
        "ACTIVE",
        "TradeState.ACTIVE",
    ), f"Trade should still be ACTIVE but got: {t.get('trade', {}).get('state')}"

    # --------------------------------------------------------
    # CASE 7: Cancel PROPOSED trade is allowed
    #
    # Scenario:
    #   user1 proposes a trade. Before user2 accepts (trade still PROPOSED),
    #   user1 cancels it.
    #
    # Expected:
    #   cancel submission is accepted.
    #   after mining, trade is CANCELLED and collateral is returned.
    # --------------------------------------------------------
    print_case("CASE 7: Cancel PROPOSED (unaccepted) trade is allowed")

    trade_proposed_cancel = f"PROPCANCEL{int(time.time())}"
    collateral3 = 3000

    txp7 = create_propose_trade_transaction(
        trade_id=trade_proposed_cancel,
        party_a=A["address"],
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=45000,
        expiry_hours=1,
        collateral_amount=collateral3,
        privkey_hex=A["privkey_hex"],
    )
    r = submit(N1, txp7)
    print("propose:", r)
    assert_ok(r, "proposal submit")

    # Mine so the proposal is on-chain (collateral locked)
    r = mine(N1)
    print("mine proposal:", r)
    assert_ok(r, "mine proposal")

    t = get_trade(N1, trade_proposed_cancel)
    print("trade state after proposal mined:", t)
    assert_ok(t, "proposed trade lookup")
    assert t.get("trade", {}).get("state") in (
        "proposed",
        "PROPOSED",
        "TradeState.PROPOSED",
    ), t

    # Cancel the proposed (unaccepted) trade — must succeed
    txc7 = create_cancel_proposal_transaction(
        trade_id=trade_proposed_cancel,
        party_a=A["address"],
        privkey_hex=A["privkey_hex"],
    )
    r = submit(N1, txc7)
    print("cancel proposed tx:", r)
    assert_ok(r, "cancel of proposed trade should be accepted")
    print("✅ Cancel of PROPOSED trade accepted into mempool")

    r = mine(N1)
    print("mine cancel:", r)
    assert_ok(r, "mine cancel")

    t = get_trade(N1, trade_proposed_cancel)
    print("trade state after cancel mined:", t)
    assert_ok(t, "cancelled trade lookup")
    assert t.get("trade", {}).get("state") in (
        "cancelled",
        "CANCELLED",
        "TradeState.CANCELLED",
    ), f"Expected CANCELLED but got: {t.get('trade', {}).get('state')}"
    print("✅ PROPOSED trade correctly moved to CANCELLED after mining")

    print("\nALL DONE ✅")


if __name__ == "__main__":
    main()
