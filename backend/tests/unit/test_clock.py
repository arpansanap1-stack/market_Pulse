"""Unit tests verifying Clock protocol, SimulatedClock, and WallClock invariants."""

import pytest

from marketpulse.core.clock import Clock, SimulatedClock, WallClock


def test_clock_protocol_conformance() -> None:
    """Verify both SimulatedClock and WallClock satisfy runtime Clock protocol."""
    sim = SimulatedClock()
    wall = WallClock()
    assert isinstance(sim, Clock)
    assert isinstance(wall, Clock)


def test_simulated_clock_initialization() -> None:
    """Verify default and custom initial timestamps."""
    clock_default = SimulatedClock()
    assert clock_default.now_ns() == 0

    clock_custom = SimulatedClock(10_000_000)
    assert clock_custom.now_ns() == 10_000_000

    with pytest.raises(ValueError, match="initial_ts_ns must be non-negative"):
        SimulatedClock(-1)


def test_simulated_clock_advance() -> None:
    """Verify time advancing and error on negative duration."""
    clock = SimulatedClock(1_000)
    new_time = clock.advance_by(500)
    assert new_time == 1_500
    assert clock.now_ns() == 1_500

    clock.sleep_ns(250)
    assert clock.now_ns() == 1_750

    with pytest.raises(ValueError, match="duration_ns must be non-negative"):
        clock.advance_by(-100)

    with pytest.raises(ValueError, match="duration_ns must be non-negative"):
        clock.sleep_ns(-50)


def test_simulated_clock_set_time() -> None:
    """Verify set_time advances forward but raises error on backwards movement."""
    clock = SimulatedClock(1_000)
    clock.set_time(2_000)
    assert clock.now_ns() == 2_000

    # Setting to current timestamp is valid (no-op)
    clock.set_time(2_000)
    assert clock.now_ns() == 2_000

    with pytest.raises(ValueError, match="Cannot move clock backward"):
        clock.set_time(1_999)


def test_simulated_clock_reset() -> None:
    """Verify reset sets clock back to initial_ts_ns and rejects negative values."""
    clock = SimulatedClock(5_000)
    clock.advance_by(5_000)
    assert clock.now_ns() == 10_000

    clock.reset(0)
    assert clock.now_ns() == 0

    clock.reset(1_000)
    assert clock.now_ns() == 1_000

    with pytest.raises(ValueError, match="initial_ts_ns must be non-negative"):
        clock.reset(-1)


def test_wall_clock() -> None:
    """Verify WallClock returns positive monotonic timestamps."""
    wall = WallClock()
    t1 = wall.now_ns()
    assert t1 > 0

    wall.sleep_ns(1_000_000)  # 1 ms sleep
    t2 = wall.now_ns()
    assert t2 >= t1

    with pytest.raises(ValueError, match="duration_ns must be non-negative"):
        wall.sleep_ns(-1)
