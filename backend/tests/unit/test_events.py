"""Unit and property-based tests for Event schema, validation, and serialization."""

from dataclasses import FrozenInstanceError

import pytest
from hypothesis import given
from hypothesis import strategies as st

from marketpulse.core.events import (
    BookDelta,
    EventType,
    MarketEvent,
    OrderAccepted,
    OrderCanceled,
    OrderRejected,
    OrderSubmitted,
    OrderType,
    SessionEnded,
    SessionStarted,
    Side,
    TimeInForce,
    TradeExecuted,
    event_from_dict,
    event_from_json,
    price_to_ticks,
    ticks_to_price,
)


def test_order_submitted_validation() -> None:
    """Verify validation constraints on OrderSubmitted."""
    # Valid order
    order = OrderSubmitted(
        seq=1,
        ts_ns=100,
        symbol="AAPL",
        order_id="o1",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=10,
        tif=TimeInForce.GTC,
    )
    assert order.seq == 1
    assert order.event_type == EventType.ORDER_SUBMITTED

    # Mutability test (must be frozen)
    with pytest.raises(FrozenInstanceError):
        order.qty = 20  # type: ignore[misc]

    # Invalid sequence
    with pytest.raises(ValueError, match="seq must be >= 1"):
        OrderSubmitted(
            seq=0,
            ts_ns=100,
            symbol="AAPL",
            order_id="o1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=10,
        )

    # Invalid quantity
    with pytest.raises(ValueError, match="qty must be positive"):
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="o1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=0,
        )

    # Missing price on limit order
    with pytest.raises(ValueError, match="LIMIT order requires price_ticks > 0"):
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="o1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=None,
            qty=10,
        )


def test_trade_executed_validation() -> None:
    """Verify TradeExecuted constraints."""
    trade = TradeExecuted(
        seq=2,
        ts_ns=200,
        symbol="AAPL",
        trade_id="t1",
        price_ticks=15025,
        qty=50,
        aggressor_side=Side.BUY,
        buy_order_id="b1",
        sell_order_id="s1",
    )
    assert trade.price_ticks == 15025

    with pytest.raises(ValueError, match="price_ticks must be positive"):
        TradeExecuted(
            seq=2,
            ts_ns=200,
            symbol="AAPL",
            trade_id="t1",
            price_ticks=0,
            qty=50,
            aggressor_side=Side.BUY,
            buy_order_id="b1",
            sell_order_id="s1",
        )


def test_book_delta_validation() -> None:
    """Verify BookDelta constraints."""
    delta = BookDelta(
        seq=3,
        ts_ns=300,
        symbol="AAPL",
        side=Side.SELL,
        price_ticks=15030,
        new_total_qty=0,  # 0 is valid for level deletion
    )
    assert delta.new_total_qty == 0

    with pytest.raises(ValueError, match="new_total_qty must be >= 0"):
        BookDelta(
            seq=3,
            ts_ns=300,
            symbol="AAPL",
            side=Side.SELL,
            price_ticks=15030,
            new_total_qty=-1,
        )


def test_session_lifecycle_events() -> None:
    """Verify SessionStarted and SessionEnded events."""
    started = SessionStarted(
        seq=1,
        ts_ns=0,
        symbol="SYSTEM",
        session_id="sim_100",
        seed=42,
        config_hash="abc",
        symbols=("AAPL", "MSFT"),
    )
    assert started.seed == 42
    assert started.symbols == ("AAPL", "MSFT")

    ended = SessionEnded(
        seq=2,
        ts_ns=1000,
        symbol="SYSTEM",
        session_id="sim_100",
        reason="COMPLETED",
        total_events=100,
    )
    assert ended.reason == "COMPLETED"


def test_market_event() -> None:
    """Verify MarketEvent payload and roundtrip."""
    evt = MarketEvent(
        seq=10,
        ts_ns=5000,
        symbol="AAPL",
        kind="VOLATILITY_REGIME",
        params={"multiplier": 2.0},
    )
    d = evt.to_dict()
    assert d["kind"] == "VOLATILITY_REGIME"
    assert d["params"]["multiplier"] == 2.0
    deserialized = event_from_dict(d)
    assert deserialized == evt


def test_tick_conversions() -> None:
    """Verify price and tick conversion helpers."""
    tick_size = 0.01
    assert ticks_to_price(15025, tick_size) == 150.25
    assert price_to_ticks(150.25, tick_size) == 15025

    tick_size_crypto = 0.50
    assert ticks_to_price(100, tick_size_crypto) == 50.0
    assert price_to_ticks(50.0, tick_size_crypto) == 100


