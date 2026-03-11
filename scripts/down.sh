#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CLEAN="${1:-}"

if [[ "$CLEAN" == "--clean" ]]; then
  docker compose down --remove-orphans --volumes
else
  docker compose down --remove-orphans
fi

if [[ "$CLEAN" == "--clean" ]]; then
  rm -rf volumes/node1 volumes/node2 volumes/node3
  rm -f users.json
fi
