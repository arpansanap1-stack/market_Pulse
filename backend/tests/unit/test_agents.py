"""Unit tests for simulated trading agents and AgentOrderSource."""

from __future__ import annotations

from marketpulse.core.events import (
    BookDelta,
    OrderAccepted,
    OrderSubmitted,
    OrderType,
    Side,
    TradeExecuted,
)
from marketpulse.sim.agent_source import AgentOrderSource
from marketpulse.sim.agents import (
    MarketMakerAgent,
    NoiseTraderAgent,
    TrendFollowerAgent,
)
from marketpulse.sim.source import create_rng


def test_market_maker_agent() -> None:
    """Market maker produces balanced two-sided limit orders around reference price."""
    rng = create_rng(42)
    mm = MarketMakerAgent("mm1", rng=rng, half_spread_ticks=2, levels=3, qty_per_level=50)

    orders = mm.generate_orders(
        symbol="AAPL",
        best_bid=14998,
        best_ask=15002,
        ref_price_ticks=15000,
        seq_start=1,
        ts_ns=1_000_000,
    )

    # 3 bid levels + 3 ask levels = 6 orders
    assert len(orders) == 6
    bids = [o for o in orders if o.side == Side.BUY]
    asks = [o for o in orders if o.side == Side.SELL]
    assert len(bids) == 3
    assert len(asks) == 3

    for o in orders:
        assert o.symbol == "AAPL"
        assert o.order_type == OrderType.LIMIT
        assert o.qty > 0
        assert o.price_ticks is not None and o.price_ticks > 0

    # Best bid should be strictly less than best ask
    bid_prices = [b.price_ticks for b in bids if b.price_ticks is not None]
    ask_prices = [a.price_ticks for a in asks if a.price_ticks is not None]
    assert max(bid_prices) < min(ask_prices)


def test_noise_trader_agent() -> None:
    """Noise trader produces both limit and market orders."""
    rng = create_rng(123)
    noise = NoiseTraderAgent("noise1", rng=rng, market_order_prob=0.5)

    orders: list[OrderSubmitted] = []
    for i in range(50):
        o = noise.generate_orders(
            symbol="AAPL",
            best_bid=14995,
            best_ask=15005,
            ref_price_ticks=15000,
            seq_start=i + 1,
            ts_ns=(i + 1) * 1000,
        )
        orders.extend(o)

    assert len(orders) == 50
    types = {o.order_type for o in orders}
    sides = {o.side for o in orders}

    assert OrderType.LIMIT in types
    assert OrderType.MARKET in types
    assert Side.BUY in sides
    assert Side.SELL in sides


def test_trend_follower_agent() -> None:
    """Trend follower stays quiet on flat prices and emits directional orders on trends."""
    rng = create_rng(999)
    trend = TrendFollowerAgent("trend1", rng=rng, lookback=5, threshold_ticks=3)

    # Flat market -> no orders
    for i in range(10):
        orders = trend.generate_orders(
            symbol="AAPL",
            best_bid=14999,
            best_ask=15001,
            ref_price_ticks=15000,
            seq_start=i + 1,
            ts_ns=i * 1000,
        )
        assert orders == []

    # Upward shock -> emits BUY order
    orders_shock = trend.generate_orders(
        symbol="AAPL",
        best_bid=15010,
        best_ask=15012,
        ref_price_ticks=15011,
        seq_start=100,
        ts_ns=100_000,
    )
    assert len(orders_shock) == 1
    assert orders_shock[0].side == Side.BUY


def test_agent_order_source_event_stream() -> None:
    """AgentOrderSource produces a valid sequence of accepted orders, trades, and deltas."""
    source = AgentOrderSource(
        seed=42,
        symbol="AAPL",
        initial_price=150.0,
        max_events=200,
    )

    events = list(source.stream())
    assert len(events) == 200

    # Monotonic seq and non-decreasing ts_ns
    for i in range(1, len(events)):
        assert events[i].seq == events[i - 1].seq + 1
        assert events[i].ts_ns >= events[i - 1].ts_ns

    # Check event types present
    has_accepted = any(isinstance(e, OrderAccepted) for e in events)
    has_trades = any(isinstance(e, TradeExecuted) for e in events)
    has_deltas = any(isinstance(e, BookDelta) for e in events)

    assert has_accepted
    assert has_trades
    assert has_deltas

    # Check order book snapshot
    snapshot = source.book_snapshot(max_levels=5)
    assert snapshot["symbol"] == "AAPL"
    assert len(snapshot["bids"]) > 0
    assert len(snapshot["asks"]) > 0
    assert snapshot["best_bid"] is not None
    assert snapshot["best_ask"] is not None
    assert snapshot["best_bid"] <= snapshot["best_ask"]


def test_agent_order_source_determinism() -> None:
    """Identical seeds yield byte-identical emitted event logs."""
    source1 = AgentOrderSource(seed=777, symbol="AAPL", max_events=150)
    source2 = AgentOrderSource(seed=777, symbol="AAPL", max_events=150)

    events1 = [e.to_json() for e in source1.stream()]
    events2 = [e.to_json() for e in source2.stream()]

    assert events1 == events2

    # Reset test
    source1.reset(seed=777)
    reset_events = [e.to_json() for e in source1.stream()]
    assert reset_events == events1
