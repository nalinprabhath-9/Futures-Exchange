#!/usr/bin/env bash
set -euo pipefail

./scripts/up.sh

# wait for nodes to be ready
sleep 2

# bootstrap users + fund
export NODES="http://localhost:5001,http://localhost:5002,http://localhost:5003"
python scripts/bootstrap_users.py
python scripts/bootstrap_faucet.py

# run tests
python tests/test_all.py

echo "Successfully completed."
