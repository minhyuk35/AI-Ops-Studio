"""Commerce Event Ledger tests for the mock-commerce-api service.

services/core-api and services/mock-commerce-api both expose a top-level
``app`` package. pytest's shared ``pythonpath`` setting can only bind one of
them to the ``app`` name per process, so this module loads mock-commerce-api's
``app`` package on demand and restores whatever was previously bound
afterwards, keeping this file order-independent from the core-api tests.
"""

import importlib
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

COMMERCE_ROOT = Path(__file__).resolve().parents[1] / "services" / "mock-commerce-api"


@pytest.fixture
def commerce_app(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMERCE_DB_PATH", str(tmp_path / "commerce.db"))
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.")
    }
    for name in saved_modules:
        del sys.modules[name]
    monkeypatch.syspath_prepend(str(COMMERCE_ROOT))
    try:
        db = importlib.import_module("app.db")
        main = importlib.import_module("app.main")
        db.initialize_database()
        yield db, main
    finally:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        sys.modules.update(saved_modules)


async def _client(main):
    transport = ASGITransport(app=main.app)
    return AsyncClient(transport=transport, base_url="http://test")


CHECKOUT_FIELDS = {
    "email": "buyer@example.com",
    "recipient": "김구매",
    "phone": "010-1234-5678",
    "postal_code": "04524",
    "address1": "서울특별시 중구 세종대로 110",
}


@pytest.mark.asyncio
async def test_order_lifecycle_records_commerce_events(commerce_app) -> None:
    _db, main = commerce_app
    async with await _client(main) as client:
        cart_id = "cart_test_lifecycle"
        add_response = await client.post(
            f"/carts/{cart_id}/items", json={"variant_id": "var_001_s", "quantity": 1}
        )
        assert add_response.status_code == 200

        order_response = await client.post(
            "/checkout/orders", json={"cart_id": cart_id, **CHECKOUT_FIELDS}
        )
        assert order_response.status_code == 201
        order = order_response.json()
        order_id = order["id"]
        assert order["total"] == 69_000 + 3_000  # under the free-shipping threshold

        created_events = (await client.get("/events", params={"order_id": order_id})).json()
        order_created = [e for e in created_events if e["event_type"] == "ORDER_CREATED"]
        assert len(order_created) == 1
        assert order_created[0]["amount"] == order["total"]
        assert order_created[0]["quantity"] == 1

        stock_events = [e for e in created_events if e["event_type"] == "STOCK_CHANGED"]
        assert len(stock_events) == 1
        assert stock_events[0]["variant_id"] == "var_001_s"
        assert stock_events[0]["quantity"] == -1

        # Confirming payment twice must only ever produce one PAYMENT_CONFIRMED event.
        for _ in range(2):
            pay_response = await client.post(
                "/payments/confirm",
                json={"order_id": order_id, "amount": order["total"]},
            )
            assert pay_response.status_code == 200
        payment_events = (
            await client.get(
                "/events", params={"order_id": order_id, "event_type": "PAYMENT_CONFIRMED"}
            )
        ).json()
        assert len(payment_events) == 1
        assert payment_events[0]["amount"] == order["total"]

        cancel_response = await client.post(
            f"/orders/{order_id}/cancel", json={"reason": "고객 단순 변심"}
        )
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "CANCELLED"

        cancel_events = (await client.get("/events", params={"order_id": order_id})).json()
        cancelled = [e for e in cancel_events if e["event_type"] == "ORDER_CANCELLED"]
        refunded = [e for e in cancel_events if e["event_type"] == "REFUND_COMPLETED"]
        assert len(cancelled) == 1
        assert cancelled[0]["amount"] == order["total"]
        assert len(refunded) == 1
        assert refunded[0]["refund_amount"] == order["total"]

        # Stock leaves the ledger net-zero: -1 on create, +1 on cancel.
        stock_events = [e for e in cancel_events if e["event_type"] == "STOCK_CHANGED"]
        assert len(stock_events) == 2
        assert sum(e["quantity"] for e in stock_events) == 0

        product = (await client.get("/products/prd_001")).json()
        restored_variant = next(v for v in product["variants"] if v["id"] == "var_001_s")
        assert restored_variant["stock"] == 8  # seed stock, fully restored


@pytest.mark.asyncio
async def test_return_request_records_event_without_refund_completed(commerce_app) -> None:
    _db, main = commerce_app
    async with await _client(main) as client:
        # ord_1003 ships DELIVERED with a single unit of var_003_260 (total 89000).
        response = await client.post(
            "/orders/ord_1003/refund", json={"reason": "사이즈가 맞지 않아요"}
        )
        assert response.status_code == 200
        claim = response.json()["claim"]
        assert claim["status"] == "REQUESTED"
        assert claim["refund_amount"] == 89_000 - 3_000

        events = (await client.get("/events", params={"order_id": "ord_1003"})).json()
        requested = [e for e in events if e["event_type"] == "RETURN_REQUESTED"]
        completed = [e for e in events if e["event_type"] == "REFUND_COMPLETED"]
        assert len(requested) == 1
        assert requested[0]["refund_amount"] == claim["refund_amount"]
        # The return hasn't actually finished (no pickup/inspection step exists yet),
        # so no REFUND_COMPLETED must be recorded alongside the request.
        assert completed == []


def test_record_event_is_idempotent_on_external_event_id(commerce_app) -> None:
    db, _main = commerce_app
    with db.transaction() as connection:
        for _ in range(2):
            db.record_event(
                connection,
                event_type="ORDER_CREATED",
                external_event_id="ord_dedupe_test:ORDER_CREATED",
                order_id="ord_dedupe_test",
                amount=10_000,
            )
        rows = connection.execute(
            "SELECT * FROM commerce_events WHERE order_id = ?", ("ord_dedupe_test",)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["amount"] == 10_000
