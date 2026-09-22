"""Unit tests for OrderBook and MatchingEngine.

Validates price-time priority, Limit/Market orders, GTC/IOC/FOK TIF,
BookDelta emissions, cancellation, determinism, and execution speed.
"""

from __future__ import annotations

import time

from marketpulse.core.events import (
    BookDelta,
    OrderAccepted,
    OrderCanceled,
    OrderRejected,
    OrderSubmitted,
    OrderType,
    Side,
    STPPolicy,
    TimeInForce,
    TradeExecuted,
)
from marketpulse.core.orderbook import MatchingEngine, OrderBook


def test_empty_book() -> None:
    """Validate empty order book state."""
    book = OrderBook("AAPL")
    assert book.best_bid() is None
    assert book.best_ask() is None
    assert book.spread() is None
    assert book.mid_price_ticks() is None
    snapshot = book.depth_snapshot(10)
    assert snapshot["symbol"] == "AAPL"
    assert snapshot["bids"] == []
    assert snapshot["asks"] == []


def test_single_limit_order_resting() -> None:
    """A non-crossing limit order rests in the book and emits BookDelta."""
    engine = MatchingEngine("AAPL", initial_seq=1)
    order = OrderSubmitted(
        seq=1,
        ts_ns=1_000_000,
        symbol="AAPL",
        order_id="buy_1",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=100,
        tif=TimeInForce.GTC,
    )
    events = engine.submit_order(order)
    assert len(events) == 2
    assert isinstance(events[0], OrderAccepted)
    assert events[0].order_id == "buy_1"
    assert isinstance(events[1], BookDelta)
    assert events[1].side == Side.BUY
    assert events[1].price_ticks == 15000
    assert events[1].new_total_qty == 100

    assert engine.book.best_bid() == 15000
    assert engine.book.best_ask() is None
    assert engine.book.spread() is None


def test_crossing_orders_full_match() -> None:
    """Buy and sell at same price execute a full trade."""
    engine = MatchingEngine("AAPL", initial_seq=1)

    # 1. Passive sell order
    sell = OrderSubmitted(
        seq=1,
        ts_ns=1_000_000,
        symbol="AAPL",
        order_id="sell_1",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=50,
        tif=TimeInForce.GTC,
    )
    events1 = engine.submit_order(sell)
    assert len(events1) == 2

    # 2. Aggressive buy order
    buy = OrderSubmitted(
        seq=2,
        ts_ns=2_000_000,
        symbol="AAPL",
        order_id="buy_1",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=50,
        tif=TimeInForce.GTC,
    )
    events2 = engine.submit_order(buy)

    # Expected: OrderAccepted, TradeExecuted, BookDelta (ask level cleared to 0)
    assert len(events2) == 3
    assert isinstance(events2[0], OrderAccepted)
    assert isinstance(events2[1], TradeExecuted)
    trade = events2[1]
    assert trade.price_ticks == 15000
    assert trade.qty == 50
    assert trade.aggressor_side == Side.BUY
    assert trade.buy_order_id == "buy_1"
    assert trade.sell_order_id == "sell_1"

    assert isinstance(events2[2], BookDelta)
    assert events2[2].side == Side.SELL
    assert events2[2].price_ticks == 15000
    assert events2[2].new_total_qty == 0

    assert engine.book.best_bid() is None
    assert engine.book.best_ask() is None


def test_partial_fill_and_resting_remainder() -> None:
    """Incoming buy for 100 matches resting sell of 60, remainder 40 rests on bid side."""
    engine = MatchingEngine("AAPL")

    sell = OrderSubmitted(
        seq=1,
        ts_ns=1_000_000,
        symbol="AAPL",
        order_id="s1",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=60,
    )
    engine.submit_order(sell)

    buy = OrderSubmitted(
        seq=2,
        ts_ns=2_000_000,
        symbol="AAPL",
        order_id="b1",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=100,
    )
    events = engine.submit_order(buy)

    # OrderAccepted, TradeExecuted (60), BookDelta (ask 15000 -> 0), BookDelta (bid 15000 -> 40)
    assert len(events) == 4
    assert isinstance(events[0], OrderAccepted)
    assert isinstance(events[1], TradeExecuted)
    assert events[1].qty == 60
    assert isinstance(events[2], BookDelta)
    assert events[2].side == Side.SELL
    assert events[2].new_total_qty == 0
    assert isinstance(events[3], BookDelta)
    assert events[3].side == Side.BUY
    assert events[3].price_ticks == 15000
    assert events[3].new_total_qty == 40

    assert engine.book.best_bid() == 15000
    assert engine.book.best_ask() is None


