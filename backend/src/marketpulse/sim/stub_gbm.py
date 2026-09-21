"""Geometric Brownian Motion (GBM) stub market event source for Phase 1.

Generates realistic continuous price paths quantized to integer ticks and emits
sequenced TradeExecuted events behind the pure EventSource protocol.

Invariants:
- Deterministic: Identical seed produces byte-identical trade event logs.
- Monotonic: seq >= 1 and strictly increasing; ts_ns strictly increasing.
- Price handling: Internal prices are strictly positive integer ticks (price_ticks).
"""

from __future__ import annotations

import math
from collections.abc import Iterator

import numpy as np

from marketpulse.core.clock import Clock, SimulatedClock
from marketpulse.core.events import Event, Side, TradeExecuted, price_to_ticks
from marketpulse.sim.source import EventSource, create_rng


class StubGBMSource(EventSource):
    """Stub simulator generating synthetic trades via Geometric Brownian Motion."""

    __slots__ = (
        "_annual_drift",
        "_annual_volatility",
        "_clock",
        "_current_price",
        "_current_price_ticks",
        "_drift_term",
        "_initial_price",
        "_interval_ns",
        "_max_events",
        "_rng",
        "_seed",
        "_seq",
        "_symbol",
        "_tick_size",
        "_time_step_s",
        "_vol_term",
    )

    def __init__(
        self,
        seed: int,
        symbol: str = "AAPL",
        initial_price: float = 150.0,
        annual_volatility: float = 0.20,
        annual_drift: float = 0.05,
        tick_size: float = 0.01,
        time_step_s: float = 0.001,
        max_events: int | None = None,
        clock: Clock | None = None,
    ) -> None:
        """Initialize the GBM stub market source.

        Args:
            seed: Non-negative integer seed for the NumPy Generator.
            symbol: Ticker symbol to emit trades for.
            initial_price: Starting decimal currency price.
            annual_volatility: Annualized return volatility (sigma).
            annual_drift: Annualized expected drift (mu).
            tick_size: Minimum price increment in currency units.
            time_step_s: Simulated time step duration in seconds between trades.
            max_events: Optional maximum number of events to emit before exhausting.
            clock: Optional Clock instance (defaults to SimulatedClock).
        """
        if initial_price <= 0:
            raise ValueError(f"initial_price must be positive, got {initial_price}")
        if annual_volatility <= 0:
            raise ValueError(f"annual_volatility must be positive, got {annual_volatility}")
        if tick_size <= 0:
            raise ValueError(f"tick_size must be positive, got {tick_size}")
        if time_step_s <= 0:
            raise ValueError(f"time_step_s must be positive, got {time_step_s}")

        self._seed = seed
        self._symbol = symbol
        self._initial_price = initial_price
        self._annual_volatility = annual_volatility
        self._annual_drift = annual_drift
        self._tick_size = tick_size
        self._time_step_s = time_step_s
        self._max_events = max_events
        self._interval_ns = int(time_step_s * 1_000_000_000)
        self._clock: Clock = clock if clock is not None else SimulatedClock(0)
        self._rng: np.random.Generator = create_rng(seed)

        # Precompute GBM log-drift and diffusion coefficients (252 days * 6.5h * 3600s)
        trading_seconds_per_year = 252.0 * 6.5 * 3600.0
        dt = time_step_s / trading_seconds_per_year
        self._drift_term = (annual_drift - 0.5 * annual_volatility**2) * dt
        self._vol_term = annual_volatility * math.sqrt(dt)

        self._current_price = initial_price
        self._current_price_ticks = max(1, price_to_ticks(initial_price, tick_size))
        self._seq = 1

    def reset(self, seed: int) -> None:
        """Reset the source state and RNG deterministically to initial conditions."""
        self._seed = seed
        self._rng = create_rng(seed)
        self._current_price = self._initial_price
        self._current_price_ticks = max(1, price_to_ticks(self._initial_price, self._tick_size))
        self._seq = 1
        if isinstance(self._clock, SimulatedClock):
            self._clock.reset(0)

    def next_event(self) -> Event | None:
        """Generate the next sequenced TradeExecuted event or None if exhausted."""
        if self._max_events is not None and self._seq > self._max_events:
            return None

        self._clock.sleep_ns(self._interval_ns)
        ts_ns = self._clock.now_ns()

        # GBM step: S_{t+dt} = S_t * exp(drift + vol * Z)
        z = float(self._rng.standard_normal())
        log_return = self._drift_term + self._vol_term * z
        next_price = self._current_price * math.exp(log_return)

        # Quantize to integer price ticks
        next_price_ticks = max(1, price_to_ticks(next_price, self._tick_size))

        # Determine aggressor side from price direction
        aggressor_side = Side.BUY if next_price_ticks >= self._current_price_ticks else Side.SELL

        # Discrete realistic trade size sampling (e.g., 10, 25, 50, 100, 200, 500 shares)
        size_choices = (10, 25, 50, 100, 200, 500)
        size_weights = (0.35, 0.25, 0.20, 0.12, 0.06, 0.02)
        qty = int(self._rng.choice(size_choices, p=size_weights))

        trade = TradeExecuted(
            seq=self._seq,
            ts_ns=ts_ns,
            symbol=self._symbol,
            trade_id=f"trd_{self._seq:06d}",
            price_ticks=next_price_ticks,
            qty=qty,
            aggressor_side=aggressor_side,
            buy_order_id=f"ord_b_{self._seq:06d}",
            sell_order_id=f"ord_s_{self._seq:06d}",
        )

        self._current_price = next_price
        self._current_price_ticks = next_price_ticks
        self._seq += 1
        return trade

    def stream(self) -> Iterator[Event]:
        """Iterate over all generated trade events."""
        while True:
            evt = self.next_event()
            if evt is None:
                break
            yield evt
