# MARKETPULSE

> **EDUCATIONAL SIMULATION DISCLAIMER**
> MarketPulse is an educational, technical demonstration of a real-time financial market simulation, order matching engine, time-series analytics, and streaming trading terminal.
> **It does not predict markets, execute real trades, connect to brokerages, or provide financial advice.** All data and market behaviors are simulated.

---

## Overview

MarketPulse replicates the end-to-end architecture of a modern electronic trading system:
1. **Event Ingestion:** Deterministic order generation (market makers, noise traders, trend followers) feeding an append-only sequenced event log.
2. **Matching Engine:** High-performance, single-threaded pure Python order book implementing price-time priority (FIFO per price level), cancel in $\mathcal{O}(1)$, and strict integer ticks.
3. **Analytics Pipeline:** Incremental $\mathcal{O}(1)$ OHLC multi-timeframe aggregation and live streaming indicators (SMA, EMA, RSI, MACD, Bollinger Bands, VWAP).
4. **Edge Distribution:** Real-time WebSocket broadcasting with server-side batching, coalescing, and backpressure protection.
5. **Trading Terminal:** Dark-mode, responsive React/TypeScript terminal featuring TradingView Lightweight Charts, live L2 depth ladder, trade tape, and replay controls.

## Key Invariants

- **Pure Core:** Matching, aggregation, and indicators are pure Python with zero I/O or framework dependencies.
- **Strict Determinism:** Same seed + same config = byte-identical event log across runs.
- **Integer Ticks:** All internal prices use integer ticks (`price_ticks`), preventing floating-point rounding errors.
- **Clock Abstraction:** Monotonic integer nanosecond clock (`Clock`) enabling accelerated, step-by-step, or historical replay.

## Getting Started

### Prerequisites
- Python 3.12+
- Node.js 20+

### Installation

```bash
# Setup backend virtual environment
cd backend
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies in editable mode
pip install -e ".[dev]"

# Run tests
pytest
```

## Documentation

- [Architecture Guide](docs/ARCHITECTURE.md)
- [Architecture Decisions (ADRs)](docs/DECISIONS.md)
- [Event Schema Specification](docs/EVENT_SCHEMA.md)
- [Streaming Protocol Specification](docs/PROTOCOL.md)
