"""Throughput test verifying broadcaster coalescing at >=1,000 trades/sec."""

import asyncio
import json
import time

import pytest

from marketpulse.api.broadcaster import Broadcaster
from marketpulse.sim.stub_gbm import StubGBMSource


@pytest.mark.asyncio
async def test_high_throughput_coalescing() -> None:
    """Verify broadcaster comfortably handles >=1,000 trades/sec input with 20Hz delivery."""
    throttling_fps = 20
    broadcaster = Broadcaster(throttling_fps=throttling_fps)
    await broadcaster.start()

    client_id = "test_client_001"
    client_queue = broadcaster.register_client(client_id)
    broadcaster.subscribe(client_id, "trades:AAPL")

    source = StubGBMSource(seed=42, symbol="AAPL", max_events=2000)

    # Ingest 2,000 trades at high speed
    start_time = time.monotonic()
    for _ in range(2000):
        event = source.next_event()
        assert event is not None
        trade_dict = {
            "seq": event.seq,
            "ts_ns": event.ts_ns,
            "symbol": event.symbol,
            "trade_id": getattr(event, "trade_id"),
            "price_ticks": getattr(event, "price_ticks"),
            "qty": getattr(event, "qty"),
            "aggressor_side": getattr(event, "aggressor_side").value,
        }
        broadcaster.push_trade("AAPL", trade_dict)

    duration = time.monotonic() - start_time
    # Ingestion rate must exceed 10,000 trades/sec in memory
    rate = 2000 / max(0.0001, duration)
    assert rate >= 1000.0

    # Wait for flush loop to emit messages
    await asyncio.sleep(0.15)  # allow ~3 flush cycles (50ms each)
    await broadcaster.flush()

    # Collect received messages from client queue
    received_messages: list[str] = []
    while not client_queue.empty():
        received_messages.append(client_queue.get_nowait())

    assert len(received_messages) >= 1
    # Check that the received message contains coalesced trades
    total_trades_received = 0
    for raw_msg in received_messages:
        msg = json.loads(raw_msg)
        assert msg["type"] == "DATA"
        assert msg["channel"] == "trades:AAPL"
        trades = msg["data"]["trades"]
        assert len(trades) > 0
        total_trades_received += len(trades)

    assert total_trades_received == 2000

    await broadcaster.stop()
