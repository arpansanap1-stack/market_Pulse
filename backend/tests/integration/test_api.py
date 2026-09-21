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


def test_book_endpoint(client: TestClient) -> None:
    """Verify /api/v1/book returns L2 order book depth snapshot."""
    client.post(
        "/api/v1/sessions",
        json={
            "seed": 123,
            "symbol": "AAPL",
            "trades_per_sec": 100.0,
            "initial_price": 150.0,
            "volatility": 0.20,
            "tick_size": 0.01,
        },
    )

    res = client.get("/api/v1/book?symbol=AAPL&levels=5")
    assert res.status_code == 200
    book = res.json()
    assert book["symbol"] == "AAPL"
    assert "bids" in book
    assert "asks" in book
    assert isinstance(book["bids"], list)
    assert isinstance(book["asks"], list)
    assert len(book["bids"]) <= 5
    assert len(book["asks"]) <= 5
    if len(book["bids"]) > 0:
        assert "price" in book["bids"][0]
        assert "qty" in book["bids"][0]


def test_websocket_book_subscription(client: TestClient) -> None:
    """Verify WebSocket subscribing to book channel receives book deltas."""
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "SUBSCRIBE", "channel": "book:AAPL"}))
        ack = json.loads(ws.receive_text())
        assert ack["type"] == "ACK"
        assert ack["channel"] == "book:AAPL"

        # Wait for delta message
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "DATA"
        assert msg["channel"] == "book:AAPL"
        assert "deltas" in msg["data"]
        assert isinstance(msg["data"]["deltas"], list)


def test_scenarios_and_injection_endpoints(client: TestClient) -> None:
    """Verify /api/v1/scenarios and /api/v1/scenarios/inject endpoints."""
    # Start session
    client.post(
        "/api/v1/sessions",
        json={
            "seed": 42,
            "symbol": "AAPL",
            "trades_per_sec": 50.0,
            "initial_price": 150.0,
            "volatility": 0.20,
            "tick_size": 0.01,
        },
    )

    # 1. List scenarios
    res = client.get("/api/v1/scenarios")
    assert res.status_code == 200
    catalog = res.json()
    assert isinstance(catalog, list)
    assert len(catalog) >= 5

    # 2. Inject positive earnings shock
    inj_res = client.post(
        "/api/v1/scenarios/inject",
        json={
            "scenario_id": "earnings_shock_positive",
            "symbol": "AAPL",
            "params": {"jump_pct": 0.05},
        },
    )
    assert inj_res.status_code == 200
    assert inj_res.json()["status"] == "injected"

    # 3. Check market status
    status_res = client.get("/api/v1/market-status?symbol=AAPL")
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "ACTIVE"

    # 4. Inject halt
    halt_res = client.post(
        "/api/v1/scenarios/inject",
        json={
            "scenario_id": "halt_trading",
            "symbol": "AAPL",
            "params": {"reason": "CIRCUIT_BREAKER"},
        },
    )
    assert halt_res.status_code == 200
    assert halt_res.json()["is_halted"] is True

    # 5. Check market status reflects halt
    status_res2 = client.get("/api/v1/market-status?symbol=AAPL")
    assert status_res2.status_code == 200
    assert status_res2.json()["status"] == "HALTED"
    assert status_res2.json()["is_halted"] is True

    # 6. Book snapshot also reflects halt
    book_res = client.get("/api/v1/book?symbol=AAPL")
    assert book_res.status_code == 200
    assert book_res.json()["is_halted"] is True

    # 7. Resume trading
    res_res = client.post(
        "/api/v1/scenarios/inject",
        json={"scenario_id": "resume_trading", "symbol": "AAPL"},
    )
    assert res_res.status_code == 200
    assert res_res.json()["is_halted"] is False


def test_anomalies_and_websocket_events_subscription(client: TestClient) -> None:
    """Verify /api/v1/anomalies endpoint and WebSocket anomaly/event channels."""
    client.post(
        "/api/v1/sessions",
        json={
            "seed": 42,
            "symbol": "AAPL",
            "trades_per_sec": 100.0,
            "initial_price": 150.0,
            "volatility": 0.20,
            "tick_size": 0.01,
        },
    )

    # Fetch anomalies list
    anom_res = client.get("/api/v1/anomalies?limit=20")
    assert anom_res.status_code == 200
    assert isinstance(anom_res.json(), list)

    with client.websocket_connect("/ws") as ws:
        # Subscribe to anomalies channel
        ws.send_text(json.dumps({"type": "SUBSCRIBE", "channel": "anomalies:AAPL"}))
        ack1 = json.loads(ws.receive_text())
        assert ack1["type"] == "ACK"
        assert ack1["channel"] == "anomalies:AAPL"

        # Subscribe to events channel
        ws.send_text(json.dumps({"type": "SUBSCRIBE", "channel": "events:market"}))
        ack2 = json.loads(ws.receive_text())
        assert ack2["type"] == "ACK"
        assert ack2["channel"] == "events:market"
