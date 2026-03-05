#!/usr/bin/env bash
set -euo pipefail

N="${1:-3}"
OUT="docker-compose.generated.yml"

echo "version: '3.9'" > "$OUT"
echo "services:" >> "$OUT"

for i in $(seq 1 "$N"); do
  PORT=$((5000 + i))
  NAME="node${i}"
  VOL="./volumes/${NAME}:/data"

  # Build peers list excluding self
  PEERS=""
  for j in $(seq 1 "$N"); do
    if [[ "$j" != "$i" ]]; then
      PPORT=$((5000 + j))
      PEERS="${PEERS}http://node${j}:${PPORT},"
    fi
  done
  PEERS="${PEERS%,}"

  cat >> "$OUT" <<EOF
  ${NAME}:
    build:
      context: .
      dockerfile: docker/Dockerfile
    container_name: ${NAME}
    ports:
      - "${PORT}:${PORT}"
    environment:
      - NODE_ID=${NAME}
      - PORT=${PORT}
      - DB_PATH=/data/chain.db
      - PEERS=${PEERS}
      - MINER_ADDRESS=miner_${NAME}
      - PROPOSAL_TIMEOUT=3600
    volumes:
      - ${VOL}
EOF
done

echo "Generated ${OUT} with ${N} nodes"