# MARKETPULSE

> **EDUCATIONAL SIMULATION DISCLAIMER**
> MarketPulse is an educational, technical demonstration of a real-time financial market simulation, order matching engine, time-series analytics, and streaming trading terminal.
> **It does not predict markets, execute real trades, connect to brokerages, or provide financial advice.** All data and market behaviors are simulated.

---

## Overview

MarketPulse replicates the end-to-end architecture of a modern electronic trading system:
1. **Concurrent Multi-Asset Simulation:** Deterministic order generation across multiple simulated equities (`AAPL`, `MSFT`, `GOOGL`, `NVDA`) interleaved via min-heap priority-queue event multiplexing.
2. **Matching Engine:** High-performance, single-threaded pure Python order book implementing price-time priority (FIFO per price level), cancel in $\mathcal{O}(1)$, strict integer ticks, and Self-Trade Prevention (STP).
3. **Analytics Pipeline:** Incremental $\mathcal{O}(1)$ OHLC multi-timeframe aggregation and live streaming indicators (SMA, EMA, RSI, MACD, Bollinger Bands, VWAP).
4. **Order Management System (OMS) & Paper Portfolio (PMS):** User order entry (`LIMIT`, `MARKET`, `IOC`, `FOK`), synthetic risk triggers (`STOP_LOSS`, `STOP_LIMIT`, `TAKE_PROFIT`, `TRAILING_STOP`), atomic `One-Cancels-the-Other` (OCO) brackets, and real-time cash/inventory/equity accounting.
5. **Circuit Breakers & Exogenous Scenarios:** Realistic volatility halts, resumption auctions, liquidity shocks, and earnings jump scenarios.
6. **Session Persistence & Historical Replay:** Append-only SQLite event log with full variable-speed playback scrubber ($0.5\times$ to $10,000\times$), pause, and seek.
7. **Edge Distribution:** Real-time WebSocket broadcasting with server-side batching, coalescing, and backpressure protection (1,000+ trades/sec capability).
8. **Institutional Trading Terminal:** Dark-mode, responsive React/TypeScript terminal featuring TradingView Lightweight Charts, live L2 depth ladder, trade tape, multi-asset watchlist ribbon, order ticket, and portfolio analytics.

## Key Invariants

- **Pure Core:** Matching, aggregation, and indicators are pure Python with zero I/O or framework dependencies.
- **Strict Determinism:** Same seed + same config = byte-identical event log across runs.
- **Integer Ticks:** All internal prices use integer ticks (`price_ticks`), preventing floating-point rounding errors.
- **Clock Abstraction:** Monotonic integer nanosecond clock (`Clock`) enabling accelerated, step-by-step, or historical replay.

## Architecture & Subsystems

```
┌─────────────────────────────────────────────────────────────┐
│                 Concurrent Multi-Asset Sources              │
│       [AAPL Source]   [MSFT Source]   [GOOGL Source]        │
│                              │                              │
│                              ▼                              │
│              [Multiplexed Priority Queue Min-Heap]          │
└──────────────────────────────┬──────────────────────────────┘
                               │ Monotonic Event Stream
                               ▼
┌─────────────────────────────────────────────────────────────┐
│               Order Management System (OMS/PMS)             │
│  - User Order Validation (Cash / Position Bounds)           │
│  - Synthetic Trigger Book (Stop-Loss, Trailing Stops, OCO)  │
│  - Self-Trade Prevention (STP Cancel-Newest/Oldest)         │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│         Matching Engines (Pure Core, Integer Ticks)         │
│  - Price-time priority FIFO per price level                 │
│  - O(1) order cancellation & multi-level sweeps             │
│  - Emits: TradeExecuted, BookDelta, OrderAccepted/Rejected  │
└──────────────┬──────────────────────────────┬───────────────┘
               │ BookDelta                    │ TradeExecuted
               ▼                              ▼
┌─────────────────────────────┐┌──────────────────────────────┐
│     L2 Order Book State     ││   Incremental OHLC Engine    │
│  - Depth ladder snapshots   ││  - O(1) bar updates per trade │
│  - Coalesced delta streams  ││  - Multi-interval (1s -> 1h) │
└──────────────┬──────────────┘└──────────────┬───────────────┘
               │                              │ BarClosed
               │                              ▼
               │               ┌──────────────────────────────┐
               │               │     Streaming Indicators     │
               │               │  - O(1) per bar (RSI, MACD,  │
               │               │    Bollinger Bands, VWAP)    │
               │               └──────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│             WebSocket Broadcaster & Edge Gateway            │
│  - Client channels: trades, book, bars, anomalies, portfolio│
│  - 20Hz coalescing & backpressure throttling (1,000+ TPS)   │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 React Trading Terminal UI                   │
│  - Multi-Asset Watchlist Ribbon (1-Click Symbol Switcher)   │
│  - TradingView Lightweight Charts (Candlesticks & Volume)   │
│  - Interactive L2 Depth Ladder & Real-Time Trade Tape       │
│  - Order Ticket with STP & Synthetic Trailing Stops / OCO   │
│  - Replay Scrubber & Exogenous Scenario Control Panel       │
└─────────────────────────────────────────────────────────────┘
```

## Getting Started

### Prerequisites
- Python 3.12+
- Node.js 20+

### 1. Backend Setup

```bash
cd backend
python -m venv .venv

# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies in editable mode
pip install -e ".[dev]"

# Run full test suite (139 unit & integration tests)
pytest

# Start FastAPI simulation server
python -m uvicorn marketpulse.api.server:app --port 8000 --reload
```

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:5173` to open the terminal.

## Documentation

- [Architecture Guide](docs/ARCHITECTURE.md)
- [Architecture Decisions (ADRs)](docs/DECISIONS.md)
- [Event Schema Specification](docs/EVENT_SCHEMA.md)
- [Streaming Protocol Specification](docs/PROTOCOL.md)
