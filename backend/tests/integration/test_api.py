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

        # Test SUBSCRIBE trades
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


def test_bars_and_indicators_endpoints(client: TestClient) -> None:
    """Verify /api/v1/bars and /api/v1/indicators endpoints."""
    # Let simulation run a moment
    client.post(
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

    # Fetch bars
    res = client.get("/api/v1/bars?symbol=AAPL&interval=1s&limit=10")
    assert res.status_code == 200
    bars = res.json()
    assert isinstance(bars, list)
    if len(bars) > 0:
        bar = bars[0]
        for key in ("time", "open", "high", "low", "close", "volume", "trade_count"):
            assert key in bar

    # Fetch with invalid symbol
    err_res = client.get("/api/v1/bars?symbol=UNKNOWN&interval=1s")
    assert err_res.status_code == 404

    # Fetch with invalid interval
    err_res2 = client.get("/api/v1/bars?symbol=AAPL&interval=invalid_interval")
    assert err_res2.status_code == 400

    # Fetch indicators
    ind_res = client.get("/api/v1/indicators?symbol=AAPL&interval=1s&limit=50")
    assert ind_res.status_code == 200
    ind_data = ind_res.json()
    assert ind_data["symbol"] == "AAPL"
    assert ind_data["interval"] == "1s"
    assert "times" in ind_data
    assert "indicators" in ind_data
    indicators = ind_data["indicators"]
    for ind_name in ("sma20", "ema20", "rsi14", "macd", "bollinger", "vwap"):
        assert ind_name in indicators


def test_websocket_bars_subscription(client: TestClient) -> None:
    """Verify WebSocket subscribing to bars channel receives aggregated bars."""
    with client.websocket_connect("/ws") as ws:
        # Subscribe to bars channel
        ws.send_text(json.dumps({"type": "SUBSCRIBE", "channel": "bars:AAPL:1s"}))
        ack = json.loads(ws.receive_text())
        assert ack["type"] == "ACK"
        assert ack["channel"] == "bars:AAPL:1s"

        # Wait for a bar update message
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "DATA"
        assert msg["channel"] == "bars:AAPL:1s"
        assert "bars" in msg["data"]
        bars = msg["data"]["bars"]
        assert isinstance(bars, list)
        if len(bars) > 0:
            assert "close" in bars[0]
            assert "time" in bars[0]
