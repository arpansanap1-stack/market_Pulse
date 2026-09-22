"""Advanced Order Types & OMS Trigger Management.

Pure domain module managing synthetic trigger orders:
- Stop-Loss (Market & Limit)
- Take-Profit (Market & Limit)
- Trailing Stop (Dynamic ratcheting high/low watermark)
- One-Cancels-the-Other (OCO) Group Coordination

Maintains strict separation between the continuous double-auction matching engine
(which only accepts active Limit & Market orders) and the OMS trigger book.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from marketpulse.core.events import (
    OrderSubmitted,
    OrderTriggered,
    OrderType,
    Side,
    STPPolicy,
    TimeInForce,
)


@dataclass(slots=True)
class TriggerOrder:
    """Represents a working untriggered synthetic order."""

    order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    qty: int
    price_ticks: int | None = None
    stop_price_ticks: int | None = None
    trail_offset_ticks: int | None = None
    oco_group_id: str | None = None
    participant_id: str = ""
    stp: STPPolicy = STPPolicy.CANCEL_NEWEST
    tif: TimeInForce = TimeInForce.GTC
    created_ts_ns: int = 0
    peak_price_ticks: int | None = None
    current_stop_ticks: int | None = None

    def __post_init__(self) -> None:
        if self.current_stop_ticks is None and self.stop_price_ticks is not None:
            self.current_stop_ticks = self.stop_price_ticks

    def to_dict(self) -> dict[str, Any]:
        """Serialize trigger order state."""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "qty": self.qty,
            "price_ticks": self.price_ticks,
            "stop_price_ticks": self.stop_price_ticks,
            "trail_offset_ticks": self.trail_offset_ticks,
            "oco_group_id": self.oco_group_id,
            "participant_id": self.participant_id,
            "stp": self.stp.value,
            "tif": self.tif.value,
            "created_ts_ns": self.created_ts_ns,
            "peak_price_ticks": self.peak_price_ticks,
            "current_stop_ticks": self.current_stop_ticks,
        }


class AdvancedOrderManager:
    """Manages untriggered synthetic orders and evaluates execution triggers on trades."""

    def __init__(self) -> None:
        # Untriggered orders indexed by order_id
        self._orders: dict[str, TriggerOrder] = {}
        # OCO tracking: group_id -> set of order_ids
        self._oco_groups: dict[str, set[str]] = {}
        # Order ID -> group_id
        self._order_to_oco: dict[str, str] = {}
        self._seq: int = 0

    def _next_seq(self, seq_fn: Callable[[], int] | None = None) -> int:
        if seq_fn is not None:
            return seq_fn()
        self._seq += 1
        return self._seq

    def register_order(self, order: TriggerOrder) -> None:
        """Register a working trigger order."""
        self._orders[order.order_id] = order
        if order.oco_group_id:
            self.register_oco_member(order.order_id, order.oco_group_id)

    def register_oco_member(self, order_id: str, oco_group_id: str) -> None:
        """Register an order (trigger or active) as a member of an OCO group."""
        self._order_to_oco[order_id] = oco_group_id
        if oco_group_id not in self._oco_groups:
            self._oco_groups[oco_group_id] = set()
        self._oco_groups[oco_group_id].add(order_id)

    def get_order(self, order_id: str) -> TriggerOrder | None:
        """Get an untriggered order by ID."""
        return self._orders.get(order_id)

    def get_open_orders(self) -> list[TriggerOrder]:
        """Return all working trigger orders."""
        return list(self._orders.values())

    def cancel_order(self, order_id: str) -> list[str]:
        """Cancel an untriggered order and all companion orders in its OCO group.

        Returns list of all canceled order IDs.
        """
        canceled_ids: list[str] = []
        if order_id in self._orders:
            del self._orders[order_id]
            canceled_ids.append(order_id)

        # Check OCO companion cancellation
        oco_group_id = self._order_to_oco.get(order_id)
        if oco_group_id:
            peers = self.cancel_oco_group(oco_group_id, exclude_order_id=order_id)
            canceled_ids.extend(peers)

        return canceled_ids

    def cancel_oco_group(self, oco_group_id: str, exclude_order_id: str | None = None) -> list[str]:
        """Cancel and purge all members of an OCO group except exclude_order_id."""
        group_members = self._oco_groups.get(oco_group_id, set())
        peer_ids_to_cancel: list[str] = []

        for member_id in list(group_members):
            if member_id == exclude_order_id:
                continue
            peer_ids_to_cancel.append(member_id)
            if member_id in self._orders:
                del self._orders[member_id]
            self._order_to_oco.pop(member_id, None)

        if exclude_order_id:
            self._order_to_oco.pop(exclude_order_id, None)
        self._oco_groups.pop(oco_group_id, None)

        return peer_ids_to_cancel

    def on_order_filled(self, order_id: str) -> list[str]:
        """Called when an order fills.

        If the order belonged to an OCO group, cancels all remaining companions.
        Returns list of peer order IDs to cancel.
        """
        oco_group_id = self._order_to_oco.get(order_id)
        if not oco_group_id:
            return []
        return self.cancel_oco_group(oco_group_id, exclude_order_id=order_id)

    def on_trade(
        self,
        trade_price_ticks: int,
        ts_ns: int,
        symbol: str | None = None,
        seq_fn: Callable[[], int] | None = None,
    ) -> tuple[list[tuple[OrderSubmitted, OrderTriggered]], list[str], list[tuple[str, int]]]:
        """Evaluate trade price against all working trigger orders.

        Returns:
            - triggered: list of (activated OrderSubmitted, OrderTriggered) tuples
            - oco_cancels: list of companion order IDs canceled due to OCO execution
            - stop_updates: list of (order_id, new_stop_ticks) for ratcheted trailing stops
        """
        activated: list[tuple[OrderSubmitted, OrderTriggered]] = []
        oco_cancels: list[str] = []
        stop_updates: list[tuple[str, int]] = []

        # Iterate over copy since triggered orders will be deleted
        for order_id, order in list(self._orders.items()):
            if symbol is not None and order.symbol != symbol:
                continue

            triggered, ratcheted_stop = self._evaluate_order(order, trade_price_ticks)

            if ratcheted_stop is not None:
                stop_updates.append((order.order_id, ratcheted_stop))

            if triggered:
                # Remove from untriggered book
                del self._orders[order_id]

                # Convert to active matching engine order
                trig_seq = self._next_seq(seq_fn)
                sub_seq = self._next_seq(seq_fn)
                sub_event, trig_event = self._activate_order(
                    order, trade_price_ticks, ts_ns, sub_seq=sub_seq, trig_seq=trig_seq
                )
                activated.append((sub_event, trig_event))

                # If OCO, cancel peers
                if order.oco_group_id:
                    peers = self.cancel_oco_group(
                        order.oco_group_id, exclude_order_id=order.order_id
                    )
                    oco_cancels.extend(peers)

        return activated, oco_cancels, stop_updates

    def _evaluate_order(
        self,
        order: TriggerOrder,
        trade_price_ticks: int,
    ) -> tuple[bool, int | None]:
        """Evaluate whether an order triggers and update trailing stop ratchet.

        Returns (is_triggered, ratcheted_stop_price_ticks_or_None).
        """
        ratcheted_stop: int | None = None

        if order.order_type in (OrderType.STOP_LOSS, OrderType.STOP_LIMIT):
            if order.stop_price_ticks is None:
                return False, None
            if order.side == Side.SELL:
                return trade_price_ticks <= order.stop_price_ticks, None
            else:
                return trade_price_ticks >= order.stop_price_ticks, None

        elif order.order_type in (OrderType.TAKE_PROFIT, OrderType.TAKE_PROFIT_LIMIT):
            if order.stop_price_ticks is None:
                return False, None
            if order.side == Side.SELL:
                return trade_price_ticks >= order.stop_price_ticks, None
            else:
                return trade_price_ticks <= order.stop_price_ticks, None

        elif order.order_type == OrderType.TRAILING_STOP:
            if order.trail_offset_ticks is None:
                return False, None

            if order.side == Side.SELL:
                # Watermark tracks highest price (peak)
                if order.peak_price_ticks is None or trade_price_ticks > order.peak_price_ticks:
                    order.peak_price_ticks = trade_price_ticks
                    new_stop = order.peak_price_ticks - order.trail_offset_ticks
                    if order.current_stop_ticks is None or new_stop > order.current_stop_ticks:
                        order.current_stop_ticks = new_stop
                        ratcheted_stop = new_stop

                # Trigger when price drops to or below stop
                triggered = (
                    order.current_stop_ticks is not None
                    and trade_price_ticks <= order.current_stop_ticks
                )
                return triggered, ratcheted_stop

            else:  # BUY
                # Watermark tracks lowest price (trough)
                if order.peak_price_ticks is None or trade_price_ticks < order.peak_price_ticks:
                    order.peak_price_ticks = trade_price_ticks
                    new_stop = order.peak_price_ticks + order.trail_offset_ticks
                    if order.current_stop_ticks is None or new_stop < order.current_stop_ticks:
                        order.current_stop_ticks = new_stop
                        ratcheted_stop = new_stop

                # Trigger when price rises to or above stop
                triggered = (
                    order.current_stop_ticks is not None
                    and trade_price_ticks >= order.current_stop_ticks
                )
                return triggered, ratcheted_stop

        return False, None

    def _activate_order(
        self,
        order: TriggerOrder,
        trigger_price_ticks: int,
        ts_ns: int,
        sub_seq: int,
        trig_seq: int,
    ) -> tuple[OrderSubmitted, OrderTriggered]:
        """Convert a triggered order into active OrderSubmitted and OrderTriggered events."""
        is_market = order.order_type in (
            OrderType.STOP_LOSS,
            OrderType.TAKE_PROFIT,
            OrderType.TRAILING_STOP,
        )

        execution_type = OrderType.MARKET if is_market else OrderType.LIMIT
        order_price = None if is_market else order.price_ticks
        order_tif = TimeInForce.IOC if is_market else order.tif

        sub_event = OrderSubmitted(
            seq=sub_seq,
            ts_ns=ts_ns,
            symbol=order.symbol,
            order_id=order.order_id,
            side=order.side,
            order_type=execution_type,
            qty=order.qty,
            price_ticks=order_price,
            tif=order_tif,
            participant_id=order.participant_id,
            stp=order.stp,
            stop_price_ticks=order.stop_price_ticks,
            trail_offset_ticks=order.trail_offset_ticks,
            oco_group_id=order.oco_group_id,
        )

        trig_event = OrderTriggered(
            seq=trig_seq,
            ts_ns=ts_ns,
            symbol=order.symbol,
            parent_order_id=order.order_id,
            triggered_order_id=order.order_id,
            order_type=order.order_type,
            trigger_price_ticks=trigger_price_ticks,
            execution_type=execution_type,
        )

        return sub_event, trig_event

    def clear(self) -> None:
        """Clear all trigger orders and OCO groups."""
        self._orders.clear()
        self._oco_groups.clear()
        self._order_to_oco.clear()
