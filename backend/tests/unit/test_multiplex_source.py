"""Unit tests for MultiplexedAgentSource multi-symbol simulation."""

from __future__ import annotations

import pytest

from marketpulse.core.clock import SimulatedClock
from marketpulse.sim.multiplex_source import MultiplexedAgentSource
from marketpulse.sim.source import EventSource


def test_multiplex_source_conformance_and_properties() -> None:
    """Verify MultiplexedAgentSource implements the EventSource protocol."""
    symbols = ("AAPL", "MSFT", "GOOGL")
    clock = SimulatedClock(0)
    source = MultiplexedAgentSource(
        seed=42,
        symbols=symbols,
        clock=clock,
    )
    assert isinstance(source, EventSource)
    for sym in symbols:
        src = source.get_source(sym)
        assert src._symbol == sym
        eng = source.get_engine(sym)
        assert eng.symbol == sym

    with pytest.raises(KeyError):
        source.get_source("UNKNOWN")
    with pytest.raises(KeyError):
        source.get_engine("UNKNOWN")


def test_multiplex_source_monotonicity_and_interleaving() -> None:
    """Verify multi-symbol events are emitted in non-decreasing chronological order."""
    symbols = ("AAPL", "MSFT")
    source = MultiplexedAgentSource(
        seed=123,
        symbols=symbols,
        max_events=100,
    )

    events = list(source.stream())
    assert len(events) == 100

    # Ensure monotonic timestamps
    for i in range(1, len(events)):
        assert events[i].ts_ns >= events[i - 1].ts_ns

    # Ensure multiple symbols are present in the stream
    emitted_symbols = {getattr(e, "symbol", None) for e in events}
    assert "AAPL" in emitted_symbols
    assert "MSFT" in emitted_symbols


def test_multiplex_source_determinism() -> None:
    """Verify identical seeds produce byte-identical event sequences."""
    symbols = ("AAPL", "MSFT", "NVDA")
    src1 = MultiplexedAgentSource(seed=999, symbols=symbols, max_events=50)
    src2 = MultiplexedAgentSource(seed=999, symbols=symbols, max_events=50)

    evts1 = list(src1.stream())
    evts2 = list(src2.stream())

    assert len(evts1) == len(evts2) == 50
    for e1, e2 in zip(evts1, evts2, strict=True):
        assert type(e1) is type(e2)
        assert e1.seq == e2.seq
        assert e1.ts_ns == e2.ts_ns
        assert getattr(e1, "symbol", None) == getattr(e2, "symbol", None)


def test_multiplex_source_reset() -> None:
    """Verify reset reproduces the deterministic stream."""
    symbols = ("AAPL", "GOOGL")
    source = MultiplexedAgentSource(seed=777, symbols=symbols, max_events=30)
    first_run = list(source.stream())

    source.reset(777)
    second_run = list(source.stream())

    assert len(first_run) == len(second_run) == 30
    for e1, e2 in zip(first_run, second_run, strict=True):
        assert e1.ts_ns == e2.ts_ns
        assert getattr(e1, "symbol", None) == getattr(e2, "symbol", None)
