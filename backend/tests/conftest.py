"""Global pytest fixtures for MarketPulse test suites."""

from __future__ import annotations

import pytest

from marketpulse.core.clock import SimulatedClock


@pytest.fixture
def sim_clock() -> SimulatedClock:
    """Fixture providing a fresh SimulatedClock initialized at t=0."""
    return SimulatedClock(initial_ts_ns=0)


@pytest.fixture
def fixed_seed() -> int:
    """Standard fixed seed for deterministic tests."""
    return 1337
