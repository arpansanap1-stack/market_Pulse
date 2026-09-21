"""Incremental OHLC multi-timeframe aggregation engine.

Invariants:
- Aggregation is strictly incremental and executes in O(1) per trade.
- Internal bar prices are stored as integer ticks
  (open_ticks, high_ticks, low_ticks, close_ticks, vwap_ticks).
- Empty intervals carry forward the previous close with volume=0 and trade_count=0.
- Bar intervals align strictly to epoch-based boundaries:
  start_ts_ns = (ts_ns // interval_ns) * interval_ns.
- Trades arrive in monotonic sequence; out-of-order events raise ValueError.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from marketpulse.core.events import TradeExecuted, ticks_to_price

INTERVAL_TO_NS: dict[str, int] = {
    "1s": 1_000_000_000,
    "5s": 5_000_000_000,
    "15s": 15_000_000_000,
    "1m": 60_000_000_000,
    "5m": 300_000_000_000,
    "15m": 900_000_000_000,
    "1h": 3_600_000_000_000,
}


@dataclass(slots=True, frozen=True)
class Bar:
    """Immutable OHLC bar representation with integer price ticks and volume."""

    symbol: str
    interval: str
    start_ts_ns: int
    end_ts_ns: int
    open_ticks: int
    high_ticks: int
    low_ticks: int
    close_ticks: int
    volume: int
    trade_count: int
    vwap_ticks: int
    is_closed: bool = False

    def to_dict(self, tick_size: float = 0.01) -> dict[str, Any]:
        """Convert bar to dictionary with decimal currency values for API and charts."""
        time_sec = self.start_ts_ns // 1_000_000_000
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "time": time_sec,
            "start_ts_ns": self.start_ts_ns,
            "end_ts_ns": self.end_ts_ns,
            "open": ticks_to_price(self.open_ticks, tick_size),
            "high": ticks_to_price(self.high_ticks, tick_size),
            "low": ticks_to_price(self.low_ticks, tick_size),
            "close": ticks_to_price(self.close_ticks, tick_size),
            "volume": self.volume,
            "trade_count": self.trade_count,
            "vwap": ticks_to_price(self.vwap_ticks, tick_size),
            "is_closed": self.is_closed,
        }


class _IntervalState:
    """Internal mutable aggregation accumulator for a single timeframe interval."""

    __slots__ = (
        "_close_ticks",
        "_high_ticks",
        "_history",
        "_interval",
        "_interval_ns",
        "_low_ticks",
        "_open_ticks",
        "_pv_sum",
        "_start_ts_ns",
        "_symbol",
        "_trade_count",
        "_volume",
    )

    def __init__(self, symbol: str, interval: str, interval_ns: int, max_history: int) -> None:
        self._symbol = symbol
        self._interval = interval
        self._interval_ns = interval_ns
        self._history: deque[Bar] = deque(maxlen=max_history)

        self._start_ts_ns: int | None = None
        self._open_ticks: int = 0
        self._high_ticks: int = 0
        self._low_ticks: int = 0
        self._close_ticks: int = 0
        self._volume: int = 0
        self._trade_count: int = 0
        self._pv_sum: int = 0

    @property
    def current_bar(self) -> Bar | None:
        """Return current in-progress bar or None if uninitialized."""
        if self._start_ts_ns is None:
            return None
        vwap_ticks = round(self._pv_sum / self._volume) if self._volume > 0 else self._close_ticks
        return Bar(
            symbol=self._symbol,
            interval=self._interval,
            start_ts_ns=self._start_ts_ns,
            end_ts_ns=self._start_ts_ns + self._interval_ns,
            open_ticks=self._open_ticks,
            high_ticks=self._high_ticks,
            low_ticks=self._low_ticks,
            close_ticks=self._close_ticks,
            volume=self._volume,
            trade_count=self._trade_count,
            vwap_ticks=vwap_ticks,
            is_closed=False,
        )

    def update_trade(self, trade: TradeExecuted) -> list[Bar]:
        """Update interval with a new trade.

        Returns:
            List of closed bars (if interval boundaries crossed), plus the updated active bar.
        """
        trade_ts = trade.ts_ns
        bucket_start = (trade_ts // self._interval_ns) * self._interval_ns
        results: list[Bar] = []

        # Initial bar initialization
        if self._start_ts_ns is None:
            self._start_ts_ns = bucket_start
            self._open_ticks = trade.price_ticks
            self._high_ticks = trade.price_ticks
            self._low_ticks = trade.price_ticks
            self._close_ticks = trade.price_ticks
            self._volume = trade.qty
            self._trade_count = 1
            self._pv_sum = trade.price_ticks * trade.qty

            active = self.current_bar
            assert active is not None
            results.append(active)
            return results

        # Trade falls within current active interval
        if bucket_start == self._start_ts_ns:
            self._high_ticks = max(self._high_ticks, trade.price_ticks)
            self._low_ticks = min(self._low_ticks, trade.price_ticks)
            self._close_ticks = trade.price_ticks
            self._volume += trade.qty
            self._trade_count += 1
            self._pv_sum += trade.price_ticks * trade.qty

            active = self.current_bar
            assert active is not None
            results.append(active)
            return results

        # Boundary crossed: close current active bar
        vwap_ticks = round(self._pv_sum / self._volume) if self._volume > 0 else self._close_ticks
        closed_bar = Bar(
            symbol=self._symbol,
            interval=self._interval,
            start_ts_ns=self._start_ts_ns,
            end_ts_ns=self._start_ts_ns + self._interval_ns,
            open_ticks=self._open_ticks,
            high_ticks=self._high_ticks,
            low_ticks=self._low_ticks,
            close_ticks=self._close_ticks,
            volume=self._volume,
            trade_count=self._trade_count,
            vwap_ticks=vwap_ticks,
            is_closed=True,
        )
        self._history.append(closed_bar)
        results.append(closed_bar)

        prev_close = self._close_ticks

        # Forward-fill empty intervals if any gaps occurred between old bucket and new bucket
        next_bucket = self._start_ts_ns + self._interval_ns
        while next_bucket < bucket_start:
            empty_bar = Bar(
                symbol=self._symbol,
                interval=self._interval,
                start_ts_ns=next_bucket,
                end_ts_ns=next_bucket + self._interval_ns,
                open_ticks=prev_close,
                high_ticks=prev_close,
                low_ticks=prev_close,
                close_ticks=prev_close,
                volume=0,
                trade_count=0,
                vwap_ticks=prev_close,
                is_closed=True,
            )
            self._history.append(empty_bar)
            results.append(empty_bar)
            next_bucket += self._interval_ns

        # Initialize the new active bar
        self._start_ts_ns = bucket_start
        self._open_ticks = trade.price_ticks
        self._high_ticks = trade.price_ticks
        self._low_ticks = trade.price_ticks
        self._close_ticks = trade.price_ticks
        self._volume = trade.qty
        self._trade_count = 1
        self._pv_sum = trade.price_ticks * trade.qty

        active = self.current_bar
        assert active is not None
        results.append(active)
        return results


class OHLCAggregator:
    """Multi-timeframe OHLC aggregator tracking real-time bars across configurable intervals."""

    def __init__(
        self,
        symbol: str,
        intervals: tuple[str, ...] = ("1s", "5s", "15s", "1m", "5m", "15m", "1h"),
        max_history_per_interval: int = 500,
    ) -> None:
        """Initialize multi-interval OHLC aggregator.

        Args:
            symbol: Ticker symbol to aggregate.
            intervals: Tuple of interval string codes.
            max_history_per_interval: Maximum closed bars retained per interval in memory.

        Raises:
            ValueError: If an interval code is unknown.
        """
        self._symbol = symbol
        self._intervals = intervals
        self._states: dict[str, _IntervalState] = {}
        self._last_trade_ts_ns: int = -1

        for interval in intervals:
            if interval not in INTERVAL_TO_NS:
                raise ValueError(f"Unknown interval '{interval}'. Valid: {list(INTERVAL_TO_NS)}")
            interval_ns = INTERVAL_TO_NS[interval]
            self._states[interval] = _IntervalState(
                symbol=symbol,
                interval=interval,
                interval_ns=interval_ns,
                max_history=max_history_per_interval,
            )

    @property
    def symbol(self) -> str:
        """Return symbol being aggregated."""
        return self._symbol

    @property
    def intervals(self) -> tuple[str, ...]:
        """Return configured intervals."""
        return self._intervals

    def update_trade(self, trade: TradeExecuted) -> dict[str, list[Bar]]:
        """Process an incoming trade and update all tracked intervals in O(1).

        Args:
            trade: TradeExecuted event from the market feed.

        Returns:
            Dictionary mapping interval name to list of emitted bars
            (closed bars followed by current active bar).

        Raises:
            ValueError: If trade timestamp is out of order or symbol mismatches.
        """
        if trade.symbol != self._symbol:
            raise ValueError(f"Symbol mismatch: expected '{self._symbol}', got '{trade.symbol}'")
        if trade.ts_ns < self._last_trade_ts_ns:
            raise ValueError(
                f"Out-of-order trade timestamp: {trade.ts_ns} < {self._last_trade_ts_ns}"
            )

        self._last_trade_ts_ns = trade.ts_ns
        updates: dict[str, list[Bar]] = {}

        for interval, state in self._states.items():
            updates[interval] = state.update_trade(trade)

        return updates

    def get_history(self, interval: str, limit: int | None = None) -> list[Bar]:
        """Return closed historical bars for a given interval.

        Args:
            interval: Interval string code (e.g. '1s', '1m').
            limit: Optional maximum number of recent closed bars to return.

        Returns:
            List of closed Bar instances ordered from oldest to newest.
        """
        state = self._states.get(interval)
        if state is None:
            raise ValueError(f"Interval '{interval}' not configured")
        bars = list(state._history)
        return bars[-limit:] if limit is not None and limit > 0 else bars

    def get_current_bar(self, interval: str) -> Bar | None:
        """Return currently active unclosed bar for interval."""
        state = self._states.get(interval)
        return state.current_bar if state is not None else None
