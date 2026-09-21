"""Dual-mode technical indicators: Streaming (O(1) per bar) and Batch (NumPy/Pandas).

Invariants:
- Streaming implementations execute in O(1) time and memory per bar.
- Both streaming and batch versions return identical values within 1e-9 tolerance.
- Return None (streaming) or np.nan (batch) during warm-up. Never invent values.
- EMA seed is the arithmetic mean (SMA) of the first N observations.
- RSI uses Wilder's smoothing with period 14 default.
- Bollinger Bands use ddof=0 (population standard deviation) matching standard trading platforms.
- VWAP tracks cumulative price * volume divided by cumulative volume, resettable per session.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Result Data Structures
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class MACDResult:
    """Result tuple for Moving Average Convergence Divergence."""

    macd: float | None
    signal: float | None
    histogram: float | None


@dataclass(slots=True, frozen=True)
class BollingerBandsResult:
    """Result tuple for Bollinger Bands."""

    upper: float | None
    middle: float | None
    lower: float | None
    bandwidth: float | None


# ---------------------------------------------------------------------------
# 1. Simple Moving Average (SMA)
# ---------------------------------------------------------------------------


class StreamingSMA:
    """Streaming O(1) Simple Moving Average over a sliding window of period N."""

    __slots__ = ("_period", "_running_sum", "_window")

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._window: deque[float] = deque(maxlen=period)
        self._running_sum: float = 0.0

    def update(self, price: float) -> float | None:
        """Add price and return current SMA, or None during warm-up."""
        if len(self._window) == self._period:
            oldest = self._window[0]
            self._running_sum += price - oldest
        else:
            self._running_sum += price

        self._window.append(price)

        if len(self._window) < self._period:
            return None
        return self._running_sum / self._period

    def reset(self) -> None:
        """Reset state."""
        self._window.clear()
        self._running_sum = 0.0


def batch_sma(prices: Sequence[float] | np.ndarray, period: int) -> np.ndarray:
    """Batch calculation of SMA using Pandas rolling mean.

    Returns:
        NumPy array of floats where the first period-1 entries are np.nan.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    s = pd.Series(prices, dtype=np.float64)
    return np.asarray(
        s.rolling(window=period, min_periods=period).mean().to_numpy(), dtype=np.float64
    )


# ---------------------------------------------------------------------------
# 2. Exponential Moving Average (EMA)
# ---------------------------------------------------------------------------


class StreamingEMA:
    """Streaming O(1) Exponential Moving Average with SMA warm-up seed."""

    __slots__ = ("_alpha", "_count", "_current_ema", "_period", "_warmup_sum")

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._alpha = 2.0 / (period + 1)
        self._current_ema: float | None = None
        self._warmup_sum: float = 0.0
        self._count: int = 0

    def update(self, price: float) -> float | None:
        """Add price and return current EMA, or None during warm-up."""
        self._count += 1

        if self._count < self._period:
            self._warmup_sum += price
            return None

        if self._count == self._period:
            self._warmup_sum += price
            self._current_ema = self._warmup_sum / self._period
            return self._current_ema

        assert self._current_ema is not None
        self._current_ema = self._alpha * price + (1.0 - self._alpha) * self._current_ema
        return self._current_ema

    def reset(self) -> None:
        """Reset state."""
        self._current_ema = None
        self._warmup_sum = 0.0
        self._count = 0


def batch_ema(prices: Sequence[float] | np.ndarray, period: int) -> np.ndarray:
    """Batch calculation of EMA with arithmetic mean warm-up seed.

    Returns:
        NumPy array of floats where the first period-1 entries are np.nan.
    """
    n = len(prices)
    result = np.full(n, np.nan, dtype=np.float64)
    if n < period or period < 1:
        return result

    alpha = 2.0 / (period + 1)
    seed_val = float(np.mean(prices[:period]))
    result[period - 1] = seed_val

    ema = seed_val
    for i in range(period, n):
        ema = alpha * float(prices[i]) + (1.0 - alpha) * ema
        result[i] = ema

    return result


# ---------------------------------------------------------------------------
# 3. Relative Strength Index (RSI - Wilder's Smoothing)
# ---------------------------------------------------------------------------