def test_price_time_priority_fifo() -> None:
    """Two orders at same price: the earlier order is matched first."""
    engine = MatchingEngine("AAPL")

    # Order s1 arrives first
    engine.submit_order(
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="s1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=30,
        )
    )
    # Order s2 arrives second at same price
    engine.submit_order(
        OrderSubmitted(
            seq=2,
            ts_ns=200,
            symbol="AAPL",
            order_id="s2",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=40,
        )
    )

    # Aggressive buy for 50
    events = engine.submit_order(
        OrderSubmitted(
            seq=3,
            ts_ns=300,
            symbol="AAPL",
            order_id="b1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=50,
        )
    )

    trades = [e for e in events if isinstance(e, TradeExecuted)]
    assert len(trades) == 2
    # First trade fills s1 completely (30)
    assert trades[0].sell_order_id == "s1"
    assert trades[0].qty == 30
    # Second trade fills s2 partially (20)
    assert trades[1].sell_order_id == "s2"
    assert trades[1].qty == 20

    # Remaining in s2 is 20
    resting_s2 = engine.book.get_order("s2")
    assert resting_s2 is not None
    assert resting_s2.remaining_qty == 20
    lvl = engine.book.asks.get_level(15000)
    assert lvl is not None
    assert lvl.total_qty == 20


def test_multi_level_sweep() -> None:
    """A large buy sweeps through multiple ask price levels."""
    engine = MatchingEngine("AAPL")

    engine.submit_order(
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="s1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=20,
        )
    )
    engine.submit_order(
        OrderSubmitted(
            seq=2,
            ts_ns=200,
            symbol="AAPL",
            order_id="s2",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15010,
            qty=30,
        )
    )
    engine.submit_order(
        OrderSubmitted(
            seq=3,
            ts_ns=300,
            symbol="AAPL",
            order_id="s3",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15020,
            qty=50,
        )
    )

    # Buy 70 at 15015 limit: sweeps 15000 (20) and 15010 (30), remaining 20 cannot match 15020
    events = engine.submit_order(
        OrderSubmitted(
            seq=4,
            ts_ns=400,
            symbol="AAPL",
            order_id="b1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15015,
            qty=70,
            tif=TimeInForce.GTC,
        )
    )

    trades = [e for e in events if isinstance(e, TradeExecuted)]
    assert len(trades) == 2
    assert trades[0].price_ticks == 15000
    assert trades[0].qty == 20
    assert trades[1].price_ticks == 15010
    assert trades[1].qty == 30

    # Remaining 20 rests at 15015
    assert engine.book.best_bid() == 15015
    assert engine.book.best_ask() == 15020
    assert engine.book.spread() == 5


def test_ioc_order() -> None:
    """IOC order fills what is available immediately and cancels the rest."""
    engine = MatchingEngine("AAPL")

    engine.submit_order(
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="s1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=30,
        )
    )

    # Buy 50 IOC at 15000
    events = engine.submit_order(
        OrderSubmitted(
            seq=2,
            ts_ns=200,
            symbol="AAPL",
            order_id="b1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=50,
            tif=TimeInForce.IOC,
        )
    )

    trades = [e for e in events if isinstance(e, TradeExecuted)]
    assert len(trades) == 1
    assert trades[0].qty == 30

    cancels = [e for e in events if isinstance(e, OrderCanceled)]
    assert len(cancels) == 1
    assert cancels[0].order_id == "b1"

    # Bid book has nothing resting
    assert engine.book.best_bid() is None


