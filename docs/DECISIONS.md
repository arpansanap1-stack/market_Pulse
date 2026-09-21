# Architecture Decision Records (ADRs)

This document records the key architectural and design decisions made throughout the development of MarketPulse.

---

## ADR-001: Integer Ticks for Internal Price Representation

- **Context:** Financial trading engines must avoid IEEE 754 floating-point rounding errors (e.g., `0.1 + 0.2 != 0.3`), which can cause subtle bugs in price matching, order book ordering, and spread calculations.
- **Decision:** All prices inside the core domain (events, order book, matching engine, indicators) are stored and manipulated as integer ticks (`price_ticks: int`). Each symbol defines a `tick_size` (e.g., `0.01` for $100.00 = 10,000 ticks). Conversions to floating-point/decimal representations occur exclusively at the API and UI boundaries.
- **Alternatives Considered:**
  - Python `decimal.Decimal`: High memory footprint and ~20-50x slower in tight matching engine loops.
  - Python `float`: Prone to precision loss, comparison hazards (`<`, `==`), and non-deterministic behavior across platforms.

---

## ADR-002: Slotted Frozen Dataclasses for Core Events

- **Context:** In Phase 0, we must decide how to model core events. The matching engine processes thousands of events per second; events are immutable facts that must be serializable and memory-efficient.
- **Decision:** Use Python `@dataclass(slots=True, frozen=True)` for all core events in `marketpulse.core.events`. Provide explicit `to_dict()`, `from_dict()`, `to_json()`, and `from_json()` functions.
- **Alternatives Considered:**
  - `pydantic.BaseModel`: Excellent validation and serialization, but ~5-10x slower instantiation overhead in tight engine loops. We reserve Pydantic for the API boundary (FastAPI request/response validation).
  - Standard `NamedTuple`: Slotted frozen dataclasses provide cleaner type-hinting, default values, and inheritance hierarchy support.

---

## ADR-003: Monotonic Integer Nanoseconds (`ts_ns`) for Simulation Clock

- **Context:** Market events require consistent timestamps across wall-clock mode, accelerated simulation (e.g. 10x, 100x), and offline replaying.
- **Decision:** Represent all event timestamps as non-negative 64-bit integer nanoseconds (`ts_ns: int`) via an explicit `Clock` abstraction (`SimulatedClock`, `WallClock`).
- **Alternatives Considered:**
  - Milliseconds (`ts_ms: int`): Micro-bursts and high-frequency order placement within the simulation can collide at the millisecond scale.
  - ISO-8601 strings: High parsing overhead and non-trivial comparison cost in sorting and aggregation.

---

## ADR-004: Pure Domain Core with Edge Adapters

- **Context:** Mixing framework logic (FastAPI, WebSockets, DB connections) with financial domain logic makes testing slow, impairs determinism, and complicates replaying.
- **Decision:** Keep `marketpulse.core` strictly pure Python with no external I/O, network, or framework imports. All I/O occurs in `marketpulse.api`, `marketpulse.sim`, or `marketpulse.storage` at the edges.
- **Alternatives Considered:**
  - Embedding async queue handles or database sessions inside order book/aggregator classes: Breaks pure unit testing, prevents offline replay, and couples domain logic to runtime infrastructure.

---

## ADR-005: Self-Trade Handling Policy

- **Context:** In continuous double-auction markets, an incoming order may cross a resting order belonging to the same participant or account (self-trade).
- **Decision:** For the initial simulation, self-trades are permitted by default when orders originate from anonymous or distinct simulated agents. When participant IDs are introduced in Phase 7, the matching engine defaults to **Cancel-Newest** (the incoming aggressor order is cancelled to protect resting liquidity).
- **Alternatives Considered:**
  - Cancel-Oldest: Cancels resting order and lets aggressor continue. More complex order book mutation.
  - Reject: Rejects the incoming order before any partial fills. Cancel-Newest provides equivalent safety with simpler execution semantics.

---

## ADR-006: Server-Side Batching and 20Hz WebSocket Coalescing

- **Context:** At 1,000+ trades/sec input, dispatching individual JSON messages per trade saturates network sockets and overwhelms browser JSON deserialization and DOM rendering.
- **Decision:** The API layer Broadcaster buffers incoming trades and emits batched payload updates at 20Hz (`throttling_fps = 20`, 50ms interval). Each batch contains an array of recent trades for the channel.
- **Alternatives Considered:**
  - Raw unthrottled streaming: Triggers browser tab lockups and extreme garbage collection pressure at >=1,000 trades/sec.
  - Client-side rate limiting only: Wastes bandwidth and keeps server busy generating thousands of WebSocket frames per second.

