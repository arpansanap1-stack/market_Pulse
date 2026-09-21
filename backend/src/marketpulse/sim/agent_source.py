"""Agent-driven continuous double-auction market event source for MarketPulse.

Orchestrates multiple simulated trading agents (Market Makers, Noise Traders,
and Trend Followers) feeding into a deterministic MatchingEngine.

Invariants:
- Pure EventSource protocol compliance.
- Monotonic sequence numbering and non-decreasing ts_ns.
- Identical seed guarantees byte-identical emitted event streams.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from typing import Any

import numpy as np

from marketpulse.core.clock import Clock, SimulatedClock
from marketpulse.core.events import (
    Event,
    MarketEvent,
    TradeExecuted,
    price_to_ticks,
)
from marketpulse.core.orderbook import MatchingEngine
from marketpulse.sim.agents import (
    Agent,
    MarketMakerAgent,
    NoiseTraderAgent,
    TrendFollowerAgent,
)
from marketpulse.sim.source import EventSource, create_rng


class AgentOrderSource(EventSource):
    """Deterministic event source running simulated agents against a matching engine."""

    __slots__ = (
        "_agents",
        "_clock",
        "_current_ref_price_ticks",
        "_engine",
        "_events_emitted",
        "_initial_price",
        "_initial_price_ticks",
        "_interval_ns",
        "_max_events",
        "_order_seq",
        "_pending_events",
        "_rng",
        "_seed",
        "_symbol",
        "_tick_size",
        "_ticks_elapsed",
    )

    def __init__(
        self,
        seed: int,
        symbol: str = "AAPL",
        initial_price: float = 150.0,
        tick_size: float = 0.01,
        time_step_s: float = 0.001,
        max_events: int | None = None,
        clock: Clock | None = None,
        num_market_makers: int = 2,
        num_noise_traders: int = 5,
        num_trend_followers: int = 1,
    ) -> None:
        """Initialize agent order source."""
        if initial_price <= 0:
            raise ValueError(f"initial_price must be positive, got {initial_price}")
        if tick_size <= 0:
            raise ValueError(f"tick_size must be positive, got {tick_size}")

        self._seed = seed
        self._symbol = symbol
        self._initial_price = initial_price
        self._tick_size = tick_size
        self._initial_price_ticks = max(1, price_to_ticks(initial_price, tick_size))
        self._current_ref_price_ticks = self._initial_price_ticks
        self._interval_ns = int(time_step_s * 1_000_000_000)
        self._max_events = max_events
        self._clock: Clock = clock if clock is not None else SimulatedClock(0)
        self._rng: np.random.Generator = create_rng(seed)

        self._engine = MatchingEngine(symbol=symbol, initial_seq=1)
        self._order_seq = 1
        self._ticks_elapsed = 0
        self._events_emitted = 0
        self._pending_events: deque[Event] = deque()

        # Build agent pool
        self._agents: list[Agent] = self._build_agents(
            num_market_makers, num_noise_traders, num_trend_followers
        )

        # Seed the book with initial liquidity from market makers
        self._bootstrap_liquidity()

    def _build_agents(
        self,
        num_mms: int,
        num_noise: int,
        num_trend: int,
    ) -> list[Agent]:
        agents: list[Agent] = []
        for i in range(num_mms):
            agent_rng = create_rng(int(self._rng.integers(0, 2**31 - 1)))
            agents.append(
                MarketMakerAgent(
                    agent_id=f"mm_{i + 1}",
                    rng=agent_rng,
                    half_spread_ticks=1 + i,
                    levels=4,
                    qty_per_level=50 + i * 25,
                )
            )

        for i in range(num_noise):
            agent_rng = create_rng(int(self._rng.integers(0, 2**31 - 1)))
            agents.append(
                NoiseTraderAgent(
                    agent_id=f"noise_{i + 1}",
                    rng=agent_rng,
                    market_order_prob=0.40,
                    price_jitter=3,
                )
            )

        for i in range(num_trend):
            agent_rng = create_rng(int(self._rng.integers(0, 2**31 - 1)))
            agents.append(
                TrendFollowerAgent(
                    agent_id=f"trend_{i + 1}",
                    rng=agent_rng,
                    lookback=8,
                    threshold_ticks=2,
                )
            )

        return agents

    def _bootstrap_liquidity(self) -> None:
        """Seed initial order book quotes from market makers before trading starts."""
        ts_ns = self._clock.now_ns()
        for agent in self._agents:
            if isinstance(agent, MarketMakerAgent):
                orders = agent.generate_orders(
                    symbol=self._symbol,
                    best_bid=None,
                    best_ask=None,
                    ref_price_ticks=self._current_ref_price_ticks,
                    seq_start=self._order_seq,
                    ts_ns=ts_ns,
                )
                self._order_seq += len(orders)
                for o in orders:
                    out = self._engine.submit_order(o)
                    self._pending_events.extend(out)

    @property
    def engine(self) -> MatchingEngine:
        """Access the underlying matching engine."""
        return self._engine

    def book_snapshot(self, max_levels: int = 10) -> dict[str, Any]:
        """Fetch current L2 depth snapshot."""
        return self._engine.book.depth_snapshot(max_levels)

    def inject_market_event(self, event: MarketEvent) -> list[Event]:
        """Inject an exogenous market event into the simulation.

        Broadcasts to all agents, triggers engine halt/resume if applicable,
        shifts ref price on earnings shock, and appends the MarketEvent to pending events.
        """
        ts_ns = max(event.ts_ns, self._clock.now_ns())
        seq = self._engine.allocate_seq()

        injected = MarketEvent(
            seq=seq,
            ts_ns=ts_ns,
            symbol=self._symbol,
            kind=event.kind,
            params=dict(event.params),
        )

        # Notify agents
        for agent in self._agents:
            agent.on_market_event(injected)

        # Engine halt / resume / shock handling
        if injected.kind == "HALT":
            self._engine.is_halted = True
        elif injected.kind == "RESUME":
            self._engine.is_halted = False
        elif injected.kind == "EARNINGS_SHOCK":
            raw_pct = float(
                injected.params.get("price_jump_pct", injected.params.get("jump_pct", 0.0))
            )
            pct = raw_pct if abs(raw_pct) > 1.0 else raw_pct * 100.0
            jump_ticks = round(self._current_ref_price_ticks * (pct / 100.0))
            self._current_ref_price_ticks = max(1, self._current_ref_price_ticks + jump_ticks)

        self._pending_events.append(injected)
        return [injected]

    def reset(self, seed: int) -> None:
        """Reset the source deterministically."""
        self._seed = seed
        self._rng = create_rng(seed)
        self._current_ref_price_ticks = self._initial_price_ticks
        self._engine = MatchingEngine(symbol=self._symbol, initial_seq=1)
        self._order_seq = 1
        self._ticks_elapsed = 0
        self._events_emitted = 0
        self._pending_events.clear()
        if isinstance(self._clock, SimulatedClock):
            self._clock.reset(0)

        self._agents = self._build_agents(num_mms=2, num_noise=5, num_trend=1)
        self._bootstrap_liquidity()

    def _step_simulation(self) -> None:
        """Advance time and generate new orders from a selected agent."""
        self._clock.sleep_ns(self._interval_ns)
        ts_ns = self._clock.now_ns()
        self._ticks_elapsed += 1

        best_bid = self._engine.book.best_bid()
        best_ask = self._engine.book.best_ask()

        # Select which agent acts this step
        # Every 10 steps, refresh MM quotes if spread is wide or one-sided
        if self._ticks_elapsed % 10 == 0 or best_bid is None or best_ask is None:
            active_agent = self._agents[0]  # Primary MM
        else:
            # Pick from noise and trend agents
            other_agents = self._agents[1:]
            idx = int(self._rng.integers(0, len(other_agents)))
            active_agent = other_agents[idx]

        orders = active_agent.generate_orders(
            symbol=self._symbol,
            best_bid=best_bid,
            best_ask=best_ask,
            ref_price_ticks=self._current_ref_price_ticks,
            seq_start=self._order_seq,
            ts_ns=ts_ns,
        )
        self._order_seq += len(orders)

        for order in orders:
            emitted = self._engine.submit_order(order)
            for evt in emitted:
                if isinstance(evt, TradeExecuted):
                    self._current_ref_price_ticks = evt.price_ticks
                self._pending_events.append(evt)

    def next_event(self) -> Event | None:
        """Return the next market event or None if max_events reached."""
        if self._max_events is not None and self._events_emitted >= self._max_events:
            return None

        while not self._pending_events:
            self._step_simulation()

        evt = self._pending_events.popleft()
        self._events_emitted += 1
        return evt

    def stream(self) -> Iterator[Event]:
        """Iterate over all generated events."""
        while True:
            evt = self.next_event()
            if evt is None:
                break
            yield evt
