"""Unit tests for PortfolioTracker, Position, and OrderRecord pure domain logic."""


from marketpulse.core.events import (
    OrderAccepted,
    OrderCanceled,
    OrderRejected,
    OrderSubmitted,
    OrderType,
    Side,
    TradeExecuted,
)
from marketpulse.core.portfolio import OrderStatus, PortfolioTracker


def test_initial_portfolio_state() -> None:
    """Verify default initial cash, zero positions, and zero P&L."""
    pms = PortfolioTracker(initial_cash=100_000.0, tick_size=0.01)
    assert pms.cash_ticks == 10_000_000
    assert pms.initial_cash_ticks == 10_000_000
    assert len(pms.positions) == 0
    assert len(pms.orders) == 0

    summary = pms.get_summary(current_price_ticks=15000, tick_size=0.01)
    assert summary["cash"] == 100_000.0
    assert summary["equity"] == 100_000.0
    assert summary["realized_pnl"] == 0.0
    assert summary["unrealized_pnl"] == 0.0
    assert summary["total_pnl"] == 0.0
    assert summary["pnl_pct"] == 0.0
    assert summary["open_orders_count"] == 0
    assert summary["positions"] == []


def test_order_validation() -> None:
    """Verify purchasing power and order parameter validation."""
    pms = PortfolioTracker(initial_cash=10_000.0, tick_size=0.01)  # 1,000,000 ticks

    # Invalid qty
    ok, err = pms.validate_order("AAPL", Side.BUY, OrderType.LIMIT, 0, 15000)
    assert not ok
    assert "Quantity must be positive" in (err or "")

    # Limit order missing price
    ok, err = pms.validate_order("AAPL", Side.BUY, OrderType.LIMIT, 10, None)
    assert not ok
    assert "Limit orders require price > 0" in (err or "")

    # Market order missing estimated price
    ok, err = pms.validate_order("AAPL", Side.BUY, OrderType.MARKET, 10, None, None)
    assert not ok
    assert "Market orders require positive reference price" in (err or "")

    # Valid buy within budget: 50 shares * 15,000 ticks = 750,000 ticks <= 1,000,000
    ok, err = pms.validate_order("AAPL", Side.BUY, OrderType.LIMIT, 50, 15000)
    assert ok
    assert err is None

    # Excessive buy exceeding cash: 100 shares * 15,000 ticks = 1,500,000 ticks > 1,000,000
    ok, err = pms.validate_order("AAPL", Side.BUY, OrderType.LIMIT, 100, 15000)
    assert not ok
    assert "Insufficient funds" in (err or "")


def test_order_lifecycle_and_rejection() -> None:
    """Verify order state transitions: PENDING -> OPEN -> REJECTED / CANCELED."""
    pms = PortfolioTracker(initial_cash=100_000.0, tick_size=0.01)

    order_sub = OrderSubmitted(
        seq=1,
        ts_ns=1000,
        symbol="AAPL",
        order_id="usr_001",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=100,
    )
    record = pms.on_order_submitted(order_sub)
    assert record.status == OrderStatus.PENDING
    assert record.remaining_qty == 100
    assert record.filled_qty == 0

    # Accept order
    pms.on_order_accepted(OrderAccepted(seq=2, ts_ns=2000, symbol="AAPL", order_id="usr_001"))
    assert pms.orders["usr_001"].status == OrderStatus.OPEN

    # Cancel order
    pms.on_order_canceled(
        OrderCanceled(seq=3, ts_ns=3000, symbol="AAPL", order_id="usr_001", reason="USER_CANCEL")
    )
    order = pms.orders["usr_001"]
    assert order.status == OrderStatus.CANCELED

    # Rejection flow
    order_sub2 = OrderSubmitted(
        seq=4,
        ts_ns=4000,
        symbol="AAPL",
        order_id="usr_002",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=50,
    )
    pms.on_order_submitted(order_sub2)
    pms.on_order_rejected(
        OrderRejected(seq=5, ts_ns=5000, symbol="AAPL", order_id="usr_002", reason="BOOK_HALTED")
    )
    assert pms.orders["usr_002"].status == OrderStatus.REJECTED
    assert pms.orders["usr_002"].reject_reason == "BOOK_HALTED"


