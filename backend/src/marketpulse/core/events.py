"""Canonical event schema, enums, dataclasses, and serialization for MarketPulse.

Invariants:
- All core events are immutable (frozen=True) and memory-efficient (slots=True).
- Event sequence numbers (seq) are positive and strictly monotonic per session.
- Event timestamps (ts_ns) are non-negative integer nanoseconds.
- All monetary values in core events are represented as integer ticks (price_ticks).
- Serialization to/from JSON is guaranteed to roundtrip identically.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, ClassVar


class Side(StrEnum):
    """Order side: BUY or SELL."""

    BUY = "BUY"
    SELL = "SELL"

    def opposite(self) -> Side:
        """Return opposite side."""
        return Side.SELL if self == Side.BUY else Side.BUY


class OrderType(StrEnum):
    """Order type: active or synthetic trigger."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_LOSS = "STOP_LOSS"
    STOP_LIMIT = "STOP_LIMIT"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"
    TRAILING_STOP = "TRAILING_STOP"


class TimeInForce(StrEnum):
    """Time in force policies."""

    GTC = "GTC"  # Good 'Til Cancel
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill


class STPPolicy(StrEnum):
    """Self-trade prevention policies."""

    CANCEL_NEWEST = "CANCEL_NEWEST"  # Incoming aggressor order is canceled (default)
    CANCEL_OLDEST = "CANCEL_OLDEST"  # Resting passive order is canceled; aggressor continues
    DECREMENT_AND_CANCEL = "DECREMENT_AND_CANCEL"  # Overlapping qty canceled from both
    NONE = "NONE"  # Self-trades permitted (STP bypassed)


class EventType(StrEnum):
    """Canonical event types recognized across the MarketPulse platform."""

    SESSION_STARTED = "SESSION_STARTED"
    SESSION_ENDED = "SESSION_ENDED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_CANCELED = "ORDER_CANCELED"
    TRADE_EXECUTED = "TRADE_EXECUTED"
    BOOK_DELTA = "BOOK_DELTA"
    MARKET_EVENT = "MARKET_EVENT"
    ORDER_TRIGGERED = "ORDER_TRIGGERED"


