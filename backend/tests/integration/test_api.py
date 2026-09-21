import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from marketpulse.api.server import create_app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Fixture providing a TestClient for the FastAPI app."""
    app = create_app(throttling_fps=50)  # Faster throttling for tests
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client: TestClient) -> None:
    """Verify health check endpoint returns 200 and expected payload."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_symbols_endpoint(client: TestClient) -> None:
    """Verify /api/v1/symbols returns current symbol status."""
    response = client.get("/api/v1/symbols")
    assert response.status_code == 200
    symbols = response.json()
    assert isinstance(symbols, list)
    assert len(symbols) >= 1
    assert symbols[0]["symbol"] == "AAPL"
    assert symbols[0]["tick_size"] == 0.01


def test_session_configuration_and_trades_endpoint(client: TestClient) -> None:
    """Verify /api/v1/sessions can configure simulation and trades populate."""
    post_res = client.post(
        "/api/v1/sessions",
        json={
            "seed": 999,
            "symbol": "AAPL",
            "trades_per_sec": 100.0,
            "initial_price": 200.0,
            "volatility": 0.25,
            "tick_size": 0.05,
        },
    )
    assert post_res.status_code == 200
    assert post_res.json()["status"] == "started"

    # Fetch trades
    trades_res = client.get("/api/v1/trades?limit=10")
    assert trades_res.status_code == 200
    trades = trades_res.json()
    assert isinstance(trades, list)


def test_websocket_ping_pong_and_subscription(client: TestClient) -> None:
    """Verify WebSocket ping/pong and channel subscription handshake."""
    with client.websocket_connect("/ws") as ws:
        # Test PING
        ws.send_text(json.dumps({"type": "PING"}))
        pong = json.loads(ws.receive_text())
        assert pong["type"] == "PONG"

        # Test SUBSCRIBE
        ws.send_text(json.dumps({"type": "SUBSCRIBE", "channel": "trades:AAPL"}))
        ack = json.loads(ws.receive_text())
        assert ack["type"] == "ACK"
        assert ack["channel"] == "trades:AAPL"

        # Await batched DATA message
        data_msg = json.loads(ws.receive_text())
        assert data_msg["type"] == "DATA"
        assert data_msg["channel"] == "trades:AAPL"
        assert "trades" in data_msg["data"]
        assert isinstance(data_msg["data"]["trades"], list)
