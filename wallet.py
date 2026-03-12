#!/usr/bin/env python3
"""
Futures-Exchange wallet CLI
============================
Simple command-line interface
"""

import argparse
import json
import os
import sys
import time

import requests

USE_COLOR = sys.stdout.isatty()

GREEN = "\033[92m" if USE_COLOR else ""
RED = "\033[91m" if USE_COLOR else ""
RESET = "\033[0m" if USE_COLOR else ""

# ── path so node.* imports work from project root ────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from node.blockchain import (
    FuturesTransaction,
    MILLI_DENOMINATION,
    CRYPTOCURRENCY_NAME,
    create_accept_trade_transaction,
    create_settle_trade_transaction,
)
from node.transaction_enums import TransactionType, TradeState, TemplateType
from node.crypto_utils import (
    get_signing_key_from_hex,
    get_compressed_pubkey,
    sign_message,
)
from node.tx_codec import futures_tx_to_wire

# ── Config from env ───────────────────────────────────────────────────────────
_node_urls = os.environ.get(
    "NODES", "http://localhost:5001,http://localhost:5002,http://localhost:5003"
).split(",")
N1, N2, N3 = _node_urls[0], _node_urls[1], _node_urls[2]
ORACLE_URL = os.environ.get("ORACLE", "http://localhost:8080")
USERS_FILE = os.environ.get("USERS_FILE", "users.json")
ASSET = os.environ.get("ASSET", "BTC/USD")
STRIKE = float(os.environ.get("STRIKE", "45000"))
COLLATERAL = int(os.environ.get("COLLATERAL", "50000"))
EXPIRY_MINS = int(os.environ.get("EXPIRY_MINS", "5"))

LAST_TRADE_FILE = ".last_trade"

# ── Display helpers ───────────────────────────────────────────────────────────
W = 60


def _sep():
    print("─" * W)


def _header(title):
    print()
    print("┌" + "─" * (W - 2) + "┐")
    pad = (W - 2 - len(title)) // 2
    print("│" + " " * pad + title + " " * (W - 2 - pad - len(title)) + "│")
    print("└" + "─" * (W - 2) + "┘")


def _ok(msg):
    print(f"{GREEN}  {msg}{RESET}")


def _err(msg):
    print(f"{RED}  {msg}{RESET}", file=sys.stderr)


def _coins(milli):
    return f"{milli / MILLI_DENOMINATION:.1f} {CRYPTOCURRENCY_NAME}"


# ── User helpers ──────────────────────────────────────────────────────────────
def _load_users():
    if not os.path.exists(USERS_FILE):
        _err(f"{USERS_FILE} not found. Run: python scripts/bootstrap_users.py")
    return {u["user_id"]: u for u in json.load(open(USERS_FILE))}


def _get_user(name):
    users = _load_users()
    key = name if name.startswith("user") else f"user{name}"
    # also accept first-name aliases
    aliases = {
        "alice": "user1",
        "bob": "user2",
        "carol": "user3",
        "dave": "user4",
        "eve": "user5",
    }
    key = aliases.get(name.lower(), key)
    if key not in users:
        _err(f"Unknown user '{name}'. Available: {list(aliases.keys())}")
    return users[key]


# ── Network helpers ───────────────────────────────────────────────────────────
def _submit(node_url, tx):
    try:
        r = requests.post(
            f"{node_url}/tx/submit",
            json={"tx": futures_tx_to_wire(tx)},
            timeout=10,
        ).json()
    except requests.exceptions.ConnectionError:
        _err(f"Could not reach {node_url}. Are the nodes running?")
    if not r.get("ok"):
        _err(f"Transaction rejected: {r.get('error', r)}")
    return r


def _mine_block(node_url):
    try:
        r = requests.post(f"{node_url}/mine", json={}, timeout=30).json()
    except requests.exceptions.ConnectionError:
        _err(f"Could not reach {node_url}.")
    if not r.get("ok"):
        _err(f"Mining failed: {r.get('error', r)}")
    return r


def _get_balance(node_url, address):
    return requests.get(f"{node_url}/balance/{address}", timeout=5).json()


def _get_trade(node_url, trade_id):
    return requests.get(f"{node_url}/trade/{trade_id}", timeout=5).json()


def _get_mempool(node_url):
    return requests.get(f"{node_url}/mempool", timeout=5).json()


