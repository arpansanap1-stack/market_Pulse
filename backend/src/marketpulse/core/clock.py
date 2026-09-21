"""Monotonic simulation and wall-clock abstractions for MarketPulse.

Invariants:
- Time is always represented as a non-negative 64-bit integer nanosecond count (`int`).
- Clocks are strictly monotonic; time cannot travel backwards.
- Domain modules must never call `time.time()` directly; they must receive a `Clock` instance.
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Protocol for monotonic time providers in MarketPulse."""

    def now_ns(self) -> int:
        """Return the current timestamp in integer nanoseconds."""
        ...

    def sleep_ns(self, duration_ns: int) -> None:
        """Pause or advance time by duration_ns nanoseconds.

        Args:
            duration_ns: Duration in non-negative integer nanoseconds.

        Raises:
            ValueError: If duration_ns is negative.
        """
        ...


class SimulatedClock:
    """Deterministic, explicitly controlled clock for simulations and testing.

    Invariants:
    - Current time starts at `initial_ts_ns` (default 0) and is non-negative.
    - Time advances explicitly via `advance_by` or `sleep_ns`.
    - Time is strictly non-decreasing; backwards steps raise ValueError.
    """

    __slots__ = ("_current_ts_ns",)

    def __init__(self, initial_ts_ns: int = 0) -> None:
        """Initialize simulated clock.

        Args:
            initial_ts_ns: Starting timestamp in integer nanoseconds (must be >= 0).

        Raises:
            ValueError: If initial_ts_ns is negative.
        """
        if initial_ts_ns < 0:
            raise ValueError(f"initial_ts_ns must be non-negative, got {initial_ts_ns}")
        self._current_ts_ns: int = initial_ts_ns

    def now_ns(self) -> int:
        """Return current simulated timestamp in integer nanoseconds."""
        return self._current_ts_ns

    def advance_by(self, duration_ns: int) -> int:
        """Advance simulated clock by duration_ns.

        Args:
            duration_ns: Non-negative integer nanoseconds to advance.

        Returns:
            The new timestamp in nanoseconds.

        Raises:
            ValueError: If duration_ns is negative.
        """
        if duration_ns < 0:
            raise ValueError(f"duration_ns must be non-negative, got {duration_ns}")
        self._current_ts_ns += duration_ns
        return self._current_ts_ns

    def set_time(self, target_ts_ns: int) -> None:
        """Set current time to a specific target timestamp.

        Args:
            target_ts_ns: Target timestamp in integer nanoseconds (must be >= current_ts).

        Raises:
            ValueError: If target_ts_ns is less than current timestamp.
        """
        if target_ts_ns < self._current_ts_ns:
            raise ValueError(
                f"Cannot move clock backward: target {target_ts_ns} < current {self._current_ts_ns}"
            )
        self._current_ts_ns = target_ts_ns

    def reset(self, initial_ts_ns: int = 0) -> None:
        """Reset the clock back to initial_ts_ns for a new simulation session.

        Args:
            initial_ts_ns: Non-negative integer nanoseconds (default 0).

        Raises:
            ValueError: If initial_ts_ns is negative.
        """
        if initial_ts_ns < 0:
            raise ValueError(f"initial_ts_ns must be non-negative, got {initial_ts_ns}")
        self._current_ts_ns = initial_ts_ns

    def sleep_ns(self, duration_ns: int) -> None:
        """Advance simulated clock by duration_ns (simulating elapsed time).

        Args:
            duration_ns: Non-negative integer nanoseconds.

        Raises:
            ValueError: If duration_ns is negative.
        """
        self.advance_by(duration_ns)


class WallClock:
    """Real-time clock adapter for live execution against wall-clock time."""

    __slots__ = ()

    def now_ns(self) -> int:
        """Return current wall-clock epoch timestamp in nanoseconds."""
        return time.time_ns()

    def sleep_ns(self, duration_ns: int) -> None:
        """Pause real execution for duration_ns nanoseconds.

        Args:
            duration_ns: Duration in non-negative integer nanoseconds.

        Raises:
            ValueError: If duration_ns is negative.
        """
        if duration_ns < 0:
            raise ValueError(f"duration_ns must be non-negative, got {duration_ns}")
        time.sleep(duration_ns / 1_000_000_000.0)