class StreamingRSI:
    """Streaming O(1) RSI using Wilder's smoothing (period 14 default)."""

    __slots__ = (
        "_avg_gain",
        "_avg_loss",
        "_count",
        "_gains",
        "_last_price",
        "_losses",
        "_period",
    )

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._last_price: float | None = None
        self._gains: list[float] = []
        self._losses: list[float] = []
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self._count: int = 0

    def update(self, price: float) -> float | None:
        """Add price and return RSI (0..100), or None during warm-up."""
        if self._last_price is None:
            self._last_price = price
            return None

        diff = price - self._last_price
        self._last_price = price
        gain = max(0.0, diff)
        loss = max(0.0, -diff)

        self._count += 1

        if self._count < self._period:
            self._gains.append(gain)
            self._losses.append(loss)
            return None

        if self._count == self._period:
            self._gains.append(gain)
            self._losses.append(loss)
            self._avg_gain = sum(self._gains) / self._period
            self._avg_loss = sum(self._losses) / self._period
        else:
            assert self._avg_gain is not None and self._avg_loss is not None
            self._avg_gain = (self._avg_gain * (self._period - 1) + gain) / self._period
            self._avg_loss = (self._avg_loss * (self._period - 1) + loss) / self._period

        if self._avg_loss == 0.0:
            return 100.0 if self._avg_gain > 0.0 else 50.0

        rs = self._avg_gain / self._avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def reset(self) -> None:
        """Reset state."""
        self._last_price = None
        self._gains.clear()
        self._losses.clear()
        self._avg_gain = None
        self._avg_loss = None
        self._count = 0


def batch_rsi(prices: Sequence[float] | np.ndarray, period: int = 14) -> np.ndarray:
    """Batch calculation of RSI using Wilder's smoothing.

    Returns:
        NumPy array of floats where the first period entries are np.nan.
    """
    n = len(prices)
    result = np.full(n, np.nan, dtype=np.float64)
    if n <= period or period < 1:
        return result

    diffs = np.diff(prices)
    gains = np.maximum(diffs, 0.0)
    losses = np.maximum(-diffs, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    def calc_rsi(ag: float, al: float) -> float:
        if al == 0.0:
            return 100.0 if ag > 0.0 else 50.0
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs))

    result[period] = calc_rsi(avg_gain, avg_loss)

    for i in range(period, len(diffs)):
        avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
        avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period
        result[i + 1] = calc_rsi(avg_gain, avg_loss)

    return result


# ---------------------------------------------------------------------------
# 4. Moving Average Convergence Divergence (MACD)
# ---------------------------------------------------------------------------


class StreamingMACD:
    """Streaming O(1) MACD (fast=12, slow=26, signal=9)."""

    __slots__ = ("_fast_ema", "_signal_ema", "_slow_ema")

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be < slow ({slow})")
        self._fast_ema = StreamingEMA(fast)
        self._slow_ema = StreamingEMA(slow)
        self._signal_ema = StreamingEMA(signal)

    def update(self, price: float) -> MACDResult:
        """Add price and return MACDResult."""
        fast_val = self._fast_ema.update(price)
        slow_val = self._slow_ema.update(price)

        if fast_val is None or slow_val is None:
            return MACDResult(macd=None, signal=None, histogram=None)

        macd_line = fast_val - slow_val
        signal_line = self._signal_ema.update(macd_line)
        histogram = (macd_line - signal_line) if signal_line is not None else None

        return MACDResult(macd=macd_line, signal=signal_line, histogram=histogram)

    def reset(self) -> None:
        """Reset state."""
        self._fast_ema.reset()
        self._slow_ema.reset()
        self._signal_ema.reset()