def _get_health(node_url):
    return requests.get(f"{node_url}/health", timeout=5).json()


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_health(args):
    _header("NETWORK STATUS")
    for label, url in [("node1", N1), ("node2", N2), ("node3", N3)]:
        try:
            h = _get_health(url)
            peers = len(h.get("peers", []))
            _ok(
                f"{label:<8}  height={h['tip_height']}  mempool={h['mempool']}  peers={peers}  {url}"
            )
        except Exception:
            _err(f"{label:<8}  UNREACHABLE  {url}")


def cmd_balance(args):
    user = _get_user(args.user)
    addr = user["address"]
    _header(f"BALANCE — {args.user.upper()}")
    print(f"Address : {addr}")
    _sep()
    for label, url in [("node1", N1), ("node2", N2), ("node3", N3)]:
        try:
            b = _get_balance(url, addr)
            if not b.get("ok"):
                print(f"{label}  unexpected response: {b}")
                continue
            _ok(
                f"{label}  total={_coins(b['balance'])}  locked={_coins(b['locked'])}  available={_coins(b['available'])}"
            )
        except Exception:
            _err(f"{label}  UNREACHABLE")


def cmd_propose(args):
    user = _get_user(args.user)
    trade_id = f"DEMO-{int(time.time())}"
    asset = args.asset or ASSET
    strike = args.strike or STRIKE
    collat = args.collateral or COLLATERAL
    expiry = args.expiry or EXPIRY_MINS

    _header(f"PROPOSE TRADE — {args.user.upper()} → node1")
    print(f"Asset    : {asset}")
    print(f"Template : UP/DOWN  (binary: price above or below strike at expiry)")
    print(f"Strike   : ${strike:,.0f}")
    print(f"Collat   : {_coins(collat)} (will lock from {args.user} on mine)")
    print(f"Expiry   : {expiry} minutes from now")
    print(f"Trade ID : {trade_id}")
    _sep()

    expiry_ts = int(time.time()) + expiry * 60
    tx = FuturesTransaction(
        trade_id=trade_id,
        tx_type=TransactionType.PROPOSE_TRADE,
        party_a=user["address"],
        template_type=TemplateType.UP_DOWN,
        asset_pair=asset,
        strike_price=float(strike),
        expiry_timestamp=expiry_ts,
        collateral_amount=collat,
        state=TradeState.PROPOSED,
        fee=1000,
    )
    sk = get_signing_key_from_hex(user["privkey_hex"])
    tx.signature = sign_message(sk, tx.get_signing_data())
    tx.pubkey = get_compressed_pubkey(sk.verifying_key)

    r = _submit(N1, tx)

    _ok(f"Accepted by node1  tx={r['tx_hash'][:20]}...")


