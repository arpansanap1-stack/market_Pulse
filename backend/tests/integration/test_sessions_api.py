"""Integration tests for session persistence, historical replay, and control endpoints."""

from __future__ import annotations

import json
import time
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from marketpulse.api.server import create_app
from marketpulse.storage.event_store import SQLiteEventStore


@pytest.fixture
def test_app_client() -> Generator[TestClient, None, None]:
    """Fixture providing a TestClient with an isolated in-memory event store."""
    store = SQLiteEventStore(":memory:")
    app = create_app(throttling_fps=50, store=store)
    with TestClient(app) as client:
        yield client


def test_session_lifecycle_and_listing(test_app_client: TestClient) -> None:
    """Verify creating, listing, retrieving, and stopping simulation sessions."""
    # 1. Create a new session
    res = test_app_client.post(
        "/api/v1/sessions",
        json={
            "seed": 1234,
            "symbol": "AAPL",
            "trades_per_sec": 100.0,
            "initial_price": 150.0,
            "volatility": 0.20,
            "tick_size": 0.01,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "started"
    session_id = data["session_id"]
    assert session_id.startswith("sess_")

    # 2. Check active session status
    active_res = test_app_client.get("/api/v1/sessions/active")
    assert active_res.status_code == 200
    active_data = active_res.json()
    assert active_data["session_id"] == session_id
    assert active_data["mode"] == "LIVE"
    assert active_data["symbol"] == "AAPL"

    # 3. List sessions
    list_res = test_app_client.get("/api/v1/sessions?limit=10")
    assert list_res.status_code == 200
    sessions = list_res.json()
    assert isinstance(sessions, list)
    matching = [s for s in sessions if s["session_id"] == session_id]
    assert len(matching) == 1
    assert matching[0]["seed"] == 1234

    # 4. Get specific session
    get_res = test_app_client.get(f"/api/v1/sessions/{session_id}")
    assert get_res.status_code == 200
    meta = get_res.json()
    assert meta["session_id"] == session_id
    assert meta["symbol"] == "AAPL"

    # 404 on missing session
    missing_res = test_app_client.get("/api/v1/sessions/unknown_session")
    assert missing_res.status_code == 404

    # 5. Stop session
    stop_res = test_app_client.post(f"/api/v1/sessions/{session_id}/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["status"] == "stopped"

    # Verify status is STOPPED
    stopped_meta = test_app_client.get(f"/api/v1/sessions/{session_id}").json()
    assert stopped_meta["status"] == "STOPPED"


def test_session_events_query(test_app_client: TestClient) -> None:
    """Verify events emitted during live simulation are persisted and queryable."""
    # Start high-rate session
    res = test_app_client.post(
        "/api/v1/sessions",
        json={
            "seed": 42,
            "symbol": "AAPL",
            "trades_per_sec": 500.0,
            "initial_price": 150.0,
            "volatility": 0.20,
            "tick_size": 0.01,
        },
    )
    session_id = res.json()["session_id"]

    # Allow simulation to generate events
    time.sleep(0.1)

    # Query events
    events_res = test_app_client.get(f"/api/v1/sessions/{session_id}/events?limit=50")
    assert events_res.status_code == 200
    events = events_res.json()
    assert isinstance(events, list)
    assert len(events) >= 1
    # Check that sequence numbers are strictly positive and monotonic
    seqs = [e["seq"] for e in events]
    assert all(s >= 1 for s in seqs)
    assert seqs == sorted(seqs)


def test_session_replay_controls_and_seeking(test_app_client: TestClient) -> None:
    """Verify replaying a recorded session, pausing, seeking, and adjusting speed."""
    # 1. Run simulation to produce events
    start_res = test_app_client.post(
        "/api/v1/sessions",
        json={
            "seed": 999,
            "symbol": "AAPL",
            "trades_per_sec": 1000.0,
            "initial_price": 150.0,
            "volatility": 0.20,
            "tick_size": 0.01,
        },
    )
    session_id = start_res.json()["session_id"]
    time.sleep(0.15)

    # Stop recording
    test_app_client.post(f"/api/v1/sessions/{session_id}/stop")

    # 2. Start replay mode at 5.0x speed
    replay_res = test_app_client.post(
        f"/api/v1/sessions/{session_id}/replay",
        json={"speed_multiplier": 5.0, "seek_seq": 1},
    )
    assert replay_res.status_code == 200
    data = replay_res.json()
    assert data["status"] == "replaying"
    assert data["speed_multiplier"] == 5.0

    # Verify active mode is REPLAY
    active_res = test_app_client.get("/api/v1/sessions/active")
    assert active_res.json()["mode"] in ("REPLAY", "STOPPED")

    # 3. Update playback speed
    speed_res = test_app_client.post(
        f"/api/v1/sessions/{session_id}/speed",
        json={"speed_multiplier": 10.0},
    )
    assert speed_res.status_code == 200
    assert speed_res.json()["speed_multiplier"] == 10.0

    # 4. Pause and Resume
    pause_res = test_app_client.post(f"/api/v1/sessions/{session_id}/pause")
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "paused"

    resume_res = test_app_client.post(f"/api/v1/sessions/{session_id}/resume")
    assert resume_res.status_code == 200
    assert resume_res.json()["status"] == "resumed"

    # 5. Seek to sequence 10
    seek_res = test_app_client.post(
        f"/api/v1/sessions/{session_id}/seek",
        json={"target_seq": 10},
    )
    assert seek_res.status_code == 200
    assert seek_res.json()["target_seq"] == 10

    # Error cases
    bad_replay = test_app_client.post(
        "/api/v1/sessions/nonexistent/replay",
        json={"speed_multiplier": 1.0},
    )
    assert bad_replay.status_code == 404


def test_websocket_streaming_during_replay(test_app_client: TestClient) -> None:
    """Verify WebSocket delivers messages while replaying a historical session."""
    # 1. Record session with events
    start_res = test_app_client.post(
        "/api/v1/sessions",
        json={
            "seed": 42,
            "symbol": "AAPL",
            "trades_per_sec": 500.0,
            "initial_price": 150.0,
            "volatility": 0.20,
            "tick_size": 0.01,
        },
    )
    session_id = start_res.json()["session_id"]
    time.sleep(0.3)
    test_app_client.post(f"/api/v1/sessions/{session_id}/stop")

    # 2. Start replay mode
    test_app_client.post(
        f"/api/v1/sessions/{session_id}/replay",
        json={"speed_multiplier": 1.0, "seek_seq": 1},
    )

    # 3. Connect WebSocket and subscribe to order book deltas
    with test_app_client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "SUBSCRIBE", "channel": "book:AAPL"}))
        ack = json.loads(ws.receive_text())
        assert ack["type"] == "ACK"
        assert ack["channel"] == "book:AAPL"

        # Await replayed book delta message
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "DATA"
        assert msg["channel"] == "book:AAPL"
        assert "deltas" in msg["data"]
