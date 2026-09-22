from marketpulse.core.advanced_orders import AdvancedOrderManager, TriggerOrder
from marketpulse.core.events import (
    OrderSubmitted,
    OrderTriggered,
    OrderType,
    Side,
    TimeInForce,
)


def test_trigger_order_to_dict() -> None:
    order = TriggerOrder(
        order_id="stop-1",
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.STOP_LOSS,
        qty=100,
        stop_price_ticks=14500,
        oco_group_id="oco-1",
    )
    d = order.to_dict()
    assert d["order_id"] == "stop-1"
    assert d["symbol"] == "AAPL"
    assert d["side"] == "SELL"
    assert d["order_type"] == "STOP_LOSS"
    assert d["qty"] == 100
    assert d["stop_price_ticks"] == 14500
    assert d["current_stop_ticks"] == 14500
    assert d["oco_group_id"] == "oco-1"


def test_stop_loss_sell_trigger() -> None:
    manager = AdvancedOrderManager()
    order = TriggerOrder(
        order_id="sl-sell",
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.STOP_LOSS,
        qty=50,
        stop_price_ticks=14800,
        created_ts_ns=1_000_000,
    )
    manager.register_order(order)
    assert manager.get_order("sl-sell") is not None
    assert len(manager.get_open_orders()) == 1

    # Trade above stop price -> no trigger
    activated, oco_cancels, stops = manager.on_trade(14900, 2_000_000, symbol="AAPL")
    assert len(activated) == 0
    assert len(oco_cancels) == 0
    assert len(stops) == 0
    assert manager.get_order("sl-sell") is not None

    # Trade at or below stop price -> triggers!
    activated, oco_cancels, stops = manager.on_trade(14800, 3_000_000, symbol="AAPL")
    assert len(activated) == 1
    sub, trig = activated[0]
    assert isinstance(sub, OrderSubmitted)
    assert isinstance(trig, OrderTriggered)
    assert sub.order_id == "sl-sell"
    assert sub.order_type == OrderType.MARKET
    assert sub.tif == TimeInForce.IOC
    assert trig.trigger_price_ticks == 14800
    assert trig.execution_type == OrderType.MARKET

    # No longer in manager
    assert manager.get_order("sl-sell") is None
    assert len(manager.get_open_orders()) == 0


def test_stop_loss_buy_trigger() -> None:
    manager = AdvancedOrderManager()
    order = TriggerOrder(
        order_id="sl-buy",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.STOP_LOSS,
        qty=30,
        stop_price_ticks=15200,
    )
    manager.register_order(order)

    # Trade below stop -> no trigger
    activated, _, _ = manager.on_trade(15100, 100, "AAPL")
    assert len(activated) == 0

    # Trade above stop -> triggers
    activated, _, _ = manager.on_trade(15250, 200, "AAPL")
    assert len(activated) == 1
    sub, trig = activated[0]
    assert sub.order_id == "sl-buy"
    assert sub.order_type == OrderType.MARKET
    assert trig.trigger_price_ticks == 15250


def test_stop_limit_trigger() -> None:
    manager = AdvancedOrderManager()
    order = TriggerOrder(
        order_id="stop-lim-1",
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.STOP_LIMIT,
        qty=100,
        price_ticks=14400,  # limit price
        stop_price_ticks=14500,  # trigger stop price
    )
    manager.register_order(order)

    # Trade at 14450 triggers
    activated, _, _ = manager.on_trade(14450, 500, "AAPL")
    assert len(activated) == 1
    sub, trig = activated[0]
    assert sub.order_type == OrderType.LIMIT
    assert sub.price_ticks == 14400
    assert sub.tif == TimeInForce.GTC
    assert trig.execution_type == OrderType.LIMIT


def test_take_profit_sell_and_buy() -> None:
    manager = AdvancedOrderManager()
    tp_sell = TriggerOrder(
        order_id="tp-sell",
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.TAKE_PROFIT,
        qty=20,
        stop_price_ticks=16000,
    )
    tp_buy = TriggerOrder(
        order_id="tp-buy",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.TAKE_PROFIT_LIMIT,
        qty=20,
        price_ticks=13950,
        stop_price_ticks=14000,
    )
    manager.register_order(tp_sell)
    manager.register_order(tp_buy)

    # Trade at 15000: neither triggers
    activated, _, _ = manager.on_trade(15000, 1000, "AAPL")
    assert len(activated) == 0

    # Trade rises to 16000: tp_sell triggers (SELL at target high)
    activated, _, _ = manager.on_trade(16000, 2000, "AAPL")
    assert len(activated) == 1
    assert activated[0][0].order_id == "tp-sell"
    assert activated[0][0].order_type == OrderType.MARKET

    # Trade dips to 13900: tp_buy triggers (BUY at dip low)
    activated, _, _ = manager.on_trade(13900, 3000, "AAPL")
    assert len(activated) == 1
    assert activated[0][0].order_id == "tp-buy"
    assert activated[0][0].order_type == OrderType.LIMIT
    assert activated[0][0].price_ticks == 13950