def cmd_accept(args):
    user = _get_user(args.user)

    # If --trade-id was given explicitly, skip the interactive list
    if args.trade_id:
        trade_id = args.trade_id
    else:
        # Fetch open proposals from node1
        try:
            resp = requests.get(f"{N1}/proposals", timeout=5).json()
            proposals = resp.get("open", [])
        except Exception:
            _err("Could not reach node1 to fetch proposals.")

        # Filter out proposals made by this user (can't accept your own trade)
        proposals = [p for p in proposals if p.get("party_a") != user["address"]]

        if not proposals:
            _err("No open proposals available to accept.")

        _header("OPEN PROPOSALS")
        for i, p in enumerate(proposals):
            expiry_str = time.strftime(
                "%H:%M:%S", time.localtime(p.get("expiry_timestamp", 0))
            )
            collat_str = _coins(p.get("collateral_amount", 0))
            party_a_short = (p.get("party_a") or "")[:16]
            print(
                f"  [{i + 1}]  {p['trade_id']}"
                f"\n       Asset  : {p.get('asset_pair')}  Strike : ${p.get('strike_price', 0):,.0f}"
                f"\n       Collateral : {collat_str}  Expiry : {expiry_str}"
                f"\n       From   : {party_a_short}..."
            )
        _sep()

        # Prompt user to pick
        while True:
            try:
                choice = input(
                    f"  Enter number to accept [1-{len(proposals)}], or 'q' to quit: "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                _err("Aborted.")
                sys.exit(1)
            if choice.lower() == "q":
                _err("Aborted.")
                sys.exit(1)
            if choice.isdigit() and 1 <= int(choice) <= len(proposals):
                selected = proposals[int(choice) - 1]
                trade_id = selected["trade_id"]
                break
            print(f"Invalid choice, enter a number between 1 and {len(proposals)}.")

    _header(f"ACCEPT TRADE — {args.user.upper()} → node2")
    print(f"Trade ID : {trade_id}")
    print(f"Party B  : {user['address']}")
    _sep()

    tx = create_accept_trade_transaction(
        trade_id=trade_id,
        party_b=user["address"],
        privkey_hex=user["privkey_hex"],
    )
    r = _submit(N2, tx)
    _ok(f"Accepted by node2  tx={r['tx_hash'][:20]}...")


def cmd_mempool(args):
    _header("MEMPOOL — PENDING TRANSACTIONS")
    for label, url in [("node1", N1), ("node2", N2), ("node3", N3)]:
        try:
            mp = _get_mempool(url)
            txs = mp.get("mempool", [])
            if txs:
                for t in txs:
                    _ok(
                        f"{label}  {t['tx_type']:<20}  fee={t['fee']}  trade={t.get('trade_id','')}"
                    )
            else:
                print(f"{label}  (empty)")
        except Exception:
            _err(f"{label}  UNREACHABLE")


def _sync_node(label, node_url, source_url):
    """Ask node_url to sync from source_url. Returns new height or None."""
    try:
        r = requests.post(
            f"{node_url}/admin/sync_from", json={"peer": source_url}, timeout=20
        ).json()
        if r.get("ok"):
            return r.get("tip_height")
    except Exception:
        pass
    return None


def cmd_mine(args):
    node_url = N1
    _header("MINE BLOCK — node1")
    r = _mine_block(node_url)
    _ok(
        f"Block mined!  height={r['mined_height']}  txs={r['included_txs']}  mempool_after={r['mempool_after']}"
    )
    _ok(f"Hash  : {r['block_hash']}")
    # Push the new block to node2 and node3
    time.sleep(0.5)  # brief pause for gossip to propagate
    for label, url in [("node2", N2), ("node3", N3)]:
        try:
            h = requests.get(f"{url}/health", timeout=3).json().get("tip_height", "?")
            if h != r["mined_height"]:
                new_h = _sync_node(label, url, N1)
                if new_h is not None:
                    _ok(f"{label}  synced, height={new_h}")
        except Exception:
            pass


def cmd_flush(args):
    """Clear stale mempool entries on all nodes (useful before a fresh demo run)."""
    _header("FLUSH MEMPOOL — all nodes")
    for label, url in [("node1", N1), ("node2", N2), ("node3", N3)]:
        try:
            r = requests.post(f"{url}/admin/flush_mempool", json={}, timeout=5).json()
            if r.get("ok"):
                _ok(f"{label}  mempool cleared")
            else:
                _err(f"{label}  {r.get('error', r)}")
        except Exception:
            _err(f"{label}  UNREACHABLE")


def cmd_sync(args):
    """Sync node2 and node3 with node1."""
    _header("SYNC — node2 & node3 with node1")
    for label, url in [("node2", N2), ("node3", N3)]:
        new_h = _sync_node(label, url, N1)
        if new_h is not None:
            _ok(f"{label}  synced, height={new_h}")
        else:
            _err(f"{label}  sync failed or already up to date")


def cmd_oracle(args):
    asset = (args.asset or "BTC").upper()
    symbol = asset.split("/")[0]  # "BTC/USD" -> "BTC"
    _header(f"ORACLE PRICE — {symbol}")
    try:
        r = requests.get(f"{ORACLE_URL}/price/{symbol}", timeout=10).json()
    except requests.exceptions.ConnectionError:
        _err(f"Oracle unreachable at {ORACLE_URL}. Is it running?")

    ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["timestamp"]))
    _ok(f"Price      : ${r['price']:,.2f}")
    _ok(f"Timestamp  : {ts_str}")
    _ok(f"Signature  : {r['signature'][:32]}...")
    _ok(f"Oracle key : {r['oracle_pubkey'][:24]}...")


