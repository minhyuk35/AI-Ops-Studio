import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from httpx import ASGITransport, AsyncClient


async def verify() -> None:
    with TemporaryDirectory(prefix="ai-ops-commerce-") as temp_dir:
        os.environ["COMMERCE_DB_PATH"] = str(Path(temp_dir) / "commerce.db")

        from app.db import initialize_database
        from app.main import app

        initialize_database()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            products_response = await client.get("/products")
            products_response.raise_for_status()
            products = products_response.json()
            assert len(products) >= 6

            detail_response = await client.get(f"/products/{products[0]['slug']}")
            detail_response.raise_for_status()
            detail = detail_response.json()
            variant = next(item for item in detail["variants"] if item["stock"] > 0)

            cart_response = await client.post(
                "/carts/verify/items",
                json={"variant_id": variant["id"], "quantity": 1},
            )
            cart_response.raise_for_status()
            cart = cart_response.json()

            checkout_response = await client.post(
                "/checkout/orders",
                json={
                    "cart_id": "verify",
                    "email": "demo@example.com",
                    "recipient": "김민지",
                    "phone": "010-0000-0000",
                    "postal_code": "04524",
                    "address1": "서울특별시 중구 세종대로 110",
                    "address2": "101호",
                    "delivery_memo": "문 앞",
                    "coupon_code": "WELCOME10",
                    "customer_id": "cus_demo",
                },
            )
            checkout_response.raise_for_status()
            order = checkout_response.json()

            payment_response = await client.post(
                "/payments/confirm",
                json={"order_id": order["id"], "amount": order["total"], "method": "CARD"},
            )
            payment_response.raise_for_status()
            paid_order = payment_response.json()["order"]
            assert paid_order["status"] == "PREPARING"

            cancel_response = await client.post(
                f"/orders/{order['id']}/cancel",
                json={"reason": "통합 검증"},
            )
            cancel_response.raise_for_status()
            assert cancel_response.json()["status"] == "CANCELLED"

            print("Commerce flow verified successfully.")
            print(f"Products: {len(products)}")
            print(f"Cart items: {cart['item_count']}")
            print("Flow: catalog -> cart -> checkout -> payment -> cancellation")


if __name__ == "__main__":
    asyncio.run(verify())