def batch_macd(
    prices: Sequence[float] | np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Batch calculation of MACD line, signal line, and histogram.

    Returns:
        Tuple of (macd_line, signal_line, histogram) NumPy arrays.
    """
    fast_arr = batch_ema(prices, fast)
    slow_arr = batch_ema(prices, slow)

    macd_line = fast_arr - slow_arr

    # To compute signal line matching streaming, feed non-nan macd values to batch_ema
    n = len(prices)
    signal_line = np.full(n, np.nan, dtype=np.float64)
    valid_idx = np.where(~np.isnan(macd_line))[0]

    if len(valid_idx) >= signal:
        valid_macd = macd_line[valid_idx]
        sig_valid = batch_ema(valid_macd, signal)
        signal_line[valid_idx] = sig_valid

    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ---------------------------------------------------------------------------
# 5. Bollinger Bands
# ---------------------------------------------------------------------------


class StreamingBollingerBands:
    """Streaming O(1) Bollinger Bands (period=20, num_std=2.0)."""

    __slots__ = ("_num_std", "_period", "_sum", "_sum_sq", "_window")

    def __init__(self, period: int = 20, num_std: float = 2.0) -> None:
        if period < 2:
            raise ValueError(f"period must be >= 2, got {period}")
        if num_std <= 0:
            raise ValueError(f"num_std must be positive, got {num_std}")
        self._period = period
        self._num_std = num_std
        self._window: deque[float] = deque(maxlen=period)
        self._sum: float = 0.0
        self._sum_sq: float = 0.0

    def update(self, price: float) -> BollingerBandsResult:
        """Add price and return BollingerBandsResult."""
        if len(self._window) == self._period:
            oldest = self._window[0]
            self._sum += price - oldest
            self._sum_sq += price * price - oldest * oldest
        else:
            self._sum += price
            self._sum_sq += price * price

        self._window.append(price)

        if len(self._window) < self._period:
            return BollingerBandsResult(upper=None, middle=None, lower=None, bandwidth=None)

        middle = self._sum / self._period
        variance = max(0.0, (self._sum_sq / self._period) - (middle * middle))
        std_dev = math.sqrt(variance)

        upper = middle + self._num_std * std_dev
        lower = middle - self._num_std * std_dev
        bandwidth = ((upper - lower) / middle) if middle > 0 else 0.0

        return BollingerBandsResult(upper=upper, middle=middle, lower=lower, bandwidth=bandwidth)

    def reset(self) -> None:
        """Reset state."""
        self._window.clear()
        self._sum = 0.0
        self._sum_sq = 0.0


def batch_bollinger_bands(
    prices: Sequence[float] | np.ndarray,
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Batch calculation of Bollinger Bands using ddof=0 population standard deviation.

    Returns:
        Tuple of (upper, middle, lower, bandwidth) NumPy arrays.
    """
    s = pd.Series(prices, dtype=np.float64)
    middle = np.asarray(
        s.rolling(window=period, min_periods=period).mean().to_numpy(), dtype=np.float64
    )
    std = np.asarray(
        s.rolling(window=period, min_periods=period).std(ddof=0).to_numpy(), dtype=np.float64
    )

    upper = middle + num_std * std
    lower = middle - num_std * std
    bandwidth = np.where(middle > 0, (upper - lower) / middle, 0.0)

    return upper, middle, lower, bandwidth


# ---------------------------------------------------------------------------
# 6. Volume Weighted Average Price (VWAP)
# ---------------------------------------------------------------------------


class StreamingVWAP:
    """Streaming O(1) session-cumulative Volume Weighted Average Price."""

    __slots__ = ("_cum_pv", "_cum_v")

    def __init__(self) -> None:
        self._cum_pv: float = 0.0
        self._cum_v: float = 0.0

    def update(self, price: float, volume: float) -> float | None:
        """Add price and volume, return cumulative VWAP."""
        if volume <= 0:
            return (self._cum_pv / self._cum_v) if self._cum_v > 0 else None
        self._cum_pv += price * volume
        self._cum_v += volume
        return self._cum_pv / self._cum_v

    def reset(self) -> None:
        """Reset state for a new session."""
        self._cum_pv = 0.0
        self._cum_v = 0.0


def batch_vwap(
    prices: Sequence[float] | np.ndarray,
    volumes: Sequence[float] | np.ndarray,
) -> np.ndarray:
    """Batch calculation of cumulative VWAP."""
    p = np.asarray(prices, dtype=np.float64)
    v = np.asarray(volumes, dtype=np.float64)
    cum_pv = np.cumsum(p * v)
    cum_v = np.cumsum(v)
    return np.where(cum_v > 0, cum_pv / cum_v, np.nan)


# ---------------------------------------------------------------------------
# 7. Log Returns & Rolling Realized Volatility
# ---------------------------------------------------------------------------


class StreamingRollingVolatility:
    """Streaming O(1) rolling realized volatility of log returns."""

    __slots__ = (
        "_annualize_factor",
        "_last_price",
        "_returns",
        "_sum_r",
        "_sum_r_sq",
        "_window",
    )

    def __init__(self, window: int = 20, annualize_factor: float | None = None) -> None:
        if window < 2:
            raise ValueError(f"window must be >= 2, got {window}")
        self._window = window
        self._annualize_factor = annualize_factor
        self._last_price: float | None = None
        self._returns: deque[float] = deque(maxlen=window)
        self._sum_r: float = 0.0
        self._sum_r_sq: float = 0.0

    def update(self, price: float) -> float | None:
        """Add price and return rolling volatility of log returns."""
        if self._last_price is None or self._last_price <= 0 or price <= 0:
            self._last_price = price
            return None

        r = math.log(price / self._last_price)
        self._last_price = price

        if len(self._returns) == self._window:
            old_r = self._returns[0]
            self._sum_r += r - old_r
            self._sum_r_sq += r * r - old_r * old_r
        else:
            self._sum_r += r
            self._sum_r_sq += r * r

        self._returns.append(r)

        if len(self._returns) < self._window:
            return None

        # Sample standard deviation (ddof=1)
        mean_r = self._sum_r / self._window
        var = max(0.0, (self._sum_r_sq - self._window * mean_r * mean_r) / (self._window - 1))
        vol = math.sqrt(var)

        if self._annualize_factor is not None:
            vol *= self._annualize_factor
        return vol

    def reset(self) -> None:
        """Reset state."""
        self._last_price = None
        self._returns.clear()
        self._sum_r = 0.0
        self._sum_r_sq = 0.0


def batch_realized_volatility(
    prices: Sequence[float] | np.ndarray,
    window: int = 20,
    annualize_factor: float | None = None,
) -> np.ndarray:
    """Batch calculation of rolling sample standard deviation of log returns."""
    p = np.asarray(prices, dtype=np.float64)
    n = len(p)
    result = np.full(n, np.nan, dtype=np.float64)
    if n <= window:
        return result

    log_returns = np.diff(np.log(p))
    s = pd.Series(log_returns, dtype=np.float64)
    rolling_std = np.asarray(
        s.rolling(window=window, min_periods=window).std(ddof=1).to_numpy(), dtype=np.float64
    )

    if annualize_factor is not None:
        rolling_std *= annualize_factor

    result[window:] = rolling_std[window - 1 :]
    return result


# ---------------------------------------------------------------------------
# 8. Volume Trend
# ---------------------------------------------------------------------------


class StreamingVolumeTrend:
    """Streaming O(1) ratio of current volume vs rolling SMA(20) of volume."""

    __slots__ = ("_period", "_sum_v", "_window")

    def __init__(self, period: int = 20) -> None:
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        self._period = period
        self._window: deque[float] = deque(maxlen=period)
        self._sum_v: float = 0.0

    def update(self, volume: float) -> float | None:
        """Add volume and return ratio of volume to rolling average volume."""
        if len(self._window) == self._period:
            oldest = self._window[0]
            self._sum_v += volume - oldest
        else:
            self._sum_v += volume

        self._window.append(volume)

        if len(self._window) < self._period:
            return None

        avg_v = self._sum_v / self._period
        return (volume / avg_v) if avg_v > 0 else 1.0

    def reset(self) -> None:
        """Reset state."""
        self._window.clear()
        self._sum_v = 0.0


def batch_volume_trend(
    volumes: Sequence[float] | np.ndarray,
    period: int = 20,
) -> np.ndarray:
    """Batch calculation of volume trend ratio (V / SMA(V))."""
    v = np.asarray(volumes, dtype=np.float64)
    s = pd.Series(v, dtype=np.float64)
    sma_v = np.asarray(
        s.rolling(window=period, min_periods=period).mean().to_numpy(), dtype=np.float64
    )
    return np.where(sma_v > 0, v / sma_v, np.nan)