def cmd_settle(args):
    user = _get_user(args.user)

    if args.trade_id:
        trade_id = args.trade_id
    else:
        # Fetch all active trades from node1
        try:
            resp = requests.get(f"{N1}/trades", timeout=5).json()
            active = resp.get("active", [])
        except Exception:
            _err("Could not reach node1 to fetch active trades.")

        # Filter to only trades that have reached expiry
        now = int(time.time())
        ready = [t for t in active if t.get("expiry_timestamp", 0) <= now]
        not_ready = [t for t in active if t.get("expiry_timestamp", 0) > now]

        if not active:
            _err("No active trades found. Mine the proposal + acceptance block first.")

        _header("ACTIVE TRADES")
        if not_ready:
            print("Not yet expired (cannot settle):")
            for t in not_ready:
                remaining = t.get("expiry_timestamp", 0) - now
                mins, secs = divmod(remaining, 60)
                expiry_str = time.strftime(
                    "%H:%M:%S", time.localtime(t.get("expiry_timestamp", 0))
                )
                print(
                    f"  {t['trade_id']}  {t.get('asset_pair')}  "
                    f"strike=${t.get('strike_price', 0):,.0f}  "
                    f"expires {expiry_str} ({mins}m {secs}s)"
                )
            _sep()

        if not ready:
            _err(
                "No trades have reached expiry yet. Wait for the expiry time shown above."
            )

        print("Ready to settle:")
        for i, t in enumerate(ready):
            expiry_str = time.strftime(
                "%H:%M:%S", time.localtime(t.get("expiry_timestamp", 0))
            )
            party_a_short = (t.get("party_a") or "")[:16]
            party_b_short = (t.get("party_b") or "")[:16]
            print(
                f"  [{i + 1}]  {t['trade_id']}"
                f"\n       Asset  : {t.get('asset_pair')}  Strike : ${t.get('strike_price', 0):,.0f}"
                f"\n       Collat : {_coins(t.get('collateral_amount', 0))}  Expired : {expiry_str}"
                f"\n       A={party_a_short}...  B={party_b_short}..."
            )
        _sep()

        while True:
            try:
                choice = input(
                    f"  Enter number to settle [1-{len(ready)}], or 'q' to quit: "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                _err("Aborted.")
                sys.exit(1)
            if choice.lower() == "q":
                _err("Aborted.")
                sys.exit(1)
            if choice.isdigit() and 1 <= int(choice) <= len(ready):
                trade_id = ready[int(choice) - 1]["trade_id"]
                break
            print(f"     Invalid choice, enter a number between 1 and {len(ready)}.")

    # Fetch the selected trade
    t = _get_trade(N1, trade_id).get("trade")
    if not t:
        _err(f"Trade {trade_id} not found on node1. Has the proposal been mined?")
    if t.get("state") not in ("TradeState.ACTIVE", "active", "ACTIVE"):
        _err(
            f"Trade is not ACTIVE (state={t.get('state')}). Mine the proposal/accept block first."
        )

    expiry = t.get("expiry_timestamp", 0)
    now = int(time.time())
    if expiry and now < expiry:
        remaining = expiry - now
        mins, secs = divmod(remaining, 60)
        expiry_str = time.strftime("%H:%M:%S", time.localtime(expiry))
        _err(
            f"Trade has not expired yet (expires at {expiry_str}, {mins}m {secs}s remaining).\n"
            f"     Settlement is only valid at or after expiry."
        )

    party_a = t["party_a"]
    party_b = t["party_b"]
    collat = t["collateral_amount"]
    strike = float(t["strike_price"])
    asset = t["asset_pair"].split("/")[0]

    # Fetch oracle price
    try:
        oracle = requests.get(f"{ORACLE_URL}/price/{asset}", timeout=10).json()
    except Exception:
        _err(f"Oracle unreachable at {ORACLE_URL}.")

    price = oracle["price"]

    # Determine winner
    if price > strike:
        winner, loser = party_a, party_b
        winner_label, loser_label = "Party A (proposer)", "Party B (acceptor)"
        result = f"${price:,.2f} > ${strike:,.0f} → price went UP"
    else:
        winner, loser = party_b, party_a
        winner_label, loser_label = "Party B (acceptor)", "Party A (proposer)"
        result = f"${price:,.2f} ≤ ${strike:,.0f} → price went DOWN"

    winner_payout = collat * 2
    loser_payout = 0

    _header(f"SETTLE TRADE — {args.user.upper()} → node3")
    print(f"Trade ID       : {trade_id}")
    print(f"Oracle price   : ${price:,.2f}")
    print(f"Strike price   : ${strike:,.0f}")
    print(f"Result         : {result}")
    _sep()
    print(f"Winner  : {winner_label}  → receives {_coins(winner_payout)}")
    print(f"Loser   : {loser_label}   → receives {_coins(loser_payout)}")
    _sep()

    tx = create_settle_trade_transaction(
        trade_id=trade_id,
        settlement_price=price,
        winner=winner,
        winner_payout=winner_payout,
        loser_payout=loser_payout,
        privkey_hex=user["privkey_hex"],
    )
    r = _submit(N3, tx)
    _ok(f"Settlement accepted by node3  tx={r['tx_hash'][:20]}...")
    _ok("Mine the next block to finalize the payout")


def cmd_status(args):
    """Show all active trades across all 3 nodes."""
    _header("ACTIVE TRADES ACROSS ALL NODES")
    for label, url in [("node1", N1), ("node2", N2), ("node3", N3)]:
        try:
            resp = requests.get(f"{url}/trades", timeout=5)
            if resp.status_code == 200:
                trades = resp.json().get("active", [])
                print(f"{label}: {len(trades)} active trade(s)")
                for t in trades:
                    expiry_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t.get("expiry_timestamp", 0)))
                    print(f"  {t['trade_id']}  {t.get('asset_pair')}  strike=${t.get('strike_price', 0):,.0f}  collat={_coins(t.get('collateral_amount', 0))}  expires {expiry_str}  A={t.get('party_a','')[:8]}...  B={t.get('party_b','')[:8]}...")
            else:
                print(f"{label}: not found")
        except Exception as e:
            print(f"{label}: error ({e})")
    _sep()


