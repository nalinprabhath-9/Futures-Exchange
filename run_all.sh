#!/usr/bin/env bash
set -euo pipefail

NODE1="http://127.0.0.1:5001"
NODE2="http://127.0.0.1:5002"
NODE3="http://127.0.0.1:5003"

DB1="node_5001.db"
DB2="node_5002.db"
DB3="node_5003.db"

USERS_JSON="users.json"
KEYSTORE="keystore"

ALICE="alice"
BOB="bob"

UNDERLYING="BTC"
SIDE="LONG"
QTY=1
PRICE=45000
EXPIRY_SECONDS=3600
COLLATERAL=200

FAUCET_AMOUNT=500
LOCK_AMOUNT=250  # >= COLLATERAL

banner () {
  echo
  echo "============================================================"
  echo "$1"
  echo "============================================================"
}

wait_health () {
  local url="$1"
  echo -n "Waiting for $url/health "
  for i in {1..30}; do
    if curl -s "$url/health" >/dev/null 2>&1; then
      echo "✅"
      return 0
    fi
    echo -n "."
    sleep 0.2
  done
  echo
  echo "[ERROR] Node did not become healthy: $url"
  exit 1
}

banner "STEP 0: Reset old state"
pkill -f "python node.py" >/dev/null 2>&1 || true
rm -f ${DB1}* ${DB2}* ${DB3}* "${USERS_JSON}" >/dev/null 2>&1 || true
rm -rf "${KEYSTORE}" >/dev/null 2>&1 || true
rm -f node5001.log node5002.log node5003.log >/dev/null 2>&1 || true
echo "[OK] reset done"

banner "STEP 1: Install deps"
python -m pip install -r requirements.txt
echo "[OK] deps installed"

banner "STEP 2: Seed users + keystore (client-side private keys)"
python seed_users.py --out "${USERS_JSON}" --names "Alice,Bob,Carol" --balance 2000 --keystore "${KEYSTORE}"
echo "[OK] created ${USERS_JSON} and ${KEYSTORE}/"
ls -1 "${KEYSTORE}" | sed 's/^/[KEY] /'

banner "STEP 3: Start nodes"
python node.py --port 5001 --db "${DB1}" --peers "${NODE2},${NODE3}" > node5001.log 2>&1 &
python node.py --port 5002 --db "${DB2}" --peers "${NODE1},${NODE3}" > node5002.log 2>&1 &
python node.py --port 5003 --db "${DB3}" --peers "${NODE1},${NODE2}" > node5003.log 2>&1 &

wait_health "${NODE1}"
wait_health "${NODE2}"
wait_health "${NODE3}"

banner "STEP 4: Import users into all nodes"
curl -s -X POST "${NODE1}/import_users" -H 'Content-Type: application/json' -d "{\"path\":\"${USERS_JSON}\"}" | python -m json.tool
curl -s -X POST "${NODE2}/import_users" -H 'Content-Type: application/json' -d "{\"path\":\"${USERS_JSON}\"}" | python -m json.tool
curl -s -X POST "${NODE3}/import_users" -H 'Content-Type: application/json' -d "{\"path\":\"${USERS_JSON}\"}" | python -m json.tool
echo "[OK] users imported"

banner "STEP 5: Fund + lock collateral"
python deposit.py --node "${NODE1}" --user "${ALICE}" --amount "${FAUCET_AMOUNT}"
python deposit.py --node "${NODE2}" --user "${BOB}" --amount "${FAUCET_AMOUNT}"

python lock.py --node "${NODE1}" --user "${ALICE}" --amount "${LOCK_AMOUNT}"
python lock.py --node "${NODE2}" --user "${BOB}" --amount "${LOCK_AMOUNT}"
echo "[OK] funded and locked"

banner "STEP 6: Alice proposes on NODE1"
PROPOSE_OUT=$(python propose.py \
  --node "${NODE1}" \
  --maker "${ALICE}" \
  --key "${KEYSTORE}/${ALICE}.pem" \
  --template FUTURES_V1 \
  --underlying "${UNDERLYING}" \
  --side "${SIDE}" \
  --qty "${QTY}" \
  --price "${PRICE}" \
  --expiry "${EXPIRY_SECONDS}" \
  --collateral "${COLLATERAL}")

echo "[RESULT] propose output:"
echo "${PROPOSE_OUT}"

PROPOSAL_ID=$(echo "${PROPOSE_OUT}" | python -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('proposal_id',''))")
if [ -z "${PROPOSAL_ID}" ]; then
  echo "[ERROR] could not parse proposal_id"
  exit 1
fi
echo "[OK] proposal_id=${PROPOSAL_ID}"

sleep 0.5
echo "[INFO] NODE2 proposals (should show OPEN):"
curl -s "${NODE2}/proposals" | python -m json.tool

banner "STEP 7: Bob accepts on NODE2 (tx is built on NODE2 and gossiped to peers)"
ACCEPT_OUT=$(python accept.py \
  --node "${NODE2}" \
  --taker "${BOB}" \
  --key "${KEYSTORE}/${BOB}.pem" \
  --proposal "${PROPOSAL_ID}")

echo "[RESULT] accept output:"
echo "${ACCEPT_OUT}"

sleep 0.8

banner "STEP 8: Prove tx gossip (mempool on NODE1 should contain tx even though accept ran on NODE2)"
echo "[INFO] NODE2 mempool:"
curl -s "${NODE2}/mempool" | python -m json.tool

echo "[INFO] NODE1 mempool:"
curl -s "${NODE1}/mempool" | python -m json.tool

banner "STEP 9: Mine on NODE1 (different node than accept) with capacity limit"
echo "[ACTION] mine on NODE1"
python mine.py --node "${NODE1}"

echo "[INFO] NODE1 mempool after mining:"
curl -s "${NODE1}/mempool" | python -m json.tool

echo "[INFO] NODE1 chain tip (latest 5 blocks):"
curl -s "${NODE1}/chain?limit=5" | python -m json.tool

banner "DONE ✅"
echo "Stop nodes: pkill -f 'python node.py'"
echo "Logs: node5001.log node5002.log node5003.log"