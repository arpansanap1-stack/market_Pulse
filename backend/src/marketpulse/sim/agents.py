"""Simulated trading agents generating deterministic two-sided order flow.

Agents:
- MarketMakerAgent: Quotes two-sided liquidity around mid-price across multiple levels.
- NoiseTraderAgent: Generates stochastic liquidity-taking and liquidity-providing orders.
- TrendFollowerAgent: Momentum-based directional orders.
"""

from __future__ import annotations

from collections import deque
from typing import Protocol, runtime_checkable

import numpy as np

from marketpulse.core.events import (
    MarketEvent,
    OrderSubmitted,
    OrderType,
    Side,
    TimeInForce,
)


@runtime_checkable
class Agent(Protocol):
    """Protocol for simulated autonomous market participants."""

    @property
    def agent_id(self) -> str:
        """Unique identifier for this agent."""
        ...

    def generate_orders(
        self,
        symbol: str,
        best_bid: int | None,
        best_ask: int | None,
        ref_price_ticks: int,
        seq_start: int,
        ts_ns: int,
    ) -> list[OrderSubmitted]:
        """Generate next batch of orders based on current market state."""
        ...

    def on_market_event(self, event: MarketEvent) -> None:
        """Handle incoming market shock or regime shift."""
        ...

    def reset(self, rng: np.random.Generator) -> None:
        """Reset agent state and RNG."""
        ...


class MarketMakerAgent:
    """Provides two-sided liquidity around mid-price across multiple depth levels."""

    __slots__ = (
        "_active_orders",
        "_base_half_spread_ticks",
        "_half_spread_ticks",
        "_levels",
        "_order_counter",
        "_qty_per_level",
        "_rng",
        "agent_id",
    )

    def __init__(
        self,
        agent_id: str,
        rng: np.random.Generator,
        half_spread_ticks: int = 2,
        levels: int = 3,
        qty_per_level: int = 50,
    ) -> None:
        self.agent_id = agent_id
        self._rng = rng
        self._base_half_spread_ticks = max(1, half_spread_ticks)
        self._half_spread_ticks = self._base_half_spread_ticks
        self._levels = max(1, levels)
        self._qty_per_level = max(1, qty_per_level)
        self._order_counter = 0
        self._active_orders: list[str] = []

    def reset(self, rng: np.random.Generator) -> None:
        """Reset state with new RNG."""
        self._rng = rng
        self._half_spread_ticks = self._base_half_spread_ticks
        self._order_counter = 0
        self._active_orders.clear()

    def on_market_event(self, event: MarketEvent) -> None:
        """Adjust quoting spread and volume on market events."""
        if event.kind == "VOLATILITY_REGIME":
            mult = float(event.params.get("volatility_multiplier", 1.0))
            self._half_spread_ticks = max(1, round(self._base_half_spread_ticks * mult))
        elif event.kind == "EARNINGS_SHOCK":
            mult = float(event.params.get("volatility_multiplier", 2.0))
            self._half_spread_ticks = max(1, round(self._base_half_spread_ticks * mult))

    def generate_orders(
        self,
        symbol: str,
        best_bid: int | None,
        best_ask: int | None,
        ref_price_ticks: int,
        seq_start: int,
        ts_ns: int,
    ) -> list[OrderSubmitted]:
        """Generate layered bids and asks around mid/ref price."""
        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) // 2
        else:
            mid = ref_price_ticks

        orders: list[OrderSubmitted] = []
        curr_seq = seq_start

        # Post bids below mid
        for level in range(self._levels):
            bid_price = max(1, mid - self._half_spread_ticks - level)
            jitter = int(self._rng.integers(-5, 6))
            qty = max(10, self._qty_per_level + jitter)
            self._order_counter += 1
            order_id = f"{self.agent_id}_b_{self._order_counter}"
            orders.append(
                OrderSubmitted(
                    seq=curr_seq,
                    ts_ns=ts_ns,
                    symbol=symbol,
                    order_id=order_id,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    price_ticks=bid_price,
                    qty=qty,
                    tif=TimeInForce.GTC,
                )
            )
            curr_seq += 1

        # Post asks above mid
        for level in range(self._levels):
            ask_price = max(mid + 1, mid + self._half_spread_ticks + level)
            jitter = int(self._rng.integers(-5, 6))
            qty = max(10, self._qty_per_level + jitter)
            self._order_counter += 1
            order_id = f"{self.agent_id}_s_{self._order_counter}"
            orders.append(
                OrderSubmitted(
                    seq=curr_seq,
                    ts_ns=ts_ns,
                    symbol=symbol,
                    order_id=order_id,
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    price_ticks=ask_price,
                    qty=qty,
                    tif=TimeInForce.GTC,
                )
            )
            curr_seq += 1

        return orders


