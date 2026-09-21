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
