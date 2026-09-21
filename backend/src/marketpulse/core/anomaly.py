"""Real-time streaming anomaly detection engine for MarketPulse.

Invariants:
- Pure domain logic running in O(1) time per event update.
- Zero external I/O or network dependencies.
- Detects Price Shocks (>3 sigma), Volume Surges (>3x mean),
  Spread Blowouts (>3x baseline), and Order Book Imbalance (>85% skew).
- Incorporates configurable cooldown thresholds to prevent alert storms.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from marketpulse.core.events import TradeExecuted, ticks_to_price


class AnomalyType(StrEnum):
    """Types of market anomalies detected in real-time."""

    PRICE_SHOCK = "PRICE_SHOCK"
    VOLUME_SURGE = "VOLUME_SURGE"
    SPREAD_BLOWOUT = "SPREAD_BLOWOUT"
    BOOK_IMBALANCE = "BOOK_IMBALANCE"


class AnomalySeverity(StrEnum):
    """Severity classification for detected anomalies."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketAnomaly:
    """Represents a detected market microstructure anomaly."""

    seq: int
    ts_ns: int
    symbol: str
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    metric_value: float
    threshold: float
    message: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize anomaly to dictionary."""
        d = asdict(self)
        d["type"] = self.anomaly_type.value
        d["anomaly_type"] = self.anomaly_type.value
        d["severity"] = self.severity.value
        return d

    def to_json(self) -> str:
        """Serialize anomaly to JSON string."""
        return json.dumps(self.to_dict(), sort_keys=True)


class StreamingAnomalyDetector:
    """Incremental O(1) anomaly detector for trade and order book feeds."""

    __slots__ = (
        "_baseline_spread_ticks",
        "_last_alert_ts",
        "_last_price_ticks",
        "_min_cooldown_ns",
        "_price_returns",
        "_recent_spreads",
        "_recent_volumes",
        "_seq",
        "_symbol",
        "_vol_window",
    )

    def __init__(
        self,
        symbol: str,
        vol_window: int = 30,
        min_cooldown_ns: int = 500_000_000,  # 500ms cooldown per anomaly type
    ) -> None:
        self._symbol = symbol
        self._vol_window = max(10, vol_window)
        self._min_cooldown_ns = min_cooldown_ns
        self._seq = 1

        self._last_price_ticks: int | None = None
        self._price_returns: deque[float] = deque(maxlen=self._vol_window)
        self._recent_volumes: deque[int] = deque(maxlen=50)
        self._recent_spreads: deque[int] = deque(maxlen=30)
        self._baseline_spread_ticks: float = 1.0

        # AnomalyType -> last emitted ts_ns
        self._last_alert_ts: dict[AnomalyType, int] = {}

    def _next_seq(self) -> int:
        s = self._seq
        self._seq += 1
        return s

    def _is_cooled_down(self, anomaly_type: AnomalyType, ts_ns: int) -> bool:
        """Check if enough time has passed since last alert of this type."""
        last_ts = self._last_alert_ts.get(anomaly_type)
        if last_ts is None:
            return True
        return (ts_ns - last_ts) >= self._min_cooldown_ns

    def update_trade(
        self,
        trade: TradeExecuted,
        tick_size: float = 0.01,
    ) -> list[MarketAnomaly]:
        """Evaluate incoming TradeExecuted for Price Shock and Volume Surge anomalies."""
        if trade.symbol != self._symbol:
            return []

        anomalies: list[MarketAnomaly] = []
        price_ticks = trade.price_ticks
        qty = trade.qty
        ts_ns = trade.ts_ns

        # 1. Volume Surge Detection
        if len(self._recent_volumes) >= 10:
            mean_vol = sum(self._recent_volumes) / len(self._recent_volumes)
            if mean_vol > 0 and qty >= 3.0 * mean_vol:
                severity = (
                    AnomalySeverity.CRITICAL if qty >= 5.0 * mean_vol else AnomalySeverity.WARNING
                )
                if self._is_cooled_down(AnomalyType.VOLUME_SURGE, ts_ns):
                    self._last_alert_ts[AnomalyType.VOLUME_SURGE] = ts_ns
                    anomalies.append(
                        MarketAnomaly(
                            seq=self._next_seq(),
                            ts_ns=ts_ns,
                            symbol=self._symbol,
                            anomaly_type=AnomalyType.VOLUME_SURGE,
                            severity=severity,
                            metric_value=float(qty),
                            threshold=round(3.0 * mean_vol, 1),
                            message=(
                                f"Large trade volume surge: {qty} shares "
                                f"({qty / mean_vol:.1f}x avg vol {mean_vol:.0f})"
                            ),
                        )
                    )
        self._recent_volumes.append(qty)

        # 2. Price Shock Detection (return > 3 * rolling std)
        if self._last_price_ticks is not None and self._last_price_ticks > 0:
            ret = (price_ticks - self._last_price_ticks) / self._last_price_ticks
            self._price_returns.append(ret)

            if len(self._price_returns) >= 15:
                mean_ret = sum(self._price_returns) / len(self._price_returns)
                var = sum((r - mean_ret) ** 2 for r in self._price_returns) / len(
                    self._price_returns
                )
                std_ret = math.sqrt(var)

                # At least 0.0005 minimum threshold to avoid micro noise
                threshold = max(0.001, 3.0 * std_ret)
                abs_ret = abs(ret)

                if abs_ret >= threshold and self._is_cooled_down(AnomalyType.PRICE_SHOCK, ts_ns):
                    severity = (
                        AnomalySeverity.CRITICAL
                        if abs_ret >= 1.5 * threshold
                        else AnomalySeverity.WARNING
                    )
                    self._last_alert_ts[AnomalyType.PRICE_SHOCK] = ts_ns
                    curr_price = ticks_to_price(price_ticks, tick_size)
                    ratio = abs_ret / max(std_ret, 1e-6)
                    anomalies.append(
                        MarketAnomaly(
                            seq=self._next_seq(),
                            ts_ns=ts_ns,
                            symbol=self._symbol,
                            anomaly_type=AnomalyType.PRICE_SHOCK,
                            severity=severity,
                            metric_value=round(abs_ret * 100, 3),
                            threshold=round(threshold * 100, 3),
                            message=(
                                f"Sharp price jump to ${curr_price:.2f} "
                                f"({ret * 100:+.2f}%, {ratio:.1f} std shock)"
                            ),
                        )
                    )

        self._last_price_ticks = price_ticks
        return anomalies

    def on_trade(
        self,
        trade: TradeExecuted,
        tick_size: float = 0.01,
    ) -> list[MarketAnomaly]:
        """Convenience alias for update_trade."""
        return self.update_trade(trade, tick_size)

    def update_book(
        self,
        best_bid: int | None,
        best_ask: int | None,
        total_bid_qty: int,
        total_ask_qty: int,
        ts_ns: int,
    ) -> list[MarketAnomaly]:
        """Evaluate order book state for Spread Blowout and Book Imbalance."""
        anomalies: list[MarketAnomaly] = []

        # 1. Spread Blowout Detection
        if best_bid is not None and best_ask is not None:
            spread_ticks = best_ask - best_bid
            if len(self._recent_spreads) >= 10:
                median_spread = sorted(self._recent_spreads)[len(self._recent_spreads) // 2]
                threshold_spread = max(3.0, 3.0 * median_spread)

                if spread_ticks >= threshold_spread and self._is_cooled_down(
                    AnomalyType.SPREAD_BLOWOUT, ts_ns
                ):
                    severity = (
                        AnomalySeverity.CRITICAL
                        if spread_ticks >= 5.0 * median_spread
                        else AnomalySeverity.WARNING
                    )
                    self._last_alert_ts[AnomalyType.SPREAD_BLOWOUT] = ts_ns
                    anomalies.append(
                        MarketAnomaly(
                            seq=self._next_seq(),
                            ts_ns=ts_ns,
                            symbol=self._symbol,
                            anomaly_type=AnomalyType.SPREAD_BLOWOUT,
                            severity=severity,
                            metric_value=float(spread_ticks),
                            threshold=float(threshold_spread),
                            message=(
                                f"Bid-ask spread blowout: {spread_ticks} ticks "
                                f"(median {median_spread} ticks)"
                            ),
                        )
                    )
            self._recent_spreads.append(spread_ticks)

        # 2. Book Imbalance (Liquidity Skew)
        total_depth = total_bid_qty + total_ask_qty
        if total_depth >= 100:
            skew = abs(total_bid_qty - total_ask_qty) / total_depth
            if skew >= 0.85 and self._is_cooled_down(AnomalyType.BOOK_IMBALANCE, ts_ns):
                dominant_side = "BUY" if total_bid_qty > total_ask_qty else "SELL"
                severity = (
                    AnomalySeverity.CRITICAL if skew >= 0.90 else AnomalySeverity.WARNING
                )
                self._last_alert_ts[AnomalyType.BOOK_IMBALANCE] = ts_ns
                anomalies.append(
                    MarketAnomaly(
                        seq=self._next_seq(),
                        ts_ns=ts_ns,
                        symbol=self._symbol,
                        anomaly_type=AnomalyType.BOOK_IMBALANCE,
                        severity=severity,
                        metric_value=round(skew * 100, 1),
                        threshold=85.0,
                        message=(
                            f"Extreme book imbalance: {skew * 100:.1f}% liquidity "
                            f"skewed toward {dominant_side}"
                        ),
                    )
                )

        return anomalies

    def on_book_update(
        self,
        symbol: str,
        ts_ns: int,
        best_bid_ticks: int | None,
        best_ask_ticks: int | None,
        total_bid_vol: int,
        total_ask_vol: int,
    ) -> list[MarketAnomaly]:
        """Convenience alias for update_book with symbol guard."""
        if symbol != self._symbol:
            return []
        return self.update_book(
            best_bid=best_bid_ticks,
            best_ask=best_ask_ticks,
            total_bid_qty=total_bid_vol,
            total_ask_qty=total_ask_vol,
            ts_ns=ts_ns,
        )
