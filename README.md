# FutureCoin Futures Exchange

A peer-to-peer blockchain-based futures trading system for crypto assets, combining proof-of-work mining with bilateral futures contracts.

## Overview

FutureCoin is a custom blockchain implementation that enables users to:

1. **Mine FutureCoins** using proof-of-work consensus
2. **Trade futures contracts** using mined coins as collateral
3. **Execute deterministic settlements** based on oracle price feeds

The system supports bilateral, template-based futures trades without orderbooks or liquidity pools.

## Features

### Blockchain Core

- Proof-of-Work mining with adjustable difficulty
- Double SHA-256 hashing
- Merkle root calculation
- Block validation and chain integrity
- Transaction memory pool (mempool)
- UTXO-style outputs with script addresses

### Futures Trading

- Multiple transaction types (Propose, Accept, Deposit, Settle, Cancel)
- Collateral locking mechanism
- Balance tracking (total, locked, available)
- Trade state management
- Automatic settlement execution
- Template-based contract logic

### Supported Templates

1. **UP/DOWN** - Binary outcome: price goes up or down
2. **LONG/SHORT** - Proportional payout based on price movement
3. **RANGE** - Price stays within specified range (planned)