def test_fok_order() -> None:
    """FOK order rejects if total liquidity is insufficient; fills fully if sufficient."""
    engine = MatchingEngine("AAPL")

    engine.submit_order(
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="s1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=30,
        )
    )

    # 1. Buy 50 FOK when only 30 available -> rejected
    events1 = engine.submit_order(
        OrderSubmitted(
            seq=2,
            ts_ns=200,
            symbol="AAPL",
            order_id="b_fok_fail",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=50,
            tif=TimeInForce.FOK,
        )
    )
    assert len(events1) == 1
    assert isinstance(events1[0], OrderRejected)
    assert events1[0].reason == "FOK_NOT_FILLABLE"
    lvl1 = engine.book.asks.get_level(15000)
    assert lvl1 is not None
    assert lvl1.total_qty == 30

    # 2. Buy 25 FOK when 30 available -> executes fully
    events2 = engine.submit_order(
        OrderSubmitted(
            seq=3,
            ts_ns=300,
            symbol="AAPL",
            order_id="b_fok_ok",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=25,
            tif=TimeInForce.FOK,
        )
    )
    trades = [e for e in events2 if isinstance(e, TradeExecuted)]
    assert len(trades) == 1
    assert trades[0].qty == 25
    lvl2 = engine.book.asks.get_level(15000)
    assert lvl2 is not None
    assert lvl2.total_qty == 5


def test_market_order() -> None:
    """Market order executes against available liquidity; rejects on empty book."""
    engine = MatchingEngine("AAPL")

    # 1. Market order on empty book rejects
    events1 = engine.submit_order(
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="m_fail",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            price_ticks=None,
            qty=50,
        )
    )
    assert len(events1) == 1
    assert isinstance(events1[0], OrderRejected)
    assert events1[0].reason == "NO_LIQUIDITY"

    # 2. Add sell liquidity
    engine.submit_order(
        OrderSubmitted(
            seq=2,
            ts_ns=200,
            symbol="AAPL",
            order_id="s1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=40,
        )
    )

    # 3. Market order matches and remainder cancels
    events2 = engine.submit_order(
        OrderSubmitted(
            seq=3,
            ts_ns=300,
            symbol="AAPL",
            order_id="m_ok",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            price_ticks=None,
            qty=60,
        )
    )
    trades = [e for e in events2 if isinstance(e, TradeExecuted)]
    assert len(trades) == 1
    assert trades[0].qty == 40
    cancels = [e for e in events2 if isinstance(e, OrderCanceled)]
    assert len(cancels) == 1
    assert cancels[0].order_id == "m_ok"


def test_order_cancellation() -> None:
    """Resting order can be canceled, emitting OrderCanceled and BookDelta."""
    engine = MatchingEngine("AAPL")

    engine.submit_order(
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="s1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=40,
        )
    )
    assert engine.book.best_ask() == 15000

    # Cancel order
    events = engine.cancel_order("s1", ts_ns=200)
    assert len(events) == 2
    assert isinstance(events[0], OrderCanceled)
    assert events[0].order_id == "s1"
    assert isinstance(events[1], BookDelta)
    assert events[1].new_total_qty == 0
    assert engine.book.best_ask() is None

    # Cancel non-existent order
    events_not_found = engine.cancel_order("fake_id", ts_ns=300)
    assert len(events_not_found) == 1
    assert isinstance(events_not_found[0], OrderRejected)
    assert events_not_found[0].reason == "ORDER_NOT_FOUND"


def test_matching_engine_determinism() -> None:
    """Same input order stream through fresh engines yields byte-identical event logs."""

    def run_simulation(seed: int = 42) -> list[str]:
        engine = MatchingEngine("AAPL")
        events: list[str] = []
        for i in range(1, 201):
            side = Side.BUY if i % 2 == 0 else Side.SELL
            price = 15000 + (i % 10) * (1 if side == Side.SELL else -1)
            order = OrderSubmitted(
                seq=i,
                ts_ns=i * 1000,
                symbol="AAPL",
                order_id=f"ord_{i}",
                side=side,
                order_type=OrderType.LIMIT,
                price_ticks=price,
                qty=10 * ((i % 5) + 1),
            )
            out = engine.submit_order(order)
            events.extend(e.to_json() for e in out)
        return events

    run1 = run_simulation()
    run2 = run_simulation()
    assert run1 == run2
    assert len(run1) > 100


