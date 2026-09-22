"""Integration tests for user order submission, cancellation, and portfolio tracking."""

from __future__ import annotations

import time
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from marketpulse.api.server import create_app
from marketpulse.storage.event_store import SQLiteEventStore


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Fixture providing a TestClient with an isolated in-memory event store."""
    store = SQLiteEventStore(":memory:")
    app = create_app(throttling_fps=50, store=store)
    with TestClient(app) as test_client:
        yield test_client


def test_portfolio_initial_state(client: TestClient) -> None:
    """Verify default initial portfolio balances and empty positions."""
    res = client.get("/api/v1/portfolio")
    assert res.status_code == 200
    data = res.json()
    assert data["initial_cash"] == 100_000.0
    assert data["cash"] == 100_000.0
    assert data["equity"] == 100_000.0
    assert data["realized_pnl"] == 0.0
    assert data["unrealized_pnl"] == 0.0
    assert data["total_pnl"] == 0.0
    assert data["positions"] == []


def test_order_validation_errors(client: TestClient) -> None:
    """Verify invalid order parameters return appropriate 422 or 400 HTTP errors."""
    # 1. Invalid quantity (pydantic gt=0 schema validation -> 422)
    res_qty = client.post(
        "/api/v1/orders",
        json={
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": 150.0,
            "qty": 0,
        },
    )
    assert res_qty.status_code == 422

    # 2. Missing limit price for LIMIT order (domain validation -> 400)
    res_price = client.post(
        "/api/v1/orders",
        json={
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "qty": 10,
        },
    )
    assert res_price.status_code == 400
    assert "price" in res_price.json()["detail"].lower()

    # 3. Insufficient funds for large buy (domain validation -> 400)
    res_funds = client.post(
        "/api/v1/orders",
        json={
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": 1000.0,
            "qty": 1_000_000,
        },
    )
    assert res_funds.status_code == 400
    assert "insufficient funds" in res_funds.json()["detail"].lower()


def test_limit_order_placement_and_cancellation(client: TestClient) -> None:
    """Verify placing a resting limit order and subsequently canceling it."""
    # Ensure simulation has generated initial depth
    time.sleep(0.1)

    # Place a LIMIT BUY well below market ($50.00 vs ~$150.00) so it rests
    post_res = client.post(
        "/api/v1/orders",
        json={
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": 50.0,
            "qty": 10,
            "time_in_force": "GTC",
        },
    )
    assert post_res.status_code == 200
    order = post_res.json()
    assert order["order_id"].startswith("usr_")
    assert order["status"] == "OPEN"
    assert order["side"] == "BUY"
    assert order["qty"] == 10
    assert order["filled_qty"] == 0
    assert order["price"] == 50.0
    order_id = order["order_id"]

    # List orders
    list_res = client.get("/api/v1/orders")
    assert list_res.status_code == 200
    all_orders = list_res.json()
    assert any(o["order_id"] == order_id for o in all_orders)

    # Filter by open orders
    open_res = client.get("/api/v1/orders?status=open")
    assert open_res.status_code == 200
    open_orders = open_res.json()
    assert any(o["order_id"] == order_id for o in open_orders)

    # Retrieve single order
    get_res = client.get(f"/api/v1/orders/{order_id}")
    assert get_res.status_code == 200
    assert get_res.json()["order_id"] == order_id

    # Non-existent order
    assert client.get("/api/v1/orders/usr_nonexistent").status_code == 404

    # Cancel the resting order
    cancel_res = client.delete(f"/api/v1/orders/{order_id}")
    assert cancel_res.status_code == 200
    canceled_order = cancel_res.json()
    assert canceled_order["status"] == "CANCELED"

    # Canceling again should fail
    re_cancel_res = client.delete(f"/api/v1/orders/{order_id}")
    assert re_cancel_res.status_code == 400

    # Canceling non-existent order
    assert client.delete("/api/v1/orders/usr_fake").status_code == 404

    # Now open orders list should not contain this order
    open_res_after = client.get("/api/v1/orders?status=open")
    assert not any(o["order_id"] == order_id for o in open_res_after.json())


def test_market_order_execution_and_portfolio_update(client: TestClient) -> None:
    """Verify executing a market buy order updates positions and trade history."""
    # Allow background simulation loop to populate book with liquidity
    time.sleep(0.15)

    # Place a MARKET BUY for 5 shares
    buy_res = client.post(
        "/api/v1/orders",
        json={
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "MARKET",
            "qty": 5,
        },
    )
    assert buy_res.status_code == 200
    buy_order = buy_res.json()
    assert buy_order["order_id"].startswith("usr_")
    assert buy_order["filled_qty"] > 0
    assert buy_order["status"] in ("FILLED", "PARTIALLY_FILLED")

    # Check portfolio state
    p_res = client.get("/api/v1/portfolio")
    assert p_res.status_code == 200
    p_data = p_res.json()
    assert p_data["cash"] < 100_000.0
    assert len(p_data["positions"]) >= 1
    aapl_pos = next(p for p in p_data["positions"] if p["symbol"] == "AAPL")
    assert aapl_pos["qty"] == buy_order["filled_qty"]
    assert aapl_pos["avg_entry_price"] > 0.0

    # Check trade history
    trades_res = client.get("/api/v1/portfolio/trades")
    assert trades_res.status_code == 200
    user_trades = trades_res.json()
    assert len(user_trades) >= 1
    assert user_trades[-1]["order_id"] == buy_order["order_id"]
    assert user_trades[-1]["symbol"] == "AAPL"


def test_portfolio_reset(client: TestClient) -> None:
    """Verify resetting portfolio resets cash, positions, and order records."""
    # Place a quick order
    time.sleep(0.1)
    client.post(
        "/api/v1/orders",
        json={
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": 10.0,
            "qty": 1,
        },
    )
    assert len(client.get("/api/v1/orders").json()) >= 1

    # Reset portfolio with custom balance
    reset_res = client.post(
        "/api/v1/portfolio/reset",
        json={"initial_cash": 250_000.0},
    )
    assert reset_res.status_code == 200
    reset_data = reset_res.json()
    assert reset_data["status"] == "reset"
    p_data = reset_data["portfolio"]
    assert p_data["initial_cash"] == 250_000.0
    assert p_data["cash"] == 250_000.0
    assert p_data["equity"] == 250_000.0
    assert p_data["positions"] == []

    # Verify orders list is cleared
    orders_res = client.get("/api/v1/orders")
    assert orders_res.json() == []

    # Verify trades list is cleared
    trades_res = client.get("/api/v1/portfolio/trades")
    assert trades_res.json() == []


def test_order_stp_cancel_newest_via_api(client: TestClient) -> None:
    """Verify STP CANCEL_NEWEST cancels the incoming user order when matching self."""
    # 1. Fetch current book to find empty inside spread (mid price)
    book_res = client.get("/api/v1/book?symbol=AAPL")
    assert book_res.status_code == 200
    mid = book_res.json()["mid_price"]

    # 2. Place a resting LIMIT SELL at mid inside spread
    sell_res = client.post(
        "/api/v1/orders",
        json={
            "symbol": "AAPL",
            "side": "SELL",
            "order_type": "LIMIT",
            "price": mid,
            "qty": 10,
            "participant_id": "desk_alpha",
            "stp": "CANCEL_NEWEST",
        },
    )
    assert sell_res.status_code == 200
    sell_order = sell_res.json()
    assert sell_order["status"] == "OPEN"
    assert sell_order["participant_id"] == "desk_alpha"

    # 3. Place an aggressive LIMIT BUY at mid from the same participant
    buy_res = client.post(
        "/api/v1/orders",
        json={
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": mid,
            "qty": 10,
            "participant_id": "desk_alpha",
            "stp": "CANCEL_NEWEST",
        },
    )
    assert buy_res.status_code == 200
    buy_order = buy_res.json()
    assert buy_order["status"] == "CANCELED"
    assert buy_order["reject_reason"] == "STP_CANCEL_NEWEST"

    # 4. Verify the resting sell order is still OPEN
    s_check = client.get(f"/api/v1/orders/{sell_order['order_id']}")
    assert s_check.status_code == 200
    assert s_check.json()["status"] == "OPEN"

    # 5. Check market-status telemetry
    status_res = client.get("/api/v1/market-status")
    assert status_res.status_code == 200
    stp_stats = status_res.json()["stp_stats"]
    assert stp_stats["cancel_newest"] >= 1
    assert stp_stats["total_prevented"] >= 1


def test_order_stp_cancel_oldest_via_api(client: TestClient) -> None:
    """Verify STP CANCEL_OLDEST cancels the resting order when matched by self."""
    # 1. Fetch current book to find empty inside spread (mid price)
    book_res = client.get("/api/v1/book?symbol=AAPL")
    assert book_res.status_code == 200
    mid = book_res.json()["mid_price"]

    # 2. Place resting LIMIT SELL at mid inside spread
    sell_res = client.post(
        "/api/v1/orders",
        json={
            "symbol": "AAPL",
            "side": "SELL",
            "order_type": "LIMIT",
            "price": mid,
            "qty": 10,
            "participant_id": "desk_beta",
            "stp": "CANCEL_OLDEST",
        },
    )
    assert sell_res.status_code == 200
    sell_order = sell_res.json()
    assert sell_order["status"] == "OPEN"

    # 3. Aggressive LIMIT BUY at mid with CANCEL_OLDEST
    buy_res = client.post(
        "/api/v1/orders",
        json={
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": mid,
            "qty": 10,
            "participant_id": "desk_beta",
            "stp": "CANCEL_OLDEST",
        },
    )
    assert buy_res.status_code == 200
    buy_order = buy_res.json()
    assert buy_order["status"] == "OPEN"

    # 4. Resting sell order should now be CANCELED
    s_check = client.get(f"/api/v1/orders/{sell_order['order_id']}")
    assert s_check.status_code == 200
    assert s_check.json()["status"] == "CANCELED"
    assert s_check.json()["reject_reason"] == "STP_CANCEL_OLDEST"

    # 5. Check market-status telemetry
    status_res = client.get("/api/v1/market-status")
    assert status_res.status_code == 200
    stp_stats = status_res.json()["stp_stats"]
    assert stp_stats["cancel_oldest"] >= 1
