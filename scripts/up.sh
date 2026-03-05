#!/usr/bin/env bash
set -euo pipefail
N="${1:-3}"

mkdir -p volumes
for i in $(seq 1 "$N"); do
  mkdir -p "volumes/node${i}"
done

./scripts/gen_compose.sh "$N"
docker compose -f docker-compose.generated.yml up -d --build
echo "Nodes up. Example: http://localhost:5001/health"