---

## ADR-007: Out-of-React-State Chart Streaming with Lightweight Charts

- **Context:** Storing streaming tick data directly in React state (`useState`) triggers component tree re-renders on every incoming batch, causing perceptible UI stutter.
- **Decision:** Drive TradingView Lightweight Charts directly via `series.update(...)` inside a `requestAnimationFrame` loop or event callback. React state is reserved strictly for UI metadata (connection badge, last price, capped trade tape).
- **Alternatives Considered:**
  - Full React state re-rendering: High frame drops and latency spikes during high-throughput bursts.

---

## ADR-008: Empty Interval Forward-Fill Policy for OHLC Aggregation

- **Context:** In financial markets with intermittent or illiquid trading, intervals (e.g. 1s, 5s) may elapse with zero executed trades. Downstream charting libraries and technical indicators require uninterrupted contiguous time series.
- **Decision:** When an incoming trade crosses over one or more unpopulated interval buckets, the aggregator emits synthetic closed bars for each intermediate interval with `open = high = low = close = previous_close`, `volume = 0`, and `trade_count = 0`.
- **Alternatives Considered:**
  - Omit empty bars: Creates non-uniform timestamps; breaks fixed-window rolling indicators like SMA and RSI.
  - Interpolate prices: Fictitious price points distort realized volatility and Bollinger Band width.

---

## ADR-009: Wilder Smoothing Seed and Indicator Warm-Up Policy

- **Context:** Technical indicators (EMA, RSI, MACD, Bollinger Bands) require a warm-up sequence before producing statistically sound values. Different market data systems use differing conventions for initial seed values (e.g., EMA seeded by SMA vs first value; RSI Wilder smoothing vs exponential).
- **Decision:**
  - EMA: The initial seed at step $N$ is the arithmetic mean (SMA) of the first $N$ prices; subsequent steps use $\alpha = 2 / (N + 1)$.
  - RSI: Uses Wilder's smoothing with period 14 (requires 15 price points; first 14 price differences to seed average gain/loss).
  - Warm-up values return `None` (streaming) and `np.nan` (batch) until the full lookback window is populated.
- **Alternatives Considered:**
  - Zero-filling during warm-up: Distorts moving averages and indicators toward zero.
  - Seeding EMA with first raw price ($P_0$): Produces high initial bias that lingers across dozens of steps.

---

## ADR-010: Price-Time Priority Matching with SortedDict

- **Context:** An electronic limit order book requires efficient price discovery (best bid / best ask), fast order insertion, FIFO order matching per price level, and O(1) order cancellation by order ID.
- **Decision:**
  - Model the order book using two `HalfBook` instances (Bids and Asks), backed by `sortedcontainers.SortedDict[int, PriceLevel]`.
  - Within each price level, orders are stored in a `collections.deque[RestingOrder]` to guarantee O(1) FIFO price-time priority.
  - An order index map `_orders_map: dict[str, RestingOrder]` provides O(1) order cancellation lookup.
  - All prices inside the matching engine remain strictly integer ticks (`price_ticks: int`).
  - Aggressive matching executes against resting passive orders, where the passive order dictates the execution price.
- **Alternatives Considered:**
  - Binary heaps (`heapq`): Heaps allow fast access to best price, but O(N) cancellation and deletion of price levels.
  - Balanced BST in C extensions: Introduces platform-specific compilation overhead; `SortedDict` achieves >5,000 orders/sec in pure Python.

---

## ADR-011: Agent-Driven Continuous Double-Auction Order Flow

- **Context:** In Phase 1, synthetic trades were generated directly via a Geometric Brownian Motion (GBM) stub. In Phase 3, we must simulate realistic market microstructure (bid-ask spread, order book depth, market impact) using autonomous agents feeding the matching engine.
- **Decision:**
  - Replace the GBM stub trade generator with an agent pool orchestrated by `AgentOrderSource`.
  - The pool consists of:
    1. **Market Makers:** Layered quotes on both sides of the mid-price across multiple price levels, actively maintaining two-sided liquidity and spread.
    2. **Noise Traders:** Stochastic arrivals submitting a mix of limit orders (liquidity providing) and market orders (liquidity taking).
    3. **Trend Followers:** Momentum-based agents evaluating recent price trajectories to create short-term directional trends.
  - Each agent receives an isolated, seeded `numpy.random.Generator` to maintain strict simulation determinism.
- **Alternatives Considered:**
  - Poisson point process order arrival only: Fails to produce realistic depth ladders or bid-ask spread dynamics without dedicated market making agents.

