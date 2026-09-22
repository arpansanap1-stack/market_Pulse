# ⚡ MarketPulse

> **Institutional-Grade Real-Time Financial Market Simulation, Matching Engine, and Streaming Trading Terminal**

[![CI](https://img.shields.io/badge/CI-Passing-brightgreen.svg?logo=github-actions&logoColor=white)](.github/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.8-3178C6.svg?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg?logo=react&logoColor=black)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Ruff](https://img.shields.io/badge/Linter-Ruff-black.svg?logo=ruff&logoColor=white)](https://astral.sh/ruff)
[![Mypy](https://img.shields.io/badge/Type_Check-Mypy_Strict-blue.svg)](https://mypy-lang.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

> [!WARNING]
> **EDUCATIONAL SIMULATION DISCLAIMER**  
> MarketPulse is an educational, technical demonstration of an electronic exchange architecture, matching engine, real-time analytics pipeline, and institutional trading terminal.  
> **It does not trade real capital, connect to brokerages, predict asset prices, or provide financial advice.** All market participants, order flow, and prices are simulated.

---

## 🏛️ Executive Summary

MarketPulse models the complete software architecture of a modern electronic trading venue:

- **Pure Python Matching Engine:** Deterministic, single-threaded price-time priority (FIFO per price level) order book with $\mathcal{O}(1)$ order cancellation and multi-level sweeps.
- **Self-Trade Prevention (STP):** Wash-trading elimination supporting `CANCEL_NEWEST`, `CANCEL_OLDEST`, and `DECREMENT_AND_CANCEL` policies.
- **Concurrent Multi-Asset Multiplexer:** Priority-queue min-heap interleaved event scheduling across equities (`AAPL`, `MSFT`, `GOOGL`, `NVDA`).
- **OMS & Paper Portfolio:** Full double-entry style cash accounting, inventory tracking, mark-to-market unrealized/realized PnL, and synthetic triggers (`STOP_LOSS`, `TRAILING_STOP`, atomic `OCO` brackets).
- **Streaming Analytics:** Incremental $\mathcal{O}(1)$ multi-timeframe OHLC bars (1s to 1h) and technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands, VWAP).
- **Exogenous Scenarios & Circuit Breakers:** Deterministic volatility halts, resumption auctions, liquidity shocks, and earnings jump regimes.
- **Time-Travel Historical Replay:** Append-only SQLite event log with full variable-speed scrubber ($0.5\times$ to $10,000\times$), pause, and seek.
- **Edge Gateway:** WebSocket broadcasting with 20Hz Level 2 coalescing and backpressure shedding (sustaining 1,000+ trades/sec).
- **Institutional Web Terminal:** Dark-mode React 19 + TypeScript interface featuring TradingView Lightweight Charts, interactive L2 depth ladder, real-time trade tape, and risk controls.

---

## 📐 Architecture & Data Flow

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Concurrent Multi-Asset Generation                    │
│      [AAPL Source]      [MSFT Source]      [GOOGL Source]    [NVDA]    │
│           │                   │                   │            │       │
│           └───────────────────┼───────────────────┴────────────┘       │
│                               ▼                                        │
│                 [Min-Heap Priority Queue Multiplexer]                  │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ Monotonic Event Stream (ts_ns)
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Order Management System (OMS / PMS)                  │
│    • Pre-trade risk & margin validation                                │
│    • Synthetic Trigger Engine (Stop-Loss, Trailing Stops, OCO Brackets)│
│    • Participant ID attribution & Self-Trade Prevention (STP)          │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ OrderSubmitted
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  Matching Core (Pure Python, Integer Ticks)            │
│    • FIFO Price-Time Priority                                          │
│    • O(1) order cancellation via hash indexing                         │
│    • Zero floating-point arithmetic (strict integer ticks)             │
│    • Emits: OrderAccepted, OrderRejected, TradeExecuted, BookDelta     │
└───────────────┬────────────────────────────────────────┬───────────────┘
                │ BookDelta                              │ TradeExecuted
                ▼                                        ▼
┌───────────────────────────────┐        ┌───────────────────────────────┐
│      L2 Depth Tracker         │        │    Incremental OHLC Engine    │
│   • Bids / Asks aggregation   │        │   • O(1) bar updates per tick │
│   • Spread & Mid-price        │        │   • Multi-interval forward-fill│
└───────────────┬───────────────┘        └───────────────┬───────────────┘
                │                                        │ BarClosed
                │                                        ▼
                │                        ┌───────────────────────────────┐
                │                        │     Streaming Indicators      │
                │                        │   • O(1) incremental SMA,     │
                │                        │     EMA, RSI, MACD, BB, VWAP  │
                │                        └───────────────┬───────────────┘
                │                                        │
                ▼                                        ▼
┌────────────────────────────────────────────────────────────────────────┐
│               WebSocket Broadcaster & Edge Gateway (FastAPI)           │
│    • 20Hz coalescing for Level 2 depth ladders                         │
│    • Non-blocking ring buffers with backpressure drop-tail policy      │
│    • 1,000+ trades/second distribution capability                      │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ ws://localhost:8000/ws
                                ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   React 19 Institutional Terminal                      │
│    • 1-Click Multi-Asset Ribbon     • TradingView Lightweight Charts   │
│    • Interactive L2 Depth Ladder    • Live Time & Sales Trade Tape     │
│    • Advanced Order Entry Ticket    • Historical Scrubber & Scenarios  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🛡️ Core Invariants & Engineering Principles

| Invariant | Guarantee |
|---|---|
| **Pure Domain Core** | The `marketpulse.core` module contains zero network I/O, database access, or framework code. It can be tested in complete isolation. |
| **Strict Determinism** | Running the simulation with the same seed and configuration produces the exact same byte-for-byte event sequence across platforms. |
| **Integer Tick Arithmetic** | All prices are stored and calculated as integer multiples of the asset tick size: `price_ticks = round(price / tick_size)`. This prevents IEEE-754 precision drift. |
| **Monotonic Nanosecond Clock** | A clean `Clock` abstraction decouples virtual simulation time from wall-clock time, allowing instant replays, paused inspection, and hyper-accelerated backtests. |
| **Wash-Trade Elimination** | The engine checks participant IDs and prevents self-matching under three configurable regulatory policies. |

---

## 📂 Repository Structure

```
marketPulse/
├── .github/
│   └── workflows/
│       └── ci.yml                 # Dual-matrix CI: Python backend checks + Node frontend build
├── backend/
│   ├── src/marketpulse/
│   │   ├── core/                  # Pure domain logic (Matching, OMS, OHLC, Indicators, STP)
│   │   │   ├── advanced_orders.py # Synthetic orders: Stop-Loss, Trailing Stop, OCO
│   │   │   ├── anomaly.py         # Real-time anomaly detector (spread/volume spikes)
│   │   │   ├── clock.py           # Nanosecond monotonic Clock abstraction
│   │   │   ├── events.py          # Frozen dataclass event schema
│   │   │   ├── indicators.py      # O(1) streaming technical indicators
│   │   │   ├── ohlc.py            # Incremental multi-timeframe OHLC aggregator
│   │   │   ├── orderbook.py       # FIFO matching engine with STP & O(1) cancel
│   │   │   ├── portfolio.py       # Double-entry cash/inventory accounting & OMS
│   │   │   └── scenarios.py       # Exogenous shocks, halts, and auctions
│   │   ├── sim/                   # Generative agents, multiplexer, replay sources
│   │   ├── storage/               # SQLite WAL-mode event store & query engine
│   │   ├── api/                   # FastAPI REST router & WebSocket broadcaster
│   │   └── config.py              # Pydantic configuration model
│   ├── tests/
│   │   ├── unit/                  # 130+ unit & property-based (Hypothesis) tests
│   │   └── integration/           # API, WebSocket, and 1,000+ TPS throughput tests
│   ├── pyproject.toml             # Python build, dependencies, ruff, and mypy configs
│   └── README.md                  # Backend developer documentation
├── frontend/
│   ├── src/
│   │   ├── components/            # Modular trading widgets (Chart, Book, Tape, OMS, Replay)
│   │   ├── services/              # Resilient WebSocket client & message router
│   │   ├── types/                 # Shared TypeScript event and protocol interfaces
│   │   ├── utils/                 # Frontend technical indicators & calculations
│   │   ├── App.tsx                # Main trading terminal layout & state coordination
│   │   └── main.tsx               # React 19 entry point
│   ├── package.json               # Frontend dependencies & scripts
│   ├── vite.config.ts             # Vite configuration with HMR
│   └── README.md                  # Frontend terminal documentation
├── docs/
│   ├── ARCHITECTURE.md            # Comprehensive architectural design document
│   ├── DECISIONS.md               # Architectural Decision Records (ADRs)
│   ├── EVENT_SCHEMA.md            # Exact binary & JSON event payload specifications
│   └── PROTOCOL.md                # WebSocket wire protocol and channel multiplexing
├── LICENSE                        # Open-source MIT License
├── package.json                   # Cross-platform root runner scripts
└── README.md                      # Primary project documentation
```

---

## 🚀 Quickstart Guide

### Prerequisites
- **Python 3.12+**
- **Node.js 20+**
- **npm 10+**

---

### Option A: Monorepo Runner (Recommended)

From the project root:

```bash
# 1. Install root dependencies (concurrently)
npm install

# 2. Setup Python backend virtualenv
cd backend
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# Install backend dependencies
pip install -e ".[dev]"
cd ..

# 3. Install frontend dependencies
npm --prefix frontend install

# 4. Start both Backend and Frontend concurrently
npm run dev
```

The terminal interface will be live at `http://localhost:5173` with the backend API running at `http://localhost:8000`.

---

### Option B: Individual Service Launch

#### 1. Backend Service

```bash
cd backend
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1

pip install -e ".[dev]"

# Launch FastAPI simulation server
python -m uvicorn marketpulse.api.server:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

Interactive Swagger/OpenAPI docs: `http://127.0.0.1:8000/docs`.

#### 2. Frontend Terminal

```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:5173` in your browser.

---

## 🧪 Testing & Code Quality

MarketPulse maintains high test coverage with **139 automated tests**, including property-based invariance testing via [Hypothesis](https://hypothesis.readthedocs.io/), golden file comparisons against Pandas, and end-to-end throughput benchmarks.

```bash
# Run full backend test suite (139 tests)
pytest backend/tests

# Run tests with code coverage metrics
pytest backend/tests --cov=marketpulse.core --cov=marketpulse.sim --cov-report=term-missing

# Run strict type checking (0 errors across 48 source files)
mypy --strict backend/src/marketpulse backend/tests

# Run Ruff linter & format validation
ruff check backend/
ruff format --check backend/

# Run Frontend Oxlint & TypeScript build validation
npm --prefix frontend run lint
npm --prefix frontend run build
```

---

## 🌐 API & WebSocket Reference

### Key REST Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Health check & engine status |
| `GET` | `/api/v1/symbols` | List active simulation assets (`AAPL`, `MSFT`, `GOOGL`, `NVDA`) |
| `GET` | `/api/v1/market-status` | Current market state, prices, and circuit breaker status |
| `GET` | `/api/v1/depth` | Current Level 2 order book snapshot |
| `POST` | `/api/v1/orders` | Place paper trading order (`LIMIT`, `MARKET`, `IOC`, `FOK`, `STOP_LOSS`, `TRAILING_STOP`, `OCO`) |
| `DELETE` | `/api/v1/orders/{order_id}` | Cancel resting limit order |
| `GET` | `/api/v1/portfolio` | Retrieve paper balance, equity, and positions |
| `GET` | `/api/v1/scenarios` | List available exogenous shock scenarios |
| `POST` | `/api/v1/scenarios/inject` | Inject real-time scenario (e.g. `LIQUIDITY_DRAIN`, `FLASH_CRASH`, `HALT`) |
| `POST` | `/api/v1/session/start` | Start live generative simulation or historical replay session |
| `POST` | `/api/v1/session/replay` | Initiate time-travel replay of recorded session |

### WebSocket Streaming (`ws://localhost:8000/ws`)

Clients receive JSON messages framed with a `type` identifier:

| Message Type | Frequency | Payload Content |
|---|---|---|
| `trade` | Event-driven (per execution) | Execution price, quantity, taker side, aggressive participant |
| `depth_update` | Coalesced (up to 20Hz) | Aggregated Level 2 depth ladder (bids/asks), best bid/ask, spread |
| `bar` | Periodic (per interval closure) | OHLC bar (open, high, low, close, volume) for 1s, 5s, 1m, etc. |
| `portfolio_update` | State change | Cash balance, realized PnL, active position inventory |
| `anomaly` | Event-driven | Volatility regime shifts, abnormal spread expansion alerts |
| `market_halt` / `resume` | Event-driven | Exchange circuit breaker notifications |

---

## 📚 Technical Documentation

For in-depth architectural specifications and design decisions:
- [Architecture Guide](docs/ARCHITECTURE.md) — System layers, state machines, and mathematical models.
- [Architecture Decision Records (ADRs)](docs/DECISIONS.md) — Formal records of technical trade-offs.
- [Event Schema Specification](docs/EVENT_SCHEMA.md) — Exact definitions of internal and serialized event types.
- [Streaming Wire Protocol](docs/PROTOCOL.md) — WebSocket framing, channel multiplexing, and reconnection specs.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) — see the LICENSE file for details.
