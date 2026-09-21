"""Unit and golden tests for incremental OHLCAggregator."""

import pandas as pd
import pytest

from marketpulse.core.events import Side, TradeExecuted
from marketpulse.core.ohlc import OHLCAggregator
from marketpulse.sim.stub_gbm import StubGBMSource


def test_aggregator_initialization_and_validation() -> None:
    """Verify aggregator initialization and parameter validation."""
    agg = OHLCAggregator(symbol="AAPL", intervals=("1s", "5s", "1m"))
    assert agg.symbol == "AAPL"
    assert agg.intervals == ("1s", "5s", "1m")

    with pytest.raises(ValueError, match="Unknown interval '99s'"):
        OHLCAggregator(symbol="AAPL", intervals=("99s",))


def test_aggregator_incremental_single_bucket_update() -> None:
    """Verify multiple trades in the same interval update high, low, close, and volume in O(1)."""
    agg = OHLCAggregator(symbol="AAPL", intervals=("1s",))

    # Trade 1: t = 100ms (100_000_000 ns), price = 15000 ticks, qty = 10
    t1 = TradeExecuted(
        seq=1,
        ts_ns=100_000_000,
        symbol="AAPL",
        trade_id="t1",
        price_ticks=15000,
        qty=10,
        aggressor_side=Side.BUY,
        buy_order_id="b1",
        sell_order_id="s1",
    )
    updates1 = agg.update_trade(t1)
    bar1 = updates1["1s"][0]
    assert bar1.open_ticks == 15000
    assert bar1.high_ticks == 15000
    assert bar1.low_ticks == 15000
    assert bar1.close_ticks == 15000
    assert bar1.volume == 10
    assert bar1.trade_count == 1
    assert bar1.is_closed is False

    # Trade 2: t = 500ms, price = 15050 (new high), qty = 20
    t2 = TradeExecuted(
        seq=2,
        ts_ns=500_000_000,
        symbol="AAPL",
        trade_id="t2",
        price_ticks=15050,
        qty=20,
        aggressor_side=Side.BUY,
        buy_order_id="b2",
        sell_order_id="s2",
    )
    updates2 = agg.update_trade(t2)
    bar2 = updates2["1s"][0]
    assert bar2.open_ticks == 15000
    assert bar2.high_ticks == 15050
    assert bar2.low_ticks == 15000
    assert bar2.close_ticks == 15050
    assert bar2.volume == 30
    assert bar2.trade_count == 2
    assert bar2.is_closed is False

    # Trade 3: t = 800ms, price = 14980 (new low), qty = 30
    t3 = TradeExecuted(
        seq=3,
        ts_ns=800_000_000,
        symbol="AAPL",
        trade_id="t3",
        price_ticks=14980,
        qty=30,
        aggressor_side=Side.SELL,
        buy_order_id="b3",
        sell_order_id="s3",
    )
    updates3 = agg.update_trade(t3)
    bar3 = updates3["1s"][0]
    assert bar3.open_ticks == 15000
    assert bar3.high_ticks == 15050
    assert bar3.low_ticks == 14980
    assert bar3.close_ticks == 14980
    assert bar3.volume == 60
    assert bar3.trade_count == 3


def test_aggregator_boundary_crossing_and_closure() -> None:
    """Verify interval crossing marks bar closed and starts new active bar."""
    agg = OHLCAggregator(symbol="AAPL", intervals=("1s",))

    # Trade at t = 200ms
    agg.update_trade(
        TradeExecuted(
            seq=1,
            ts_ns=200_000_000,
            symbol="AAPL",
            trade_id="t1",
            price_ticks=15000,
            qty=10,
            aggressor_side=Side.BUY,
            buy_order_id="b1",
            sell_order_id="s1",
        )
    )

    # Trade at t = 1200ms (crosses 1s boundary at 1_000_000_000 ns)
    updates = agg.update_trade(
        TradeExecuted(
            seq=2,
            ts_ns=1_200_000_000,
            symbol="AAPL",
            trade_id="t2",
            price_ticks=15020,
            qty=15,
            aggressor_side=Side.BUY,
            buy_order_id="b2",
            sell_order_id="s2",
        )
    )

    bars = updates["1s"]
    assert len(bars) == 2
    closed_bar, new_active_bar = bars[0], bars[1]

    # First bar closed
    assert closed_bar.is_closed is True
    assert closed_bar.start_ts_ns == 0
    assert closed_bar.end_ts_ns == 1_000_000_000
    assert closed_bar.close_ticks == 15000

    # Second bar active
    assert new_active_bar.is_closed is False
    assert new_active_bar.start_ts_ns == 1_000_000_000
    assert new_active_bar.open_ticks == 15020
    assert new_active_bar.volume == 15