def test_matching_engine_performance() -> None:
    """Matching engine must process >= 5,000 orders per second in pure Python."""
    engine = MatchingEngine("AAPL")

    orders: list[OrderSubmitted] = []
    for i in range(1, 5001):
        side = Side.BUY if i % 2 == 0 else Side.SELL
        price = 15000 + (i % 20) * (1 if side == Side.SELL else -1)
        orders.append(
            OrderSubmitted(
                seq=i,
                ts_ns=i * 1000,
                symbol="AAPL",
                order_id=f"ord_{i}",
                side=side,
                order_type=OrderType.LIMIT,
                price_ticks=price,
                qty=25,
            )
        )

    start = time.perf_counter()
    for o in orders:
        engine.submit_order(o)
    elapsed = time.perf_counter() - start

    rate = len(orders) / elapsed
    # Assert at least 5,000 orders/sec
    assert rate >= 5000, f"Rate {rate:.1f} orders/sec was below 5,000 target"


def test_stp_cancel_newest() -> None:
    """STP CANCEL_NEWEST cancels aggressor order when attempting to match own resting order."""
    engine = MatchingEngine("AAPL")

    # Resting sell order from participant "trader_a"
    engine.submit_order(
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="s1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=100,
            participant_id="trader_a",
        )
    )

    # Aggressor buy order from participant "trader_a" with CANCEL_NEWEST
    events = engine.submit_order(
        OrderSubmitted(
            seq=2,
            ts_ns=200,
            symbol="AAPL",
            order_id="b1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=100,
            participant_id="trader_a",
            stp=STPPolicy.CANCEL_NEWEST,
        )
    )

    trades = [e for e in events if isinstance(e, TradeExecuted)]
    cancels = [e for e in events if isinstance(e, OrderCanceled)]
    assert len(trades) == 0
    assert len(cancels) == 1
    assert cancels[0].order_id == "b1"
    assert cancels[0].reason == "STP_CANCEL_NEWEST"

    # Resting sell order remains untouched
    assert engine.book.best_ask() == 15000
    resting_s1 = engine.book.get_order("s1")
    assert resting_s1 is not None
    assert resting_s1.remaining_qty == 100

    stats = engine.get_stp_stats()
    assert stats["cancel_newest"] == 1
    assert stats["total_prevented"] == 1


def test_stp_cancel_oldest() -> None:
    """STP CANCEL_OLDEST cancels resting order and allows aggressor to match or rest."""
    engine = MatchingEngine("AAPL")

    # Resting sell order from "trader_a"
    engine.submit_order(
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="s1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=100,
            participant_id="trader_a",
        )
    )

    # Aggressor buy order from "trader_a" with CANCEL_OLDEST
    events = engine.submit_order(
        OrderSubmitted(
            seq=2,
            ts_ns=200,
            symbol="AAPL",
            order_id="b1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=50,
            participant_id="trader_a",
            stp=STPPolicy.CANCEL_OLDEST,
        )
    )

    trades = [e for e in events if isinstance(e, TradeExecuted)]
    cancels = [e for e in events if isinstance(e, OrderCanceled)]
    assert len(trades) == 0
    assert len(cancels) == 1
    assert cancels[0].order_id == "s1"
    assert cancels[0].reason == "STP_CANCEL_OLDEST"

    # s1 is gone, b1 rests at 15000
    assert engine.book.get_order("s1") is None
    assert engine.book.best_ask() is None
    assert engine.book.best_bid() == 15000
    assert engine.book.get_order("b1") is not None

    stats = engine.get_stp_stats()
    assert stats["cancel_oldest"] == 1
    assert stats["total_prevented"] == 1