# ── Argument parser ───────────────────────────────────────────────────────────


def build_parser():
    p = argparse.ArgumentParser(
        prog="wallet.py",
        description="Futures-Exchange demo wallet CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", metavar="command")
    sub.required = True

    sub.add_parser("health", help="Health check all 3 nodes")

    sp = sub.add_parser("balance", help="Show a user's balance")
    sp.add_argument("user", help="alice | bob | carol | user1 | user2 ...")

    sp = sub.add_parser(
        "propose", help="Propose a new trade (default: BTC/USD UP/DOWN)"
    )
    sp.add_argument("user", help="Proposing party, e.g. alice")
    sp.add_argument("--asset", default=None, help=f"Asset pair (default: {ASSET})")
    sp.add_argument(
        "--strike", default=None, type=float, help=f"Strike price (default: {STRIKE})"
    )
    sp.add_argument(
        "--collateral",
        default=None,
        type=int,
        help=f"Collateral in milli-coins (default: {COLLATERAL})",
    )
    sp.add_argument(
        "--expiry",
        default=None,
        type=int,
        help=f"Expiry in minutes (default: {EXPIRY_MINS})",
    )

    sp = sub.add_parser("accept", help="Pick and accept an open trade proposal")
    sp.add_argument("user", help="Accepting party, e.g. bob")
    sp.add_argument(
        "--trade-id",
        default=None,
        help="Skip the list and accept a specific trade ID directly",
    )

    sub.add_parser("mempool", help="Show pending transactions on all nodes")

    sub.add_parser("mine", help="Mine a block on node1")

    sub.add_parser("flush", help="Clear stale mempool on all nodes (run before demo)")

    sub.add_parser("sync", help="Sync node2 & node3 from node1 (catch up after mining)")

    sp = sub.add_parser("status", help="Show trade state across all 3 nodes")
    sp.add_argument(
        "--trade-id", default=None, help="Trade ID (default: last proposed)"
    )

    sp = sub.add_parser("oracle", help="Fetch signed price from oracle")
    sp.add_argument(
        "asset", nargs="?", default="BTC", help="Asset symbol, e.g. BTC (default: BTC)"
    )

    sp = sub.add_parser("settle", help="Settle the last trade using oracle price")
    sp.add_argument("user", help="Who submits the settlement, e.g. alice")
    sp.add_argument(
        "--trade-id", default=None, help="Trade ID (default: last proposed)"
    )

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "health": cmd_health,
        "balance": cmd_balance,
        "propose": cmd_propose,
        "accept": cmd_accept,
        "mempool": cmd_mempool,
        "mine": cmd_mine,
        "flush": cmd_flush,
        "sync": cmd_sync,
        "oracle": cmd_oracle,
        "settle": cmd_settle,
        "status": cmd_status,
    }
    dispatch[args.command](args)
    print()


if __name__ == "__main__":
    main()
