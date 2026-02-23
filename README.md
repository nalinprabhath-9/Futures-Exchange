# Futures-Exchange

Custom blockchain with native futures trading capability.

## Price Oracle

Standalone service that fetches, signs, and serves real-time crypto prices. Acts as the trust anchor for on-chain trade settlement — nodes verify price payloads using the oracle's secp256k1 public key.

**How it works:** Prices are fetched on demand (CoinGecko primary, CoinCap fallback) and cached for 30s. Every response is signed with ECDSA so nodes can trustlessly verify it during settlement.

### Run

```bash
docker compose up oracle --build
```

For mock mode (no internet, fake prices):

```bash
MOCK_MODE=true docker compose up oracle --build
```

### Endpoints

| Endpoint | Description |
|---|---|
| `GET /price/{symbol}` | Current signed price for any asset |
| `GET /price/{symbol}/at/{timestamp}` | Historical signed price closest to timestamp |
| `GET /health` | Liveness check + oracle public key |
| `GET /oracle/pubkey` | Oracle's compressed secp256k1 public key |
| `GET /docs` | Interactive Swagger UI |

### Example

```bash
curl -s localhost:8080/price/BTC | python3 -m json.tool
```

```json
{
    "symbol": "BTC",
    "price": 97234.5,
    "timestamp": 1708000000,
    "signature": "3045022100...",
    "oracle_pubkey": "02a3f7c1..."
}
```
