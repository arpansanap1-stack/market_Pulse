"""FastAPI application providing REST endpoints and streaming WebSocket gateway."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from marketpulse.api.broadcaster import Broadcaster
from marketpulse.core.anomaly import StreamingAnomalyDetector
from marketpulse.core.events import (
    BookDelta,
    MarketEvent,
    Side,
    TradeExecuted,
    ticks_to_price,
)
from marketpulse.core.indicators import (
    batch_bollinger_bands,
    batch_ema,
    batch_macd,
    batch_rsi,
    batch_sma,
    batch_vwap,
)
from marketpulse.core.ohlc import OHLCAggregator
from marketpulse.core.scenarios import (
    create_earnings_shock,
    create_halt_event,
    create_resume_event,
    create_volatility_regime,
    get_available_scenarios,
)
from marketpulse.sim.agent_source import AgentOrderSource

logger = logging.getLogger(__name__)


class SessionConfigRequest(BaseModel):
    """Request payload to configure or restart a simulation session."""

    seed: int = Field(default=42, ge=0)
    symbol: str = Field(default="AAPL")
    trades_per_sec: float = Field(default=50.0, gt=0, le=5000.0)
    initial_price: float = Field(default=150.0, gt=0)
    volatility: float = Field(default=0.20, gt=0)
    tick_size: float = Field(default=0.01, gt=0)


class ScenarioInjectRequest(BaseModel):
    """Request payload to inject an exogenous scenario shock into the market."""

    scenario_id: str
    symbol: str = Field(default="AAPL")
    params: dict[str, Any] = Field(default_factory=dict)


class SimulationRunner:
    """Manages the lifecycle and event production of the market simulator."""

    def __init__(self, broadcaster: Broadcaster, max_history: int = 1000) -> None:
        self.broadcaster = broadcaster
        self.max_history = max_history
        self.recent_trades: deque[dict[str, Any]] = deque(maxlen=max_history)
        self.recent_anomalies: deque[dict[str, Any]] = deque(maxlen=max_history)
        self.recent_market_events: deque[dict[str, Any]] = deque(maxlen=max_history)
        self.current_config = SessionConfigRequest()
        self.source: AgentOrderSource | None = None
        self.aggregator: OHLCAggregator = OHLCAggregator(symbol="AAPL")
        self.anomaly_detector: StreamingAnomalyDetector = StreamingAnomalyDetector(symbol="AAPL")
        self._sim_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._running: bool = False
        self._latest_price: float = 150.0

    def start(self, config: SessionConfigRequest) -> None:
        """Start or restart the simulation with new configuration."""
        self.stop()
        self.current_config = config
        self._latest_price = config.initial_price
        self.recent_trades.clear()
        self.recent_anomalies.clear()
        self.recent_market_events.clear()
        self.aggregator = OHLCAggregator(symbol=config.symbol)
        self.anomaly_detector = StreamingAnomalyDetector(symbol=config.symbol)
        self.source = AgentOrderSource(
            seed=config.seed,
            symbol=config.symbol,
            initial_price=config.initial_price,
            tick_size=config.tick_size,
        )
        self._running = True
        self._sim_task = asyncio.create_task(self._run_simulation())

    def stop(self) -> None:
        """Stop the simulation task and any pending background tasks."""
        self._running = False
        if self._sim_task is not None:
            self._sim_task.cancel()
            self._sim_task = None
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()

    def inject_scenario(
        self, scenario_id: str, custom_params: dict[str, Any] | None = None
    ) -> list[MarketEvent]:
        """Inject a scenario into the running simulation."""
        if self.source is None:
            raise RuntimeError("Simulation not running")

        params = custom_params or {}
        symbol = self.current_config.symbol
        clock_ns = self.source._clock.now_ns()
        events_to_inject: list[MarketEvent] = []

        if scenario_id in ("earnings_shock_positive", "earnings_shock_negative", "earnings_shock"):
            default_jump = (
                0.05
                if "positive" in scenario_id
                else (-0.05 if "negative" in scenario_id else 0.05)
            )
            jump_pct = float(params.get("jump_pct", params.get("price_jump_pct", default_jump)))
            vol_mult = float(
                params.get("volatility_mult", params.get("volatility_multiplier", 2.5))
            )
            evt = create_earnings_shock(
                symbol=symbol,
                jump_pct=jump_pct,
                seq=self.source.engine.allocate_seq(),
                ts_ns=clock_ns,
                volatility_mult=vol_mult,
            )
            events_to_inject.append(evt)
        elif scenario_id == "flash_crash":
            crash_pct = float(params.get("crash_pct", -0.10))
            halt_duration = float(params.get("halt_duration_s", 5.0))
            evt_shock = create_earnings_shock(
                symbol=symbol,
                jump_pct=crash_pct,
                seq=self.source.engine.allocate_seq(),
                ts_ns=clock_ns,
                volatility_mult=3.0,
            )
            evt_halt = create_halt_event(
                symbol=symbol,
                reason="CIRCUIT_BREAKER_LULD",
                seq=self.source.engine.allocate_seq(),
                ts_ns=clock_ns,
            )
            events_to_inject.extend([evt_shock, evt_halt])
            if halt_duration > 0:
                task = asyncio.create_task(self._auto_resume(halt_duration, symbol))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
        elif scenario_id in (
            "high_volatility_regime",
            "normal_volatility_regime",
            "volatility_regime",
        ):
            regime = str(params.get("regime", "HIGH" if "high" in scenario_id else "NORMAL"))
            mult = float(
                params.get(
                    "multiplier",
                    params.get("volatility_multiplier", 3.0 if regime == "HIGH" else 1.0),
                )
            )
            evt = create_volatility_regime(
                symbol=symbol,
                regime=regime,
                multiplier=mult,
                seq=self.source.engine.allocate_seq(),
                ts_ns=clock_ns,
            )
            events_to_inject.append(evt)
        elif scenario_id in ("halt_trading", "halt"):
            reason = str(params.get("reason", "MANUAL_HALT"))
            evt = create_halt_event(
                symbol=symbol,
                reason=reason,
                seq=self.source.engine.allocate_seq(),
                ts_ns=clock_ns,
            )
            events_to_inject.append(evt)
        elif scenario_id in ("resume_trading", "resume"):
            evt = create_resume_event(
                symbol=symbol,
                seq=self.source.engine.allocate_seq(),
                ts_ns=clock_ns,
            )
            events_to_inject.append(evt)
        else:
            raise ValueError(f"Unknown scenario ID: '{scenario_id}'")

        injected: list[MarketEvent] = []
        for e in events_to_inject:
            res = self.source.inject_market_event(e)
            for r in res:
                if isinstance(r, MarketEvent):
                    injected.append(r)
        return injected

    async def _auto_resume(self, delay_s: float, symbol: str) -> None:
        """Automatically resume trading after circuit breaker halt."""
        await asyncio.sleep(delay_s)
        if self._running and self.source is not None and self.source.engine.is_halted:
            evt = create_resume_event(
                symbol=symbol,
                seq=self.source.engine.allocate_seq(),
                ts_ns=self.source._clock.now_ns(),
            )
            self.source.inject_market_event(evt)

    async def _run_simulation(self) -> None:
        """Producer loop emitting simulated trades, deltas, anomalies, and OHLC updates."""
        assert self.source is not None
        interval_s = 1.0 / self.current_config.trades_per_sec

        try:
            while self._running:
                start_t = asyncio.get_event_loop().time()

                # Generate next event from agent matching pipeline
                event = self.source.next_event()
                if isinstance(event, TradeExecuted):
                    price = ticks_to_price(event.price_ticks, self.current_config.tick_size)
                    self._latest_price = price
                    trade_dict: dict[str, Any] = {
                        "seq": event.seq,
                        "ts_ns": event.ts_ns,
                        "symbol": event.symbol,
                        "trade_id": event.trade_id,
                        "price_ticks": event.price_ticks,
                        "price": price,
                        "qty": event.qty,
                        "aggressor_side": event.aggressor_side.value,
                    }
                    self.recent_trades.append(trade_dict)
                    self.broadcaster.push_trade(event.symbol, trade_dict)

                    # Streaming anomaly detection on trade
                    anomalies = self.anomaly_detector.on_trade(event)
                    for anom in anomalies:
                        anom_dict = anom.to_dict()
                        self.recent_anomalies.append(anom_dict)
                        self.broadcaster.push_anomaly(event.symbol, anom_dict)

                    # Update incremental OHLC aggregator across all intervals
                    bar_updates = self.aggregator.update_trade(event)
                    for interval, bars in bar_updates.items():
                        for bar in bars:
                            self.broadcaster.push_bar(
                                event.symbol,
                                interval,
                                bar.to_dict(self.current_config.tick_size),
                            )

                    # Book metric checks (spread blowout / imbalance)
                    best_bid = self.source.engine.book.best_bid()
                    best_ask = self.source.engine.book.best_ask()
                    bid_vol = self.source.engine.book.total_volume(Side.BUY)
                    ask_vol = self.source.engine.book.total_volume(Side.SELL)
                    book_anomalies = self.anomaly_detector.on_book_update(
                        symbol=event.symbol,
                        ts_ns=event.ts_ns,
                        best_bid_ticks=best_bid,
                        best_ask_ticks=best_ask,
                        total_bid_vol=bid_vol,
                        total_ask_vol=ask_vol,
                    )
                    for anom in book_anomalies:
                        anom_dict = anom.to_dict()
                        self.recent_anomalies.append(anom_dict)
                        self.broadcaster.push_anomaly(event.symbol, anom_dict)

                elif isinstance(event, BookDelta):
                    price = ticks_to_price(event.price_ticks, self.current_config.tick_size)
                    delta_dict: dict[str, Any] = {
                        "seq": event.seq,
                        "ts_ns": event.ts_ns,
                        "symbol": event.symbol,
                        "side": event.side.value,
                        "price_ticks": event.price_ticks,
                        "price": price,
                        "qty": event.new_total_qty,
                    }
                    self.broadcaster.push_book_delta(event.symbol, delta_dict)

                elif isinstance(event, MarketEvent):
                    event_dict: dict[str, Any] = {
                        "seq": event.seq,
                        "ts_ns": event.ts_ns,
                        "symbol": event.symbol,
                        "kind": event.kind,
                        "params": event.params,
                    }
                    self.recent_market_events.append(event_dict)
                    self.broadcaster.push_market_event(event.symbol, event_dict)

                elapsed = asyncio.get_event_loop().time() - start_t
                sleep_t = max(0.0, interval_s - elapsed)
                await asyncio.sleep(sleep_t)
        except asyncio.CancelledError:
            pass


def _clean_array(arr: np.ndarray) -> list[float | None]:
    """Convert numpy array with NaNs to JSON-compliant list of floats and Nones."""
    return [None if np.isnan(x) else round(float(x), 4) for x in arr]


def create_app(throttling_fps: int = 20) -> FastAPI:
    """Create and configure the MarketPulse FastAPI application."""
    broadcaster = Broadcaster(throttling_fps=throttling_fps)
    sim_runner = SimulationRunner(broadcaster=broadcaster)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        await broadcaster.start()
        # Start default simulation session
        sim_runner.start(SessionConfigRequest())
        yield
        sim_runner.stop()
        await broadcaster.stop()

    app = FastAPI(
        title="MarketPulse API",
        version="0.1.0",
        description="Educational real-time financial market simulation API",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/v1/symbols")
    async def get_symbols() -> list[dict[str, Any]]:
        """Return available simulated symbols and current market status."""
        cfg = sim_runner.current_config
        return [
            {
                "symbol": cfg.symbol,
                "name": f"{cfg.symbol} (Simulated Equity)",
                "tick_size": cfg.tick_size,
                "last_price": sim_runner._latest_price,
                "active": True,
            }
        ]

    @app.get("/api/v1/trades")
    async def get_recent_trades(limit: int = 50) -> list[dict[str, Any]]:
        """Return most recent historical trades."""
        trades = list(sim_runner.recent_trades)
        return trades[-limit:] if limit > 0 else trades

    @app.get("/api/v1/book")
    async def get_book(
        symbol: str = "AAPL",
        levels: int = 10,
    ) -> dict[str, Any]:
        """Return aggregated L2 order book depth snapshot."""
        if symbol != sim_runner.current_config.symbol:
            raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not active")
        if sim_runner.source is None:
            raise HTTPException(status_code=503, detail="Simulation not initialized")

        snapshot = sim_runner.source.book_snapshot(max_levels=levels)
        tick_size = sim_runner.current_config.tick_size

        bids = [
            {
                "price": ticks_to_price(b["price_ticks"], tick_size),
                "price_ticks": b["price_ticks"],
                "qty": b["qty"],
            }
            for b in snapshot["bids"]
        ]
        asks = [
            {
                "price": ticks_to_price(a["price_ticks"], tick_size),
                "price_ticks": a["price_ticks"],
                "qty": a["qty"],
            }
            for a in snapshot["asks"]
        ]

        best_bid = (
            ticks_to_price(snapshot["best_bid"], tick_size)
            if snapshot["best_bid"] is not None
            else None
        )
        best_ask = (
            ticks_to_price(snapshot["best_ask"], tick_size)
            if snapshot["best_ask"] is not None
            else None
        )
        spread_ticks = snapshot["spread"]
        spread = ticks_to_price(spread_ticks, tick_size) if spread_ticks is not None else None
        mid_ticks = snapshot["mid_price_ticks"]
        mid_price = round(mid_ticks * tick_size, 4) if mid_ticks is not None else None

        return {
            "symbol": symbol,
            "bids": bids,
            "asks": asks,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "spread_ticks": spread_ticks,
            "mid_price": mid_price,
            "is_halted": sim_runner.source.engine.is_halted if sim_runner.source else False,
        }

    @app.get("/api/v1/bars")
    async def get_bars(
        symbol: str = "AAPL",
        interval: str = "1s",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return historical and current bars for a symbol and interval."""
        if symbol != sim_runner.current_config.symbol:
            raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not active")

        try:
            closed_bars = sim_runner.aggregator.get_history(interval, limit=limit)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

        tick_size = sim_runner.current_config.tick_size
        results = [b.to_dict(tick_size) for b in closed_bars]

        current_bar = sim_runner.aggregator.get_current_bar(interval)
        if current_bar is not None:
            results.append(current_bar.to_dict(tick_size))

        return results[-limit:] if limit > 0 else results

    @app.get("/api/v1/indicators")
    async def get_indicators(
        symbol: str = "AAPL",
        interval: str = "1s",
        limit: int = 200,
    ) -> dict[str, Any]:
        """Calculate batch technical indicators for historical bars."""
        bars_data = await get_bars(symbol=symbol, interval=interval, limit=limit)
        if not bars_data:
            return {
                "symbol": symbol,
                "interval": interval,
                "times": [],
                "indicators": {
                    "sma20": [],
                    "ema20": [],
                    "rsi14": [],
                    "macd": {"macd": [], "signal": [], "histogram": []},
                    "bollinger": {"upper": [], "middle": [], "lower": []},
                    "vwap": [],
                },
            }

        times = [b["time"] for b in bars_data]
        closes = np.array([b["close"] for b in bars_data], dtype=np.float64)
        volumes = np.array([b["volume"] for b in bars_data], dtype=np.float64)

        # Batch calculations
        sma20 = batch_sma(closes, period=min(20, max(1, len(closes))))
        ema20 = batch_ema(closes, period=min(20, max(1, len(closes))))
        rsi14 = batch_rsi(closes, period=min(14, max(1, len(closes) - 1)))
        macd_line, sig_line, hist = batch_macd(closes, fast=12, slow=26, signal=9)
        upper, middle, lower, _ = batch_bollinger_bands(
            closes, period=min(20, max(2, len(closes))), num_std=2.0
        )
        vwap = batch_vwap(closes, volumes)

        return {
            "symbol": symbol,
            "interval": interval,
            "times": times,
            "indicators": {
                "sma20": _clean_array(sma20),
                "ema20": _clean_array(ema20),
                "rsi14": _clean_array(rsi14),
                "macd": {
                    "macd": _clean_array(macd_line),
                    "signal": _clean_array(sig_line),
                    "histogram": _clean_array(hist),
                },
                "bollinger": {
                    "upper": _clean_array(upper),
                    "middle": _clean_array(middle),
                    "lower": _clean_array(lower),
                },
                "vwap": _clean_array(vwap),
            },
        }

    @app.post("/api/v1/sessions")
    async def configure_session(req: SessionConfigRequest) -> dict[str, Any]:
        """Configure or restart simulation session."""
        sim_runner.start(req)
        return {"status": "started", "config": req.model_dump()}

    @app.get("/api/v1/scenarios")
    async def list_scenarios() -> list[dict[str, Any]]:
        """Return catalog of educational market stress-test scenarios."""
        return get_available_scenarios()

    @app.post("/api/v1/scenarios/inject")
    async def inject_scenario(req: ScenarioInjectRequest) -> dict[str, Any]:
        """Inject an exogenous scenario shock into the active simulation."""
        try:
            events = sim_runner.inject_scenario(req.scenario_id, req.params)
            return {
                "status": "injected",
                "scenario_id": req.scenario_id,
                "events_count": len(events),
                "is_halted": sim_runner.source.engine.is_halted if sim_runner.source else False,
            }
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.get("/api/v1/anomalies")
    async def get_anomalies(limit: int = 50) -> list[dict[str, Any]]:
        """Return recent detected streaming anomalies."""
        anomalies = list(sim_runner.recent_anomalies)
        return anomalies[-limit:] if limit > 0 else anomalies

    @app.get("/api/v1/market-status")
    async def get_market_status(symbol: str = "AAPL") -> dict[str, Any]:
        """Return market state including circuit breaker halt status."""
        is_halted = sim_runner.source.engine.is_halted if sim_runner.source else False
        return {
            "symbol": symbol,
            "is_halted": is_halted,
            "status": "HALTED" if is_halted else "ACTIVE",
            "latest_price": sim_runner._latest_price,
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """Multiplexed streaming WebSocket endpoint."""
        await websocket.accept()
        client_id = str(uuid.uuid4())
        client_queue = broadcaster.register_client(client_id)

        async def send_worker() -> None:
            """Pulls messages from client queue and sends down WebSocket."""
            try:
                while True:
                    msg = await client_queue.get()
                    await websocket.send_text(msg)
                    client_queue.task_done()
            except (asyncio.CancelledError, WebSocketDisconnect):
                pass

        sender_task = asyncio.create_task(send_worker())

        try:
            while True:
                text = await websocket.receive_text()
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue

                msg_type = payload.get("type")
                channel = payload.get("channel", "")

                if msg_type == "SUBSCRIBE" and channel:
                    broadcaster.subscribe(client_id, channel)
                    await websocket.send_text(
                        json.dumps(
                            {
                                "version": 1,
                                "type": "ACK",
                                "channel": channel,
                                "data": {"status": "subscribed"},
                            }
                        )
                    )
                elif msg_type == "UNSUBSCRIBE" and channel:
                    broadcaster.unsubscribe(client_id, channel)
                    await websocket.send_text(
                        json.dumps(
                            {
                                "version": 1,
                                "type": "ACK",
                                "channel": channel,
                                "data": {"status": "unsubscribed"},
                            }
                        )
                    )
                elif msg_type == "PING":
                    await websocket.send_text(
                        json.dumps(
                            {
                                "version": 1,
                                "type": "PONG",
                                "ts": int(asyncio.get_event_loop().time() * 1000),
                            }
                        )
                    )
        except WebSocketDisconnect:
            pass
        finally:
            sender_task.cancel()
            broadcaster.unregister_client(client_id)

    return app


app = create_app()
