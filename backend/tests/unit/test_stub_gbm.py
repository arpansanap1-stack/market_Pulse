"""Unit and determinism tests for StubGBMSource."""

import pytest

from marketpulse.core.events import EventType, TradeExecuted
from marketpulse.sim.source import EventSource
from marketpulse.sim.stub_gbm import StubGBMSource


def test_stub_gbm_protocol_conformance() -> None:
    """Verify StubGBMSource satisfies runtime EventSource protocol."""
    source = StubGBMSource(seed=42)
    assert isinstance(source, EventSource)


def test_stub_gbm_parameter_validation() -> None:
    """Verify invalid constructor parameters raise ValueError."""
    with pytest.raises(ValueError, match="initial_price must be positive"):
        StubGBMSource(seed=42, initial_price=0)

    with pytest.raises(ValueError, match="annual_volatility must be positive"):
        StubGBMSource(seed=42, annual_volatility=-0.1)

    with pytest.raises(ValueError, match="tick_size must be positive"):
        StubGBMSource(seed=42, tick_size=0)

    with pytest.raises(ValueError, match="time_step_s must be positive"):
        StubGBMSource(seed=42, time_step_s=-0.01)


def test_stub_gbm_event_generation_and_properties() -> None:
    """Verify sequencing, timestamps, integer price ticks, and quantities."""
    max_events = 50
    source = StubGBMSource(
        seed=100,
        symbol="AAPL",
        initial_price=150.0,
        tick_size=0.01,
        max_events=max_events,
    )

    trades: list[TradeExecuted] = []
    for event in source.stream():
        assert isinstance(event, TradeExecuted)
        assert event.event_type == EventType.TRADE_EXECUTED
        assert event.symbol == "AAPL"
        assert event.price_ticks > 0
        assert event.qty > 0
        trades.append(event)

    assert len(trades) == max_events

    # Verify monotonic sequencing
    for i, trade in enumerate(trades):
        assert trade.seq == i + 1
        if i > 0:
            assert trade.ts_ns > trades[i - 1].ts_ns

    # Source should now return None
    assert source.next_event() is None


def test_stub_gbm_strict_determinism() -> None:
    """Invariant: Same seed produces byte-identical trade event logs."""
    seed = 42
    count = 1000

    source_a = StubGBMSource(seed=seed, max_events=count)
    source_b = StubGBMSource(seed=seed, max_events=count)

    events_a = [e.to_json() for e in source_a.stream()]
    events_b = [e.to_json() for e in source_b.stream()]

    assert len(events_a) == count
    assert events_a == events_b


def test_stub_gbm_reset() -> None:
    """Verify reset regenerates identical trade stream."""
    seed = 999
    source = StubGBMSource(seed=seed, max_events=100)

    run_1 = [e.to_json() for e in source.stream()]
    source.reset(seed)
    run_2 = [e.to_json() for e in source.stream()]

    assert run_1 == run_2


def test_stub_gbm_seed_divergence() -> None:
    """Verify distinct seeds produce divergent trade sequences."""
    source_1 = StubGBMSource(seed=1, max_events=50)
    source_2 = StubGBMSource(seed=2, max_events=50)

    events_1 = [e.to_json() for e in source_1.stream()]
    events_2 = [e.to_json() for e in source_2.stream()]

    assert events_1 != events_2
