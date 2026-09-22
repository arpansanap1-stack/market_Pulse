"""FastAPI application providing REST endpoints and streaming WebSocket gateway."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from marketpulse.api.broadcaster import Broadcaster
from marketpulse.core.anomaly import StreamingAnomalyDetector
from marketpulse.core.events import (
    BookDelta,
    Event,
    MarketEvent,
    OrderAccepted,
    OrderCanceled,
    OrderRejected,
    OrderSubmitted,
    OrderType,
    SessionEnded,
    SessionStarted,
    Side,
    STPPolicy,
    TimeInForce,
    TradeExecuted,
    price_to_ticks,
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
from marketpulse.core.portfolio import (
    OrderStatus,
    PortfolioTracker,
)
from marketpulse.core.scenarios import (
    create_earnings_shock,
    create_halt_event,
    create_resume_event,
    create_volatility_regime,
    get_available_scenarios,
)
from marketpulse.sim.agent_source import AgentOrderSource
from marketpulse.sim.replay_source import ReplayEventSource
from marketpulse.storage.event_store import SessionMetadata, SQLiteEventStore

logger = logging.getLogger(__name__)


class RunnerMode(StrEnum):
    """Execution mode of the simulation engine."""

    LIVE = "LIVE"
    REPLAY = "REPLAY"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


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


class ReplayRequest(BaseModel):
    """Request payload to start replaying a recorded session."""

    speed_multiplier: float = Field(default=1.0, gt=0, le=10000.0)
    seek_seq: int = Field(default=1, ge=1)


class SeekRequest(BaseModel):
    """Request payload to seek an active replay to a target sequence."""

    target_seq: int = Field(ge=1)


class SpeedRequest(BaseModel):
    """Request payload to update replay playback speed."""

    speed_multiplier: float = Field(gt=0, le=10000.0)


class OrderSubmitRequest(BaseModel):
    """Request payload to submit a manual user order."""

    symbol: str = Field(default="AAPL")
    side: Side = Field(default=Side.BUY)
    order_type: OrderType = Field(default=OrderType.LIMIT)
    price: float | None = Field(default=None, gt=0)
    qty: int = Field(gt=0)
    tif: TimeInForce = Field(default=TimeInForce.GTC)
    participant_id: str = Field(default="user_trader")
    stp: STPPolicy = Field(default=STPPolicy.CANCEL_NEWEST)


class PortfolioResetRequest(BaseModel):
    """Request payload to reset portfolio balances."""

    initial_cash: float = Field(default=100000.0, gt=0)


class ReplayDepthTracker:
    """Maintains resting price level depth from BookDelta events for accurate replay snapshots."""

    def __init__(self) -> None:
        self.bids: dict[int, int] = {}
        self.asks: dict[int, int] = {}

    def clear(self) -> None:
        """Clear all resting depth levels."""
        self.bids.clear()
        self.asks.clear()

    def on_delta(self, side: Side, price_ticks: int, new_total_qty: int) -> None:
        """Apply a book delta update to resting level quantity."""
        target = self.bids if side == Side.BUY else self.asks
        if new_total_qty <= 0:
            target.pop(price_ticks, None)
        else:
            target[price_ticks] = new_total_qty

    def snapshot(self, max_levels: int = 10) -> dict[str, Any]:
        """Produce a sorted top-N depth ladder snapshot."""
        sorted_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:max_levels]
        sorted_asks = sorted(self.asks.items(), key=lambda x: x[0])[:max_levels]
        best_bid = sorted_bids[0][0] if sorted_bids else None
        best_ask = sorted_asks[0][0] if sorted_asks else None
        spread = (best_ask - best_bid) if (best_bid and best_ask) else None
        mid_ticks = ((best_bid + best_ask) / 2.0) if (best_bid and best_ask) else None
        return {
            "bids": [{"price_ticks": p, "qty": q} for p, q in sorted_bids],
            "asks": [{"price_ticks": p, "qty": q} for p, q in sorted_asks],
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "mid_price_ticks": mid_ticks,
        }


class SimulationRunner:
    """Manages the lifecycle, storage persistence, and historical replay of market sessions."""

    def __init__(
        self,
        broadcaster: Broadcaster,
        store: SQLiteEventStore,
        max_history: int = 1000,
    ) -> None:
        self.broadcaster = broadcaster
        self.store = store
        self.max_history = max_history
        self.mode: RunnerMode = RunnerMode.STOPPED
        self.active_session_id: str = ""
        self.active_session_metadata: SessionMetadata | None = None
        self.recent_trades: deque[dict[str, Any]] = deque(maxlen=max_history)
        self.recent_anomalies: deque[dict[str, Any]] = deque(maxlen=max_history)
        self.recent_market_events: deque[dict[str, Any]] = deque(maxlen=max_history)
        self.depth_tracker: ReplayDepthTracker = ReplayDepthTracker()
        self.current_config = SessionConfigRequest()
        self.source: AgentOrderSource | None = None
        self.replay_source: ReplayEventSource | None = None
        self.aggregator: OHLCAggregator = OHLCAggregator(symbol="AAPL")
        self.anomaly_detector: StreamingAnomalyDetector = StreamingAnomalyDetector(symbol="AAPL")
        self.portfolio: PortfolioTracker = PortfolioTracker()
        self._sim_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._running: bool = False
        self._replay_halted: bool = False
        self._latest_price: float = 150.0
        self._current_seq: int = 0
        self._total_events: int = 0

    def _reset_terminal_state(self) -> None:
        """Reset in-memory data structures prior to starting a new session or seeking."""
        self.recent_trades.clear()
        self.recent_anomalies.clear()
        self.recent_market_events.clear()
        self.depth_tracker.clear()
        self._replay_halted = False
        self.aggregator = OHLCAggregator(symbol=self.current_config.symbol)
        self.anomaly_detector = StreamingAnomalyDetector(symbol=self.current_config.symbol)
        self.portfolio.reset(initial_cash=100_000.0, tick_size=self.current_config.tick_size)
        self._latest_price = self.current_config.initial_price

    def start(self, config: SessionConfigRequest) -> str:
        """Start or restart a live simulation session with event log persistence."""
        self.stop()
        self.current_config = config
        self._reset_terminal_state()

        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        self.active_session_id = session_id

        self.source = AgentOrderSource(
            seed=config.seed,
            symbol=config.symbol,
            initial_price=config.initial_price,
            tick_size=config.tick_size,
        )
        self.portfolio.reset(initial_cash=100_000.0, tick_size=config.tick_size)

        start_ts_ns = self.source._clock.now_ns()
        self.active_session_metadata = self.store.create_session(
            session_id=session_id,
            symbol=config.symbol,
            seed=config.seed,
            config=config.model_dump(),
            start_ts_ns=start_ts_ns,
        )

        # Log canonical SessionStarted event
        evt_start = SessionStarted(
            seq=self.source.engine.allocate_seq(),
            ts_ns=start_ts_ns,
            symbol=config.symbol,
            session_id=session_id,
            seed=config.seed,
            config_hash="",
            symbols=(config.symbol,),
        )
        self.store.append_event(session_id, evt_start)
        self._current_seq = evt_start.seq
        self._total_events = evt_start.seq

        self.mode = RunnerMode.LIVE
        self._running = True
        self._sim_task = asyncio.create_task(self._run_simulation())
        return session_id

    def stop(self) -> None:
        """Stop the simulation or replay task and persist SessionEnded if live."""
        if self.mode == RunnerMode.LIVE and self.active_session_id:
            now_ns = self.source._clock.now_ns() if self.source else 0
            total_evts = self.store.count_events(self.active_session_id)
            seq = self.source.engine.allocate_seq() if self.source else total_evts + 1
            evt_end = SessionEnded(
                seq=seq,
                ts_ns=now_ns,
                symbol=self.current_config.symbol,
                session_id=self.active_session_id,
                reason="STOPPED_BY_USER",
                total_events=total_evts + 1,
            )
            self.store.append_event(self.active_session_id, evt_end)
            self.store.update_session(
                self.active_session_id,
                status="STOPPED",
                end_ts_ns=now_ns,
                total_events=total_evts + 1,
            )

        self._running = False
        if self._sim_task is not None:
            self._sim_task.cancel()
            self._sim_task = None
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()
        self.mode = RunnerMode.STOPPED

    def start_replay(
        self,
        session_id: str,
        speed_multiplier: float = 1.0,
        seek_seq: int = 1,
    ) -> None:
        """Start replaying a recorded simulation session."""
        meta = self.store.get_session(session_id)
        if meta is None:
            raise ValueError(f"Session '{session_id}' not found")

        self.stop()
        self.active_session_id = session_id
        self.active_session_metadata = meta

        tick_size = float(meta.config.get("tick_size", 0.01))
        initial_price = float(meta.config.get("initial_price", 150.0))
        self.current_config = SessionConfigRequest(
            symbol=meta.symbol,
            seed=meta.seed,
            tick_size=tick_size,
            initial_price=initial_price,
            trades_per_sec=float(meta.config.get("trades_per_sec", 50.0)),
            volatility=float(meta.config.get("volatility", 0.20)),
        )

        self._reset_terminal_state()
        self.replay_source = ReplayEventSource(
            event_store=self.store,
            session_id=session_id,
            speed_multiplier=speed_multiplier,
        )
        self._total_events = meta.total_events or self.store.count_events(session_id)

        if seek_seq > 1:
            self._fast_forward(seek_seq)
        else:
            self.replay_source.seek(1)
            self._current_seq = 1

        self.mode = RunnerMode.REPLAY
        self._running = True
        self._sim_task = asyncio.create_task(self._run_replay())

    def _fast_forward(self, target_seq: int) -> None:
        """Fast-forward internal projections (OHLC, L2 depth, anomalies) to target sequence."""
        self._reset_terminal_state()
        events = self.store.get_events(
            session_id=self.active_session_id,
            from_seq=1,
            to_seq=target_seq - 1,
        )
        for e in events:
            self._process_event(e, broadcast=False)

        assert self.replay_source is not None
        self.replay_source.seek(target_seq)
        self._current_seq = target_seq

    def seek_replay(self, target_seq: int) -> None:
        """Reposition replay progress to target sequence."""
        if self.replay_source is None:
            raise ValueError("No replay session initialized")

        was_paused = self.mode == RunnerMode.PAUSED
        self._fast_forward(target_seq)
        if was_paused:
            self.mode = RunnerMode.PAUSED
            self.replay_source.pause()
        else:
            self._running = True
            self.mode = RunnerMode.REPLAY
            self.replay_source.resume()
            if self._sim_task is None or self._sim_task.done():
                self._sim_task = asyncio.create_task(self._run_replay())

    def set_replay_speed(self, multiplier: float) -> None:
        """Adjust replay playback speed multiplier."""
        if self.replay_source is None:
            raise ValueError("No replay session initialized")
        self.replay_source.set_speed(multiplier)

    def pause(self) -> None:
        """Pause playback progression."""
        if self.replay_source is not None:
            self.mode = RunnerMode.PAUSED
            self.replay_source.pause()

    def resume(self) -> None:
        """Resume playback progression."""
        if self.replay_source is not None:
            self.mode = RunnerMode.REPLAY
            self.replay_source.resume()
            if self._sim_task is None or self._sim_task.done():
                self._running = True
                self._sim_task = asyncio.create_task(self._run_replay())

    def get_active_status(self) -> dict[str, Any]:
        """Return active runner status and replay progression."""
        if self.mode in (RunnerMode.REPLAY, RunnerMode.PAUSED) and self.replay_source is not None:
            current_seq = self.replay_source.current_seq
            total_events = self.replay_source.total_events
            speed = self.replay_source.speed_multiplier
            is_halted = self._replay_halted
        else:
            current_seq = self._current_seq
            total_events = self._total_events
            speed = 1.0
            is_halted = self.source.engine.is_halted if self.source else False

        return {
            "mode": self.mode.value,
            "session_id": self.active_session_id,
            "symbol": self.current_config.symbol,
            "current_seq": current_seq,
            "total_events": total_events,
            "speed_multiplier": speed,
            "is_paused": self.mode == RunnerMode.PAUSED,
            "latest_price": self._latest_price,
            "is_halted": is_halted,
        }

    def _process_event(self, event: Event, broadcast: bool = True) -> None:
        """Apply an event to terminal aggregators, book depth, anomalies, and broadcasters."""
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
                "buyer_participant_id": event.buyer_participant_id,
                "seller_participant_id": event.seller_participant_id,
            }
            self.recent_trades.append(trade_dict)
            if broadcast:
                self.broadcaster.push_trade(event.symbol, trade_dict)

            # Portfolio execution fill updates
            if event.buy_order_id in self.portfolio.orders:
                self.portfolio.on_trade_executed(event, event.buy_order_id, Side.BUY)
                if broadcast:
                    summary = self.portfolio.get_summary(
                        current_price_ticks=event.price_ticks,
                        tick_size=self.current_config.tick_size,
                        symbol=event.symbol,
                    )
                    self.broadcaster.push_portfolio(summary)
            if event.sell_order_id in self.portfolio.orders:
                self.portfolio.on_trade_executed(event, event.sell_order_id, Side.SELL)
                if broadcast:
                    summary = self.portfolio.get_summary(
                        current_price_ticks=event.price_ticks,
                        tick_size=self.current_config.tick_size,
                        symbol=event.symbol,
                    )
                    self.broadcaster.push_portfolio(summary)

            # Streaming anomaly detection
            anomalies = self.anomaly_detector.on_trade(event)
            for anom in anomalies:
                anom_dict = anom.to_dict()
                self.recent_anomalies.append(anom_dict)
                if broadcast:
                    self.broadcaster.push_anomaly(event.symbol, anom_dict)

            # Incremental OHLC update
            bar_updates = self.aggregator.update_trade(event)
            for interval, bars in bar_updates.items():
                for bar in bars:
                    if broadcast:
                        self.broadcaster.push_bar(
                            event.symbol,
                            interval,
                            bar.to_dict(self.current_config.tick_size),
                        )

            # Book-level anomaly checks
            depth = self.depth_tracker.snapshot()
            best_bid = depth["best_bid"]
            best_ask = depth["best_ask"]
            bid_vol = sum(self.depth_tracker.bids.values())
            ask_vol = sum(self.depth_tracker.asks.values())
            book_anoms = self.anomaly_detector.on_book_update(
                symbol=event.symbol,
                ts_ns=event.ts_ns,
                best_bid_ticks=best_bid,
                best_ask_ticks=best_ask,
                total_bid_vol=bid_vol,
                total_ask_vol=ask_vol,
            )
            for anom in book_anoms:
                anom_dict = anom.to_dict()
                self.recent_anomalies.append(anom_dict)
                if broadcast:
                    self.broadcaster.push_anomaly(event.symbol, anom_dict)

        elif isinstance(event, BookDelta):
            price = ticks_to_price(event.price_ticks, self.current_config.tick_size)
            self.depth_tracker.on_delta(event.side, event.price_ticks, event.new_total_qty)
            delta_dict: dict[str, Any] = {
                "seq": event.seq,
                "ts_ns": event.ts_ns,
                "symbol": event.symbol,
                "side": event.side.value,
                "price_ticks": event.price_ticks,
                "price": price,
                "qty": event.new_total_qty,
            }
            if broadcast:
                self.broadcaster.push_book_delta(event.symbol, delta_dict)

        elif isinstance(event, MarketEvent):
            if event.kind == "HALT":
                self._replay_halted = True
            elif event.kind == "RESUME":
                self._replay_halted = False

            event_dict: dict[str, Any] = {
                "seq": event.seq,
                "ts_ns": event.ts_ns,
                "symbol": event.symbol,
                "kind": event.kind,
                "params": event.params,
            }
            self.recent_market_events.append(event_dict)
            if broadcast:
                self.broadcaster.push_market_event(event.symbol, event_dict)

    def inject_scenario(
        self, scenario_id: str, custom_params: dict[str, Any] | None = None
    ) -> list[MarketEvent]:
        """Inject an exogenous scenario into the live simulation and persist."""
        if self.source is None or self.mode != RunnerMode.LIVE:
            raise RuntimeError("Live simulation not running")

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
                    self.store.append_event(self.active_session_id, r)
        return injected

    def submit_user_order(self, req: OrderSubmitRequest) -> dict[str, Any]:
        """Validate, persist, and submit a user order to the matching engine."""
        if self.mode != RunnerMode.LIVE or self.source is None:
            raise RuntimeError("Live simulation is not running")

        if self.source.engine.is_halted:
            raise RuntimeError("Market is currently halted by circuit breaker")

        tick_size = self.current_config.tick_size
        if req.order_type == OrderType.LIMIT:
            if req.price is None or req.price <= 0:
                raise ValueError("Limit orders require a positive price")
            price_ticks: int | None = price_to_ticks(req.price, tick_size)
            est_ticks = price_ticks
        else:
            price_ticks = None
            est_ticks = price_to_ticks(self._latest_price, tick_size)

        valid, err = self.portfolio.validate_order(
            symbol=req.symbol,
            side=req.side,
            order_type=req.order_type,
            qty=req.qty,
            price_ticks=price_ticks,
            estimated_price_ticks=est_ticks,
        )
        if not valid:
            raise ValueError(err or "Order validation failed")

        order_id = f"usr_{uuid.uuid4().hex[:8]}"
        seq = self.source.engine.allocate_seq()
        ts_ns = self.source._clock.now_ns()

        order_evt = OrderSubmitted(
            seq=seq,
            ts_ns=ts_ns,
            symbol=req.symbol,
            order_id=order_id,
            side=req.side,
            order_type=req.order_type,
            price_ticks=price_ticks,
            qty=req.qty,
            tif=req.tif,
            participant_id=req.participant_id,
            stp=req.stp,
        )

        self.store.append_event(self.active_session_id, order_evt)
        self._current_seq = seq
        self._total_events = seq

        self.portfolio.on_order_submitted(order_evt)

        # Submit to matching engine
        matching_events = self.source.engine.submit_order(order_evt)
        for evt in matching_events:
            self.store.append_event(self.active_session_id, evt)
            self._current_seq = evt.seq
            self._total_events = evt.seq
            if isinstance(evt, OrderAccepted) and evt.order_id in self.portfolio.orders:
                self.portfolio.on_order_accepted(evt)
            elif isinstance(evt, OrderRejected) and evt.order_id in self.portfolio.orders:
                self.portfolio.on_order_rejected(evt)
            elif isinstance(evt, OrderCanceled) and evt.order_id in self.portfolio.orders:
                self.portfolio.on_order_canceled(evt)
            self._process_event(evt, broadcast=True)

        current_ticks = price_to_ticks(self._latest_price, tick_size)
        summary = self.portfolio.get_summary(current_ticks, tick_size, req.symbol)
        self.broadcaster.push_portfolio(summary)

        return self.portfolio.orders[order_id].to_dict(tick_size)

    def cancel_user_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an active user order in the matching engine."""
        if self.mode != RunnerMode.LIVE or self.source is None:
            raise RuntimeError("Live simulation is not running")

        if order_id not in self.portfolio.orders:
            raise KeyError(f"Order '{order_id}' not found")

        order = self.portfolio.orders[order_id]
        if order.status not in (
            OrderStatus.PENDING,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
        ):
            raise ValueError(f"Cannot cancel order in status '{order.status.value}'")

        ts_ns = self.source._clock.now_ns()
        cancel_events = self.source.engine.cancel_order(
            order_id, ts_ns=ts_ns, reason="USER_REQUESTED"
        )
        for evt in cancel_events:
            self.store.append_event(self.active_session_id, evt)
            self._current_seq = evt.seq
            self._total_events = evt.seq
            if isinstance(evt, OrderCanceled) and evt.order_id == order_id:
                self.portfolio.on_order_canceled(evt)
            self._process_event(evt, broadcast=True)

        tick_size = self.current_config.tick_size
        current_ticks = price_to_ticks(self._latest_price, tick_size)
        summary = self.portfolio.get_summary(current_ticks, tick_size, order.symbol)
        self.broadcaster.push_portfolio(summary)

        return order.to_dict(tick_size)

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
            if self.active_session_id:
                self.store.append_event(self.active_session_id, evt)

    async def _run_simulation(self) -> None:
        """Producer loop emitting and persisting simulated trades, deltas, anomalies, and bars."""
        assert self.source is not None
        interval_s = 1.0 / self.current_config.trades_per_sec

        try:
            while self._running:
                start_t = asyncio.get_event_loop().time()

                event = self.source.next_event()
                if event is not None:
                    # Persist event to append-only SQLite log
                    self.store.append_event(self.active_session_id, event)
                    self._current_seq = event.seq
                    self._total_events = event.seq

                    # Update internal projection state and broadcast
                    self._process_event(event, broadcast=True)

                elapsed = asyncio.get_event_loop().time() - start_t
                sleep_t = max(0.0, interval_s - elapsed)
                await asyncio.sleep(sleep_t)
        except asyncio.CancelledError:
            pass

    async def _run_replay(self) -> None:
        """Historical replay loop streaming recorded events with pacing and seeking."""
        assert self.replay_source is not None
        prev_ts_ns: int | None = None

        try:
            while self._running and self.replay_source.has_next():
                if self.mode == RunnerMode.PAUSED:
                    await asyncio.sleep(0.05)
                    continue

                event = self.replay_source.next_event()
                if event is None:
                    if not self.replay_source.has_next():
                        break
                    await asyncio.sleep(0.01)
                    continue

                self._current_seq = event.seq

                # Calculate pacing delay scaled by speed_multiplier
                delay_s = self.replay_source.calculate_delay_s(prev_ts_ns, event.ts_ns)
                if delay_s > 0:
                    await asyncio.sleep(delay_s)

                prev_ts_ns = event.ts_ns
                self._process_event(event, broadcast=True)

            self.mode = RunnerMode.STOPPED
        except asyncio.CancelledError:
            pass