def test_stp_decrement_and_cancel() -> None:
    """STP DECREMENT_AND_CANCEL decrements both orders by the overlap quantity."""
    engine = MatchingEngine("AAPL")

    # Resting sell order of 100 shares
    engine.submit_order(
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="s1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=100,
            participant_id="trader_a",
        )
    )

    # Aggressor buy order of 40 shares: overlap = 40.
    # Aggressor b1 is exhausted and canceled. Resting s1 is reduced from 100 to 60.
    events = engine.submit_order(
        OrderSubmitted(
            seq=2,
            ts_ns=200,
            symbol="AAPL",
            order_id="b1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=40,
            participant_id="trader_a",
            stp=STPPolicy.DECREMENT_AND_CANCEL,
        )
    )

    trades = [e for e in events if isinstance(e, TradeExecuted)]
    cancels = [e for e in events if isinstance(e, OrderCanceled)]
    assert len(trades) == 0
    assert len(cancels) == 1
    assert cancels[0].order_id == "b1"
    assert cancels[0].reason == "STP_DECREMENT_AND_CANCEL"

    s1 = engine.book.get_order("s1")
    assert s1 is not None
    assert s1.remaining_qty == 60

    # Next aggressor buy order of 80 shares: overlap = 60.
    # Resting s1 is exhausted and canceled. Aggressor b2 remaining 20 rests on book.
    events2 = engine.submit_order(
        OrderSubmitted(
            seq=3,
            ts_ns=300,
            symbol="AAPL",
            order_id="b2",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=80,
            participant_id="trader_a",
            stp=STPPolicy.DECREMENT_AND_CANCEL,
        )
    )

    cancels2 = [e for e in events2 if isinstance(e, OrderCanceled)]
    assert len(cancels2) == 1
    assert cancels2[0].order_id == "s1"
    assert cancels2[0].reason == "STP_DECREMENT_AND_CANCEL"
    assert engine.book.get_order("s1") is None

    b2 = engine.book.get_order("b2")
    assert b2 is not None
    assert b2.remaining_qty == 20
    assert engine.book.best_bid() == 15000

    stats = engine.get_stp_stats()
    assert stats["decrement_and_cancel"] == 2


def test_stp_none_policy_executes_trade() -> None:
    """STP NONE allows self-matching and attributes participant IDs to the trade."""
    engine = MatchingEngine("AAPL")

    engine.submit_order(
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="s1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=50,
            participant_id="trader_a",
        )
    )

    events = engine.submit_order(
        OrderSubmitted(
            seq=2,
            ts_ns=200,
            symbol="AAPL",
            order_id="b1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=50,
            participant_id="trader_a",
            stp=STPPolicy.NONE,
        )
    )

    trades = [e for e in events if isinstance(e, TradeExecuted)]
    assert len(trades) == 1
    assert trades[0].buyer_participant_id == "trader_a"
    assert trades[0].seller_participant_id == "trader_a"
    assert engine.get_stp_stats()["total_prevented"] == 0


def test_stp_different_participants_match() -> None:
    """Orders with different or empty participant IDs match normally."""
    engine = MatchingEngine("AAPL")

    engine.submit_order(
        OrderSubmitted(
            seq=1,
            ts_ns=100,
            symbol="AAPL",
            order_id="s1",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=100,
            participant_id="trader_a",
        )
    )

    # trader_b buy 40
    events = engine.submit_order(
        OrderSubmitted(
            seq=2,
            ts_ns=200,
            symbol="AAPL",
            order_id="b1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=40,
            participant_id="trader_b",
            stp=STPPolicy.CANCEL_NEWEST,
        )
    )
    trades = [e for e in events if isinstance(e, TradeExecuted)]
    assert len(trades) == 1
    assert trades[0].buyer_participant_id == "trader_b"
    assert trades[0].seller_participant_id == "trader_a"

    # anonymous buy 30
    events2 = engine.submit_order(
        OrderSubmitted(
            seq=3,
            ts_ns=300,
            symbol="AAPL",
            order_id="b2",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=30,
            participant_id="",
            stp=STPPolicy.CANCEL_NEWEST,
        )
    )
    trades2 = [e for e in events2 if isinstance(e, TradeExecuted)]
    assert len(trades2) == 1
    assert trades2[0].buyer_participant_id == ""
    assert trades2[0].seller_participant_id == "trader_a"
    assert engine.get_stp_stats()["total_prevented"] == 0