# Hypothesis strategies for property-based roundtrip testing
st_seq = st.integers(min_value=1, max_value=10_000_000)
st_ts = st.integers(min_value=0, max_value=1_000_000_000_000)
st_sym = st.sampled_from(["AAPL", "MSFT", "GOOG", "TSLA", "BTCUSDT"])
st_order_id = st.text(
    alphabet=st.characters(whitelist_categories=["Lu", "Ll", "Nd"]), min_size=1, max_size=16
)


@st.composite
def strategy_order_submitted(draw: st.DrawFn) -> OrderSubmitted:
    order_type = draw(st.sampled_from(list(OrderType)))
    is_limit = order_type in (
        OrderType.LIMIT,
        OrderType.STOP_LIMIT,
        OrderType.TAKE_PROFIT_LIMIT,
    )
    price_ticks = draw(st.integers(min_value=1, max_value=500_000)) if is_limit else None
    stop_types = (
        OrderType.STOP_LOSS,
        OrderType.STOP_LIMIT,
        OrderType.TAKE_PROFIT,
        OrderType.TAKE_PROFIT_LIMIT,
    )
    stop_price_ticks = (
        draw(st.integers(min_value=1, max_value=500_000)) if order_type in stop_types else None
    )
    trail_offset_ticks = (
        draw(st.integers(min_value=1, max_value=50_000))
        if order_type == OrderType.TRAILING_STOP
        else None
    )
    return OrderSubmitted(
        seq=draw(st_seq),
        ts_ns=draw(st_ts),
        symbol=draw(st_sym),
        order_id=draw(st_order_id),
        side=draw(st.sampled_from(list(Side))),
        order_type=order_type,
        price_ticks=price_ticks,
        qty=draw(st.integers(min_value=1, max_value=10_000)),
        tif=draw(st.sampled_from(list(TimeInForce))),
        stop_price_ticks=stop_price_ticks,
        trail_offset_ticks=trail_offset_ticks,
    )


@st.composite
def strategy_trade_executed(draw: st.DrawFn) -> TradeExecuted:
    return TradeExecuted(
        seq=draw(st_seq),
        ts_ns=draw(st_ts),
        symbol=draw(st_sym),
        trade_id=draw(st_order_id),
        price_ticks=draw(st.integers(min_value=1, max_value=500_000)),
        qty=draw(st.integers(min_value=1, max_value=10_000)),
        aggressor_side=draw(st.sampled_from(list(Side))),
        buy_order_id=draw(st_order_id),
        sell_order_id=draw(st_order_id),
    )


@st.composite
def strategy_book_delta(draw: st.DrawFn) -> BookDelta:
    return BookDelta(
        seq=draw(st_seq),
        ts_ns=draw(st_ts),
        symbol=draw(st_sym),
        side=draw(st.sampled_from(list(Side))),
        price_ticks=draw(st.integers(min_value=1, max_value=500_000)),
        new_total_qty=draw(st.integers(min_value=0, max_value=50_000)),
    )


@given(strategy_order_submitted())
def test_hypothesis_order_submitted_roundtrip(event: OrderSubmitted) -> None:
    """Property test: OrderSubmitted roundtrip serialization via JSON."""
    json_str = event.to_json()
    reconstructed = event_from_json(json_str)
    assert reconstructed == event


@given(strategy_trade_executed())
def test_hypothesis_trade_executed_roundtrip(event: TradeExecuted) -> None:
    """Property test: TradeExecuted roundtrip serialization via JSON."""
    json_str = event.to_json()
    reconstructed = event_from_json(json_str)
    assert reconstructed == event


@given(strategy_book_delta())
def test_hypothesis_book_delta_roundtrip(event: BookDelta) -> None:
    """Property test: BookDelta roundtrip serialization via JSON."""
    json_str = event.to_json()
    reconstructed = event_from_json(json_str)
    assert reconstructed == event


def test_side_opposite() -> None:
    """Verify Side.opposite() flips BUY and SELL."""
    assert Side.BUY.opposite() == Side.SELL
    assert Side.SELL.opposite() == Side.BUY