@dataclass(slots=True, frozen=True, kw_only=True)
class Event:
    """Base class for all sequenced MarketPulse events."""

    seq: int
    ts_ns: int
    symbol: str
    schema_version: int = 1

    event_type: ClassVar[EventType]

    def _validate_base(self) -> None:
        """Validate invariant base event fields."""
        if self.seq < 1:
            raise ValueError(f"seq must be >= 1, got {self.seq}")
        if self.ts_ns < 0:
            raise ValueError(f"ts_ns must be >= 0, got {self.ts_ns}")
        if not self.symbol:
            raise ValueError("symbol must be a non-empty string")
        if self.schema_version != 1:
            raise ValueError(f"Unsupported schema_version: {self.schema_version}")

    def __post_init__(self) -> None:
        self._validate_base()

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to a dictionary matching canonical specification."""
        d = asdict(self)
        d["type"] = self.event_type.value
        return d

    def to_json(self) -> str:
        """Serialize event to canonical JSON string with sorted keys."""
        return json.dumps(self.to_dict(), sort_keys=True)


@dataclass(slots=True, frozen=True, kw_only=True)
class SessionStarted(Event):
    """Emitted when a simulation or replay session begins."""

    event_type: ClassVar[EventType] = EventType.SESSION_STARTED

    session_id: str
    seed: int
    config_hash: str
    symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        Event._validate_base(self)
        if not self.session_id:
            raise ValueError("session_id must be non-empty")


@dataclass(slots=True, frozen=True, kw_only=True)
class SessionEnded(Event):
    """Emitted when a simulation session terminates."""

    event_type: ClassVar[EventType] = EventType.SESSION_ENDED

    session_id: str
    reason: str
    total_events: int

    def __post_init__(self) -> None:
        Event._validate_base(self)
        if not self.session_id:
            raise ValueError("session_id must be non-empty")
        if self.total_events < 0:
            raise ValueError(f"total_events must be >= 0, got {self.total_events}")


@dataclass(slots=True, frozen=True, kw_only=True)
class OrderSubmitted(Event):
    """Order submitted by a participant or simulated agent."""

    event_type: ClassVar[EventType] = EventType.ORDER_SUBMITTED

    order_id: str
    side: Side
    order_type: OrderType
    price_ticks: int | None
    qty: int
    tif: TimeInForce = TimeInForce.GTC
    participant_id: str = ""
    stp: STPPolicy = STPPolicy.CANCEL_NEWEST
    stop_price_ticks: int | None = None
    trail_offset_ticks: int | None = None
    oco_group_id: str | None = None

    def __post_init__(self) -> None:
        Event._validate_base(self)
        if not self.order_id:
            raise ValueError("order_id must be non-empty")
        if self.qty <= 0:
            raise ValueError(f"qty must be positive, got {self.qty}")
        if self.order_type == OrderType.LIMIT:
            if self.price_ticks is None or self.price_ticks <= 0:
                raise ValueError(f"LIMIT order requires price_ticks > 0, got {self.price_ticks}")
        elif (
            self.order_type == OrderType.MARKET
            and self.price_ticks is not None
            and self.price_ticks != 0
        ):
            raise ValueError(f"MARKET order price_ticks must be None or 0, got {self.price_ticks}")
        elif self.order_type in (OrderType.STOP_LOSS, OrderType.TAKE_PROFIT):
            if self.stop_price_ticks is None or self.stop_price_ticks <= 0:
                raise ValueError(
                    f"{self.order_type} requires stop_price_ticks > 0, got {self.stop_price_ticks}"
                )
        elif self.order_type in (OrderType.STOP_LIMIT, OrderType.TAKE_PROFIT_LIMIT):
            if self.stop_price_ticks is None or self.stop_price_ticks <= 0:
                raise ValueError(
                    f"{self.order_type} requires stop_price_ticks > 0, got {self.stop_price_ticks}"
                )
            if self.price_ticks is None or self.price_ticks <= 0:
                raise ValueError(
                    f"{self.order_type} requires limit price_ticks > 0, got {self.price_ticks}"
                )
        elif (
            self.order_type == OrderType.TRAILING_STOP
            and (self.trail_offset_ticks is None or self.trail_offset_ticks <= 0)
        ):
            raise ValueError(
                f"TRAILING_STOP requires trail_offset_ticks > 0, got {self.trail_offset_ticks}"
            )


@dataclass(slots=True, frozen=True, kw_only=True)
class OrderAccepted(Event):
    """Emitted when an order passes validation and enters the book or matching pipeline."""

    event_type: ClassVar[EventType] = EventType.ORDER_ACCEPTED

    order_id: str

    def __post_init__(self) -> None:
        Event._validate_base(self)
        if not self.order_id:
            raise ValueError("order_id must be non-empty")


@dataclass(slots=True, frozen=True, kw_only=True)
class OrderRejected(Event):
    """Emitted when an order fails validation or matching conditions."""

    event_type: ClassVar[EventType] = EventType.ORDER_REJECTED

    order_id: str
    reason: str

    def __post_init__(self) -> None:
        Event._validate_base(self)
        if not self.order_id:
            raise ValueError("order_id must be non-empty")
        if not self.reason:
            raise ValueError("reason must be non-empty")


@dataclass(slots=True, frozen=True, kw_only=True)
class OrderCanceled(Event):
    """Emitted when an order is canceled and removed from the resting book."""

    event_type: ClassVar[EventType] = EventType.ORDER_CANCELED

    order_id: str
    reason: str = "USER_REQUESTED"

    def __post_init__(self) -> None:
        Event._validate_base(self)
        if not self.order_id:
            raise ValueError("order_id must be non-empty")


@dataclass(slots=True, frozen=True, kw_only=True)
class TradeExecuted(Event):
    """Emitted when an aggressor order matches against a resting passive order."""

    event_type: ClassVar[EventType] = EventType.TRADE_EXECUTED

    trade_id: str
    price_ticks: int
    qty: int
    aggressor_side: Side
    buy_order_id: str
    sell_order_id: str
    buyer_participant_id: str = ""
    seller_participant_id: str = ""

    def __post_init__(self) -> None:
        Event._validate_base(self)
        if not self.trade_id:
            raise ValueError("trade_id must be non-empty")
        if self.price_ticks <= 0:
            raise ValueError(f"price_ticks must be positive, got {self.price_ticks}")
        if self.qty <= 0:
            raise ValueError(f"qty must be positive, got {self.qty}")
        if not self.buy_order_id or not self.sell_order_id:
            raise ValueError("buy_order_id and sell_order_id must be non-empty")


@dataclass(slots=True, frozen=True, kw_only=True)
class BookDelta(Event):
    """Emitted on changes to resting aggregated volume at a price level."""

    event_type: ClassVar[EventType] = EventType.BOOK_DELTA

    side: Side
    price_ticks: int
    new_total_qty: int

    def __post_init__(self) -> None:
        Event._validate_base(self)
        if self.price_ticks <= 0:
            raise ValueError(f"price_ticks must be positive, got {self.price_ticks}")
        if self.new_total_qty < 0:
            raise ValueError(f"new_total_qty must be >= 0, got {self.new_total_qty}")


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketEvent(Event):
    """Exogenous market event (earnings shock, volatility shift, trading halt)."""

    event_type: ClassVar[EventType] = EventType.MARKET_EVENT

    kind: str
    params: dict[str, Any]

    def __post_init__(self) -> None:
        Event._validate_base(self)
        if not self.kind:
            raise ValueError("kind must be non-empty")


@dataclass(slots=True, frozen=True, kw_only=True)
class OrderTriggered(Event):
    """Emitted when a synthetic trigger condition is met (Stop, Take-Profit, Trailing Stop)."""

    event_type: ClassVar[EventType] = EventType.ORDER_TRIGGERED

    parent_order_id: str
    triggered_order_id: str
    order_type: OrderType
    trigger_price_ticks: int
    execution_type: OrderType

    def __post_init__(self) -> None:
        Event._validate_base(self)
        if not self.parent_order_id:
            raise ValueError("parent_order_id must be non-empty")
        if not self.triggered_order_id:
            raise ValueError("triggered_order_id must be non-empty")
        if self.trigger_price_ticks <= 0:
            raise ValueError(
                f"trigger_price_ticks must be positive, got {self.trigger_price_ticks}"
            )


# Registry mapping EventType -> Event class for deserialization
_EVENT_TYPE_MAP: dict[EventType, type[Event]] = {
    EventType.SESSION_STARTED: SessionStarted,
    EventType.SESSION_ENDED: SessionEnded,
    EventType.ORDER_SUBMITTED: OrderSubmitted,
    EventType.ORDER_ACCEPTED: OrderAccepted,
    EventType.ORDER_REJECTED: OrderRejected,
    EventType.ORDER_CANCELED: OrderCanceled,
    EventType.TRADE_EXECUTED: TradeExecuted,
    EventType.BOOK_DELTA: BookDelta,
    EventType.MARKET_EVENT: MarketEvent,
    EventType.ORDER_TRIGGERED: OrderTriggered,
}


def event_from_dict(data: Mapping[str, Any]) -> Event:
    """Deserialize an event from a dictionary payload.

    Args:
        data: Dictionary matching the canonical event structure.

    Returns:
        Instantiated typed Event subclass.

    Raises:
        ValueError: If type is unknown or required fields are invalid.
    """
    raw_type = data.get("type")
    if raw_type is None:
        raise ValueError("Missing 'type' in event payload")

    try:
        event_type = EventType(raw_type)
    except ValueError as err:
        raise ValueError(f"Unknown event type: '{raw_type}'") from err

    cls = _EVENT_TYPE_MAP[event_type]

    # Shallow copy to avoid mutating caller's dict
    kwargs = dict(data)
    kwargs.pop("type", None)

    # Cast enum fields if present
    if "side" in kwargs and isinstance(kwargs["side"], str):
        kwargs["side"] = Side(kwargs["side"])
    if "aggressor_side" in kwargs and isinstance(kwargs["aggressor_side"], str):
        kwargs["aggressor_side"] = Side(kwargs["aggressor_side"])
    if "order_type" in kwargs and isinstance(kwargs["order_type"], str):
        kwargs["order_type"] = OrderType(kwargs["order_type"])
    if "execution_type" in kwargs and isinstance(kwargs["execution_type"], str):
        kwargs["execution_type"] = OrderType(kwargs["execution_type"])
    if "tif" in kwargs and isinstance(kwargs["tif"], str):
        kwargs["tif"] = TimeInForce(kwargs["tif"])
    if "stp" in kwargs and isinstance(kwargs["stp"], str):
        kwargs["stp"] = STPPolicy(kwargs["stp"])
    if "symbols" in kwargs and isinstance(kwargs["symbols"], list):
        kwargs["symbols"] = tuple(kwargs["symbols"])

    return cls(**kwargs)


def event_from_json(json_str: str) -> Event:
    """Deserialize an event from a JSON string.

    Args:
        json_str: Valid JSON string.

    Returns:
        Instantiated typed Event subclass.
    """
    data = json.loads(json_str)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data)}")
    return event_from_dict(data)


# Money / Tick conversion helpers
def ticks_to_price(ticks: int, tick_size: float) -> float:
    """Convert integer price ticks to floating-point currency representation.

    Args:
        ticks: Price in integer ticks.
        tick_size: Decimal size of one tick (e.g. 0.01).

    Returns:
        Floating-point price rounded to 10 decimal digits.
    """
    return round(ticks * tick_size, 10)


def price_to_ticks(price: float, tick_size: float) -> int:
    """Convert floating-point price to integer ticks.

    Args:
        price: Price in currency decimal units.
        tick_size: Decimal size of one tick (e.g. 0.01).

    Returns:
        Integer price tick count rounded to nearest tick.
    """
    return round(price / tick_size)
