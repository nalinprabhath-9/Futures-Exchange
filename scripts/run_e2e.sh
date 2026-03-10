#!/usr/bin/env bash
set -euo pipefail

N="${1:-3}"
./scripts/up.sh "$N"

# wait nodes
sleep 2

# bootstrap users + fund
export NODES=$(python - <<'PY'
n=3
print(",".join([f"http://localhost:{5000+i}" for i in range(1,n+1)]))
PY
)
python scripts/bootstrap_users.py
python scripts/bootstrap_faucet.py

# run tests
python tests/test_all.py

echo "Success: e2e finished"