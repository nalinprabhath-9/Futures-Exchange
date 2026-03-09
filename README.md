# Futures-Exchange

Execution Steps:

## Step 1: Run Full Automated Setup

This will:
- Reset databases
- Seed users + generate keystore
- Start 3 blockchain nodes
- Import users
- Deposit + lock collateral
- Create proposal
- Accept proposal
- Mine agreement into a block

```bash
chmod +x run_all.sh
./run_all.sh
```
after the above execution, you can Launch the Web UI:
In a new terminal : python ui_server.py --port 8000
and open http://127.0.0.1:8000 in browser



# 1. Start oracle
MOCK_MODE=true docker compose up oracle --build -d

# 2. Start nodes
./scripts/up.sh 3

# 3. Create users + fund
python scripts/bootstrap_users.py
python scripts/bootstrap_faucet.py

# 4. Verify oracle
curl -s localhost:8080/price/BTC | python3 -m json.tool

# 5. Run oracle integration
python test_oracle_integration.py

# 6. Run futures E2E
python tests/test_all.py