def test_trailing_stop_sell_ratchet_and_trigger() -> None:
    manager = AdvancedOrderManager()
    # SELL trailing stop with 500 ticks ($5.00) offset
    ts_order = TriggerOrder(
        order_id="trail-sell",
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.TRAILING_STOP,
        qty=100,
        trail_offset_ticks=500,
    )
    manager.register_order(ts_order)

    # Initial trade at 15000: peak becomes 15000, stop becomes 14500
    activated, _, stops = manager.on_trade(15000, 1000, "AAPL")
    assert len(activated) == 0
    assert stops == [("trail-sell", 14500)]
    assert ts_order.peak_price_ticks == 15000
    assert ts_order.current_stop_ticks == 14500

    # Price moves up to 15500: peak ratchets up to 15500, stop ratchets to 15000
    activated, _, stops = manager.on_trade(15500, 2000, "AAPL")
    assert len(activated) == 0
    assert stops == [("trail-sell", 15000)]
    assert ts_order.peak_price_ticks == 15500
    assert ts_order.current_stop_ticks == 15000

    # Price moves further up to 16000: peak ratchets to 16000, stop ratchets to 15500
    activated, _, stops = manager.on_trade(16000, 3000, "AAPL")
    assert len(activated) == 0
    assert stops == [("trail-sell", 15500)]
    assert ts_order.current_stop_ticks == 15500

    # Minor pullback to 15800: peak stays 16000, stop stays 15500 (does not trigger)
    activated, _, stops = manager.on_trade(15800, 4000, "AAPL")
    assert len(activated) == 0
    assert len(stops) == 0
    assert ts_order.current_stop_ticks == 15500

    # Retracement hits 15500: triggers!
    activated, _, _ = manager.on_trade(15500, 5000, "AAPL")
    assert len(activated) == 1
    sub, trig = activated[0]
    assert sub.order_id == "trail-sell"
    assert sub.order_type == OrderType.MARKET
    assert trig.trigger_price_ticks == 15500
    assert manager.get_order("trail-sell") is None


def test_trailing_stop_buy_ratchet_and_trigger() -> None:
    manager = AdvancedOrderManager()
    # BUY trailing stop with 300 ticks ($3.00) offset
    ts_order = TriggerOrder(
        order_id="trail-buy",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.TRAILING_STOP,
        qty=50,
        trail_offset_ticks=300,
    )
    manager.register_order(ts_order)

    # Initial trade at 15000: trough becomes 15000, stop becomes 15300
    activated, _, stops = manager.on_trade(15000, 1000, "AAPL")
    assert len(activated) == 0
    assert stops == [("trail-buy", 15300)]
    assert ts_order.current_stop_ticks == 15300

    # Price falls to 14500: trough ratchets down to 14500, stop ratchets down to 14800
    activated, _, stops = manager.on_trade(14500, 2000, "AAPL")
    assert len(activated) == 0
    assert stops == [("trail-buy", 14800)]
    assert ts_order.current_stop_ticks == 14800

    # Small bounce to 14700: doesn't trigger
    activated, _, stops = manager.on_trade(14700, 3000, "AAPL")
    assert len(activated) == 0
    assert len(stops) == 0

    # Sharp bounce to 14850: triggers!
    activated, _, _ = manager.on_trade(14850, 4000, "AAPL")
    assert len(activated) == 1
    sub, _ = activated[0]
    assert sub.order_id == "trail-buy"
    assert sub.order_type == OrderType.MARKET


def test_oco_trigger_pair_one_triggers_cancels_other() -> None:
    manager = AdvancedOrderManager()
    # Position: Long 100 shares at 150.
    # Take-Profit Limit at 160 vs Stop-Loss Market at 145.
    tp = TriggerOrder(
        order_id="tp-oco",
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.TAKE_PROFIT,
        qty=100,
        stop_price_ticks=16000,
        oco_group_id="oco-group-1",
    )
    sl = TriggerOrder(
        order_id="sl-oco",
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.STOP_LOSS,
        qty=100,
        stop_price_ticks=14500,
        oco_group_id="oco-group-1",
    )
    manager.register_order(tp)
    manager.register_order(sl)

    assert len(manager.get_open_orders()) == 2

    # Price drops to 14500: Stop triggers!
    activated, oco_cancels, _ = manager.on_trade(14500, 1000, "AAPL")
    assert len(activated) == 1
    assert activated[0][0].order_id == "sl-oco"
    # Take-profit companion must be in oco_cancels and purged from open orders
    assert oco_cancels == ["tp-oco"]
    assert manager.get_order("tp-oco") is None
    assert manager.get_order("sl-oco") is None
    assert len(manager.get_open_orders()) == 0


def test_oco_manual_cancel_cancels_companion() -> None:
    manager = AdvancedOrderManager()
    o1 = TriggerOrder(
        order_id="ord-1",
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.STOP_LOSS,
        qty=50,
        stop_price_ticks=14500,
        oco_group_id="oco-pair",
    )
    o2 = TriggerOrder(
        order_id="ord-2",
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.TAKE_PROFIT,
        qty=50,
        stop_price_ticks=15500,
        oco_group_id="oco-pair",
    )
    manager.register_order(o1)
    manager.register_order(o2)

    # Cancel ord-1 -> cancels both ord-1 and ord-2
    canceled_ids = manager.cancel_order("ord-1")
    assert "ord-1" in canceled_ids
    assert "ord-2" in canceled_ids
    assert len(manager.get_open_orders()) == 0


def test_oco_active_limit_fill_cancels_trigger_companion() -> None:
    manager = AdvancedOrderManager()
    # Active limit order resting on engine (ord-limit) paired with stop trigger (ord-stop)
    manager.register_oco_member("ord-limit", "oco-combo")
    ord_stop = TriggerOrder(
        order_id="ord-stop",
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.STOP_LOSS,
        qty=100,
        stop_price_ticks=14000,
        oco_group_id="oco-combo",
    )
    manager.register_order(ord_stop)

    # ord-limit fills on matching engine
    cancels = manager.on_order_filled("ord-limit")
    assert cancels == ["ord-stop"]
    assert manager.get_order("ord-stop") is None
