"""Limit Order Book (LOB) and deterministic matching engine for MarketPulse.

Invariants:
- Pure domain logic with zero external I/O or framework dependencies.
- Price-time priority: within each price level, orders are matched strictly FIFO.
- Execution price is determined by the resting (passive) order's price.
- Integer ticks: all price levels, orders, and match prices use integer ticks.
- Monotonic sequencing: all emitted events receive strictly increasing sequence numbers.
- BookDelta events are emitted on every change to resting price-level total quantity.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, cast

from sortedcontainers import SortedDict  # type: ignore[import-untyped]

from marketpulse.core.events import (
    BookDelta,
    Event,
    MarketEvent,
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


@dataclass(slots=True)
class RestingOrder:
    """Represents an order resting on the limit order book."""

    order_id: str
    side: Side
    price_ticks: int
    remaining_qty: int
    original_qty: int
    ts_ns: int
    seq: int
    tif: TimeInForce = TimeInForce.GTC
    participant_id: str = ""


class PriceLevel:
    """FIFO queue of resting orders at a single price tick level."""

    __slots__ = ("_orders", "price_ticks", "total_qty")

    def __init__(self, price_ticks: int) -> None:
        self.price_ticks = price_ticks
        self.total_qty = 0
        self._orders: deque[RestingOrder] = deque()

    @property
    def order_count(self) -> int:
        """Number of resting orders at this price level."""
        return len(self._orders)

    @property
    def orders(self) -> deque[RestingOrder]:
        """Direct access to the FIFO queue of orders."""
        return self._orders

    def add_order(self, order: RestingOrder) -> None:
        """Append an order to the tail of the FIFO queue."""
        self._orders.append(order)
        self.total_qty += order.remaining_qty

    def remove_order(self, order_id: str) -> RestingOrder | None:
        """Remove an order by order_id. Returns the removed order or None."""
        for i, order in enumerate(self._orders):
            if order.order_id == order_id:
                del self._orders[i]
                self.total_qty -= order.remaining_qty
                return order
        return None

    def peek_front(self) -> RestingOrder | None:
        """View the oldest resting order without removing it."""
        return self._orders[0] if self._orders else None

    def pop_front(self) -> RestingOrder:
        """Remove and return the oldest resting order."""
        order = self._orders.popleft()
        self.total_qty -= order.remaining_qty
        return order

    def reduce_front(self, qty: int) -> None:
        """Reduce remaining quantity of the front order and update total_qty."""
        assert self._orders, "Cannot reduce order in empty PriceLevel"
        front = self._orders[0]
        assert front.remaining_qty >= qty, "Reduction qty exceeds front order remaining qty"
        front.remaining_qty -= qty
        self.total_qty -= qty
        if front.remaining_qty == 0:
            self._orders.popleft()


class HalfBook:
    """One side of the order book (Bids or Asks) indexed by price ticks."""

    __slots__ = ("_levels", "side")

    def __init__(self, side: Side) -> None:
        self.side = side
        # SortedDict stores price_ticks -> PriceLevel in ascending order
        self._levels: SortedDict[int, PriceLevel] = SortedDict()

    def __len__(self) -> int:
        return len(self._levels)

    def is_empty(self) -> bool:
        """Return True if no price levels exist."""
        return len(self._levels) == 0

    def best_price(self) -> int | None:
        """Return the best price tick (highest for BUY, lowest for SELL)."""
        if not self._levels:
            return None
        # BUY (bids): best is highest price (last item in SortedDict)
        # SELL (asks): best is lowest price (first item in SortedDict)
        price = (
            self._levels.peekitem(-1)[0] if self.side == Side.BUY else self._levels.peekitem(0)[0]
        )
        return int(price)

    def best_level(self) -> PriceLevel | None:
        """Return the best PriceLevel object."""
        if not self._levels:
            return None
        level = (
            self._levels.peekitem(-1)[1] if self.side == Side.BUY else self._levels.peekitem(0)[1]
        )
        return cast(PriceLevel, level)

    def get_level(self, price_ticks: int) -> PriceLevel | None:
        """Get PriceLevel at specified price ticks."""
        return cast(PriceLevel | None, self._levels.get(price_ticks))

    def add_order(self, order: RestingOrder) -> int:
        """Add a resting order. Returns the new total quantity at this price level."""
        price = order.price_ticks
        if price not in self._levels:
            self._levels[price] = PriceLevel(price)
        level = cast(PriceLevel, self._levels[price])
        level.add_order(order)
        return int(level.total_qty)

    def remove_order(self, price_ticks: int, order_id: str) -> tuple[RestingOrder | None, int]:
        """Remove an order from a level.

        Returns (removed_order, new_level_total_qty).
        If level becomes empty, it is deleted from the book and returns (order, 0).
        """
        level = self._levels.get(price_ticks)
        if level is None:
            return None, 0

        order = level.remove_order(order_id)
        if order is None:
            return None, level.total_qty

        new_total = level.total_qty
        if new_total == 0:
            del self._levels[price_ticks]
            return order, 0

        return order, new_total

    def clean_empty_level(self, price_ticks: int) -> None:
        """Remove level if total_qty is 0."""
        level = self._levels.get(price_ticks)
        if level is not None and level.total_qty == 0:
            del self._levels[price_ticks]

    def depth(self, max_levels: int = 10) -> list[tuple[int, int]]:
        """Return aggregated depth snapshot [(price_ticks, total_qty), ...].

        For BUY: sorted descending (highest bid first).
        For SELL: sorted ascending (lowest ask first).
        """
        result: list[tuple[int, int]] = []
        if self.side == Side.BUY:
            # Iterate backwards (highest price first)
            for k in reversed(self._levels.keys()):
                result.append((k, self._levels[k].total_qty))
                if len(result) >= max_levels:
                    break
        else:
            # Iterate forwards (lowest price first)
            for k in self._levels:
                result.append((k, self._levels[k].total_qty))
                if len(result) >= max_levels:
                    break
        return result

    @property
    def total_volume(self) -> int:
        """Total resting volume across all levels on this side."""
        return sum(cast(PriceLevel, lvl).total_qty for lvl in self._levels.values())

    def total_liquidity_up_to(self, limit_price_ticks: int | None = None) -> int:
        """Calculate available quantity up to an optional limit price.

        For BUY (matching an incoming SELL): liquidity at price >= limit_price.
        For SELL (matching an incoming BUY): liquidity at price <= limit_price.
        """
        total = 0
        if self.side == Side.BUY:
            for price in reversed(self._levels.keys()):
                if limit_price_ticks is not None and price < limit_price_ticks:
                    break
                total += self._levels[price].total_qty
        else:
            for price in self._levels:
                if limit_price_ticks is not None and price > limit_price_ticks:
                    break
                total += self._levels[price].total_qty
        return total


class OrderBook:
    """Limit order book for a single symbol with price-time priority."""

    __slots__ = ("_orders_map", "asks", "bids", "symbol")

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.bids = HalfBook(Side.BUY)
        self.asks = HalfBook(Side.SELL)
        # order_id -> RestingOrder for O(1) cancel/lookup
        self._orders_map: dict[str, RestingOrder] = {}

    def best_bid(self) -> int | None:
        """Return highest bid price in integer ticks or None."""
        return self.bids.best_price()

    def best_ask(self) -> int | None:
        """Return lowest ask price in integer ticks or None."""
        return self.asks.best_price()

    def spread(self) -> int | None:
        """Return spread in integer ticks (best_ask - best_bid) or None."""
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is not None and ask is not None:
            return ask - bid
        return None

    def mid_price_ticks(self) -> float | None:
        """Return arithmetic midpoint of best bid and best ask in ticks."""
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is not None and ask is not None:
            return (bid + ask) / 2.0
        return None

    def total_volume(self, side: Side) -> int:
        """Return total resting volume for the specified book side."""
        half = self.bids if side == Side.BUY else self.asks
        return half.total_volume

    def get_order(self, order_id: str) -> RestingOrder | None:
        """Retrieve resting order by ID."""
        return self._orders_map.get(order_id)

    def add_resting_order(self, order: RestingOrder) -> int:
        """Add an order to the book. Returns new total quantity at that price level."""
        self._orders_map[order.order_id] = order
        half = self.bids if order.side == Side.BUY else self.asks
        return half.add_order(order)

    def remove_resting_order(self, order_id: str) -> tuple[RestingOrder | None, int]:
        """Cancel/remove an order from the book.

        Returns (removed_order, new_level_total_qty).
        """
        order = self._orders_map.pop(order_id, None)
        if order is None:
            return None, 0
        half = self.bids if order.side == Side.BUY else self.asks
        _, new_qty = half.remove_order(order.price_ticks, order_id)
        return order, new_qty

    def depth_snapshot(self, max_levels: int = 10) -> dict[str, Any]:
        """Return L2 depth snapshot suitable for API/UI dissemination."""
        bids_depth = self.bids.depth(max_levels)
        asks_depth = self.asks.depth(max_levels)
        return {
            "symbol": self.symbol,
            "bids": [{"price_ticks": p, "qty": q} for p, q in bids_depth],
            "asks": [{"price_ticks": p, "qty": q} for p, q in asks_depth],
            "best_bid": self.best_bid(),
            "best_ask": self.best_ask(),
            "spread": self.spread(),
            "mid_price_ticks": self.mid_price_ticks(),
        }


class MatchingEngine:
    """Continuous double-auction matching engine for a single symbol.

    Invariants:
    - Pure domain logic.
    - Strictly monotonic sequence numbering for all emitted events.
    - Matches are executed with price-time priority (FIFO).
    - Passive resting orders dictate the execution price.
    """

    __slots__ = (
        "_book",
        "_seq",
        "_trade_count",
        "default_stp_policy",
        "is_halted",
        "stp_cancel_newest_count",
        "stp_cancel_oldest_count",
        "stp_decrement_cancel_count",
        "symbol",
    )

    def __init__(
        self,
        symbol: str,
        initial_seq: int = 1,
        default_stp_policy: STPPolicy = STPPolicy.CANCEL_NEWEST,
    ) -> None:
        if initial_seq < 1:
            raise ValueError(f"initial_seq must be >= 1, got {initial_seq}")
        self.symbol = symbol
        self._book = OrderBook(symbol)
        self._seq = initial_seq
        self._trade_count = 0
        self.is_halted = False
        self.default_stp_policy = default_stp_policy
        self.stp_cancel_newest_count = 0
        self.stp_cancel_oldest_count = 0
        self.stp_decrement_cancel_count = 0

    @property
    def book(self) -> OrderBook:
        """Direct reference to underlying order book."""
        return self._book

    @property
    def next_seq(self) -> int:
        """Current next sequence number."""
        return self._seq

    def allocate_seq(self) -> int:
        """Allocate and advance the next sequence number."""
        return self._next_seq()

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq += 1
        return seq

    def _next_trade_id(self) -> str:
        self._trade_count += 1
        return f"trd_{self._trade_count:06d}"

    def halt(self, ts_ns: int, reason: str = "CIRCUIT_BREAKER") -> list[Event]:
        """Halt trading for this symbol. Rejects subsequent aggressive orders."""
        self.is_halted = True
        return [
            MarketEvent(
                seq=self._next_seq(),
                ts_ns=ts_ns,
                symbol=self.symbol,
                kind="HALT",
                params={"reason": reason},
            )
        ]

    def resume(self, ts_ns: int) -> list[Event]:
        """Resume trading for this symbol."""
        self.is_halted = False
        return [
            MarketEvent(
                seq=self._next_seq(),
                ts_ns=ts_ns,
                symbol=self.symbol,
                kind="RESUME",
                params={},
            )
        ]

    def submit_order(self, order: OrderSubmitted) -> list[Event]:
        """Process an incoming order submission and return list of resulting events."""
        if order.symbol != self.symbol:
            raise ValueError(f"Order symbol '{order.symbol}' does not match engine '{self.symbol}'")

        events: list[Event] = []

        # 0. Market Halt check
        if self.is_halted:
            events.append(
                OrderRejected(
                    seq=self._next_seq(),
                    ts_ns=order.ts_ns,
                    symbol=self.symbol,
                    order_id=order.order_id,
                    reason="MARKET_HALTED",
                )
            )
            return events

        # 1. Validation checks
        if order.qty <= 0:
            events.append(
                OrderRejected(
                    seq=self._next_seq(),
                    ts_ns=order.ts_ns,
                    symbol=self.symbol,
                    order_id=order.order_id,
                    reason="INVALID_QUANTITY",
                )
            )
            return events

        if order.order_type == OrderType.LIMIT and (
            order.price_ticks is None or order.price_ticks <= 0
        ):
            events.append(
                OrderRejected(
                    seq=self._next_seq(),
                    ts_ns=order.ts_ns,
                    symbol=self.symbol,
                    order_id=order.order_id,
                    reason="INVALID_LIMIT_PRICE",
                )
            )
            return events

        # 2. Check FOK fillability
        opposing_half = self._book.asks if order.side == Side.BUY else self._book.bids
        if order.tif == TimeInForce.FOK:
            avail = opposing_half.total_liquidity_up_to(order.price_ticks)
            if avail < order.qty:
                events.append(
                    OrderRejected(
                        seq=self._next_seq(),
                        ts_ns=order.ts_ns,
                        symbol=self.symbol,
                        order_id=order.order_id,
                        reason="FOK_NOT_FILLABLE",
                    )
                )
                return events

        # 3. Market order empty book check
        if order.order_type == OrderType.MARKET and opposing_half.is_empty():
            events.append(
                OrderRejected(
                    seq=self._next_seq(),
                    ts_ns=order.ts_ns,
                    symbol=self.symbol,
                    order_id=order.order_id,
                    reason="NO_LIQUIDITY",
                )
            )
            return events

        # Order accepted
        events.append(
            OrderAccepted(
                seq=self._next_seq(),
                ts_ns=order.ts_ns,
                symbol=self.symbol,
                order_id=order.order_id,
            )
        )

        remaining_qty = order.qty
        stp_policy = order.stp if order.stp is not None else self.default_stp_policy
        order_stp_canceled = False

        # 4. Aggressive Matching against opposing side
        while remaining_qty > 0 and not opposing_half.is_empty():
            best_level = opposing_half.best_level()
            if best_level is None:
                break

            match_price = best_level.price_ticks

            # Limit price check
            if order.order_type == OrderType.LIMIT:
                assert order.price_ticks is not None
                if order.side == Side.BUY and match_price > order.price_ticks:
                    break  # Ask price is higher than buy limit
                if order.side == Side.SELL and match_price < order.price_ticks:
                    break  # Bid price is lower than sell limit

            # Match against orders at this price level in FIFO order
            while remaining_qty > 0 and best_level.order_count > 0:
                front_order = best_level.peek_front()
                if front_order is None:
                    break

                # Self-Trade Prevention (STP) check:
                # Triggers when both orders have non-empty participant_id, they match,
                # and policy != NONE.
                is_self_trade = bool(
                    order.participant_id
                    and front_order.participant_id
                    and order.participant_id == front_order.participant_id
                    and stp_policy != STPPolicy.NONE
                )

                if is_self_trade:
                    if stp_policy == STPPolicy.CANCEL_NEWEST:
                        self.stp_cancel_newest_count += 1
                        order_stp_canceled = True
                        events.append(
                            OrderCanceled(
                                seq=self._next_seq(),
                                ts_ns=order.ts_ns,
                                symbol=self.symbol,
                                order_id=order.order_id,
                                reason="STP_CANCEL_NEWEST",
                            )
                        )
                        remaining_qty = 0
                        break

                    if stp_policy == STPPolicy.CANCEL_OLDEST:
                        self.stp_cancel_oldest_count += 1
                        removed = best_level.pop_front()
                        self._book._orders_map.pop(removed.order_id, None)
                        events.append(
                            OrderCanceled(
                                seq=self._next_seq(),
                                ts_ns=order.ts_ns,
                                symbol=self.symbol,
                                order_id=removed.order_id,
                                reason="STP_CANCEL_OLDEST",
                            )
                        )
                        continue

                    if stp_policy == STPPolicy.DECREMENT_AND_CANCEL:
                        self.stp_decrement_cancel_count += 1
                        overlap = min(remaining_qty, front_order.remaining_qty)
                        remaining_qty -= overlap

                        if front_order.remaining_qty == overlap:
                            removed = best_level.pop_front()
                            self._book._orders_map.pop(removed.order_id, None)
                            events.append(
                                OrderCanceled(
                                    seq=self._next_seq(),
                                    ts_ns=order.ts_ns,
                                    symbol=self.symbol,
                                    order_id=removed.order_id,
                                    reason="STP_DECREMENT_AND_CANCEL",
                                )
                            )
                        else:
                            best_level.reduce_front(overlap)

                        if remaining_qty == 0:
                            order_stp_canceled = True
                            events.append(
                                OrderCanceled(
                                    seq=self._next_seq(),
                                    ts_ns=order.ts_ns,
                                    symbol=self.symbol,
                                    order_id=order.order_id,
                                    reason="STP_DECREMENT_AND_CANCEL",
                                )
                            )
                            break
                        continue

                fill_qty = min(remaining_qty, front_order.remaining_qty)

                # Determine buy/sell order IDs and participant IDs
                if order.side == Side.BUY:
                    buy_id = order.order_id
                    sell_id = front_order.order_id
                    buyer_pid = order.participant_id
                    seller_pid = front_order.participant_id
                else:
                    buy_id = front_order.order_id
                    sell_id = order.order_id
                    buyer_pid = front_order.participant_id
                    seller_pid = order.participant_id

                # Emit TradeExecuted
                trade = TradeExecuted(
                    seq=self._next_seq(),
                    ts_ns=order.ts_ns,
                    symbol=self.symbol,
                    trade_id=self._next_trade_id(),
                    price_ticks=match_price,
                    qty=fill_qty,
                    aggressor_side=order.side,
                    buy_order_id=buy_id,
                    sell_order_id=sell_id,
                    buyer_participant_id=buyer_pid,
                    seller_participant_id=seller_pid,
                )
                events.append(trade)

                remaining_qty -= fill_qty

                # Update resting order
                if front_order.remaining_qty == fill_qty:
                    # Fully filled
                    removed = best_level.pop_front()
                    self._book._orders_map.pop(removed.order_id, None)
                else:
                    # Partially filled
                    best_level.reduce_front(fill_qty)

            # Price level total changed -> emit BookDelta
            new_level_qty = best_level.total_qty
            opposing_half.clean_empty_level(match_price)
            events.append(
                BookDelta(
                    seq=self._next_seq(),
                    ts_ns=order.ts_ns,
                    symbol=self.symbol,
                    side=opposing_half.side,
                    price_ticks=match_price,
                    new_total_qty=new_level_qty,
                )
            )

            if order_stp_canceled:
                break

        # 5. Handle remaining quantity
        if remaining_qty > 0 and not order_stp_canceled:
            if order.order_type == OrderType.LIMIT and order.tif == TimeInForce.GTC:
                assert order.price_ticks is not None
                resting = RestingOrder(
                    order_id=order.order_id,
                    side=order.side,
                    price_ticks=order.price_ticks,
                    remaining_qty=remaining_qty,
                    original_qty=order.qty,
                    ts_ns=order.ts_ns,
                    seq=order.seq,
                    tif=order.tif,
                    participant_id=order.participant_id,
                )
                new_total = self._book.add_resting_order(resting)
                events.append(
                    BookDelta(
                        seq=self._next_seq(),
                        ts_ns=order.ts_ns,
                        symbol=self.symbol,
                        side=order.side,
                        price_ticks=order.price_ticks,
                        new_total_qty=new_total,
                    )
                )
            elif (
                order.tif in (TimeInForce.IOC, TimeInForce.FOK)
                or order.order_type == OrderType.MARKET
            ):
                # IOC or Market unfilled remainder is canceled
                events.append(
                    OrderCanceled(
                        seq=self._next_seq(),
                        ts_ns=order.ts_ns,
                        symbol=self.symbol,
                        order_id=order.order_id,
                        reason="IMMEDIATE_UNFILLED_REMAINDER",
                    )
                )

        return events

    def cancel_order(
        self,
        order_id: str,
        ts_ns: int,
        reason: str = "USER_REQUESTED",
    ) -> list[Event]:
        """Cancel a resting order by order_id."""
        events: list[Event] = []
        order, new_qty = self._book.remove_resting_order(order_id)
        if order is None:
            events.append(
                OrderRejected(
                    seq=self._next_seq(),
                    ts_ns=ts_ns,
                    symbol=self.symbol,
                    order_id=order_id,
                    reason="ORDER_NOT_FOUND",
                )
            )
            return events

        events.append(
            OrderCanceled(
                seq=self._next_seq(),
                ts_ns=ts_ns,
                symbol=self.symbol,
                order_id=order_id,
                reason=reason,
            )
        )
        events.append(
            BookDelta(
                seq=self._next_seq(),
                ts_ns=ts_ns,
                symbol=self.symbol,
                side=order.side,
                price_ticks=order.price_ticks,
                new_total_qty=new_qty,
            )
        )
        return events

    def get_stp_stats(self) -> dict[str, int]:
        """Return self-trade prevention telemetry counts."""
        return {
            "cancel_newest": self.stp_cancel_newest_count,
            "cancel_oldest": self.stp_cancel_oldest_count,
            "decrement_and_cancel": self.stp_decrement_cancel_count,
            "total_prevented": (
                self.stp_cancel_newest_count
                + self.stp_cancel_oldest_count
                + self.stp_decrement_cancel_count
            ),
        }