---

## ADR-012: Trading Halt & Regulatory Circuit Breaker Mechanics

- **Status:** Accepted
- **Context:**
  - Real-world exchanges (e.g. NYSE, Nasdaq, CME) feature Limit-Up/Limit-Down (LULD) mechanism and Market-Wide Circuit Breakers (MWCB) that pause continuous double-auction trading during severe price dislocation.
  - We needed a deterministic, low-overhead mechanism in the matching engine to simulate halts and orderly market resumptions without corrupting resting liquidity.
- **Decision:**
  - The `MatchingEngine` maintains an explicit `is_halted: bool` state flag.
  - When halted, resting limit orders remain safe and intact on the book (preserving priority).
  - Any new aggressive or passive orders submitted during a halt are immediately rejected with `OrderRejected(reason="MARKET_HALTED")`.
  - Canonical `MarketEvent` instances (`HALT` and `RESUME`) are emitted into the event stream, preserving sequence monotonicity and auditability across downstreams and UI terminals.
- **Alternatives Considered:**
  - Canceling all resting orders on halt: Unrealistic compared to real LULD pauses where orders remain queued or accumulate in a cross/auction book.
  - Blocking execution in `AgentOrderSource`: Degrades responsiveness and hangs consumers. Immediate rejection via `OrderRejected` preserves asynchronous throughput.

---

## ADR-013: Streaming Incremental Anomaly Detection & Cooldown Guard

- **Status:** Accepted
- **Context:**
  - Educational financial terminal users need real-time indicators when market microstructure anomalies occur (e.g. price shock cascades, volume surges, spread blowouts, liquidity skew).
  - Calculating anomalies over full history in real time would incur $O(N)$ overhead per tick and trigger alert floods during shock regimes.
- **Decision:**
  - Implemented `StreamingAnomalyDetector` in `marketpulse.core.anomaly` operating with $O(1)$ amortized incremental window evaluations.
  - Implemented 4 canonical detectors:
    1. `PRICE_SHOCK`: Relative price return exceeding dynamic statistical threshold ($\ge 3\sigma$).
    2. `VOLUME_SURGE`: Individual fill volume exceeding $3\times$ recent rolling trade volume mean.
    3. `SPREAD_BLOWOUT`: Current bid-ask spread exceeding $3\times$ median baseline spread.
    4. `BOOK_IMBALANCE`: Severe liquidity skew ($\ge 85\%$ volume clustered on one side).
  - Enforced a minimum cooldown interval (500ms) per anomaly category to avoid alert storms and saturate WebSocket channels during rapid market shocks.
- **Alternatives Considered:**
  - Heavy ML/Isolation Forest batch detection: Incurred external dependencies, non-deterministic inference latency, and excessive memory footprint incompatible with pure Python domain core.

---

## ADR-014: Append-Only SQLite Event Store & Deterministic Historical Replayer

- **Status:** Accepted
- **Context:**
  - Phase 5 requires persistence and historical session replaying.
  - MarketPulse needs an event log capable of storing thousands of events per second with ACID guarantees, zero premature infrastructure (Rule 4: no Redis, Postgres, or external servers), and fast range queries by sequence number and timestamp.
  - Replaying past sessions must reconstruct order book depth, OHLC candles, and indicators deterministically, while allowing sub-millisecond seeking and paced playback (`0.5x` to `10x` / `MAX`).
- **Decision:**
  - Implemented `SQLiteEventStore` in `marketpulse.storage.event_store` using standard library `sqlite3` in WAL mode (`PRAGMA journal_mode = WAL; PRAGMA synchronous = NORMAL;`).
  - Stored events in an append-only `events` table keyed by composite primary key `(session_id, seq)` with an index on `(session_id, ts_ns)`.
  - Implemented `ReplayEventSource` in `marketpulse.sim.replay_source` adhering to the `EventSource` protocol, with dynamic timestamp pacing (`calculate_delay_s`) scaled by `speed_multiplier` and fast-forward seek state reconstruction.
  - Provided REST endpoints (`/api/v1/sessions`, `/replay`, `/seek`, `/speed`, `/pause`, `/resume`, `/events`, `/active`) for session management and replay control.
- **Alternatives Considered:**
  - Flat JSONL files: Poor random seek performance ($O(N)$ scanning required for sequence seek) and lacks ACID concurrency during high-throughput live simulation writes.
  - PostgreSQL / TimescaleDB: Violates Working Rule 4 (premature infrastructure). SQLite stdlib provides identical query capabilities with zero setup.




