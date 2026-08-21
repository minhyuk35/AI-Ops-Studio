"""Wishlist, refund bank accounts, and points-redemption-at-checkout tests
for the mock-commerce-api service.

See conftest.py's ``commerce_app`` fixture docstring for why this module
loads mock-commerce-api's ``app`` package the way it does.
"""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

CHECKOUT_FIELDS = {
    "email": "buyer@example.com",
    "recipient": "김구매",
    "phone": "010-1234-5678",
    "postal_code": "04524",
    "address1": "서울특별시 중구 세종대로 110",
}


async def _client(main):
    transport = ASGITransport(app=main.app)
    return AsyncClient(transport=transport, base_url="http://test")


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _signup(client) -> tuple[str, str]:
    response = await client.post(
        "/auth/signup",
        json={
            "email": "wallet@example.com",
            "password": "correct-horse",
            "name": "김지갑",
            "phone": "010-2222-3333",
        },
    )
    assert response.status_code == 201
    body = response.json()
    return body["access_token"], body["customer"]["id"]


def _grant_points(db, customer_id: str, amount: int) -> None:
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO point_transactions(id, customer_id, amount, reason, order_id, "
            "created_at) VALUES(?,?,?,?,?,?)",
            (f"pt_{uuid4().hex[:12]}", customer_id, amount, "테스트 지급", None, db.utc_now()),
        )