class NoiseTraderAgent:
    """Generates stochastic market and limit orders to simulate retail/liquidity flow."""

    __slots__ = (
        "_base_market_order_prob",
        "_base_price_jitter",
        "_market_order_prob",
        "_order_counter",
        "_price_jitter",
        "_rng",
        "agent_id",
    )

    def __init__(
        self,
        agent_id: str,
        rng: np.random.Generator,
        market_order_prob: float = 0.35,
        price_jitter: int = 3,
    ) -> None:
        self.agent_id = agent_id
        self._rng = rng
        self._base_market_order_prob = market_order_prob
        self._market_order_prob = market_order_prob
        self._base_price_jitter = price_jitter
        self._price_jitter = price_jitter
        self._order_counter = 0

    def reset(self, rng: np.random.Generator) -> None:
        """Reset state."""
        self._rng = rng
        self._market_order_prob = self._base_market_order_prob
        self._price_jitter = self._base_price_jitter
        self._order_counter = 0

    def on_market_event(self, event: MarketEvent) -> None:
        """Adjust noise trader behavior on market events."""
        if event.kind == "VOLATILITY_REGIME":
            mult = float(event.params.get("volatility_multiplier", 1.0))
            self._price_jitter = max(1, round(self._base_price_jitter * mult))
            self._market_order_prob = min(0.8, self._base_market_order_prob * mult)
        elif event.kind == "EARNINGS_SHOCK":
            mult = float(event.params.get("volatility_multiplier", 2.0))
            self._price_jitter = max(1, round(self._base_price_jitter * mult))
            self._market_order_prob = min(0.8, self._base_market_order_prob * mult)

    def generate_orders(
        self,
        symbol: str,
        best_bid: int | None,
        best_ask: int | None,
        ref_price_ticks: int,
        seq_start: int,
        ts_ns: int,
    ) -> list[OrderSubmitted]:
        """Generate single stochastic order."""
        side = Side.BUY if self._rng.random() < 0.5 else Side.SELL
        is_market = self._rng.random() < self._market_order_prob

        # If market order requested but no opposing book, fallback to limit
        if is_market and (
            (side == Side.BUY and best_ask is None) or (side == Side.SELL and best_bid is None)
        ):
            is_market = False

        qty_choices = (10, 20, 25, 50, 100)
        qty = int(self._rng.choice(qty_choices))
        self._order_counter += 1
        order_id = f"{self.agent_id}_{self._order_counter}"

        if is_market:
            order = OrderSubmitted(
                seq=seq_start,
                ts_ns=ts_ns,
                symbol=symbol,
                order_id=order_id,
                side=side,
                order_type=OrderType.MARKET,
                price_ticks=None,
                qty=qty,
                tif=TimeInForce.IOC,
            )
        else:
            mid = ref_price_ticks
            if best_bid is not None and best_ask is not None:
                mid = (best_bid + best_ask) // 2
            offset = int(self._rng.integers(-self._price_jitter, self._price_jitter + 1))
            limit_price = max(1, mid + offset)
            order = OrderSubmitted(
                seq=seq_start,
                ts_ns=ts_ns,
                symbol=symbol,
                order_id=order_id,
                side=side,
                order_type=OrderType.LIMIT,
                price_ticks=limit_price,
                qty=qty,
                tif=TimeInForce.GTC,
            )

        return [order]


class TrendFollowerAgent:
    """Momentum-based directional agent tracking price changes."""

    __slots__ = (
        "_history",
        "_lookback",
        "_order_counter",
        "_rng",
        "_threshold_ticks",
        "agent_id",
    )

    def __init__(
        self,
        agent_id: str,
        rng: np.random.Generator,
        lookback: int = 10,
        threshold_ticks: int = 2,
    ) -> None:
        self.agent_id = agent_id
        self._rng = rng
        self._lookback = lookback
        self._threshold_ticks = threshold_ticks
        self._history: deque[int] = deque(maxlen=lookback)
        self._order_counter = 0

    def reset(self, rng: np.random.Generator) -> None:
        """Reset state."""
        self._rng = rng
        self._history.clear()
        self._order_counter = 0

    def on_market_event(self, event: MarketEvent) -> None:
        """Clear history buffer on abrupt market events to avoid stale momentum."""
        if event.kind in ("EARNINGS_SHOCK", "HALT", "RESUME"):
            self._history.clear()

    def record_price(self, price_ticks: int) -> None:
        """Record latest price."""
        self._history.append(price_ticks)

    def generate_orders(
        self,
        symbol: str,
        best_bid: int | None,
        best_ask: int | None,
        ref_price_ticks: int,
        seq_start: int,
        ts_ns: int,
    ) -> list[OrderSubmitted]:
        """Generate trend-following orders when momentum exceeds threshold."""
        current_price = ref_price_ticks
        if best_bid is not None and best_ask is not None:
            current_price = (best_bid + best_ask) // 2

        self.record_price(current_price)

        if len(self._history) < self._lookback:
            return []

        delta = current_price - self._history[0]
        if abs(delta) < self._threshold_ticks:
            return []

        # Positive delta -> BUY, Negative delta -> SELL
        side = Side.BUY if delta > 0 else Side.SELL
        self._order_counter += 1
        order_id = f"{self.agent_id}_{self._order_counter}"
        qty = int(self._rng.choice((25, 50, 75)))

        # Limit order placed aggressively at or slightly beyond best opposite quote
        if side == Side.BUY:
            price = (best_ask if best_ask is not None else current_price) + 1
        else:
            price = max(1, (best_bid if best_bid is not None else current_price) - 1)

        return [
            OrderSubmitted(
                seq=seq_start,
                ts_ns=ts_ns,
                symbol=symbol,
                order_id=order_id,
                side=side,
                order_type=OrderType.LIMIT,
                price_ticks=price,
                qty=qty,
                tif=TimeInForce.GTC,
            )
        ]