def test_buy_and_sell_pnl_and_accounting_identity() -> None:
    """Verify weighted average entry price, realized/unrealized PnL, and accounting invariants."""
    pms = PortfolioTracker(initial_cash=100_000.0, tick_size=0.01)  # 10,000,000 ticks

    # Submit and fill first buy: 100 shares @ $150.00 (15,000 ticks)
    pms.on_order_submitted(
        OrderSubmitted(
            seq=1,
            ts_ns=1000,
            symbol="AAPL",
            order_id="usr_buy_1",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price_ticks=15000,
            qty=100,
        )
    )
    trade_1 = TradeExecuted(
        seq=2,
        ts_ns=2000,
        symbol="AAPL",
        trade_id="tr_1",
        price_ticks=15000,
        qty=100,
        aggressor_side=Side.BUY,
        buy_order_id="usr_buy_1",
        sell_order_id="mm_1",
    )
    pms.on_trade_executed(trade_1, user_order_id="usr_buy_1", side=Side.BUY)

    # Verify order filled
    order1 = pms.orders["usr_buy_1"]
    assert order1.status == OrderStatus.FILLED
    assert order1.filled_qty == 100
    assert order1.remaining_qty == 0
    assert order1.avg_fill_price_ticks == 15000.0

    # Verify cash deducted: 10,000,000 - 100*15,000 = 8,500,000 ticks ($85,000)
    assert pms.cash_ticks == 8_500_000
    pos = pms.get_position("AAPL")
    assert pos.qty == 100
    assert pos.avg_entry_price_ticks == 15000.0

    # Partial buy fill: buy another 100 shares @ $160.00 (16,000 ticks)
    trade_2 = TradeExecuted(
        seq=3,
        ts_ns=3000,
        symbol="AAPL",
        trade_id="tr_2",
        price_ticks=16000,
        qty=100,
        aggressor_side=Side.BUY,
        buy_order_id="usr_buy_2",
        sell_order_id="mm_2",
    )
    pms.on_trade_executed(trade_2, user_order_id="usr_buy_2", side=Side.BUY)
    assert pos.qty == 200
    # Average price = (100 * 15,000 + 100 * 16,000) / 200 = 15,500 ticks ($155.00)
    assert pos.avg_entry_price_ticks == 15500.0
    assert pms.cash_ticks == 8_500_000 - 1_600_000  # 6,900,000 ticks

    # Check Mark-to-market at current price $170.00 (17,000 ticks)
    summary = pms.get_summary(current_price_ticks=17000, tick_size=0.01)
    # Market value = 200 * 17,000 ticks = 3,400,000 ticks ($34,000)
    # Equity = 6,900,000 + 3,400,000 = 10,300,000 ticks ($103,000)
    assert summary["cash"] == 69_000.0
    assert summary["equity"] == 103_000.0
    # Unrealized PnL = (17,000 - 15,500) * 200 = +300,000 ticks ($3,000)
    assert summary["unrealized_pnl"] == 3_000.0
    assert summary["realized_pnl"] == 0.0
    assert summary["total_pnl"] == 3_000.0
    # Accounting invariant:
    assert summary["equity_ticks"] == summary["cash_ticks"] + (200 * 17000)
    assert (
        summary["total_pnl_ticks"]
        == summary["realized_pnl_ticks"] + summary["unrealized_pnl_ticks"]
    )
    assert summary["equity_ticks"] == pms.initial_cash_ticks + summary["total_pnl_ticks"]

    # Sell 100 shares @ $170.00 (17,000 ticks) to realize profit
    trade_sell = TradeExecuted(
        seq=4,
        ts_ns=4000,
        symbol="AAPL",
        trade_id="tr_3",
        price_ticks=17000,
        qty=100,
        aggressor_side=Side.SELL,
        buy_order_id="noise_1",
        sell_order_id="usr_sell_1",
    )
    pms.on_trade_executed(trade_sell, user_order_id="usr_sell_1", side=Side.SELL)
    # Realized PnL = (17,000 - 15,500) * 100 = 150,000 ticks ($1,500)
    assert pos.qty == 100
    assert pos.avg_entry_price_ticks == 15500.0  # entry price unchanged on partial sale
    assert pos.realized_pnl_ticks == 150_000
    assert pms.cash_ticks == 6_900_000 + 1_700_000  # 8,600,000 ticks

    summary2 = pms.get_summary(current_price_ticks=17000, tick_size=0.01)
    assert summary2["realized_pnl"] == 1_500.0
    # Remaining 100 shares unrealized: (17,000 - 15,500) * 100 = 150,000 ticks ($1,500)
    assert summary2["unrealized_pnl"] == 1_500.0
    assert summary2["total_pnl"] == 3_000.0
    assert summary2["equity"] == 103_000.0


