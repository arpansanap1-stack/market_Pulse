"""EventSource protocol and deterministic generator utilities for MarketPulse.

Invariants:
- All sources MUST use an explicit `numpy.random.Generator` initialized with a fixed seed.
- Sources must never rely on `np.random.seed()` or Python's `random` global state.
- Calling `reset(seed)` restarts the sequence deterministically from seq 1.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

import numpy as np

from marketpulse.core.clock import Clock, SimulatedClock
from marketpulse.core.events import (
    Event,
    OrderSubmitted,
    OrderType,
    Side,
    TimeInForce,
)


def create_rng(seed: int) -> np.random.Generator:
    """Create a reproducible NumPy Generator from a non-negative integer seed.

    Args:
        seed: Non-negative integer seed.

    Returns:
        Seeded np.random.Generator.

    Raises:
        ValueError: If seed is negative.
    """
    if seed < 0:
        raise ValueError(f"Seed must be non-negative, got {seed}")
    return np.random.default_rng(seed)


@runtime_checkable
class EventSource(Protocol):
    """Protocol for components generating sequenced market events."""

    def next_event(self) -> Event | None:
        """Produce the next sequenced event or None if source is currently idle."""
        ...

    def stream(self) -> Iterator[Event]:
        """Yield events as a generator stream."""
        ...

    def reset(self, seed: int) -> None:
        """Reset the source state and RNG deterministically to sequence start."""
        ...


class DeterministicSequenceSource:
    """Deterministic event source used for verification and test generation.

    Generates synthetic limit orders around a base tick price using a seeded generator.
    """

    __slots__ = (
        "_base_price_ticks",
        "_clock",
        "_count",
        "_interval_ns",
        "_max_events",
        "_rng",
        "_seed",
        "_seq",
        "_symbol",
    )

    def __init__(
        self,
        seed: int,
        symbol: str = "AAPL",
        base_price_ticks: int = 15000,
        max_events: int = 100,
        interval_ns: int = 1_000_000,
        clock: Clock | None = None,
    ) -> None:
        """Initialize the deterministic test source.

        Args:
            seed: Non-negative integer seed for RNG.
            symbol: Ticker symbol to emit.
            base_price_ticks: Reference price in integer ticks.
            max_events: Total events to emit before exhausting.
            interval_ns: Time step in nanoseconds between events.
            clock: Optional Clock instance (defaults to SimulatedClock).
        """
        self._seed = seed
        self._symbol = symbol
        self._base_price_ticks = base_price_ticks
        self._max_events = max_events
        self._interval_ns = interval_ns
        self._clock: Clock = clock if clock is not None else SimulatedClock(0)
        self._rng: np.random.Generator = create_rng(seed)
        self._seq: int = 1
        self._count: int = 0

    def reset(self, seed: int) -> None:
        """Reset source with a new or same seed."""
        self._seed = seed
        self._rng = create_rng(seed)
        self._seq = 1
        self._count = 0
        if isinstance(self._clock, SimulatedClock):
            self._clock.reset(0)

    def next_event(self) -> Event | None:
        """Generate next deterministic OrderSubmitted event or None if finished."""
        if self._count >= self._max_events:
            return None

        self._clock.sleep_ns(self._interval_ns)
        ts_ns = self._clock.now_ns()

        side = Side.BUY if self._rng.random() < 0.5 else Side.SELL
        offset = int(self._rng.integers(-5, 6))
        price_ticks = max(1, self._base_price_ticks + offset)
        qty = int(self._rng.integers(1, 100))

        event = OrderSubmitted(
            seq=self._seq,
            ts_ns=ts_ns,
            symbol=self._symbol,
            order_id=f"ord_{self._seq:06d}",
            side=side,
            order_type=OrderType.LIMIT,
            price_ticks=price_ticks,
            qty=qty,
            tif=TimeInForce.GTC,
        )

        self._seq += 1
        self._count += 1
        return event

    def stream(self) -> Iterator[Event]:
        """Iterate over all generated events."""
        while True:
            evt = self.next_event()
            if evt is None:
                break
            yield evt
