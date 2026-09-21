"""Unit tests for real-time streaming anomaly detection in MarketPulse."""

from __future__ import annotations

from marketpulse.core.anomaly import (
    AnomalySeverity,
    AnomalyType,
    MarketAnomaly,
    StreamingAnomalyDetector,
)
from marketpulse.core.events import Side, TradeExecuted


def test_anomaly_to_dict() -> None:
    """Test MarketAnomaly dataclass serialization."""
    anomaly = MarketAnomaly(
        seq=1,
        ts_ns=1_000_000_000,
        symbol="AAPL",
        anomaly_type=AnomalyType.PRICE_SHOCK,
        severity=AnomalySeverity.CRITICAL,
        metric_value=4.5,
        threshold=2.0,
        message="Sharp price jump detected",
    )
    d = anomaly.to_dict()
    assert d["seq"] == 1
    assert d["symbol"] == "AAPL"
    assert d["type"] == "PRICE_SHOCK"
    assert d["severity"] == "CRITICAL"
    assert d["metric_value"] == 4.5
    assert d["threshold"] == 2.0
    assert d["message"] == "Sharp price jump detected"


def test_volume_surge_detection() -> None:
    """Detect trade volume surge when a trade is >= 3x rolling mean volume."""
    detector = StreamingAnomalyDetector(symbol="AAPL", min_cooldown_ns=0)

    # Prime baseline with 20 trades of 50 shares
    for i in range(20):
        t = TradeExecuted(
            seq=i + 1,
            ts_ns=1_000_000 * (i + 1),
            symbol="AAPL",
            trade_id=f"trd_{i}",
            price_ticks=15000,
            qty=50,
            aggressor_side=Side.BUY,
            buy_order_id=f"b_{i}",
            sell_order_id=f"s_{i}",
        )
        anomalies = detector.on_trade(t)
        assert len(anomalies) == 0

    # Submit a 300-share trade (6x average of 50)
    surge_trade = TradeExecuted(
        seq=21,
        ts_ns=21_000_000,
        symbol="AAPL",
        trade_id="trd_surge",
        price_ticks=15000,
        qty=300,
        aggressor_side=Side.BUY,
        buy_order_id="b_surge",
        sell_order_id="s_surge",
    )
    anomalies = detector.on_trade(surge_trade)
    assert len(anomalies) == 1
    anom = anomalies[0]
    assert anom.anomaly_type == AnomalyType.VOLUME_SURGE
    assert anom.severity == AnomalySeverity.CRITICAL
    assert anom.metric_value == 300.0


def test_price_shock_detection() -> None:
    """Detect price shock when return deviates significantly from rolling returns."""
    detector = StreamingAnomalyDetector(symbol="AAPL", min_cooldown_ns=0)

    # Establish tight baseline returns (15000 -> 15001 -> 15000 -> 15002 ...)
    base_price = 15000
    for i in range(25):
        price = base_price + (i % 2)
        t = TradeExecuted(
            seq=i + 1,
            ts_ns=1_000_000 * (i + 1),
            symbol="AAPL",
            trade_id=f"trd_{i}",
            price_ticks=price,
            qty=25,
            aggressor_side=Side.BUY,
            buy_order_id=f"b_{i}",
            sell_order_id=f"s_{i}",
        )
        detector.on_trade(t)

    # Abrupt jump of 300 ticks (+2.0%)
    shock_trade = TradeExecuted(
        seq=26,
        ts_ns=26_000_000,
        symbol="AAPL",
        trade_id="trd_shock",
        price_ticks=15300,
        qty=25,
        aggressor_side=Side.BUY,
        buy_order_id="b_shock",
        sell_order_id="s_shock",
    )
    anomalies = detector.on_trade(shock_trade)
    price_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.PRICE_SHOCK]
    assert len(price_anomalies) == 1
    assert price_anomalies[0].severity in (AnomalySeverity.WARNING, AnomalySeverity.CRITICAL)


