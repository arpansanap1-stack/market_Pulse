"""Unit and determinism tests for EventSource protocol and DeterministicSequenceSource."""

import pytest

from marketpulse.sim.source import (
    DeterministicSequenceSource,
    EventSource,
    create_rng,
)


def test_source_protocol_conformance() -> None:
    """Verify DeterministicSequenceSource satisfies runtime EventSource protocol."""
    source = DeterministicSequenceSource(seed=42)
    assert isinstance(source, EventSource)


def test_create_rng_reproducibility() -> None:
    """Verify seeded numpy generator reproducibility and parameter validation."""
    rng1 = create_rng(12345)
    rng2 = create_rng(12345)
    assert (rng1.random(10) == rng2.random(10)).all()

    with pytest.raises(ValueError, match="Seed must be non-negative"):
        create_rng(-1)


def test_source_event_generation_and_exhaustion() -> None:
    """Verify event sequencing, monotonic timestamps, and exhaustion limit."""
    max_events = 25
    source = DeterministicSequenceSource(seed=999, max_events=max_events)

    events = list(source.stream())
    assert len(events) == max_events

    # Verify monotonic sequencing and timestamps
    for i, event in enumerate(events):
        assert event.seq == i + 1
        if i > 0:
            assert event.ts_ns > events[i - 1].ts_ns

    # Source should now return None
    assert source.next_event() is None


def test_source_strict_determinism() -> None:
    """Invariant: Same seed produces byte-identical serialized event streams."""
    seed = 42
    source_a = DeterministicSequenceSource(seed=seed, max_events=50)
    source_b = DeterministicSequenceSource(seed=seed, max_events=50)

    events_a = [e.to_json() for e in source_a.stream()]
    events_b = [e.to_json() for e in source_b.stream()]

    assert len(events_a) == 50
    assert events_a == events_b


def test_source_reset() -> None:
    """Verify calling reset() regenerates the identical event stream."""
    seed = 777
    source = DeterministicSequenceSource(seed=seed, max_events=30)

    run_1 = [e.to_json() for e in source.stream()]
    source.reset(seed)
    run_2 = [e.to_json() for e in source.stream()]

    assert run_1 == run_2


def test_different_seeds_produce_divergent_streams() -> None:
    """Verify distinct seeds generate distinct events."""
    source_1 = DeterministicSequenceSource(seed=1, max_events=20)
    source_2 = DeterministicSequenceSource(seed=2, max_events=20)

    events_1 = [e.to_json() for e in source_1.stream()]
    events_2 = [e.to_json() for e in source_2.stream()]

    assert events_1 != events_2