def test_aggregator_empty_interval_forward_fill_policy() -> None:
    """Verify empty intervals between trades are forward-filled with previous close and 0 volume."""
    agg = OHLCAggregator(symbol="AAPL", intervals=("1s",))

    # Trade in bucket 0s..1s
    agg.update_trade(
        TradeExecuted(
            seq=1,
            ts_ns=500_000_000,
            symbol="AAPL",
            trade_id="t1",
            price_ticks=15000,
            qty=50,
            aggressor_side=Side.BUY,
            buy_order_id="b1",
            sell_order_id="s1",
        )
    )

    # Next trade at 4500ms (skipping 1s..2s, 2s..3s, 3s..4s)
    updates = agg.update_trade(
        TradeExecuted(
            seq=2,
            ts_ns=4_500_000_000,
            symbol="AAPL",
            trade_id="t2",
            price_ticks=15100,
            qty=20,
            aggressor_side=Side.BUY,
            buy_order_id="b2",
            sell_order_id="s2",
        )
    )

    bars = updates["1s"]
    # Should contain: closed bucket 0..1, empty 1..2, empty 2..3, empty 3..4, and active 4..5
    assert len(bars) == 5

    # Check the 3 empty forward-filled bars
    for i in range(1, 4):
        empty_bar = bars[i]
        assert empty_bar.is_closed is True
        assert empty_bar.start_ts_ns == i * 1_000_000_000
        assert empty_bar.open_ticks == 15000
        assert empty_bar.high_ticks == 15000
        assert empty_bar.low_ticks == 15000
        assert empty_bar.close_ticks == 15000
        assert empty_bar.volume == 0
        assert empty_bar.trade_count == 0


def test_aggregator_out_of_order_and_symbol_validation() -> None:
    """Verify out-of-order timestamps and symbol mismatches raise ValueError."""
    agg = OHLCAggregator(symbol="AAPL", intervals=("1s",))

    agg.update_trade(
        TradeExecuted(
            seq=1,
            ts_ns=1_000_000_000,
            symbol="AAPL",
            trade_id="t1",
            price_ticks=15000,
            qty=10,
            aggressor_side=Side.BUY,
            buy_order_id="b1",
            sell_order_id="s1",
        )
    )

    with pytest.raises(ValueError, match="Symbol mismatch"):
        agg.update_trade(
            TradeExecuted(
                seq=2,
                ts_ns=2_000_000_000,
                symbol="MSFT",
                trade_id="t2",
                price_ticks=15000,
                qty=10,
                aggressor_side=Side.BUY,
                buy_order_id="b2",
                sell_order_id="s2",
            )
        )

    with pytest.raises(ValueError, match="Out-of-order trade timestamp"):
        agg.update_trade(
            TradeExecuted(
                seq=3,
                ts_ns=500_000_000,  # 500ms < 1000ms
                symbol="AAPL",
                trade_id="t3",
                price_ticks=15000,
                qty=10,
                aggressor_side=Side.BUY,
                buy_order_id="b3",
                sell_order_id="s3",
            )
        )


def test_aggregator_pandas_resample_golden_test() -> None:
    """Golden Test: Aggregator output matches Pandas resample on non-empty intervals."""
    source = StubGBMSource(
        seed=42,
        symbol="AAPL",
        initial_price=150.0,
        tick_size=0.01,
        time_step_s=0.1,  # 10 trades per second
        max_events=100,
    )
    trades: list[TradeExecuted] = [e for e in source.stream() if isinstance(e, TradeExecuted)]

    agg = OHLCAggregator(symbol="AAPL", intervals=("1s",))
    for t in trades:
        agg.update_trade(t)

    # Force closure of the final bar by pushing an epoch-distant trade
    final_trade = TradeExecuted(
        seq=999,
        ts_ns=trades[-1].ts_ns + 2_000_000_000,
        symbol="AAPL",
        trade_id="t_final",
        price_ticks=trades[-1].price_ticks,
        qty=1,
        aggressor_side=Side.BUY,
        buy_order_id="bf",
        sell_order_id="sf",
    )
    agg.update_trade(final_trade)

    history = agg.get_history("1s")
    # Exclude the artificial final trade's bars
    aggregated_bars = [
        b for b in history if b.start_ts_ns <= trades[-1].ts_ns and b.trade_count > 0
    ]

    # Build Pandas DataFrame for golden comparison
    timestamps = [pd.to_datetime(t.ts_ns, unit="ns") for t in trades]
    prices = [t.price_ticks for t in trades]
    volumes = [t.qty for t in trades]

    df = pd.DataFrame({"price": prices, "volume": volumes}, index=timestamps)
    resampled = df.resample("1s", origin="epoch").agg(
        {
            "price": ["first", "max", "min", "last", "count"],
            "volume": "sum",
        }
    )
    resampled.dropna(inplace=True)

    assert len(aggregated_bars) == len(resampled)

    for bar, (_, row) in zip(aggregated_bars, resampled.iterrows(), strict=True):
        assert bar.open_ticks == row[("price", "first")]
        assert bar.high_ticks == row[("price", "max")]
        assert bar.low_ticks == row[("price", "min")]
        assert bar.close_ticks == row[("price", "last")]
        assert bar.trade_count == row[("price", "count")]
        assert bar.volume == row[("volume", "sum")]
