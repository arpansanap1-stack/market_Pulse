"""Pure core portfolio tracking and order management system (OMS/PMS).

Invariants:
- Pure domain logic with zero external I/O or framework dependencies.
- All monetary balances (cash, equity, prices, P&L) maintain internal precision in integer ticks.
- Accounting identity strictly preserved:
  Total Equity == Cash + Market Value == Initial Cash + Realized PnL + Unrealized PnL.
- Supports long and short position inventory, weighted average entry price updates,
  and FIFO/weighted realized PnL.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from marketpulse.core.events import (
    OrderAccepted,
    OrderCanceled,
    OrderRejected,
    OrderSubmitted,
    OrderType,
    Side,
    STPPolicy,
    TimeInForce,
    TradeExecuted,
    ticks_to_price,
)


class OrderStatus(StrEnum):
    """Lifecycle status of a user order."""

    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNTRIGGERED = "UNTRIGGERED"
    TRIGGERED = "TRIGGERED"


@dataclass(slots=True)
class Position:
    """Represents a symbol position inventory."""

    symbol: str
    qty: int = 0
    avg_entry_price_ticks: float = 0.0
    realized_pnl_ticks: int = 0

    def market_value_ticks(self, current_price_ticks: int) -> int:
        """Market value of position in integer ticks."""
        return self.qty * current_price_ticks

    def unrealized_pnl_ticks(self, current_price_ticks: int) -> int:
        """Unrealized mark-to-market P&L in integer ticks."""
        if self.qty == 0:
            return 0
        pnl = (current_price_ticks - self.avg_entry_price_ticks) * self.qty
        return round(pnl)

    def to_dict(self, current_price_ticks: int, tick_size: float) -> dict[str, Any]:
        """Serialize position to dictionary with tick and dollar representations."""
        unrealized_ticks = self.unrealized_pnl_ticks(current_price_ticks)
        avg_entry_price = round(self.avg_entry_price_ticks * tick_size, 4)
        current_price = ticks_to_price(current_price_ticks, tick_size)
        market_val_ticks = self.market_value_ticks(current_price_ticks)

        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "avg_entry_price": avg_entry_price,
            "avg_entry_price_ticks": round(self.avg_entry_price_ticks, 2),
            "current_price": current_price,
            "current_price_ticks": current_price_ticks,
            "market_value": round(market_val_ticks * tick_size, 2),
            "market_value_ticks": market_val_ticks,
            "unrealized_pnl": round(unrealized_ticks * tick_size, 2),
            "unrealized_pnl_ticks": unrealized_ticks,
            "realized_pnl": round(self.realized_pnl_ticks * tick_size, 2),
            "realized_pnl_ticks": self.realized_pnl_ticks,
        }


@dataclass(slots=True)
class OrderRecord:
    """Tracks status and execution history of a user-submitted order."""

    order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    price_ticks: int | None
    qty: int
    filled_qty: int = 0
    remaining_qty: int = 0
    status: OrderStatus = OrderStatus.PENDING
    tif: TimeInForce = TimeInForce.GTC
    created_ts_ns: int = 0
    updated_ts_ns: int = 0
    avg_fill_price_ticks: float | None = None
    reject_reason: str | None = None
    participant_id: str = ""
    stp: STPPolicy = STPPolicy.CANCEL_NEWEST
    stop_price_ticks: int | None = None
    trail_offset_ticks: int | None = None
    oco_group_id: str | None = None
    current_stop_ticks: int | None = None

    def __post_init__(self) -> None:
        if self.remaining_qty == 0 and self.filled_qty == 0:
            self.remaining_qty = self.qty

    def to_dict(self, tick_size: float) -> dict[str, Any]:
        """Serialize order record to dictionary."""
        price = (
            ticks_to_price(self.price_ticks, tick_size) if self.price_ticks is not None else None
        )
        stop_price = (
            ticks_to_price(self.stop_price_ticks, tick_size)
            if self.stop_price_ticks is not None
            else None
        )
        trail_offset = (
            ticks_to_price(self.trail_offset_ticks, tick_size)
            if self.trail_offset_ticks is not None
            else None
        )
        current_stop = (
            ticks_to_price(self.current_stop_ticks, tick_size)
            if self.current_stop_ticks is not None
            else None
        )
        avg_fill_price = (
            round(self.avg_fill_price_ticks * tick_size, 4)
            if self.avg_fill_price_ticks is not None
            else None
        )
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "price": price,
            "price_ticks": self.price_ticks,
            "qty": self.qty,
            "filled_qty": self.filled_qty,
            "remaining_qty": self.remaining_qty,
            "status": self.status.value,
            "tif": self.tif.value,
            "created_ts_ns": self.created_ts_ns,
            "updated_ts_ns": self.updated_ts_ns,
            "avg_fill_price": avg_fill_price,
            "avg_fill_price_ticks": (
                round(self.avg_fill_price_ticks, 2)
                if self.avg_fill_price_ticks is not None
                else None
            ),
            "reject_reason": self.reject_reason,
            "participant_id": self.participant_id,
            "stp": self.stp.value,
            "stop_price": stop_price,
            "stop_price_ticks": self.stop_price_ticks,
            "trail_offset": trail_offset,
            "trail_offset_ticks": self.trail_offset_ticks,
            "oco_group_id": self.oco_group_id,
            "current_stop": current_stop,
            "current_stop_ticks": self.current_stop_ticks,
        }


class PortfolioTracker:
    """In-memory pure domain portfolio and user order manager."""

    def __init__(self, initial_cash: float = 100_000.0, tick_size: float = 0.01) -> None:
        self.tick_size = tick_size
        self.initial_cash_ticks: int = round(initial_cash / tick_size)
        self.cash_ticks: int = self.initial_cash_ticks
        self.positions: dict[str, Position] = {}
        self.orders: dict[str, OrderRecord] = {}
        self.order_history: list[OrderRecord] = []
        self.trade_history: list[dict[str, Any]] = []

    def reset(self, initial_cash: float = 100_000.0, tick_size: float | None = None) -> None:
        """Reset account cash balances, positions, and order records."""
        if tick_size is not None:
            self.tick_size = tick_size
        self.initial_cash_ticks = round(initial_cash / self.tick_size)
        self.cash_ticks = self.initial_cash_ticks
        self.positions.clear()
        self.orders.clear()
        self.order_history.clear()
        self.trade_history.clear()

    def get_position(self, symbol: str) -> Position:
        """Get or create position tracker for symbol."""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def validate_order(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        qty: int,
        price_ticks: int | None,
        estimated_price_ticks: int | None = None,
    ) -> tuple[bool, str | None]:
        """Validate whether the user has sufficient cash to place the order."""
        if qty <= 0:
            return False, "Quantity must be positive"

        is_limit_type = order_type in (
            OrderType.LIMIT,
            OrderType.STOP_LIMIT,
            OrderType.TAKE_PROFIT_LIMIT,
        )
        if is_limit_type:
            if price_ticks is None or price_ticks <= 0:
                return False, "Limit orders require price > 0"
            required_price = price_ticks
        else:
            if estimated_price_ticks is None or estimated_price_ticks <= 0:
                return False, "Market orders require positive reference price"
            required_price = estimated_price_ticks

        if side == Side.BUY:
            required_cost_ticks = qty * required_price
            if required_cost_ticks > self.cash_ticks:
                return (
                    False,
                    f"Insufficient funds: required {required_cost_ticks * self.tick_size:.2f}, "
                    f"available {self.cash_ticks * self.tick_size:.2f}",
                )

        return True, None

    def on_order_submitted(self, order: OrderSubmitted) -> OrderRecord:
        """Record order submission."""
        is_synthetic = order.order_type in (
            OrderType.STOP_LOSS,
            OrderType.STOP_LIMIT,
            OrderType.TAKE_PROFIT,
            OrderType.TAKE_PROFIT_LIMIT,
            OrderType.TRAILING_STOP,
        )
        initial_status = OrderStatus.UNTRIGGERED if is_synthetic else OrderStatus.PENDING
        record = OrderRecord(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            price_ticks=order.price_ticks,
            qty=order.qty,
            filled_qty=0,
            remaining_qty=order.qty,
            status=initial_status,
            tif=order.tif,
            created_ts_ns=order.ts_ns,
            updated_ts_ns=order.ts_ns,
            participant_id=order.participant_id,
            stp=order.stp,
            stop_price_ticks=order.stop_price_ticks,
            trail_offset_ticks=order.trail_offset_ticks,
            oco_group_id=order.oco_group_id,
            current_stop_ticks=order.stop_price_ticks,
        )
        self.orders[order.order_id] = record
        self.order_history.append(record)
        return record

    def on_order_triggered(self, order_id: str, ts_ns: int) -> None:
        """Mark synthetic order as triggered."""
        order = self.orders.get(order_id)
        if order is not None and order.status == OrderStatus.UNTRIGGERED:
            order.status = OrderStatus.TRIGGERED
            order.updated_ts_ns = ts_ns

    def update_stop_price(self, order_id: str, current_stop_ticks: int, ts_ns: int) -> None:
        """Update dynamic stop price on a working trailing stop order."""
        order = self.orders.get(order_id)
        if order is not None:
            order.current_stop_ticks = current_stop_ticks
            order.updated_ts_ns = ts_ns

    def on_order_accepted(self, event: OrderAccepted) -> None:
        """Handle order acceptance into the matching engine."""
        order = self.orders.get(event.order_id)
        if order is not None and order.status in (OrderStatus.PENDING, OrderStatus.TRIGGERED):
            order.status = OrderStatus.OPEN
            order.updated_ts_ns = event.ts_ns

    def on_order_rejected(self, event: OrderRejected) -> None:
        """Handle order rejection by matching engine."""
        order = self.orders.get(event.order_id)
        if order is not None:
            order.status = OrderStatus.REJECTED
            order.reject_reason = event.reason
            order.updated_ts_ns = event.ts_ns

    def on_order_canceled(self, event: OrderCanceled) -> None:
        """Handle order cancellation."""
        order = self.orders.get(event.order_id)
        if order is not None:
            order.status = OrderStatus.CANCELED
            order.reject_reason = event.reason
            order.updated_ts_ns = event.ts_ns

    def on_trade_executed(self, trade: TradeExecuted, user_order_id: str, side: Side) -> None:
        """Update portfolio balances, positions, and order status on execution fill."""
        order = self.orders.get(user_order_id)
        pos = self.get_position(trade.symbol)
        fill_qty = trade.qty
        fill_price_ticks = trade.price_ticks

        # Update order fill metrics
        if order is not None:
            prev_filled = order.filled_qty
            new_filled = prev_filled + fill_qty
            if order.avg_fill_price_ticks is None or prev_filled == 0:
                order.avg_fill_price_ticks = float(fill_price_ticks)
            else:
                total_val = (prev_filled * order.avg_fill_price_ticks) + (
                    fill_qty * fill_price_ticks
                )
                order.avg_fill_price_ticks = total_val / new_filled

            order.filled_qty = new_filled
            order.remaining_qty = max(0, order.qty - new_filled)
            order.status = (
                OrderStatus.FILLED if order.remaining_qty == 0 else OrderStatus.PARTIALLY_FILLED
            )
            order.updated_ts_ns = trade.ts_ns

        # Update position and cash
        if side == Side.BUY:
            # User pays cash
            self.cash_ticks -= fill_qty * fill_price_ticks

            if pos.qty >= 0:
                # Increasing or opening long position
                new_qty = pos.qty + fill_qty
                pos.avg_entry_price_ticks = (
                    (pos.qty * pos.avg_entry_price_ticks) + (fill_qty * fill_price_ticks)
                ) / new_qty
                pos.qty = new_qty
            else:
                # Covering short position
                covered_qty = min(fill_qty, abs(pos.qty))
                realized_pnl = (pos.avg_entry_price_ticks - fill_price_ticks) * covered_qty
                pos.realized_pnl_ticks += round(realized_pnl)

                remaining_buy = fill_qty - covered_qty
                if remaining_buy > 0:
                    pos.qty = remaining_buy
                    pos.avg_entry_price_ticks = float(fill_price_ticks)
                else:
                    pos.qty += covered_qty
                    if pos.qty == 0:
                        pos.avg_entry_price_ticks = 0.0
        else:
            # User sells, receives cash
            self.cash_ticks += fill_qty * fill_price_ticks

            if pos.qty > 0:
                # Closing part or all of long position
                closed_qty = min(fill_qty, pos.qty)
                realized_pnl = (fill_price_ticks - pos.avg_entry_price_ticks) * closed_qty
                pos.realized_pnl_ticks += round(realized_pnl)

                remaining_sell = fill_qty - closed_qty
                if remaining_sell > 0:
                    pos.qty = -remaining_sell
                    pos.avg_entry_price_ticks = float(fill_price_ticks)
                else:
                    pos.qty -= closed_qty
                    if pos.qty == 0:
                        pos.avg_entry_price_ticks = 0.0
            else:
                # Increasing short position
                new_short_qty = abs(pos.qty) + fill_qty
                pos.avg_entry_price_ticks = (
                    (abs(pos.qty) * pos.avg_entry_price_ticks) + (fill_qty * fill_price_ticks)
                ) / new_short_qty
                pos.qty -= fill_qty

        # Record trade in user trade history
        self.trade_history.append(
            {
                "trade_id": trade.trade_id,
                "order_id": user_order_id,
                "symbol": trade.symbol,
                "side": side.value,
                "price": ticks_to_price(fill_price_ticks, self.tick_size),
                "price_ticks": fill_price_ticks,
                "qty": fill_qty,
                "ts_ns": trade.ts_ns,
            }
        )

    def get_summary(
        self,
        current_price_ticks: int,
        tick_size: float | None = None,
        symbol: str = "AAPL",
    ) -> dict[str, Any]:
        """Compute live equity, unrealized/realized P&L, and position summary."""
        effective_tick_size = tick_size if tick_size is not None else self.tick_size
        pos = self.get_position(symbol)
        pos_dict = pos.to_dict(current_price_ticks, effective_tick_size)

        total_market_value_ticks = sum(
            p.market_value_ticks(current_price_ticks) for p in self.positions.values()
        )
        total_unrealized_ticks = sum(
            p.unrealized_pnl_ticks(current_price_ticks) for p in self.positions.values()
        )
        total_realized_ticks = sum(p.realized_pnl_ticks for p in self.positions.values())

        total_equity_ticks = self.cash_ticks + total_market_value_ticks
        total_pnl_ticks = total_realized_ticks + total_unrealized_ticks

        cash_balance = round(self.cash_ticks * effective_tick_size, 2)
        total_equity = round(total_equity_ticks * effective_tick_size, 2)
        initial_cash = round(self.initial_cash_ticks * effective_tick_size, 2)
        realized_pnl = round(total_realized_ticks * effective_tick_size, 2)
        unrealized_pnl = round(total_unrealized_ticks * effective_tick_size, 2)
        total_pnl = round(total_pnl_ticks * effective_tick_size, 2)
        pnl_pct = round((total_pnl / initial_cash) * 100.0, 2) if initial_cash > 0 else 0.0

        return {
            "initial_cash": initial_cash,
            "cash": cash_balance,
            "cash_ticks": self.cash_ticks,
            "equity": total_equity,
            "equity_ticks": total_equity_ticks,
            "realized_pnl": realized_pnl,
            "realized_pnl_ticks": total_realized_ticks,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_ticks": total_unrealized_ticks,
            "total_pnl": total_pnl,
            "total_pnl_ticks": total_pnl_ticks,
            "pnl_pct": pnl_pct,
            "positions": [pos_dict] if pos.qty != 0 or pos.realized_pnl_ticks != 0 else [],
            "open_orders_count": sum(
                1
                for o in self.orders.values()
                if o.status
                in (
                    OrderStatus.PENDING,
                    OrderStatus.OPEN,
                    OrderStatus.PARTIALLY_FILLED,
                    OrderStatus.UNTRIGGERED,
                    OrderStatus.TRIGGERED,
                )
            ),
        }

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Return list of resting/active user orders."""
        active_statuses = (
            OrderStatus.PENDING,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.UNTRIGGERED,
            OrderStatus.TRIGGERED,
        )
        return [
            o.to_dict(self.tick_size) for o in self.orders.values() if o.status in active_statuses
        ]

    def get_order_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return user order history."""
        orders = [o.to_dict(self.tick_size) for o in reversed(self.order_history)]
        return orders[:limit] if limit > 0 else orders

    def get_trade_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return user execution fill trade history."""
        trades = list(reversed(self.trade_history))
        return trades[:limit] if limit > 0 else trades
