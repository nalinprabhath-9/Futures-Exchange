import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json, time, requests
from node.blockchain import (
    create_propose_trade_transaction,
    create_accept_trade_transaction,
    create_cancel_proposal_transaction,
    create_cancel_trade_transaction,
)
from node.transaction_enums import TemplateType

N1 = "http://localhost:5001"
N2 = "http://localhost:5002"
N3 = "http://localhost:5003"


def submit(node, tx):
    from node.tx_codec import futures_tx_to_wire
    return requests.post(f"{node}/tx/submit", json={"tx": futures_tx_to_wire(tx)}, timeout=10).json()


def mine(node):
    return requests.post(f"{node}/mine", json={}, timeout=30).json()


def get_trade(node, trade_id):
    return requests.get(f"{node}/trade/{trade_id}", timeout=10).json()


def get_balance(node, address):
    return requests.get(f"{node}/balance/{address}", timeout=10).json()


def assert_ok(resp):
    assert resp.get("ok"), resp


def assert_not_ok(resp):
    assert not resp.get("ok"), resp


def main():
    users = json.load(open("users.json"))
    A = users[0]
    B = users[1]
    C = users[2]

    # -----------------------------------------
    # Happy path: propose(A)->accept(B)->mine
    # -----------------------------------------
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
    assert_ok(r)

    txa = create_accept_trade_transaction(
        trade_id=trade_id,
        party_b=B["address"],
        privkey_hex=B["privkey_hex"],
        high_priority=True,
    )
    r = submit(N2, txa)
    print("accept:", r)
    assert_ok(r)

    r = mine(N1)
    print("mine:", r)
    assert_ok(r)

    t = get_trade(N1, trade_id)
    print("trade:", t)
    assert_ok(t)
    assert t.get("trade", {}).get("state") in ("active", "ACTIVE", "TradeState.ACTIVE"), t

    # -----------------------------------------
    # Edge: low fee rejection
    # -----------------------------------------
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
            fee=1,  # too low intentionally
            privkey_hex=A["privkey_hex"],
        )
        r = submit(N1, tx_lowfee)
        print("low fee submit:", r)
        assert_not_ok(r)
        print("✅ Low-fee tx rejected at submit/mempool")
    except ValueError as e:
        print("✅ Low-fee tx rejected at construction time:", str(e))

    # -----------------------------------------
    # Edge: invalid signature rejection
    # -----------------------------------------
    trade_sig = f"BADSIG{int(time.time())}"
    tx_bad_sig = create_propose_trade_transaction(
        trade_id=trade_sig,
        party_a=A["address"],
        template_type=TemplateType.UP_DOWN,
        asset_pair="BTC/USD",
        strike_price=45000,
        expiry_hours=1,
        collateral_amount=collateral,
        privkey_hex=None,  # unsigned
    )
    tx_bad_sig.signature = b"\x30\x00"  # invalid DER
    tx_bad_sig.pubkey = bytes.fromhex(A["pubkey_hex"])
    r = submit(N1, tx_bad_sig)
    print("bad sig submit:", r)
    assert_not_ok(r)
    print("✅ Bad signature rejected")

    # -----------------------------------------
    # Edge: cancel proposal before acceptance
    # -----------------------------------------
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
    assert_ok(r)

    txc = create_cancel_proposal_transaction(
        trade_id=trade_cancel,
        privkey_hex=A["privkey_hex"],
    )
    r = submit(N1, txc)
    print("cancel proposal tx:", r)
    assert_ok(r)

    r = mine(N1)
    print("mine cancel:", r)
    assert_ok(r)

    t = get_trade(N1, trade_cancel)
    print("trade cancel state:", t)
    assert_ok(t)
    assert t.get("trade", {}).get("state") in ("cancelled", "CANCELLED", "TradeState.CANCELLED"), t
    print("✅ Cancel proposal works")

    # --------------------------------------------------------
    # Edge: insufficient collateral for party B acceptance
    # --------------------------------------------------------
    # Make collateral huge so B cannot cover it.
    # This should cause accept to be rejected (either at submit validation
    # or when mined/processed).
    trade_insuf = f"INSUF{int(time.time())}"
    huge_collateral = 10_000_000_000  # absurdly large milli amount

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

    # proposal might itself fail if A can't lock huge collateral; that's still valid.
    if not r.get("ok"):
        print("✅ Insufficient-collateral test: proposal rejected as expected (A can't lock huge collateral)")
    else:
        # If A somehow has enough (unlikely), then B acceptance should fail.
        tx_insuf_acc = create_accept_trade_transaction(
            trade_id=trade_insuf,
            party_b=B["address"],
            privkey_hex=B["privkey_hex"],
        )
        r2 = submit(N2, tx_insuf_acc)
        print("accept insuf:", r2)

        # Depending on your server rules, it might reject immediately
        # OR accept into mempool but fail on mining. Handle both:
        if not r2.get("ok"):
            print("✅ Acceptance rejected at submit due to insufficient collateral")
        else:
            # Try mining; if accept is invalid, chain processing should reject it.
            r3 = mine(N1)
            print("mine insuf:", r3)
            assert_ok(r3)
            t2 = get_trade(N1, trade_insuf)
            print("trade insuf state:", t2)

            # Trade should NOT become active.
            if t2.get("ok"):
                assert t2.get("trade", {}).get("state") not in ("active", "ACTIVE", "TradeState.ACTIVE"), t2
            print("✅ Acceptance did not activate trade due to insufficient collateral")

    # --------------------------------------------------------
    # Edge: cancel ACTIVE trade (after acceptance)
    # --------------------------------------------------------
    trade_active_cancel = f"ACTCANCEL{int(time.time())}"
    collateral2 = 40000

    # record balances before (optional sanity)
    balA_before = get_balance(N1, A["address"])
    balB_before = get_balance(N1, B["address"])
    print("balA before:", balA_before)
    print("balB before:", balB_before)

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
    assert_ok(r)

    txa5 = create_accept_trade_transaction(
        trade_id=trade_active_cancel,
        party_b=B["address"],
        privkey_hex=B["privkey_hex"],
    )
    r = submit(N2, txa5)
    print("accept active-cancel:", r)
    assert_ok(r)

    r = mine(N1)
    print("mine to activate:", r)
    assert_ok(r)

    t = get_trade(N1, trade_active_cancel)
    print("trade active:", t)
    assert_ok(t)
    assert t.get("trade", {}).get("state") in ("active", "ACTIVE", "TradeState.ACTIVE"), t

    # cancel active trade (party_a cancels)
    tx_can_active = create_cancel_trade_transaction(
        trade_id=trade_active_cancel,
        party_a=A["address"],
        privkey_hex=A["privkey_hex"],
    )
    r = submit(N1, tx_can_active)
    print("cancel active tx:", r)
    assert_ok(r)

    r = mine(N1)
    print("mine cancel active:", r)
    assert_ok(r)

    t = get_trade(N1, trade_active_cancel)
    print("trade after cancel active:", t)
    assert_ok(t)
    assert t.get("trade", {}).get("state") in ("cancelled", "CANCELLED", "TradeState.CANCELLED"), t
    print("✅ Cancel ACTIVE trade works")

    # balances after (optional sanity)
    balA_after = get_balance(N1, A["address"])
    balB_after = get_balance(N1, B["address"])
    print("balA after:", balA_after)
    print("balB after:", balB_after)

    print("\nALL DONE ✅")


if __name__ == "__main__":
    main()