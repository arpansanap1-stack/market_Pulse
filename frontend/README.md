# MarketPulse Trading Terminal (Frontend)

An institutional-grade, dark-mode real-time trading terminal built with **React 19**, **TypeScript**, and **Tailwind CSS**, designed for sub-millisecond visual updates and streaming financial market telemetry.

---

## Key Features & UI Components

The terminal is structured into high-performance, modular trading widgets:

| Widget | File | Description |
|---|---|---|
| **Multi-Asset Watchlist Ribbon** | [`Watchlist.tsx`](src/components/Watchlist.tsx) | 1-click symbol switcher across concurrent simulated equities (`AAPL`, `MSFT`, `GOOGL`, `NVDA`) with 24h change indicators. |
| **Interactive Price Chart** | [`PriceChart.tsx`](src/components/PriceChart.tsx) | Canvas-rendered TradingView Lightweight Charts with multi-timeframe bars (1s to 1h), volume histogram, and toggleable streaming indicators (SMA 20, EMA 20, VWAP, Bollinger Bands). |
| **L2 Depth Ladder** | [`DepthLadder.tsx`](src/components/DepthLadder.tsx) | Real-time Level 2 order book visualizer displaying bid/ask depth bars, cumulative liquidity, mid-price, and spread. |
| **Real-Time Trade Tape** | [`TradeTape.tsx`](src/components/TradeTape.tsx) | Time & sales execution tape with side-based color coding (bid/ask aggressive sweeps) and quantity badges. |
| **Institutional Order Ticket** | [`OrderTicket.tsx`](src/components/OrderTicket.tsx) | Order entry supporting `LIMIT`, `MARKET`, `IOC`, `FOK`, `STOP_LOSS`, `TRAILING_STOP`, and atomic `OCO` brackets, with participant IDs and Self-Trade Prevention (STP) policies. |
| **Portfolio & Risk Panel** | [`PortfolioPanel.tsx`](src/components/PortfolioPanel.tsx) | Real-time cash accounting, unrealized/realized PnL, inventory positions, open order cancellation, and fill history. |
| **Scenario Control Panel** | [`ScenarioControls.tsx`](src/components/ScenarioControls.tsx) | Inject exogenous market events: liquidity shocks, volatility regime changes, earnings surprises, and exchange circuit breaker halts/resumptions. |
| **Historical Replay Scrubber** | [`ReplayControls.tsx`](src/components/ReplayControls.tsx) | Timeline scrubber for recorded simulation sessions with variable speed ($0.5\times$ to $10,000\times$), seek, and step-through capability. |
| **Anomaly Intelligence Feed** | [`AnomalyFeed.tsx`](src/components/AnomalyFeed.tsx) | Live detection feed alerting on abnormal spread widening, volume spikes, and volatility regime transitions. |

---

## Tech Stack

- **Framework:** React 19 + TypeScript (Strict Mode)
- **Styling:** Tailwind CSS 3.4 + PostCSS
- **Charting:** [TradingView Lightweight Charts v5](https://tradingview.github.io/lightweight-charts/)
- **Icons:** Lucide React
- **Streaming Client:** Custom typed WebSocket client ([`wsClient.ts`](src/services/wsClient.ts)) with exponential backoff and multiplexed channel dispatch
- **Linter & Bundler:** Vite 6 + Oxlint

---

## Getting Started

### Prerequisites
- Node.js 20+
- npm 10+

### Installation & Development

```bash
# Install dependencies
npm install

# Start Vite dev server with Hot Module Replacement (HMR)
npm run dev

# Run Oxlint static analysis
npm run lint

# Compile TypeScript and create production bundle
npm run build

# Preview production build locally
npm run preview
```

The application will launch at `http://localhost:5173`. By default, it communicates with the FastAPI simulation server at `http://localhost:8000` and `ws://localhost:8000/ws`.
