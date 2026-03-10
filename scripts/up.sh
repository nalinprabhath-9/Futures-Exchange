#!/usr/bin/env bash
set -euo pipefail

mkdir -p volumes/node1 volumes/node2 volumes/node3

docker compose up -d --build
echo "Price oracle + nodes running. Example: http://localhost:5001/health"
