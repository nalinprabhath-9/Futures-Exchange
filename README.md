# Futures-Exchange

A blockchain-based futures trading system with 3 nodes, a price oracle, and a CLI wallet.

---

## Setup

Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

## Starting the System

```bash
# 1. Bring up oracle + 3 blockchain nodes (all in one)
docker compose up --build -d

# 2. Create 5 users and write keys to users.json
python scripts/bootstrap_users.py

# 3. Fund each user with starting balance on all nodes
python scripts/bootstrap_faucet.py
```

To stop everything:

```bash
docker compose down
```

---

## CLI Usage

```text
python wallet.py <command>
```

| Command | Description |
| --- | --- |
| `health` | Health check all 3 nodes |
| `balance <user>` | Show total / locked / available balance |
| `propose <user>` | Propose a new trade (interactive options) |
| `accept <user>` | Show open proposals and pick one to accept |
| `mempool` | Show pending transactions across all nodes |
| `mine` | Mine a block on node1 and sync to node2/node3 |
| `oracle <asset>` | Fetch live signed price from the oracle |
| `settle <user>` | Show active expired trades and pick one to settle |
| `flush` | Clear mempool on all nodes |
| `sync` | Force node2/node3 to sync from node1 |

User aliases: `alice` = user1, `bob` = user2, `carol` = user3

Propose options:

```bash
python wallet.py propose alice --asset ETH/USD --strike 3000 --collateral 50000 --expiry 5
```

`--collateral` is in milli-coins (1000 = 1 FutureCoin). `--expiry` is in minutes.

---

## End-to-End Trade

```bash
# Check everyone is up
python wallet.py health

# Check balances
python wallet.py balance alice
python wallet.py balance bob

# Alice proposes a trade
python wallet.py propose alice --asset BTC/USD --strike 85000 --collateral 50000 --expiry 5

# Bob picks from the open proposal list and accepts
python wallet.py accept bob

# Mine to lock in both proposal and acceptance
python wallet.py mine

# Confirm trade is now ACTIVE on all nodes
python wallet.py status

# Wait for expiry (5 minutes), then settle
# Carol (or any user) submits settlement using the oracle price
python wallet.py settle carol

# Mine to finalise the payout
python wallet.py mine

# Check updated balances — winner receives 2x collateral
python wallet.py balance alice
python wallet.py balance bob
```

---

## Running Tests

### Automated E2E (starts nodes, bootstraps, runs all tests, tears down)

```bash
chmod +x scripts/run_e2e.sh
./scripts/run_e2e.sh
```

This script:

1. Calls `./scripts/up.sh 3` to generate the compose file and start 3 nodes
2. Bootstraps users and funds them via faucet
3. Runs `tests/test_all.py` (propose → accept → mine → settle, plus edge cases)

### Manual steps

```bash
# Start nodes
./scripts/up.sh 3

# Bootstrap users and fund
python scripts/bootstrap_users.py
python scripts/bootstrap_faucet.py

# Run the full test suite
python tests/test_all.py

# Stop nodes
./scripts/down.sh
```
