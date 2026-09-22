# MarketPulse Architecture

MarketPulse is an educational, deterministic, real-time financial market simulation and analytics platform. It models the end-to-end data pipeline of an electronic trading terminal: order generation, double-auction matching, trade dissemination, incremental multi-timeframe OHLC aggregation, live technical indicators, and real-time streaming to a web-based terminal.

> **Disclaimer:** MarketPulse is strictly an educational simulation. It does not predict markets, execute real trades, connect to brokerages, or provide financial advice. All data and market behaviors are simulated.

---

## 1. System Pipeline

The entire system operates around a single, unified abstraction: **an append-only, sequenced event log**. Downstream consumers (aggregators, indicators, broadcasters, storage) consume sequenced events without knowledge of whether the trade was produced by a stub generator or the full agent-driven matching engine.

```
┌─────────────────────────────────────────────────────────────┐
│                 Event Sources (Phase 1-4)                   │
│  [Stub GBM / Random Walk]  ──►  [Agent Sim: MM, Noise, Trend]│
└─────────────────────────────┬───────────────────────────────┘
                              │ OrderSubmitted, OrderCanceled
                              ▼
┌─────────────────────────────────────────────────────────────┐
│         Matching Engine (Pure Core, Single-Threaded)        │
│  - Price-time priority (FIFO per price level)               │
│  - Integer ticks for all price levels and orders            │
│  - Outputs: OrderAccepted/Rejected, TradeExecuted, BookDelta│
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
│  - Client subscriptions: trades, book, bars, stats          │
│  - Server-side coalescing & backpressure throttling (10-20Hz)│
└─────────────────────────────┬───────────────────────────────┘
                              │ JSON over WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                React Terminal UI (Phase 1+)                 │
│  - TradingView Lightweight Charts (Candlesticks & Volume)   │
│  - L2 Depth Ladder, Trade Tape, Watchlist, Anomaly Feed     │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Core Architectural Principles

### 2.1 Pure Domain Core
All matching logic, order books, aggregators, clocks, and indicators reside in `marketpulse.core`. These modules are pure Python: zero dependencies on FastAPI, WebSockets, databases, or external I/O. They take inputs (events or ticks) and return deterministic state or output events. Adapters live strictly at the system boundaries.

### 2.2 Strict Determinism & Simulation Clock
- **No Global RNG:** Every stochastic process accepts an explicit `numpy.random.Generator` initialized with a known seed.
- **Clock Abstraction (`Clock`):** No component calls `time.time()` or `datetime.now()`. Time is dictated by a `Clock` protocol. During simulation or replay, a `SimulatedClock` advances monotonically in integer nanoseconds (`ts_ns`). Given the same seed and configuration, the output event log is byte-identical across runs.

### 2.3 Integer Ticks
Floating-point arithmetic introduces non-deterministic precision errors and rounding artifacts. Within the matching engine and core events, all prices are represented as **integer ticks**:
$$\text{price\_ticks} = \text{round}\left(\frac{\text{price}}{\text{tick\_size}}\right)$$
Conversions to human-readable decimals occur exclusively at API/UI boundaries.

### 2.4 Append-Only Event Log & State Derivation
State is never the source of truth; **the event log is the sole source of truth**. Order book depth, OHLC candles, and indicator values are derived projections from the event stream. Replaying an event log from sequence 0 recreates the exact state at any point in time.

---

## 3. Performance & Latency Targets

- **Matching Engine:** $\ge 5,000$ events/second per symbol in single-threaded pure Python.
- **Streaming Throttling:** Raw engine events are coalesced at the edge broadcaster to 10–20 updates/second per channel to preserve browser responsiveness.
- **Incremental Computations:** OHLC aggregation and streaming indicators execute in $\mathcal{O}(1)$ time per event/bar update.

---

## 4. Multi-Asset Simulation Engine (Phase 5)

MarketPulse concurrently simulates multiple equity order books (`AAPL`, `MSFT`, `GOOGL`, `NVDA`) using priority-queue event multiplexing:
- **`MultiplexedAgentSource`:** Spawns independent `AgentOrderSource` instances per symbol, each managing its own deterministic seed (`seed + i`), agent population, and `MatchingEngine`.
- **Chronological Min-Heap:** A min-heap priority queue (`heapq`) keyed by `(ts_ns, tie_breaker, event, iterator)` interleaves events chronologically across all symbols without thread race conditions.
- **State Partitioning:** The API server projects state into symbol-keyed maps (`aggregators[symbol]`, `anomaly_detectors[symbol]`, `depth_trackers[symbol]`, `advanced_orders[symbol]`, `_latest_prices[symbol]`).
- **Interactive Watchlist:** The terminal renders a real-time multi-asset ribbon with live price updates and 1-click active symbol switching.

---

## 5. Order Management System (OMS) & Paper Portfolio (PMS) (Phase 6 & 8A)

The OMS and PMS provide educational paper trading capabilities with institutional realism:
- **Account Ledger:** `PortfolioTracker` maintains cash balances, position inventory (long and short), realized/unrealized P&L, and equity in integer ticks.
- **Order Lifecycle:** Orders transition across `PENDING` $\to$ `OPEN` $\to$ `PARTIALLY_FILLED` $\to$ `FILLED` / `CANCELED` / `REJECTED`.
- **Synthetic Trigger Engine:** `AdvancedOrderManager` manages off-book risk orders (`STOP_LOSS`, `STOP_LIMIT`, `TAKE_PROFIT`, `TAKE_PROFIT_LIMIT`, `TRAILING_STOP`) and `One-Cancels-the-Other` (OCO) bracket groups. Triggers are evaluated in $\mathcal{O}(1)$ time on each trade execution, ratcheting trailing stops with peak/trough watermarks.
- **Atomic OCO Submission:** Multi-leg bracket submissions validate all legs atomically; validation failure on any leg rolls back the entire submission.

---

## 6. Self-Trade Prevention (STP) & Participant Attribution (Phase 7)

MarketPulse prevents wash-trading and artificial volume inflation:
- **Participant Attribution:** Every order and resting queue entry carries a `participant_id` (e.g., `mm_1`, `noise_2`, `user_trader`).
- **STP Policies:** The matching engine enforces configurable self-crossing rules:
  - `CANCEL_NEWEST`: Aggressor order is canceled with reason `STP_CANCEL_NEWEST`, preserving resting book depth.
  - `CANCEL_OLDEST`: Conflicting resting order is canceled; aggressor continues matching.
  - `DECREMENT_AND_CANCEL`: Overlapping quantity is decremented from both orders.
- **Microstructure Telemetry:** STP statistics (`cancel_newest`, `cancel_oldest`, `decrement_and_cancel`, `total_prevented`) stream live to `/api/v1/market-status`.

---

## 7. Event Sourcing, Session Persistence & Historical Replay (Phase 5)

All simulation sessions are persisted and replayable:
- **Append-Only Store:** `SQLiteEventStore` records sequenced events with WAL mode, chunked prefetching, and structured metadata.
- **Replay Engine:** `ReplayEventSource` replays historical sessions at variable speeds ($0.5\times$ to $10,000\times$, pause, seek) with pacing delay calculation.
- **Full-Duplex Replay Streaming:** WebSockets stream historical session replays with live order book reconstruction and candle aggregation identical to real-time mode.

