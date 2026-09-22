# MarketPulse Backend

High-performance, deterministic financial market simulation engine, order matching core, time-series analytics, and streaming edge distribution gateway.

---

## Subsystem Architecture

The backend adheres to a strict layered architectural pattern:

```
backend/src/marketpulse/
├── core/                # Pure Python domain logic (ZERO I/O, ZERO framework dependencies)
│   ├── clock.py         # Nanosecond monotonic integer clock abstraction (Simulated & System)
│   ├── events.py        # Strictly typed frozen event dataclasses with integer ticks
│   ├── orderbook.py     # Price-time priority FIFO matching engine, O(1) cancel, STP policies
│   ├── advanced_orders.py# Synthetic order triggers (Stop-Loss, Trailing Stops, atomic OCO)
│   ├── portfolio.py     # Order Management System (OMS) & Paper Portfolio (PMS) accounting
│   ├── ohlc.py          # O(1) incremental multi-timeframe OHLC aggregator with forward-filling
│   ├── indicators.py    # O(1) incremental streaming technical indicators (SMA, EMA, RSI, MACD, BB, VWAP)
│   ├── anomaly.py       # Online market anomaly detection (spread spikes, volume surges)
│   └── scenarios.py     # Deterministic exogenous shocks (liquidity drains, halts, earnings jumps)
├── sim/                 # Generative market agent simulation & scheduling
│   ├── agents.py        # MarketMaker, MomentumAgent, NoiseTrader behavioral agents
│   ├── agent_source.py  # Discrete event generator feeding single-book matching engine
│   ├── multiplex_source.py # Min-heap priority-queue multiplexer for concurrent multi-asset simulation
│   └── replay_source.py # Time-travel playback engine from recorded session event logs
├── storage/             # Session persistence & historical audit trail
│   └── event_store.py   # High-throughput SQLite event store with WAL mode and streaming iterators
├── api/                 # Edge gateway & distribution layer
│   ├── broadcaster.py   # High-throughput WebSocket broadcaster with 20Hz batching and client backpressure protection
│   └── server.py        # FastAPI application, REST endpoints, and WebSocket connection handlers
└── config.py            # Pydantic configuration schemas for simulation runs
```

---

## Core Invariants

1. **Pure Core:** The `core/` package contains pure mathematical and data structure domain logic. It has zero external I/O, database, network, or asynchronous dependencies.
2. **Strict Determinism:** Identical `(seed, configuration)` pairs guarantee 100% byte-identical event logs and execution sequences across runs and platforms.
3. **Integer Ticks:** All prices are tracked internally as integer tick increments (`price_ticks = round(price / tick_size)`), eliminating floating-point rounding divergence.
4. **Self-Trade Prevention (STP):** Configurable participant-level protection (`CANCEL_NEWEST`, `CANCEL_OLDEST`, `DECREMENT_AND_CANCEL`) to eliminate wash-trading.
5. **Backpressure Resilient:** The WebSocket broadcaster coalesces high-frequency Level 2 updates at 20Hz and drops lagged frames for congested slow clients, sustaining 1,000+ trades/sec without memory bloating.

---

## Development & Testing

### Environment Setup

```bash
# Create and activate Python 3.12 virtual environment
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# Install in editable mode with development dependencies
pip install -e ".[dev]"
```

### Verification Commands

```bash
# 1. Run full test suite (139 unit and integration tests)
pytest

# 2. Run tests with coverage reporting
pytest --cov=marketpulse.core --cov=marketpulse.sim --cov-report=term-missing

# 3. Static type-checking (Strict mode)
mypy --strict src/marketpulse tests

# 4. Code quality & linting
ruff check src/marketpulse tests

# 5. Code formatting check
ruff format --check src/marketpulse tests
```

### Launching the Simulation Server

```bash
python -m uvicorn marketpulse.api.server:create_app --factory --host 127.0.0.1 --port 8000 --reload
```
Interactive OpenAPI documentation will be accessible at `http://127.0.0.1:8000/docs`.