@pytest.mark.asyncio
async def test_wishlist_add_list_remove_roundtrip(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        token, _customer_id = await _signup(client)

        empty = await client.get("/customers/me/wishlist", headers=_auth_header(token))
        assert empty.status_code == 200
        assert empty.json() == []

        add = await client.post(
            "/customers/me/wishlist/prd_001", headers=_auth_header(token)
        )
        assert add.status_code == 201

        # Adding the same product twice must not error or duplicate it.
        again = await client.post(
            "/customers/me/wishlist/prd_001", headers=_auth_header(token)
        )
        assert again.status_code == 201

        listed = await client.get("/customers/me/wishlist", headers=_auth_header(token))
        assert [item["id"] for item in listed.json()] == ["prd_001"]

        remove = await client.delete(
            "/customers/me/wishlist/prd_001", headers=_auth_header(token)
        )
        assert remove.status_code == 204

        after_remove = await client.get("/customers/me/wishlist", headers=_auth_header(token))
        assert after_remove.json() == []


@pytest.mark.asyncio
async def test_wishlist_unknown_product_is_rejected(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        token, _customer_id = await _signup(client)
        response = await client.post(
            "/customers/me/wishlist/prd_does_not_exist", headers=_auth_header(token)
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_bank_account_crud_and_default_switching(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        token, _customer_id = await _signup(client)

        first = await client.post(
            "/customers/me/bank-accounts",
            headers=_auth_header(token),
            json={
                "label": "주계좌", "bank_name": "국민은행",
                "account_holder": "김지갑", "last4": "1234", "is_default": True,
            },
        )
        assert first.status_code == 201
        first_id = first.json()["id"]
        assert bool(first.json()["is_default"])

        second = await client.post(
            "/customers/me/bank-accounts",
            headers=_auth_header(token),
            json={
                "label": "부계좌", "bank_name": "신한은행",
                "account_holder": "김지갑", "last4": "5678", "is_default": False,
            },
        )
        assert second.status_code == 201
        second_id = second.json()["id"]

        switch = await client.post(
            f"/customers/me/bank-accounts/{second_id}/default", headers=_auth_header(token)
        )
        assert switch.status_code == 200

        listed = (
            await client.get("/customers/me/bank-accounts", headers=_auth_header(token))
        ).json()
        by_id = {row["id"]: row for row in listed}
        assert bool(by_id[second_id]["is_default"])
        assert not bool(by_id[first_id]["is_default"])

        delete = await client.delete(
            f"/customers/me/bank-accounts/{first_id}", headers=_auth_header(token)
        )
        assert delete.status_code == 204
        remaining = (
            await client.get("/customers/me/bank-accounts", headers=_auth_header(token))
        ).json()
        assert [row["id"] for row in remaining] == [second_id]


@pytest.mark.asyncio
async def test_points_redemption_reduces_order_total_and_deducts_balance(commerce_app) -> None:
    db, main, _analytics = commerce_app
    async with await _client(main) as client:
        token, customer_id = await _signup(client)
        _grant_points(db, customer_id, 50_000)

        cart_id = "cart_points_a"
        await client.post(
            f"/carts/{cart_id}/items", json={"variant_id": "var_001_s", "quantity": 1}
        )
        order_response = await client.post(
            "/checkout/orders",
            headers=_auth_header(token),
            json={"cart_id": cart_id, "points_used": 30_000, **CHECKOUT_FIELDS},
        )
        assert order_response.status_code == 201
        order = order_response.json()
        assert order["points_used"] == 30_000
        assert order["total"] == 69_000 + 3_000 - 30_000

        points = (
            await client.get("/customers/me/points", headers=_auth_header(token))
        ).json()
        assert points["balance"] == 50_000 - 30_000

        pay = await client.post(
            "/payments/confirm", json={"order_id": order["id"], "amount": order["total"]}
        )
        assert pay.status_code == 200


@pytest.mark.asyncio
async def test_points_used_over_balance_is_rejected(commerce_app) -> None:
    db, main, _analytics = commerce_app
    async with await _client(main) as client:
        token, customer_id = await _signup(client)
        _grant_points(db, customer_id, 1_000)

        cart_id = "cart_points_b"
        await client.post(
            f"/carts/{cart_id}/items", json={"variant_id": "var_001_s", "quantity": 1}
        )
        response = await client.post(
            "/checkout/orders",
            headers=_auth_header(token),
            json={"cart_id": cart_id, "points_used": 2_000, **CHECKOUT_FIELDS},
        )
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_points_used_over_order_total_is_rejected(commerce_app) -> None:
    db, main, _analytics = commerce_app
    async with await _client(main) as client:
        token, customer_id = await _signup(client)
        _grant_points(db, customer_id, 1_000_000)

        cart_id = "cart_points_c"
        await client.post(
            f"/carts/{cart_id}/items", json={"variant_id": "var_001_s", "quantity": 1}
        )
        response = await client.post(
            "/checkout/orders",
            headers=_auth_header(token),
            json={"cart_id": cart_id, "points_used": 999_999, **CHECKOUT_FIELDS},
        )
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_points_used_without_auth_is_rejected(commerce_app) -> None:
    _db, main, _analytics = commerce_app
    async with await _client(main) as client:
        cart_id = "cart_points_d"
        await client.post(
            f"/carts/{cart_id}/items", json={"variant_id": "var_001_s", "quantity": 1}
        )
        response = await client.post(
            "/checkout/orders",
            json={"cart_id": cart_id, "points_used": 1_000, **CHECKOUT_FIELDS},
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_cancelling_an_order_refunds_the_points_it_used(commerce_app) -> None:
    db, main, _analytics = commerce_app
    async with await _client(main) as client:
        token, customer_id = await _signup(client)
        _grant_points(db, customer_id, 50_000)

        cart_id = "cart_points_e"
        await client.post(
            f"/carts/{cart_id}/items", json={"variant_id": "var_001_s", "quantity": 1}
        )
        order = (
            await client.post(
                "/checkout/orders",
                headers=_auth_header(token),
                json={"cart_id": cart_id, "points_used": 30_000, **CHECKOUT_FIELDS},
            )
        ).json()

        balance_after_checkout = (
            await client.get("/customers/me/points", headers=_auth_header(token))
        ).json()["balance"]
        assert balance_after_checkout == 20_000

        cancel = await client.post(
            f"/orders/{order['id']}/cancel", json={"reason": "단순 변심"}
        )
        assert cancel.status_code == 200

        balance_after_cancel = (
            await client.get("/customers/me/points", headers=_auth_header(token))
        ).json()["balance"]
        assert balance_after_cancel == 50_000
