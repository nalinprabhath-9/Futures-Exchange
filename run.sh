#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Futures Exchange Full Flow Runner
#
# Uses ONLY existing project scripts / endpoints.
#
# Usage:
#   ./scripts/run_full_flow.sh <num_nodes> <num_users>
#
# Example:
#   ./scripts/run_full_flow.sh 3 5
#
# Flow covered:
#   1) Create node containers
#   2) Create users
#   3) Import same users into all nodes
#   4) Show users
#   5) Show available contract templates
#   6) User1 creates proposal and signs it
#   7) Proposal reaches all nodes
#   8) Mine proposal -> maker collateral lock happens here
#   9) User2 accepts and signs it
#  10) Accept reaches all nodes
#  11) Mine accept -> taker collateral lock happens here
#  12) Show trade state / mempool / blockchain
#
# IMPORTANT:
#   In current blockchain.py:
#   - proposal tx is signed with ECDSA (secp256k1)
#   - accept tx is signed with ECDSA (secp256k1)
#   - collateral is locked when tx is mined
#   - mining is NOT automatic unless separately implemented
# ============================================================

NODES="${1:-3}"
USERS="${2:-5}"

ROOT_DIR="$(pwd)"
cd "$ROOT_DIR"
echo "$ROOT_DIR"

echo "=================================================="
echo " Futures Exchange Full Flow"
echo " Nodes: $NODES"
echo " Users: $USERS"
echo "=================================================="

echo
echo "STEP 1: Create node containers"
echo "Triggers:"
echo "  - scripts/gen_compose.sh"
echo "  - docker compose"
echo "  - node/app.py starts inside each container"
chmod +x scripts/gen_compose.sh scripts/up.sh scripts/down.sh || true
./scripts/up.sh "$NODES"

echo
echo "STEP 2: Create users"
echo "Triggers:"
echo "  - scripts/bootstrap_users.py"
echo "  - node/crypto_utils.py"
echo "      get_signing_key_from_hex()"
echo "      get_compressed_pubkey()"
echo "      pubkey_to_address()"
export USERS="$USERS"
export NODES="$(printf "http://localhost:%s," $(seq 5001 $((5000+NODES))) | sed 's/,$//')"
python scripts/bootstrap_users.py

echo
echo "STEP 3: Fund wallets"
echo "Triggers:"
echo "  - scripts/bootstrap_faucet.py"
echo "  - node/app.py -> /admin/fund or /faucet"
python scripts/bootstrap_faucet.py

echo
echo "STEP 4: Show all users on all nodes"
echo "Triggers:"
echo "  - node/app.py -> /users"
for i in $(seq 1 "$NODES"); do
  PORT=$((5000 + i))
  echo
  echo "--- node${i} users ---"
  curl -s "http://localhost:${PORT}/users" | python -m json.tool
done

echo
echo "STEP 5: Show available contract templates"
echo "Defined in:"
echo "  - node/transaction_enums.py -> TemplateType"
python - <<'PY'
from node.transaction_enums import TemplateType
print("Available templates:")
for t in TemplateType:
    print(" -", t.value)
PY

echo
echo "STEP 6 onward uses tests/test_all.py"
echo "Triggers inside that file:"
echo "  - node/blockchain.py -> create_propose_trade_transaction()"
echo "  - node/blockchain.py -> create_accept_trade_transaction()"
echo "  - node/crypto_utils.py -> sign_message(), verify_signature()"
echo "  - node/tx_codec.py -> futures_tx_to_wire()"
echo "  - node/app.py -> /tx/submit, /mine, /trade/<id>, /mempool"
echo "  - node/blockchain.py -> Miner.mine_block(), Blockchain.add_block()"
echo "  - node/blockchain.py -> _process_futures_transaction()"
echo "      PROPOSE_TRADE => maker collateral lock (when mined)"
echo "      ACCEPT_TRADE  => taker collateral lock (when mined)"
echo

echo "STEP 6-15: Run full test flow"
python tests/test_all.py

echo
echo "STEP 16: Show blockchain state on all nodes"
for i in $(seq 1 "$NODES"); do
  PORT=$((5000 + i))
  echo
  echo "--- node${i} chain ---"
  curl -s "http://localhost:${PORT}/chain?limit=5" | python -m json.tool || true
done

echo
echo "STEP 17: Show mempool state on all nodes"
for i in $(seq 1 "$NODES"); do
  PORT=$((5000 + i))
  echo
  echo "--- node${i} mempool ---"
  curl -s "http://localhost:${PORT}/mempool" | python -m json.tool || true
done

echo
echo "=================================================="
echo " Full flow complete ✅"
echo "=================================================="
echo
echo "Note:"
echo "  Transactions may gossip automatically."
echo "  Mining does NOT automatically start unless you implemented"
echo "  a background miner in node/app.py."
echo
echo "Stop containers with:"
echo "  ./scripts/down.sh"