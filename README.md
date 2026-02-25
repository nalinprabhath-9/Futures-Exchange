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
