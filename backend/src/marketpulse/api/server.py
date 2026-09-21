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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from marketpulse.api.broadcaster import Broadcaster
from marketpulse.core.events import TradeExecuted, ticks_to_price
from marketpulse.sim.stub_gbm import StubGBMSource

logger = logging.getLogger(__name__)


class SessionConfigRequest(BaseModel):
    """Request payload to configure or restart a simulation session."""

    seed: int = Field(default=42, ge=0)
    symbol: str = Field(default="AAPL")
    trades_per_sec: float = Field(default=50.0, gt=0, le=5000.0)
    initial_price: float = Field(default=150.0, gt=0)
    volatility: float = Field(default=0.20, gt=0)
    tick_size: float = Field(default=0.01, gt=0)


class SimulationRunner:
    """Manages the lifecycle and event production of the market simulator."""

    def __init__(self, broadcaster: Broadcaster, max_history: int = 1000) -> None:
        self.broadcaster = broadcaster
        self.max_history = max_history
        self.recent_trades: deque[dict[str, Any]] = deque(maxlen=max_history)
        self.current_config = SessionConfigRequest()
        self.source: StubGBMSource | None = None
        self._sim_task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._latest_price: float = 150.0

    def start(self, config: SessionConfigRequest) -> None:
        """Start or restart the simulation with new configuration."""
        self.stop()
        self.current_config = config
        self._latest_price = config.initial_price
        self.source = StubGBMSource(
            seed=config.seed,
            symbol=config.symbol,
            initial_price=config.initial_price,
            annual_volatility=config.volatility,
            tick_size=config.tick_size,
        )
        self._running = True
        self._sim_task = asyncio.create_task(self._run_simulation())

    def stop(self) -> None:
        """Stop the simulation task."""
        self._running = False
        if self._sim_task is not None:
            self._sim_task.cancel()
            self._sim_task = None

    async def _run_simulation(self) -> None:
        """Producer loop emitting simulated trades at trades_per_sec rate."""
        assert self.source is not None
        interval_s = 1.0 / self.current_config.trades_per_sec

        try:
            while self._running:
                start_t = asyncio.get_event_loop().time()

                # Generate event from stub source
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

                elapsed = asyncio.get_event_loop().time() - start_t
                sleep_t = max(0.0, interval_s - elapsed)
                await asyncio.sleep(sleep_t)
        except asyncio.CancelledError:
            pass


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

    # Enable CORS for frontend dev server
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

    @app.post("/api/v1/sessions")
    async def configure_session(req: SessionConfigRequest) -> dict[str, Any]:
        """Configure or restart simulation session."""
        sim_runner.start(req)
        return {"status": "started", "config": req.model_dump()}

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
                    # Acknowledge subscription
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