def _clean_array(arr: np.ndarray) -> list[float | None]:
    """Convert numpy array with NaNs to JSON-compliant list of floats and Nones."""
    return [None if np.isnan(x) else round(float(x), 4) for x in arr]


def create_app(
    throttling_fps: int = 20,
    store: SQLiteEventStore | None = None,
    db_path: str = "marketpulse.db",
) -> FastAPI:
    """Create and configure the MarketPulse FastAPI application."""
    event_store = store if store is not None else SQLiteEventStore(db_path)
    broadcaster = Broadcaster(throttling_fps=throttling_fps)
    sim_runner = SimulationRunner(broadcaster=broadcaster, store=event_store)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        await broadcaster.start()
        # Start default simulation session
        sim_runner.start(SessionConfigRequest())
        yield
        sim_runner.stop()
        await broadcaster.stop()
        sim_runner.store.close()

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

        tick_size = sim_runner.current_config.tick_size
        if sim_runner.mode == RunnerMode.REPLAY:
            snapshot = sim_runner.depth_tracker.snapshot(max_levels=levels)
            is_halted = sim_runner._replay_halted
        elif sim_runner.source is not None:
            snapshot = sim_runner.source.book_snapshot(max_levels=levels)
            is_halted = sim_runner.source.engine.is_halted
        else:
            raise HTTPException(status_code=503, detail="Simulation not initialized")

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
            "is_halted": is_halted,
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

    # --- Session Persistence & Historical Replay Endpoints ---

    @app.get("/api/v1/sessions")
    async def list_sessions(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """List recorded simulation sessions ordered by creation date."""
        sessions = sim_runner.store.list_sessions(limit=limit, offset=offset)
        return [s.to_dict() for s in sessions]

    @app.post("/api/v1/sessions")
    async def configure_session(req: SessionConfigRequest) -> dict[str, Any]:
        """Configure and start a new live simulation session."""
        session_id = sim_runner.start(req)
        return {"status": "started", "session_id": session_id, "config": req.model_dump()}

    @app.get("/api/v1/sessions/active")
    async def get_active_session() -> dict[str, Any]:
        """Return active runner status, mode, and replay progression."""
        return sim_runner.get_active_status()

    @app.get("/api/v1/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        """Retrieve metadata for a recorded session."""
        meta = sim_runner.store.get_session(session_id)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
        return meta.to_dict()

    @app.post("/api/v1/sessions/{session_id}/stop")
    async def stop_session(session_id: str) -> dict[str, Any]:
        """Terminate an active live or replay session."""
        sim_runner.stop()
        return {"status": "stopped", "session_id": session_id}

    @app.post("/api/v1/sessions/{session_id}/replay")
    async def replay_session(
        session_id: str,
        req: ReplayRequest | None = None,
    ) -> dict[str, Any]:
        """Start historical replay of a recorded session."""
        effective_req = req or ReplayRequest()
        try:
            sim_runner.start_replay(
                session_id=session_id,
                speed_multiplier=effective_req.speed_multiplier,
                seek_seq=effective_req.seek_seq,
            )
            return {
                "status": "replaying",
                "session_id": session_id,
                "speed_multiplier": effective_req.speed_multiplier,
                "seek_seq": effective_req.seek_seq,
            }
        except ValueError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err

    @app.post("/api/v1/sessions/{session_id}/seek")
    async def seek_session(session_id: str, req: SeekRequest) -> dict[str, Any]:
        """Seek replay to a specific sequence number."""
        try:
            sim_runner.seek_replay(req.target_seq)
            return {"status": "seeked", "target_seq": req.target_seq}
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.post("/api/v1/sessions/{session_id}/speed")
    async def set_replay_speed(session_id: str, req: SpeedRequest) -> dict[str, Any]:
        """Update replay playback speed."""
        try:
            sim_runner.set_replay_speed(req.speed_multiplier)
            return {"status": "updated", "speed_multiplier": req.speed_multiplier}
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.post("/api/v1/sessions/{session_id}/pause")
    async def pause_session(session_id: str) -> dict[str, Any]:
        """Pause replay progression."""
        sim_runner.pause()
        return {"status": "paused", "session_id": session_id}

    @app.post("/api/v1/sessions/{session_id}/resume")
    async def resume_session(session_id: str) -> dict[str, Any]:
        """Resume replay progression."""
        sim_runner.resume()
        return {"status": "resumed", "session_id": session_id}

    @app.get("/api/v1/sessions/{session_id}/events")
    async def get_session_events(
        session_id: str,
        from_seq: int = 1,
        to_seq: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve historical sequenced events from the session log."""
        events = sim_runner.store.get_events(
            session_id=session_id,
            from_seq=from_seq,
            to_seq=to_seq,
            limit=limit,
        )
        return [e.to_dict() for e in events]

    # --- Scenarios & Anomaly Endpoints ---

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
        except (ValueError, RuntimeError) as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.get("/api/v1/anomalies")
    async def get_anomalies(limit: int = 50) -> list[dict[str, Any]]:
        """Return recent detected streaming anomalies."""
        anomalies = list(sim_runner.recent_anomalies)
        return anomalies[-limit:] if limit > 0 else anomalies

    @app.get("/api/v1/market-status")
    async def get_market_status(symbol: str = "AAPL") -> dict[str, Any]:
        """Return market state including circuit breaker halt status and STP metrics."""
        if sim_runner.mode == RunnerMode.REPLAY:
            is_halted = sim_runner._replay_halted
        else:
            is_halted = sim_runner.source.engine.is_halted if sim_runner.source else False

        stp_stats = (
            sim_runner.source.engine.get_stp_stats()
            if (sim_runner.source and sim_runner.mode == RunnerMode.LIVE)
            else {
                "cancel_newest": 0,
                "cancel_oldest": 0,
                "decrement_and_cancel": 0,
                "total_prevented": 0,
            }
        )

        return {
            "symbol": symbol,
            "is_halted": is_halted,
            "status": "HALTED" if is_halted else "ACTIVE",
            "latest_price": sim_runner._latest_price,
            "stp_stats": stp_stats,
        }

    # --- User Orders & Portfolio Management (OMS/PMS) Endpoints ---

    @app.post("/api/v1/orders")
    async def place_order(req: OrderSubmitRequest) -> dict[str, Any]:
        """Submit a manual limit or market order to the matching engine."""
        try:
            return sim_runner.submit_user_order(req)
        except KeyError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except (ValueError, RuntimeError) as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.delete("/api/v1/orders/{order_id}")
    async def cancel_order(order_id: str) -> dict[str, Any]:
        """Cancel an open resting limit order."""
        try:
            return sim_runner.cancel_user_order(order_id)
        except KeyError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except (ValueError, RuntimeError) as err:
            raise HTTPException(status_code=400, detail=str(err)) from err

    @app.get("/api/v1/orders")
    async def get_orders(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List active open orders or complete order history."""
        if status == "open":
            return sim_runner.portfolio.get_open_orders()
        return sim_runner.portfolio.get_order_history(limit=limit)

    @app.get("/api/v1/orders/{order_id}")
    async def get_order(order_id: str) -> dict[str, Any]:
        """Retrieve details of a single user order."""
        order = sim_runner.portfolio.orders.get(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found")
        return order.to_dict(sim_runner.current_config.tick_size)

    @app.get("/api/v1/portfolio")
    async def get_portfolio() -> dict[str, Any]:
        """Return paper trading account balance, equity, and position inventory."""
        tick_size = sim_runner.current_config.tick_size
        current_ticks = price_to_ticks(sim_runner._latest_price, tick_size)
        return sim_runner.portfolio.get_summary(
            current_price_ticks=current_ticks,
            tick_size=tick_size,
            symbol=sim_runner.current_config.symbol,
        )

    @app.post("/api/v1/portfolio/reset")
    async def reset_portfolio(req: PortfolioResetRequest | None = None) -> dict[str, Any]:
        """Reset paper trading balance and clear positions."""
        effective_req = req or PortfolioResetRequest()
        tick_size = sim_runner.current_config.tick_size
        sim_runner.portfolio.reset(
            initial_cash=effective_req.initial_cash,
            tick_size=tick_size,
        )
        current_ticks = price_to_ticks(sim_runner._latest_price, tick_size)
        summary = sim_runner.portfolio.get_summary(
            current_price_ticks=current_ticks,
            tick_size=tick_size,
            symbol=sim_runner.current_config.symbol,
        )
        sim_runner.broadcaster.push_portfolio(summary)
        return {"status": "reset", "portfolio": summary}

    @app.get("/api/v1/portfolio/trades")
    async def get_user_trades(limit: int = 50) -> list[dict[str, Any]]:
        """Return user filled trade executions."""
        return sim_runner.portfolio.get_trade_history(limit=limit)

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