def test_spread_blowout_detection() -> None:
    """Detect spread blowout when bid-ask spread widens beyond 3x baseline median."""
    detector = StreamingAnomalyDetector(symbol="AAPL", min_cooldown_ns=0)

    # Baseline spread: 2 ticks (15000 bid, 15002 ask)
    for i in range(15):
        detector.on_book_update(
            symbol="AAPL",
            ts_ns=1_000_000 * i,
            best_bid_ticks=15000,
            best_ask_ticks=15002,
            total_bid_vol=500,
            total_ask_vol=500,
        )

    # Spread suddenly blows out to 15 ticks (15000 bid, 15015 ask)
    anomalies = detector.on_book_update(
        symbol="AAPL",
        ts_ns=20_000_000,
        best_bid_ticks=15000,
        best_ask_ticks=15015,
        total_bid_vol=200,
        total_ask_vol=200,
    )
    blowouts = [a for a in anomalies if a.anomaly_type == AnomalyType.SPREAD_BLOWOUT]
    assert len(blowouts) == 1
    assert blowouts[0].metric_value == 15.0
    assert blowouts[0].severity == AnomalySeverity.CRITICAL


def test_book_imbalance_detection() -> None:
    """Detect extreme liquidity skew (>85% on one side)."""
    detector = StreamingAnomalyDetector(symbol="AAPL", min_cooldown_ns=0)

    # 95% bids (950 bid vs 50 ask)
    anomalies = detector.on_book_update(
        symbol="AAPL",
        ts_ns=5_000_000,
        best_bid_ticks=15000,
        best_ask_ticks=15002,
        total_bid_vol=950,
        total_ask_vol=50,
    )
    imbalances = [a for a in anomalies if a.anomaly_type == AnomalyType.BOOK_IMBALANCE]
    assert len(imbalances) == 1
    assert imbalances[0].anomaly_type == AnomalyType.BOOK_IMBALANCE
    assert imbalances[0].severity == AnomalySeverity.CRITICAL
    assert "BUY" in imbalances[0].message


def test_cooldown_suppression() -> None:
    """Test that rapid subsequent anomalies within cooldown window are suppressed."""
    cooldown_ns = 500_000_000  # 500ms
    detector = StreamingAnomalyDetector(symbol="AAPL", min_cooldown_ns=cooldown_ns)

    # Establish baseline
    for i in range(15):
        detector.on_book_update(
            symbol="AAPL",
            ts_ns=1_000_000 * i,
            best_bid_ticks=15000,
            best_ask_ticks=15002,
            total_bid_vol=500,
            total_ask_vol=500,
        )

    # 1st blowout at t=50ms -> triggers
    a1 = detector.on_book_update(
        symbol="AAPL",
        ts_ns=50_000_000,
        best_bid_ticks=15000,
        best_ask_ticks=15020,
        total_bid_vol=200,
        total_ask_vol=200,
    )
    assert len([a for a in a1 if a.anomaly_type == AnomalyType.SPREAD_BLOWOUT]) == 1

    # 2nd blowout at t=100ms (< 500ms later) -> suppressed
    a2 = detector.on_book_update(
        symbol="AAPL",
        ts_ns=100_000_000,
        best_bid_ticks=15000,
        best_ask_ticks=15025,
        total_bid_vol=200,
        total_ask_vol=200,
    )
    assert len([a for a in a2 if a.anomaly_type == AnomalyType.SPREAD_BLOWOUT]) == 0

    # 3rd blowout at t=600ms (> 500ms later) -> triggers
    a3 = detector.on_book_update(
        symbol="AAPL",
        ts_ns=600_000_000,
        best_bid_ticks=15000,
        best_ask_ticks=15025,
        total_bid_vol=200,
        total_ask_vol=200,
    )
    assert len([a for a in a3 if a.anomaly_type == AnomalyType.SPREAD_BLOWOUT]) == 1
