"""Unit tests for ReplayEventSource and historical pacing/seeking."""

from __future__ import annotations

import pytest

from marketpulse.core.events import Side, TradeExecuted
from marketpulse.sim.replay_source import ReplayEventSource
from marketpulse.sim.source import EventSource
from marketpulse.storage.event_store import SQLiteEventStore


@pytest.fixture
def populated_store() -> tuple[SQLiteEventStore, str, list[TradeExecuted]]:
    """Fixture providing a SQLiteEventStore populated with a 20-event session."""
    store = SQLiteEventStore(":memory:")
    session_id = "test_replay_sess"
    store.create_session(
        session_id=session_id,
        symbol="AAPL",
        seed=42,
        config={"trades_per_sec": 50},
        start_ts_ns=1_000_000_000,
    )

    events: list[TradeExecuted] = []
    for i in range(1, 21):
        evt = TradeExecuted(
            seq=i,
            ts_ns=1_000_000_000 + i * 20_000_000,  # 20ms apart
            symbol="AAPL",
            trade_id=f"t_{i}",
            price_ticks=15000 + i,
            qty=10,
            aggressor_side=Side.BUY if i % 2 == 0 else Side.SELL,
            buy_order_id=f"b_{i}",
            sell_order_id=f"s_{i}",
        )
        events.append(evt)

    store.append_events(session_id, events)
    return store, session_id, events


def test_replay_source_protocol_and_properties(
    populated_store: tuple[SQLiteEventStore, str, list[TradeExecuted]],
) -> None:
    """Verify EventSource protocol compliance and initial properties."""
    store, session_id, events = populated_store
    source = ReplayEventSource(store, session_id, speed_multiplier=2.0)

    assert isinstance(source, EventSource)
    assert source.session_id == session_id
    assert source.current_seq == 1
    assert source.total_events == len(events)
    assert source.speed_multiplier == 2.0
    assert not source.is_paused
    assert source.has_next()


def test_sequential_playback(
    populated_store: tuple[SQLiteEventStore, str, list[TradeExecuted]],
) -> None:
    """Verify event-by-event playback matches original recorded events exactly."""
    store, session_id, events = populated_store
    source = ReplayEventSource(store, session_id, speed_multiplier=1.0)

    replayed: list[TradeExecuted] = []
    while source.has_next():
        evt = source.next_event()
        if evt is not None:
            assert isinstance(evt, TradeExecuted)
            replayed.append(evt)

    assert len(replayed) == len(events)
    assert replayed == events
    assert source.current_seq == 21
    assert not source.has_next()
    assert source.next_event() is None


def test_seeking_and_reset(
    populated_store: tuple[SQLiteEventStore, str, list[TradeExecuted]],
) -> None:
    """Verify seeking to arbitrary sequence positions and reset."""
    store, session_id, events = populated_store
    source = ReplayEventSource(store, session_id, chunk_size=5)

    # Seek forward to sequence 10
    source.seek(10)
    assert source.current_seq == 10
    evt10 = source.next_event()
    assert evt10 is not None
    assert evt10.seq == 10
    assert evt10 == events[9]

    # Seek backward to sequence 3
    source.seek(3)
    assert source.current_seq == 3
    evt3 = source.next_event()
    assert evt3 is not None
    assert evt3.seq == 3

    # Reset returns to sequence 1
    source.reset()
    assert source.current_seq == 1
    evt1 = source.next_event()
    assert evt1 is not None
    assert evt1.seq == 1

    # Clamping tests: 0 or negative clamps to 1
    source.seek(0)
    assert source.current_seq == 1
    source.seek(-5)
    assert source.current_seq == 1


def test_pause_and_resume(
    populated_store: tuple[SQLiteEventStore, str, list[TradeExecuted]],
) -> None:
    """Verify pause suppresses next_event and resume restores stream."""
    store, session_id, _ = populated_store
    source = ReplayEventSource(store, session_id)

    evt1 = source.next_event()
    assert evt1 is not None and evt1.seq == 1

    source.pause()
    assert source.is_paused
    assert source.next_event() is None

    source.resume()
    assert not source.is_paused
    evt2 = source.next_event()
    assert evt2 is not None and evt2.seq == 2


def test_speed_multiplier_and_delay_calculation(
    populated_store: tuple[SQLiteEventStore, str, list[TradeExecuted]],
) -> None:
    """Verify speed scaling and delay calculations."""
    store, session_id, _ = populated_store
    source = ReplayEventSource(store, session_id, speed_multiplier=1.0)

    # Rejects invalid speed
    with pytest.raises(ValueError, match="speed_multiplier must be > 0"):
        source.set_speed(0)
    with pytest.raises(ValueError, match="speed_multiplier must be > 0"):
        source.set_speed(-1.5)

    # 1.0x speed delay for 100ms (100_000_000 ns)
    delay_1x = source.calculate_delay_s(1_000_000_000, 1_100_000_000)
    assert pytest.approx(delay_1x, 1e-6) == 0.100

    # 2.0x speed delay
    source.set_speed(2.0)
    delay_2x = source.calculate_delay_s(1_000_000_000, 1_100_000_000)
    assert pytest.approx(delay_2x, 1e-6) == 0.050

    # Non-increasing or None timestamp
    assert source.calculate_delay_s(None, 1_000_000_000) == 0.0
    assert source.calculate_delay_s(1_200_000_000, 1_100_000_000) == 0.0

    # Extreme speed mode (MAX mode, >= 1000x)
    source.set_speed(1000.0)
    assert source.calculate_delay_s(1_000_000_000, 2_000_000_000) == 0.0

    # Ceiling capping
    source.set_speed(1.0)
    capped_delay = source.calculate_delay_s(1_000_000_000, 10_000_000_000, max_delay_s=1.5)
    assert capped_delay == 1.5


def test_stream_generator(
    populated_store: tuple[SQLiteEventStore, str, list[TradeExecuted]],
) -> None:
    """Verify stream() generator produces all events."""
    store, session_id, events = populated_store
    source = ReplayEventSource(store, session_id)

    streamed = list(source.stream())
    assert streamed == events
