"""WebSocket broadcaster with server-side batching, coalescing, and backpressure protection.

Invariants:
- High-throughput incoming events (>=1,000 trades/sec) are buffered and dispatched
  in coalesced batches at a configurable rate (default 20 Hz = 50ms).
- Each connected client has an isolated bounded queue (maxsize=256) to prevent slow
  clients from blocking the simulation loop or leaking memory.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class Broadcaster:
    """Manages WebSocket client subscriptions and rate-limited batch delivery."""

    def __init__(self, throttling_fps: int = 20, queue_size: int = 256) -> None:
        """Initialize broadcaster.

        Args:
            throttling_fps: Batch flush frequency in updates per second (default 20).
            queue_size: Maximum bounded queue size per client connection.
        """
        self._throttling_fps = throttling_fps
        self._flush_interval_s = 1.0 / throttling_fps
        self._queue_size = queue_size

        # channel -> set of client_ids
        self._channel_subscriptions: dict[str, set[str]] = defaultdict(set)
        # client_id -> set of channels
        self._client_channels: dict[str, set[str]] = defaultdict(set)
        # client_id -> asyncio.Queue[str]
        self._client_queues: dict[str, asyncio.Queue[str]] = {}

        # Buffered trades: channel -> list of trade dicts
        self._pending_trades: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # Buffered bars: channel -> list of bar dicts
        self._pending_bars: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # Monotonic sequence counter per channel
        self._channel_seq: dict[str, int] = defaultdict(int)

        self._flush_task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the background flush loop."""
        if not self._running:
            self._running = True
            self._flush_task = asyncio.create_task(self._run_flush_loop())

    async def stop(self) -> None:
        """Stop the flush loop and disconnect all clients."""
        self._running = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None

    def register_client(self, client_id: str) -> asyncio.Queue[str]:
        """Register a new client connection and return its bounded output queue."""
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_size)
        self._client_queues[client_id] = queue
        return queue

    def unregister_client(self, client_id: str) -> None:
        """Remove a client and clean up all its channel subscriptions."""
        for channel in self._client_channels.get(client_id, set()):
            self._channel_subscriptions[channel].discard(client_id)
        self._client_channels.pop(client_id, None)
        self._client_queues.pop(client_id, None)

    def subscribe(self, client_id: str, channel: str) -> None:
        """Subscribe client to a channel."""
        if client_id in self._client_queues:
            self._channel_subscriptions[channel].add(client_id)
            self._client_channels[client_id].add(channel)

    def unsubscribe(self, client_id: str, channel: str) -> None:
        """Unsubscribe client from a channel."""
        self._channel_subscriptions[channel].discard(client_id)
        if client_id in self._client_channels:
            self._client_channels[client_id].discard(channel)

    def push_trade(self, symbol: str, trade_dict: dict[str, Any]) -> None:
        """Enqueue a trade for batch dispatch on channel trades:{symbol}."""
        channel = f"trades:{symbol}"
        self._pending_trades[channel].append(trade_dict)

    def push_bar(self, symbol: str, interval: str, bar_dict: dict[str, Any]) -> None:
        """Enqueue an OHLC bar update for dispatch on channel bars:{symbol}:{interval}."""
        channel = f"bars:{symbol}:{interval}"
        self._pending_bars[channel].append(bar_dict)

    async def _run_flush_loop(self) -> None:
        """Periodic flush loop dispatching batched messages at throttling_fps."""
        while self._running:
            start_time = time.monotonic()
            await self.flush()
            elapsed = time.monotonic() - start_time
            sleep_duration = max(0.0, self._flush_interval_s - elapsed)
            await asyncio.sleep(sleep_duration)

    async def flush(self) -> None:
        """Flush all pending trade and bar batches to subscribed clients."""
        if not self._pending_trades and not self._pending_bars:
            return

        async with self._lock:
            trade_batches = dict(self._pending_trades)
            bar_batches = dict(self._pending_bars)
            self._pending_trades.clear()
            self._pending_bars.clear()

        epoch_ms = int(time.time() * 1000)

        # 1. Flush trade batches
        for channel, trades in trade_batches.items():
            if not trades:
                continue

            subscribers = self._channel_subscriptions.get(channel)
            if not subscribers:
                continue

            self._channel_seq[channel] += 1
            seq = self._channel_seq[channel]

            envelope = {
                "version": 1,
                "type": "DATA",
                "channel": channel,
                "seq": seq,
                "ts": epoch_ms,
                "data": {
                    "trades": trades,
                },
            }
            self._send_to_subscribers(subscribers, json.dumps(envelope))

        # 2. Flush bar batches
        for channel, bars in bar_batches.items():
            if not bars:
                continue

            subscribers = self._channel_subscriptions.get(channel)
            if not subscribers:
                continue

            self._channel_seq[channel] += 1
            seq = self._channel_seq[channel]

            envelope = {
                "version": 1,
                "type": "DATA",
                "channel": channel,
                "seq": seq,
                "ts": epoch_ms,
                "data": {
                    "bars": bars,
                },
            }
            self._send_to_subscribers(subscribers, json.dumps(envelope))

    def _send_to_subscribers(self, subscribers: set[str], msg: str) -> None:
        """Dispatch serialized message to a set of client subscribers."""
        for client_id in list(subscribers):
            queue = self._client_queues.get(client_id)
            if queue is not None:
                try:
                    queue.put_nowait(msg)
                except asyncio.QueueFull:
                    logger.warning(
                        "Client queue full for %s, dropping frame to maintain backpressure",
                        client_id,
                    )
                    try:
                        _ = queue.get_nowait()
                        queue.put_nowait(msg)
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        pass
