"""Multiplexed event source for concurrent multi-symbol simulation.

Runs multiple AgentOrderSources and yields their events chronologically.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterator
from typing import Any

from marketpulse.core.clock import Clock, SimulatedClock
from marketpulse.core.events import Event
from marketpulse.sim.agent_source import AgentOrderSource
from marketpulse.sim.source import EventSource


class MultiplexedAgentSource(EventSource):
    """Event source that interleaves events from multiple AgentOrderSources by timestamp."""

    __slots__ = (
        "_clock",
        "_events_emitted",
        "_heap",
        "_heap_initialized",
        "_max_events",
        "_sources",
        "_sources_by_symbol",
        "_tie_breaker",
    )

    def __init__(
        self,
        seed: int,
        symbols: tuple[str, ...],
        initial_price: float = 150.0,
        tick_size: float = 0.01,
        time_step_s: float = 0.001,
        max_events: int | None = None,
        clock: Clock | None = None,
    ) -> None:
        """Initialize multiplexed source with multiple symbols."""
        self._max_events = max_events
        self._clock = clock
        self._events_emitted = 0

        self._sources: list[AgentOrderSource] = []
        for i, symbol in enumerate(symbols):
            source_seed = seed + i
            source = AgentOrderSource(
                seed=source_seed,
                symbol=symbol,
                initial_price=initial_price,
                tick_size=tick_size,
                time_step_s=time_step_s,
                max_events=max_events,
                clock=clock,
            )
            self._sources.append(source)

        self._heap: list[tuple[int, int, Event, Iterator[Event]]] = []
        self._sources_by_symbol = {s._symbol: s for s in self._sources}
        self._heap_initialized = False
        self._tie_breaker = 0

    def get_source(self, symbol: str) -> AgentOrderSource:
        """Get the underlying AgentOrderSource for a symbol."""
        if symbol not in self._sources_by_symbol:
            raise KeyError(f"No source configured for symbol {symbol}")
        return self._sources_by_symbol[symbol]

    def get_engine(self, symbol: str) -> Any:
        """Get the underlying MatchingEngine for a symbol."""
        return self.get_source(symbol).engine

    def _initialize_heap(self) -> None:
        if self._heap_initialized:
            return
        self._heap_initialized = True
        self._tie_breaker = 0
        for source in self._sources:
            iterator = source.stream()
            try:
                first_event = next(iterator)
                heapq.heappush(
                    self._heap,
                    (first_event.ts_ns, self._tie_breaker, first_event, iterator),
                )
                self._tie_breaker += 1
            except StopIteration:
                pass

    def next_event(self) -> Event | None:
        """Produce the next sequenced event chronologically across all sources."""
        if not self._heap_initialized:
            self._initialize_heap()

        if not self._heap:
            return None

        if self._max_events is not None and self._events_emitted >= self._max_events:
            return None

        ts_ns, _, event, iterator = heapq.heappop(self._heap)

        if isinstance(self._clock, SimulatedClock):
            self._clock.set_time(ts_ns)

        self._events_emitted += 1

        try:
            next_evt = next(iterator)
            heapq.heappush(
                self._heap,
                (next_evt.ts_ns, self._tie_breaker, next_evt, iterator),
            )
            self._tie_breaker += 1
        except StopIteration:
            pass

        return event

    def stream(self) -> Iterator[Event]:
        """Yield events as a generator stream."""
        while True:
            evt = self.next_event()
            if evt is None:
                break
            yield evt

    def reset(self, seed: int) -> None:
        """Reset the source deterministically."""
        self._events_emitted = 0
        self._heap = []
        self._heap_initialized = False
        self._tie_breaker = 0
        for i, source in enumerate(self._sources):
            source.reset(seed + i)