def test_short_position_inventory_and_cover() -> None:
    """Verify short selling and covering behavior."""
    pms = PortfolioTracker(initial_cash=100_000.0, tick_size=0.01)

    # Sell 50 shares short @ 15,000 ticks
    trade_short = TradeExecuted(
        seq=1,
        ts_ns=1000,
        symbol="AAPL",
        trade_id="tr_s1",
        price_ticks=15000,
        qty=50,
        aggressor_side=Side.SELL,
        buy_order_id="mm_1",
        sell_order_id="usr_short",
    )
    pms.on_trade_executed(trade_short, user_order_id="usr_short", side=Side.SELL)
    pos = pms.get_position("AAPL")
    assert pos.qty == -50
    assert pos.avg_entry_price_ticks == 15000.0
    assert pms.cash_ticks == 10_000_000 + (50 * 15000)

    # Price drops to 14,000 ticks -> unrealized profit
    summary = pms.get_summary(current_price_ticks=14000, tick_size=0.01)
    # Unrealized = (14,000 - 15,000) * (-50) = +50,000 ticks ($500)
    assert summary["unrealized_pnl"] == 500.0

    # Cover short by buying 50 shares @ 14,000 ticks
    trade_cover = TradeExecuted(
        seq=2,
        ts_ns=2000,
        symbol="AAPL",
        trade_id="tr_c1",
        price_ticks=14000,
        qty=50,
        aggressor_side=Side.BUY,
        buy_order_id="usr_cover",
        sell_order_id="mm_2",
    )
    pms.on_trade_executed(trade_cover, user_order_id="usr_cover", side=Side.BUY)
    assert pos.qty == 0
    assert pos.avg_entry_price_ticks == 0.0
    assert pos.realized_pnl_ticks == 50_000  # $500 realized profit

    summary_flat = pms.get_summary(current_price_ticks=14000, tick_size=0.01)
    assert summary_flat["realized_pnl"] == 500.0
    assert summary_flat["unrealized_pnl"] == 0.0
    assert summary_flat["equity"] == 100_500.0


def test_portfolio_reset_and_queries() -> None:
    """Verify reset, open orders, and trade history queries."""
    pms = PortfolioTracker(initial_cash=50_000.0, tick_size=0.01)
    order_sub = OrderSubmitted(
        seq=1,
        ts_ns=1000,
        symbol="AAPL",
        order_id="usr_o1",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=10,
    )
    pms.on_order_submitted(order_sub)
    pms.on_order_accepted(OrderAccepted(seq=2, ts_ns=2000, symbol="AAPL", order_id="usr_o1"))

    open_orders = pms.get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0]["order_id"] == "usr_o1"

    order_history = pms.get_order_history()
    assert len(order_history) == 1

    pms.reset(initial_cash=100_000.0, tick_size=0.01)
    assert pms.cash_ticks == 10_000_000
    assert len(pms.get_open_orders()) == 0
    assert len(pms.get_order_history()) == 0
    assert len(pms.get_trade_history()) == 0
