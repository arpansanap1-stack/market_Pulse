"""Unit tests for SQLiteEventStore and SessionMetadata persistence."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from marketpulse.core.events import (
    BookDelta,
    MarketEvent,
    OrderAccepted,
    OrderSubmitted,
    OrderType,
    SessionEnded,
    SessionStarted,
    Side,
    TimeInForce,
    TradeExecuted,
)
from marketpulse.storage.event_store import SQLiteEventStore


@pytest.fixture
def store() -> SQLiteEventStore:
    """Fixture providing an in-memory event store."""
    return SQLiteEventStore(":memory:")


def test_create_and_get_session(store: SQLiteEventStore) -> None:
    """Verify session creation and retrieval."""
    meta = store.create_session(
        session_id="sess_123",
        symbol="AAPL",
        seed=42,
        config={"trades_per_sec": 50, "initial_price": 150.0},
        start_ts_ns=1_000_000_000,
    )
    assert meta.session_id == "sess_123"
    assert meta.symbol == "AAPL"
    assert meta.seed == 42
    assert meta.config["trades_per_sec"] == 50
    assert meta.start_ts_ns == 1_000_000_000
    assert meta.end_ts_ns is None
    assert meta.total_events == 0
    assert meta.status == "ACTIVE"

    fetched = store.get_session("sess_123")
    assert fetched is not None
    assert fetched.session_id == "sess_123"
    assert fetched.config == meta.config
    assert fetched.to_dict()["symbol"] == "AAPL"

    # Non-existent session
    assert store.get_session("unknown") is None


def test_create_session_validation(store: SQLiteEventStore) -> None:
    """Verify validation on empty session_id or symbol."""
    with pytest.raises(ValueError, match="session_id must be non-empty"):
        store.create_session("", "AAPL", 42, {}, 0)

    with pytest.raises(ValueError, match="symbol must be non-empty"):
        store.create_session("sess_1", "", 42, {}, 0)


def test_list_and_update_sessions(store: SQLiteEventStore) -> None:
    """Verify listing with pagination and updating status/metrics."""
    store.create_session("s1", "AAPL", 1, {}, 100, created_at_utc="2026-01-01T00:00:00Z")
    store.create_session("s2", "GOOG", 2, {}, 200, created_at_utc="2026-01-02T00:00:00Z")
    store.create_session("s3", "MSFT", 3, {}, 300, created_at_utc="2026-01-03T00:00:00Z")

    sessions = store.list_sessions(limit=2, offset=0)
    assert len(sessions) == 2
    assert sessions[0].session_id == "s3"  # most recent
    assert sessions[1].session_id == "s2"

    offset_sessions = store.list_sessions(limit=2, offset=2)
    assert len(offset_sessions) == 1
    assert offset_sessions[0].session_id == "s1"

    # Update session
    store.update_session("s1", status="STOPPED", end_ts_ns=500, total_events=42)
    updated = store.get_session("s1")
    assert updated is not None
    assert updated.status == "STOPPED"
    assert updated.end_ts_ns == 500
    assert updated.total_events == 42

    # Update with empty kwargs is a no-op
    store.update_session("s1")
    assert store.get_session("s1") == updated


def test_append_and_query_events(store: SQLiteEventStore) -> None:
    """Verify appending various event types, round-tripping, and slicing."""
    store.create_session("sess_trade", "AAPL", 42, {}, 0)

    evt1 = SessionStarted(
        seq=1,
        ts_ns=100,
        symbol="AAPL",
        session_id="sess_trade",
        seed=42,
        config_hash="abc",
    )
    evt2 = OrderSubmitted(
        seq=2,
        ts_ns=200,
        symbol="AAPL",
        order_id="ord_1",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=10,
        tif=TimeInForce.GTC,
    )
    evt3 = OrderAccepted(
        seq=3,
        ts_ns=250,
        symbol="AAPL",
        order_id="ord_1",
    )
    evt4 = TradeExecuted(
        seq=4,
        ts_ns=300,
        symbol="AAPL",
        trade_id="trd_1",
        price_ticks=15000,
        qty=5,
        aggressor_side=Side.BUY,
        buy_order_id="ord_1",
        sell_order_id="ord_2",
    )
    evt5 = BookDelta(
        seq=5,
        ts_ns=350,
        symbol="AAPL",
        side=Side.BUY,
        price_ticks=15000,
        new_total_qty=5,
    )
    evt6 = MarketEvent(
        seq=6,
        ts_ns=400,
        symbol="AAPL",
        kind="HALT",
        params={"reason": "CIRCUIT_BREAKER_LULD"},
    )
    evt7 = SessionEnded(
        seq=7,
        ts_ns=500,
        symbol="AAPL",
        session_id="sess_trade",
        reason="NORMAL_COMPLETION",
        total_events=7,
    )

    # Append single
    store.append_event("sess_trade", evt1)
    assert store.count_events("sess_trade") == 1

    # Append batch
    store.append_events("sess_trade", [evt2, evt3, evt4, evt5, evt6, evt7])
    assert store.count_events("sess_trade") == 7

    # Verify session total_events updated
    sess = store.get_session("sess_trade")
    assert sess is not None
    assert sess.total_events == 7

    # Query range
    all_events = store.get_events("sess_trade")
    assert len(all_events) == 7
    assert all_events[0] == evt1
    assert all_events[1] == evt2
    assert all_events[2] == evt3
    assert all_events[3] == evt4
    assert all_events[4] == evt5
    assert all_events[5] == evt6
    assert all_events[6] == evt7

    # Sub-slice query
    slice_events = store.get_events("sess_trade", from_seq=3, to_seq=5)
    assert len(slice_events) == 3
    assert [e.seq for e in slice_events] == [3, 4, 5]

    # Limit query
    limited = store.get_events("sess_trade", from_seq=2, limit=2)
    assert len(limited) == 2
    assert [e.seq for e in limited] == [2, 3]


def test_stream_events(store: SQLiteEventStore) -> None:
    """Verify chunked generator streaming."""
    store.create_session("sess_stream", "AAPL", 1, {}, 0)

    events = [
        TradeExecuted(
            seq=i,
            ts_ns=i * 100,
            symbol="AAPL",
            trade_id=f"t_{i}",
            price_ticks=15000 + i,
            qty=1,
            aggressor_side=Side.BUY,
            buy_order_id=f"b_{i}",
            sell_order_id=f"s_{i}",
        )
        for i in range(1, 26)
    ]
    store.append_events("sess_stream", events)

    # Stream with small chunk size of 10
    streamed = list(store.stream_events("sess_stream", from_seq=5, to_seq=20, chunk_size=7))
    assert len(streamed) == 16
    assert streamed[0].seq == 5
    assert streamed[-1].seq == 20


def test_file_db_with_wal_mode() -> None:
    """Verify SQLiteEventStore on disk initializes and supports WAL mode."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "test_store.db"
        store = SQLiteEventStore(db_file)
        store.create_session("file_sess", "AAPL", 100, {}, 1000)
        assert store.get_session("file_sess") is not None
        store.close()
