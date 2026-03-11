#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p volumes/node1 volumes/node2 volumes/node3

docker compose up -d --build
echo "Price oracle + nodes running. Example: http://localhost:5001/health"