def test_order_lifecycle_events() -> None:
    """Verify OrderAccepted, OrderRejected, and OrderCanceled creation and validation."""
    accepted = OrderAccepted(seq=5, ts_ns=500, symbol="AAPL", order_id="ord_1")
    assert accepted.order_id == "ord_1"
    assert event_from_json(accepted.to_json()) == accepted

    with pytest.raises(ValueError, match="order_id must be non-empty"):
        OrderAccepted(seq=5, ts_ns=500, symbol="AAPL", order_id="")

    rejected = OrderRejected(seq=6, ts_ns=600, symbol="AAPL", order_id="ord_2", reason="DUPLICATE")
    assert rejected.reason == "DUPLICATE"
    assert event_from_json(rejected.to_json()) == rejected

    with pytest.raises(ValueError, match="reason must be non-empty"):
        OrderRejected(seq=6, ts_ns=600, symbol="AAPL", order_id="ord_2", reason="")

    canceled = OrderCanceled(seq=7, ts_ns=700, symbol="AAPL", order_id="ord_1")
    assert canceled.reason == "USER_REQUESTED"
    assert event_from_json(canceled.to_json()) == canceled


def test_event_base_validation() -> None:
    """Verify base event constraints: ts_ns, symbol, schema_version."""
    with pytest.raises(ValueError, match="ts_ns must be >= 0"):
        OrderAccepted(seq=1, ts_ns=-1, symbol="AAPL", order_id="o1")

    with pytest.raises(ValueError, match="symbol must be a non-empty string"):
        OrderAccepted(seq=1, ts_ns=0, symbol="", order_id="o1")

    with pytest.raises(ValueError, match="Unsupported schema_version"):
        OrderAccepted(seq=1, ts_ns=0, symbol="AAPL", schema_version=2, order_id="o1")


def test_market_order_validation() -> None:
    """Verify Market order validation constraints."""
    mo = OrderSubmitted(
        seq=1,
        ts_ns=0,
        symbol="AAPL",
        order_id="m1",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        price_ticks=None,
        qty=100,
    )
    assert mo.price_ticks is None

    mo_zero = OrderSubmitted(
        seq=2,
        ts_ns=0,
        symbol="AAPL",
        order_id="m2",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        price_ticks=0,
        qty=100,
    )
    assert mo_zero.price_ticks == 0

    with pytest.raises(ValueError, match="MARKET order price_ticks must be None or 0"):
        OrderSubmitted(
            seq=3,
            ts_ns=0,
            symbol="AAPL",
            order_id="m3",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            price_ticks=100,
            qty=100,
        )


def test_event_deserialization_error_handling() -> None:
    """Verify deserialization handles malformed inputs gracefully."""
    with pytest.raises(ValueError, match="Missing 'type' in event payload"):
        event_from_dict({"seq": 1, "ts_ns": 0, "symbol": "AAPL"})

    with pytest.raises(ValueError, match="Unknown event type"):
        event_from_dict({"type": "INVALID_TYPE", "seq": 1, "ts_ns": 0, "symbol": "AAPL"})

    with pytest.raises(ValueError, match="Expected JSON object"):
        event_from_json('["not", "a", "dict"]')


def test_order_triggered_event() -> None:
    """Verify OrderTriggered roundtrip serialization and validation."""
    from marketpulse.core.events import OrderTriggered

    trig = OrderTriggered(
        seq=10,
        ts_ns=1_000_000_000,
        symbol="AAPL",
        parent_order_id="stop_123",
        triggered_order_id="stop_123",
        order_type=OrderType.STOP_LOSS,
        trigger_price_ticks=14500,
        execution_type=OrderType.MARKET,
    )
    d = trig.to_dict()
    assert d["type"] == "ORDER_TRIGGERED"
    assert d["parent_order_id"] == "stop_123"
    assert d["trigger_price_ticks"] == 14500
    assert d["execution_type"] == "MARKET"

    # JSON roundtrip
    restored = event_from_json(trig.to_json())
    assert isinstance(restored, OrderTriggered)
    assert restored.parent_order_id == trig.parent_order_id
    assert restored.trigger_price_ticks == 14500
    assert restored.execution_type == OrderType.MARKET

    # Validation errors
    with pytest.raises(ValueError, match="parent_order_id must be non-empty"):
        OrderTriggered(
            seq=11,
            ts_ns=0,
            symbol="AAPL",
            parent_order_id="",
            triggered_order_id="stop_123",
            order_type=OrderType.STOP_LOSS,
            trigger_price_ticks=14500,
            execution_type=OrderType.MARKET,
        )

    with pytest.raises(ValueError, match="trigger_price_ticks must be positive"):
        OrderTriggered(
            seq=12,
            ts_ns=0,
            symbol="AAPL",
            parent_order_id="p1",
            triggered_order_id="stop_123",
            order_type=OrderType.STOP_LOSS,
            trigger_price_ticks=-10,
            execution_type=OrderType.MARKET,
        )
