"""Unit and golden tests for streaming and batch technical indicators."""

import math

import numpy as np
import pytest

from marketpulse.core.indicators import (
    StreamingBollingerBands,
    StreamingEMA,
    StreamingMACD,
    StreamingRollingVolatility,
    StreamingRSI,
    StreamingSMA,
    StreamingVolumeTrend,
    StreamingVWAP,
    batch_bollinger_bands,
    batch_ema,
    batch_macd,
    batch_realized_volatility,
    batch_rsi,
    batch_sma,
    batch_volume_trend,
    batch_vwap,
)


@pytest.fixture
def sample_prices() -> list[float]:
    """Generate realistic price series for indicator testing."""
    rng = np.random.default_rng(42)
    # 200 price points starting from 100 with 1% random returns
    returns = rng.normal(0.0005, 0.015, size=200)
    prices = 100.0 * np.exp(np.cumsum(returns))
    return [float(p) for p in prices]


@pytest.fixture
def sample_volumes() -> list[float]:
    """Generate volume series for indicator testing."""
    rng = np.random.default_rng(123)
    volumes = rng.integers(10, 500, size=200)
    return [float(v) for v in volumes]


# ---------------------------------------------------------------------------
# 1. SMA Tests
# ---------------------------------------------------------------------------


def test_sma_streaming_vs_batch_golden(sample_prices: list[float]) -> None:
    """Golden test: Streaming SMA identically matches batch SMA to within 1e-9 tolerance."""
    period = 20
    streaming = StreamingSMA(period=period)
    stream_results: list[float | None] = []

    for p in sample_prices:
        stream_results.append(streaming.update(p))

    batch_results = batch_sma(sample_prices, period=period)

    assert len(stream_results) == len(batch_results)

    # Warm-up check: first period-1 entries must be None / NaN
    for i in range(period - 1):
        assert stream_results[i] is None
        assert np.isnan(batch_results[i])

    # Value check from period-1 onwards
    for i in range(period - 1, len(sample_prices)):
        val = stream_results[i]
        assert val is not None
        assert math.isclose(val, batch_results[i], rel_tol=1e-9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 2. EMA Tests
# ---------------------------------------------------------------------------


def test_ema_streaming_vs_batch_golden(sample_prices: list[float]) -> None:
    """Golden test: Streaming EMA identically matches batch EMA to within 1e-9 tolerance."""
    period = 14
    streaming = StreamingEMA(period=period)
    stream_results: list[float | None] = []

    for p in sample_prices:
        stream_results.append(streaming.update(p))

    batch_results = batch_ema(sample_prices, period=period)

    assert len(stream_results) == len(batch_results)

    # Warm-up check: first period-1 entries must be None / NaN
    for i in range(period - 1):
        assert stream_results[i] is None
        assert np.isnan(batch_results[i])

    # Seed check at bar period-1
    seed_val = stream_results[period - 1]
    assert seed_val is not None
    assert math.isclose(
        seed_val,
        batch_results[period - 1],
        rel_tol=1e-9,
        abs_tol=1e-9,
    )

    # Subsequent values check
    for i in range(period, len(sample_prices)):
        val = stream_results[i]
        assert val is not None
        assert math.isclose(val, batch_results[i], rel_tol=1e-9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 3. RSI Tests
# ---------------------------------------------------------------------------


def test_rsi_streaming_vs_batch_golden(sample_prices: list[float]) -> None:
    """Golden test: Streaming Wilder RSI matches batch RSI to within 1e-9 tolerance."""
    period = 14
    streaming = StreamingRSI(period=period)
    stream_results: list[float | None] = []

    for p in sample_prices:
        stream_results.append(streaming.update(p))

    batch_results = batch_rsi(sample_prices, period=period)

    assert len(stream_results) == len(batch_results)

    # Warm-up check: first period entries (14 price diffs require 15 prices: index 0..13)
    for i in range(period):
        assert stream_results[i] is None
        assert np.isnan(batch_results[i])

    # Values check
    for i in range(period, len(sample_prices)):
        val = stream_results[i]
        assert val is not None
        assert math.isclose(val, batch_results[i], rel_tol=1e-9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 4. MACD Tests
# ---------------------------------------------------------------------------


def test_macd_streaming_vs_batch_golden(sample_prices: list[float]) -> None:
    """Golden test: Streaming MACD matches batch MACD to within 1e-9 tolerance."""
    fast, slow, signal = 12, 26, 9
    streaming = StreamingMACD(fast=fast, slow=slow, signal=signal)

    stream_macd: list[float | None] = []
    stream_signal: list[float | None] = []
    stream_hist: list[float | None] = []

    for p in sample_prices:
        res = streaming.update(p)
        stream_macd.append(res.macd)
        stream_signal.append(res.signal)
        stream_hist.append(res.histogram)

    batch_m, batch_s, batch_h = batch_macd(sample_prices, fast=fast, slow=slow, signal=signal)

    assert len(stream_macd) == len(batch_m)

    # Check MACD Line
    for i in range(len(sample_prices)):
        m_val = stream_macd[i]
        if m_val is None:
            assert np.isnan(batch_m[i])
        else:
            assert math.isclose(m_val, batch_m[i], rel_tol=1e-9, abs_tol=1e-9)

    # Check Signal Line and Histogram
    for i in range(len(sample_prices)):
        s_val = stream_signal[i]
        h_val = stream_hist[i]
        if s_val is None:
            assert np.isnan(batch_s[i])
            assert h_val is None
            assert np.isnan(batch_h[i])
        else:
            assert math.isclose(s_val, batch_s[i], rel_tol=1e-9, abs_tol=1e-9)
            assert h_val is not None
            assert math.isclose(h_val, batch_h[i], rel_tol=1e-9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 5. Bollinger Bands Tests
# ---------------------------------------------------------------------------


def test_bollinger_bands_streaming_vs_batch_golden(sample_prices: list[float]) -> None:
    """Golden test: Streaming Bollinger Bands matches batch calculation within 1e-9 tolerance."""
    period = 20
    streaming = StreamingBollingerBands(period=period, num_std=2.0)

    stream_upper: list[float | None] = []
    stream_middle: list[float | None] = []
    stream_lower: list[float | None] = []
    stream_bandwidth: list[float | None] = []

    for p in sample_prices:
        res = streaming.update(p)
        stream_upper.append(res.upper)
        stream_middle.append(res.middle)
        stream_lower.append(res.lower)
        stream_bandwidth.append(res.bandwidth)

    batch_u, batch_m, batch_l, batch_bw = batch_bollinger_bands(
        sample_prices, period=period, num_std=2.0
    )

    # Warm-up check
    for i in range(period - 1):
        assert stream_upper[i] is None
        assert np.isnan(batch_u[i])

    # Value checks
    for i in range(period - 1, len(sample_prices)):
        up_val = stream_upper[i]
        mid_val = stream_middle[i]
        low_val = stream_lower[i]
        bw_val = stream_bandwidth[i]
        assert up_val is not None
        assert mid_val is not None
        assert low_val is not None
        assert bw_val is not None

        assert math.isclose(up_val, batch_u[i], rel_tol=1e-9, abs_tol=1e-9)
        assert math.isclose(mid_val, batch_m[i], rel_tol=1e-9, abs_tol=1e-9)
        assert math.isclose(low_val, batch_l[i], rel_tol=1e-9, abs_tol=1e-9)
        assert math.isclose(bw_val, batch_bw[i], rel_tol=1e-9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 6. VWAP Tests
# ---------------------------------------------------------------------------


def test_vwap_streaming_vs_batch_golden(
    sample_prices: list[float],
    sample_volumes: list[float],
) -> None:
    """Golden test: Streaming VWAP matches batch cumulative VWAP within 1e-9 tolerance."""
    streaming = StreamingVWAP()
    stream_results: list[float | None] = []

    for p, v in zip(sample_prices, sample_volumes, strict=True):
        stream_results.append(streaming.update(p, v))

    batch_results = batch_vwap(sample_prices, sample_volumes)

    for s_val, b_val in zip(stream_results, batch_results, strict=True):
        assert s_val is not None
        assert math.isclose(s_val, b_val, rel_tol=1e-9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 7. Realized Volatility Tests
# ---------------------------------------------------------------------------


def test_realized_volatility_streaming_vs_batch_golden(sample_prices: list[float]) -> None:
    """Golden test: Streaming realized volatility matches batch calculation."""
    window = 20
    streaming = StreamingRollingVolatility(window=window)
    stream_results: list[float | None] = []

    for p in sample_prices:
        stream_results.append(streaming.update(p))

    batch_results = batch_realized_volatility(sample_prices, window=window)

    for i in range(window):
        assert stream_results[i] is None
        assert np.isnan(batch_results[i])

    for i in range(window, len(sample_prices)):
        v_val = stream_results[i]
        assert v_val is not None
        assert math.isclose(v_val, batch_results[i], rel_tol=1e-9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 8. Volume Trend Tests
# ---------------------------------------------------------------------------


def test_volume_trend_streaming_vs_batch_golden(sample_volumes: list[float]) -> None:
    """Golden test: Streaming volume trend matches batch calculation."""
    period = 20
    streaming = StreamingVolumeTrend(period=period)
    stream_results: list[float | None] = []

    for v in sample_volumes:
        stream_results.append(streaming.update(v))

    batch_results = batch_volume_trend(sample_volumes, period=period)

    for i in range(period - 1):
        assert stream_results[i] is None
        assert np.isnan(batch_results[i])

    for i in range(period - 1, len(sample_volumes)):
        vt_val = stream_results[i]
        assert vt_val is not None
        assert math.isclose(vt_val, batch_results[i], rel_tol=1e-9, abs_tol=1e-9)
