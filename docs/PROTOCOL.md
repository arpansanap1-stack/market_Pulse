# MarketPulse Streaming & API Protocol Specification

Version: `1.0.0`

This specification defines the communication protocol between the MarketPulse backend edge services (FastAPI + WebSockets) and client applications (React UI, external consumers).

---

## 1. WebSocket Protocol

A client establishes a single, multiplexed WebSocket connection to the streaming gateway endpoint:
`ws://<host>:<port>/ws`

### 1.1 Envelope Structure

All messages sent across the WebSocket connection adhere to the standard JSON envelope:

```json
{
  "version": 1,
  "type": "SUBSCRIBE | UNSUBSCRIBE | DATA | SNAPSHOT | DELTA | ERROR | PING | PONG",
  "channel": "trades:AAPL | book:AAPL | bars:AAPL:1s | stats:AAPL | anomalies",
  "seq": 1042,
  "ts": 1726912345000,
  "data": { ... }
}
```

- `version`: Protocol schema version (integer `1`).
- `type`: Message framing type.
- `channel`: Target or originating channel.
- `seq`: Channel-specific sequence counter for gap detection.
- `ts`: Message generation timestamp (epoch milliseconds).
- `data`: Typed payload.

---

### 1.2 Channel Subscriptions

Clients subscribe and unsubscribe by sending control messages:

#### Subscribe
```json
{
  "version": 1,
  "type": "SUBSCRIBE",
  "channel": "book:AAPL"
}
```

#### Unsubscribe
```json
{
  "version": 1,
  "type": "UNSUBSCRIBE",
  "channel": "book:AAPL"
}
```

#### Available Channels
- `trades:{sym}`: Real-time executed trades.
- `book:{sym}`: Level-2 order book depth (snapshot + deltas).
- `bars:{sym}:{interval}`: OHLC candlesticks (`interval` in `1s`, `5s`, `15s`, `1m`, `5m`, `15m`, `1h`).
- `stats:{sym}`: Rolling 24h/session statistics (high, low, vwap, volume, volatility).
- `anomalies`: Global or per-symbol detected market anomalies.

---

### 1.3 Order Book Gap Detection & Resynchronization

1. **Initial Subscription:** Upon subscribing to `book:{sym}`, the server immediately transmits a `SNAPSHOT` message containing the current top-$N$ bid/ask price levels with an initial `seq`.
2. **Delta Dissemination:** Subsequent depth updates arrive as `DELTA` messages with monotonic `seq`.
3. **Gap Detection:** The client verifies that each incoming message satisfies `seq == last_seq + 1`.
4. **Resynchronization:** If `seq > last_seq + 1`, the client detects a dropped frame, sends a `RESYNC` request, and awaits a fresh `SNAPSHOT`.

---

### 1.4 Throttling, Coalescing & Backpressure

1. **Rate Limiting:** The matching engine may process $>5,000$ events/sec. The server coalesces order book level updates and limits broadcast frequency to **10–20 updates/second** per channel.
2. **Backpressure Policy:** Each client connection maintains a bounded output buffer (e.g., 256 messages). If a client falls behind:
   - Coalescible updates (intermediate `book` deltas, `bar_update`) are dropped or collapsed into the latest state.
   - Critical discrete events (`trades`, `bar_closed`) are never silently dropped; if the buffer overflows, the connection is flagged for forced resynchronization.

---

### 1.5 Heartbeat & Reconnection

- **Ping / Pong:** Clients send a `PING` every 15 seconds; the server responds with `PONG`. If no response is received within 30 seconds, the client initiates reconnection.
- **Exponential Backoff:** Clients reconnect using exponential backoff with jitter (e.g. 500ms, 1s, 2s, 4s, capped at 30s).
- **Post-Reconnect Resubscription:** Upon reconnecting, the client re-subscribes to its active channels and awaits clean state snapshots.

---

## 2. REST API Specification

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/symbols` | List all available symbols, tick sizes, and trading status. |
| `GET` | `/api/v1/bars` | Historical OHLC bars: `?symbol=AAPL&interval=1s&from=...&to=...` |
| `GET` | `/api/v1/trades` | Recent historical trades for a symbol. |
| `GET` | `/api/v1/indicators` | Batch indicators calculation for a symbol and interval. |
| `GET` | `/api/v1/sessions` | List recorded simulation sessions. |
| `POST` | `/api/v1/sessions` | Start a new simulation session (`seed`, `config`). |
| `POST` | `/api/v1/sessions/{id}/stop` | Terminate an active session. |
| `POST` | `/api/v1/sessions/{id}/replay` | Start replaying a session (`speed_multiplier`, `seek_seq`). |
