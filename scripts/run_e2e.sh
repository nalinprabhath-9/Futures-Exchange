#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

cleanup() {
  ./scripts/down.sh --clean
}

wait_for_ready() {
  local endpoints=(
    "http://localhost:8080/health"
    "http://localhost:5001/health"
    "http://localhost:5002/health"
    "http://localhost:5003/health"
  )

  for endpoint in "${endpoints[@]}"; do
    echo "Waiting for ${endpoint}..."
    for _ in $(seq 1 60); do
      if curl -fsS "$endpoint" >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done

    curl -fsS "$endpoint" >/dev/null
  done
}

trap cleanup EXIT

cleanup
./scripts/up.sh
wait_for_ready

# bootstrap users + fund
export NODES="http://localhost:5001,http://localhost:5002,http://localhost:5003"
python scripts/bootstrap_users.py
python scripts/bootstrap_faucet.py

# run tests
python tests/test_all.py

echo "Successfully completed."
