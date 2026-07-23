from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from app.analytics import (
    PERIOD_PATTERN,
    current_period,
    product_breakdown,
    revenue_summary_with_comparison,
)
from app.db import connect, initialize_database, record_event, row_to_dict, transaction, utc_now

FREE_SHIPPING_THRESHOLD = 100_000
STANDARD_SHIPPING_FEE = 3_000


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Everyday Market Commerce API",
    version="1.0.0",
    description="Persistent demo commerce service for AI Ops Studio",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CartItemCreate(BaseModel):
    variant_id: str
    quantity: int = Field(default=1, ge=1, le=20)


class CartItemUpdate(BaseModel):
    quantity: int = Field(ge=1, le=20)


class CheckoutRequest(BaseModel):
    cart_id: str
    email: EmailStr
    recipient: str = Field(min_length=2, max_length=50)
    phone: str = Field(min_length=9, max_length=20)
    postal_code: str = Field(min_length=3, max_length=10)
    address1: str = Field(min_length=5, max_length=200)
    address2: str = Field(default="", max_length=200)
    delivery_memo: str = Field(default="", max_length=200)
    coupon_code: str | None = Field(default=None, max_length=30)
    customer_id: str | None = "cus_demo"


class PaymentConfirm(BaseModel):
    order_id: str
    amount: int = Field(gt=0)
    method: Literal["CARD", "EASY_PAY"] = "CARD"


class OrderAction(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=4, max_length=100)


def fetch_product(connection, identifier: str) -> dict[str, object]:
    product = connection.execute(
        """
        SELECT p.*, c.name category_name, c.slug category_slug,
               COALESCE(SUM(v.stock), 0) total_stock
        FROM products p
        JOIN categories c ON c.id = p.category_id
        LEFT JOIN variants v ON v.product_id = p.id
        WHERE p.id = ? OR p.slug = ?
        GROUP BY p.id
        """,
        (identifier, identifier),
    ).fetchone()
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
    result = dict(product)
    result["in_stock"] = int(result.pop("total_stock")) > 0
    result["variants"] = [
        dict(row)
        for row in connection.execute(
            "SELECT id, sku, color, size, price, stock FROM variants WHERE product_id = ?",
            (result["id"],),
        ).fetchall()
    ]
    result["shipping"] = {
        "fee": STANDARD_SHIPPING_FEE,
        "free_threshold": FREE_SHIPPING_THRESHOLD,
        "estimated_days": "2~3영업일",
    }
    result["return_policy"] = {
        "window_days": 7,
        "return_fee": 3_000,
        "exchange_fee": 6_000,
    }
    return result


def ensure_cart(connection, cart_id: str) -> None:
    now = utc_now()
    connection.execute(
        "INSERT OR IGNORE INTO carts(id, customer_id, created_at, updated_at) VALUES(?,?,?,?)",
        (cart_id, None, now, now),
    )


def cart_payload(connection, cart_id: str, coupon_code: str | None = None) -> dict[str, object]:
    ensure_cart(connection, cart_id)
    rows = connection.execute(
        """
        SELECT ci.id, ci.quantity, v.id variant_id, v.sku, v.color, v.size,
               v.price, v.stock, p.id product_id, p.slug, p.brand, p.name, p.image
        FROM cart_items ci
        JOIN variants v ON v.id = ci.variant_id
        JOIN products p ON p.id = v.product_id
        WHERE ci.cart_id = ? ORDER BY ci.rowid
        """,
        (cart_id,),
    ).fetchall()
    items: list[dict[str, object]] = []
    subtotal = 0
    valid = True
    for row in rows:
        item = dict(row)
        item["line_total"] = int(item["price"]) * int(item["quantity"])
        item["available"] = int(item["stock"]) >= int(item["quantity"])
        valid = valid and bool(item["available"])
        subtotal += int(item["line_total"])
        items.append(item)
    discount = 0
    normalized_coupon = coupon_code.strip().upper() if coupon_code else None
    coupon_message = None
    if normalized_coupon == "WELCOME10":
        if subtotal >= 50_000:
            discount = min(subtotal // 10, 10_000)
            coupon_message = "첫 구매 10% 할인이 적용되었습니다."
        else:
            valid = False
            coupon_message = "WELCOME10은 상품금액 50,000원 이상부터 사용할 수 있습니다."
    elif normalized_coupon:
        valid = False
        coupon_message = "사용할 수 없는 쿠폰입니다."
    shipping_fee = (
        0 if subtotal == 0 or subtotal >= FREE_SHIPPING_THRESHOLD else STANDARD_SHIPPING_FEE
    )
    return {
        "id": cart_id,
        "items": items,
        "item_count": sum(int(item["quantity"]) for item in items),
        "subtotal": subtotal,
        "discount": discount,
        "shipping_fee": shipping_fee,
        "total": max(subtotal - discount + shipping_fee, 0),
        "coupon_code": normalized_coupon,
        "coupon_message": coupon_message,
        "valid": valid and bool(items),
        "free_shipping_remaining": max(FREE_SHIPPING_THRESHOLD - subtotal, 0),
    }


def order_payload(connection, order_id: str) -> dict[str, object]:
    order = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    result = dict(order)
    result["items"] = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM order_items WHERE order_id = ?", (order_id,)
        ).fetchall()
    ]
    result["shipment"] = row_to_dict(
        connection.execute("SELECT * FROM shipments WHERE order_id = ?", (order_id,)).fetchone()
    )
    result["payment"] = row_to_dict(
        connection.execute("SELECT * FROM payments WHERE order_id = ?", (order_id,)).fetchone()
    )
    result["claims"] = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM claims WHERE order_id = ? ORDER BY created_at DESC", (order_id,)
        ).fetchall()
    ]
    return result


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "Everyday Market Commerce API", "docs": "/docs"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "mock-commerce-api"}


@app.get("/categories")
async def list_categories() -> list[dict[str, object]]:
    with closing(connect()) as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM categories ORDER BY sort_order, name"
            ).fetchall()
        ]


@app.get("/products")
async def list_products(
    q: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=50),
    sort: Literal["recommended", "newest", "price_asc", "price_desc", "reviews"] = "recommended",
    in_stock: bool = False,
) -> list[dict[str, object]]:
    order_by = {
        "recommended": "p.rating DESC, p.review_count DESC",
        "newest": "p.created_at DESC",
        "price_asc": "p.price ASC",
        "price_desc": "p.price DESC",
        "reviews": "p.review_count DESC",
    }[sort]
    clauses: list[str] = []
    parameters: list[object] = []
    if q:
        clauses.append("(p.name LIKE ? OR p.brand LIKE ? OR p.description LIKE ?)")
        term = f"%{q.strip()}%"
        parameters.extend([term, term, term])
    if category:
        clauses.append("(c.slug = ? OR c.id = ?)")
        parameters.extend([category, category])
    if in_stock:
        clauses.append(
            "EXISTS(SELECT 1 FROM variants sv WHERE sv.product_id = p.id AND sv.stock > 0)"
        )
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with closing(connect()) as connection:
        rows = connection.execute(
            f"""
            SELECT p.*, c.name category_name, c.slug category_slug,
                   COALESCE(SUM(v.stock), 0) total_stock
            FROM products p JOIN categories c ON c.id = p.category_id
            LEFT JOIN variants v ON v.product_id = p.id
            {where} GROUP BY p.id ORDER BY {order_by}
            """,
            parameters,
        ).fetchall()
        products = []
        for row in rows:
            product = dict(row)
            product["in_stock"] = int(product.pop("total_stock")) > 0
            products.append(product)
        return products


@app.get("/products/{identifier}")
async def get_product(identifier: str) -> dict[str, object]:
    with closing(connect()) as connection:
        return fetch_product(connection, identifier)


@app.post("/auth/login")
async def login(payload: LoginRequest) -> dict[str, object]:
    with closing(connect()) as connection:
        customer = connection.execute(
            "SELECT id, email, name, phone FROM customers WHERE email = ?", (payload.email,)
        ).fetchone()
    if customer is None:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호를 확인해주세요.")
    return {
        "access_token": "demo-customer-token",
        "token_type": "bearer",
        "customer": dict(customer),
    }


@app.get("/customers/me")
async def current_customer() -> dict[str, object]:
    with closing(connect()) as connection:
        customer = connection.execute(
            "SELECT id, email, name, phone FROM customers WHERE id = 'cus_demo'"
        ).fetchone()
    return dict(customer) if customer else {}


@app.get("/carts/{cart_id}")
async def get_cart(cart_id: str, coupon_code: str | None = None) -> dict[str, object]:
    with transaction() as connection:
        return cart_payload(connection, cart_id, coupon_code)


@app.post("/carts/{cart_id}/items")
async def add_cart_item(cart_id: str, payload: CartItemCreate) -> dict[str, object]:
    with transaction() as connection:
        ensure_cart(connection, cart_id)
        variant = connection.execute(
            "SELECT stock FROM variants WHERE id = ?", (payload.variant_id,)
        ).fetchone()
        if variant is None:
            raise HTTPException(status_code=404, detail="상품 옵션을 찾을 수 없습니다.")
        current = connection.execute(
            "SELECT id, quantity FROM cart_items WHERE cart_id = ? AND variant_id = ?",
            (cart_id, payload.variant_id),
        ).fetchone()
        next_quantity = payload.quantity + (int(current["quantity"]) if current else 0)
        if next_quantity > int(variant["stock"]):
            raise HTTPException(
                status_code=409, detail=f"구매 가능한 수량은 {variant['stock']}개입니다."
            )
        if current:
            connection.execute(
                "UPDATE cart_items SET quantity = ? WHERE id = ?", (next_quantity, current["id"])
            )
        else:
            connection.execute(
                "INSERT INTO cart_items(id, cart_id, variant_id, quantity) VALUES(?,?,?,?)",
                (f"ci_{uuid4().hex[:12]}", cart_id, payload.variant_id, payload.quantity),
            )
        connection.execute("UPDATE carts SET updated_at = ? WHERE id = ?", (utc_now(), cart_id))
        return cart_payload(connection, cart_id)


@app.patch("/carts/{cart_id}/items/{item_id}")
async def update_cart_item(
    cart_id: str, item_id: str, payload: CartItemUpdate
) -> dict[str, object]:
    with transaction() as connection:
        item = connection.execute(
            """
            SELECT ci.id, v.stock FROM cart_items ci JOIN variants v ON v.id = ci.variant_id
            WHERE ci.id = ? AND ci.cart_id = ?
            """,
            (item_id, cart_id),
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="장바구니 상품을 찾을 수 없습니다.")
        if payload.quantity > int(item["stock"]):
            raise HTTPException(
                status_code=409, detail=f"구매 가능한 수량은 {item['stock']}개입니다."
            )
        connection.execute(
            "UPDATE cart_items SET quantity = ? WHERE id = ?", (payload.quantity, item_id)
        )
        return cart_payload(connection, cart_id)


@app.delete("/carts/{cart_id}/items/{item_id}")
async def delete_cart_item(cart_id: str, item_id: str) -> dict[str, object]:
    with transaction() as connection:
        connection.execute(
            "DELETE FROM cart_items WHERE id = ? AND cart_id = ?", (item_id, cart_id)
        )
        return cart_payload(connection, cart_id)


@app.post("/checkout/validate")
async def validate_checkout(payload: CheckoutRequest) -> dict[str, object]:
    with transaction() as connection:
        return cart_payload(connection, payload.cart_id, payload.coupon_code)


@app.post("/checkout/orders", status_code=201)
async def create_order(payload: CheckoutRequest) -> dict[str, object]:
    with transaction() as connection:
        cart = cart_payload(connection, payload.cart_id, payload.coupon_code)
        if not cart["valid"]:
            raise HTTPException(
                status_code=409, detail=cart["coupon_message"] or "장바구니를 확인해주세요."
            )
        order_id = f"ord_{datetime.now(UTC).strftime('%y%m%d')}_{uuid4().hex[:8]}"
        for item in cart["items"]:
            updated = connection.execute(
                "UPDATE variants SET stock = stock - ? WHERE id = ? AND stock >= ?",
                (item["quantity"], item["variant_id"], item["quantity"]),
            )
            if updated.rowcount != 1:
                raise HTTPException(
                    status_code=409, detail=f"{item['name']}의 재고가 변경되었습니다."
                )
        now = utc_now()
        connection.execute(
            """
            INSERT INTO orders(
                id, customer_id, email, recipient, phone, postal_code, address1, address2,
                delivery_memo, status, subtotal, discount, shipping_fee, total,
                payment_status, ordered_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                order_id,
                payload.customer_id,
                payload.email,
                payload.recipient,
                payload.phone,
                payload.postal_code,
                payload.address1,
                payload.address2,
                payload.delivery_memo,
                "PENDING_PAYMENT",
                cart["subtotal"],
                cart["discount"],
                cart["shipping_fee"],
                cart["total"],
                "READY",
                now,
                now,
            ),
        )
        for item in cart["items"]:
            connection.execute(
                "INSERT INTO order_items VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    f"oi_{uuid4().hex[:12]}",
                    order_id,
                    item["product_id"],
                    item["variant_id"],
                    item["name"],
                    item["sku"],
                    f"{item['color']} / {item['size']}",
                    item["price"],
                    item["quantity"],
                    item["line_total"],
                ),
            )
        eta = (datetime.now(UTC) + timedelta(days=3)).date().isoformat()
        connection.execute(
            "INSERT INTO shipments VALUES(?,?,?,?,?,?,?,?)",
            (f"ship_{uuid4().hex[:10]}", order_id, None, None, "PREPARING", eta, None, now),
        )
        connection.execute("DELETE FROM cart_items WHERE cart_id = ?", (payload.cart_id,))
        record_event(
            connection,
            event_type="ORDER_CREATED",
            external_event_id=f"{order_id}:ORDER_CREATED",
            order_id=order_id,
            quantity=sum(int(item["quantity"]) for item in cart["items"]),
            amount=int(cart["total"]),
            discount=int(cart["discount"]),
            shipping_fee=int(cart["shipping_fee"]),
            occurred_at=now,
        )
        for item in cart["items"]:
            record_event(
                connection,
                event_type="STOCK_CHANGED",
                external_event_id=f"{order_id}:{item['variant_id']}:STOCK_CHANGED:ORDER_CREATED",
                order_id=order_id,
                product_id=item["product_id"],
                variant_id=item["variant_id"],
                quantity=-int(item["quantity"]),
                occurred_at=now,
            )
        return order_payload(connection, order_id)


@app.post("/payments/confirm")
async def confirm_payment(payload: PaymentConfirm) -> dict[str, object]:
    with transaction() as connection:
        order = connection.execute(
            "SELECT * FROM orders WHERE id = ?", (payload.order_id,)
        ).fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
        if int(order["total"]) != payload.amount:
            raise HTTPException(
                status_code=400, detail="결제 금액이 주문 금액과 일치하지 않습니다."
            )
        existing = connection.execute(
            "SELECT * FROM payments WHERE order_id = ?", (payload.order_id,)
        ).fetchone()
        if existing:
            return {"payment": dict(existing), "order": order_payload(connection, payload.order_id)}
        now = utc_now()
        payment = {
            "id": f"pay_{uuid4().hex[:12]}",
            "order_id": payload.order_id,
            "payment_key": f"test_{uuid4().hex}",
            "method": payload.method,
            "amount": payload.amount,
            "status": "PAID",
            "approved_at": now,
        }
        connection.execute(
            """
            INSERT INTO payments
            VALUES(:id,:order_id,:payment_key,:method,:amount,:status,:approved_at)
            """,
            payment,
        )
        connection.execute(
            """
            UPDATE orders SET status = 'PREPARING', payment_status = 'PAID', updated_at = ?
            WHERE id = ?
            """,
            (now, payload.order_id),
        )
        record_event(
            connection,
            event_type="PAYMENT_CONFIRMED",
            external_event_id=f"{payload.order_id}:PAYMENT_CONFIRMED",
            order_id=payload.order_id,
            amount=payload.amount,
            occurred_at=now,
        )
        return {"payment": payment, "order": order_payload(connection, payload.order_id)}


@app.get("/orders")
@app.get("/customers/me/orders")
async def list_orders() -> list[dict[str, object]]:
    with closing(connect()) as connection:
        ids = connection.execute(
            "SELECT id FROM orders WHERE customer_id = 'cus_demo' ORDER BY ordered_at DESC"
        ).fetchall()
        return [order_payload(connection, row["id"]) for row in ids]


@app.get("/orders/{order_id}")
@app.get("/customers/me/orders/{order_id}")
async def get_order(order_id: str) -> dict[str, object]:
    with closing(connect()) as connection:
        return order_payload(connection, order_id)


@app.get("/orders/{order_id}/shipment")
async def get_shipment(order_id: str) -> dict[str, object] | None:
    with closing(connect()) as connection:
        order_payload(connection, order_id)
        return row_to_dict(
            connection.execute("SELECT * FROM shipments WHERE order_id = ?", (order_id,)).fetchone()
        )


@app.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: str, payload: OrderAction) -> dict[str, object]:
    with transaction() as connection:
        order = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
        if order["status"] not in {"PENDING_PAYMENT", "PREPARING"}:
            raise HTTPException(
                status_code=409,
                detail="이미 출고된 주문은 취소할 수 없습니다. 반품을 신청해주세요.",
            )
        items = connection.execute(
            "SELECT * FROM order_items WHERE order_id = ?", (order_id,)
        ).fetchall()
        now = utc_now()
        for item in items:
            connection.execute(
                "UPDATE variants SET stock = stock + ? WHERE id = ?",
                (item["quantity"], item["variant_id"]),
            )
            record_event(
                connection,
                event_type="STOCK_CHANGED",
                external_event_id=f"{order_id}:{item['variant_id']}:STOCK_CHANGED:ORDER_CANCELLED",
                order_id=order_id,
                product_id=item["product_id"],
                variant_id=item["variant_id"],
                quantity=int(item["quantity"]),
                occurred_at=now,
            )
        connection.execute(
            """
            UPDATE orders SET status = 'CANCELLED', payment_status = 'REFUNDED', updated_at = ?
            WHERE id = ?
            """,
            (now, order_id),
        )
        connection.execute(
            "UPDATE payments SET status = 'REFUNDED' WHERE order_id = ?", (order_id,)
        )
        claim = {
            "id": f"clm_{uuid4().hex[:12]}",
            "order_id": order_id,
            "type": "CANCEL",
            "reason": payload.reason,
            "status": "REFUNDED",
            "refund_amount": order["total"],
            "return_fee": 0,
            "created_at": now,
            "updated_at": now,
        }
        connection.execute(
            """
            INSERT INTO claims
            VALUES(:id,:order_id,:type,:reason,:status,:refund_amount,
                   :return_fee,:created_at,:updated_at)
            """,
            claim,
        )
        record_event(
            connection,
            event_type="ORDER_CANCELLED",
            external_event_id=f"{order_id}:ORDER_CANCELLED",
            order_id=order_id,
            amount=order["total"],
            occurred_at=now,
        )
        record_event(
            connection,
            event_type="REFUND_COMPLETED",
            external_event_id=f"{order_id}:REFUND_COMPLETED:CANCEL",
            order_id=order_id,
            refund_amount=claim["refund_amount"],
            occurred_at=now,
        )
        return order_payload(connection, order_id)


@app.post("/orders/{order_id}/refund")
@app.post("/orders/{order_id}/returns")
async def request_return(order_id: str, payload: OrderAction) -> dict[str, object]:
    with transaction() as connection:
        order = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
        if order["status"] != "DELIVERED":
            raise HTTPException(
                status_code=409, detail="배송 완료된 주문만 반품을 신청할 수 있습니다."
            )
        return_fee = 3_000
        now = utc_now()
        claim = {
            "id": f"clm_{uuid4().hex[:12]}",
            "order_id": order_id,
            "type": "RETURN",
            "reason": payload.reason,
            "status": "REQUESTED",
            "refund_amount": max(int(order["total"]) - return_fee, 0),
            "return_fee": return_fee,
            "created_at": now,
            "updated_at": now,
        }
        connection.execute(
            """
            INSERT INTO claims
            VALUES(:id,:order_id,:type,:reason,:status,:refund_amount,
                   :return_fee,:created_at,:updated_at)
            """,
            claim,
        )
        connection.execute(
            "UPDATE orders SET status = 'RETURN_REQUESTED', updated_at = ? WHERE id = ?",
            (now, order_id),
        )
        # Only the request is recorded here. REFUND_COMPLETED is emitted separately
        # once a return actually finishes (pickup/inspection/refund), which this
        # demo API does not yet implement — see docs/ai-ops-studio-master-prd.html.
        record_event(
            connection,
            event_type="RETURN_REQUESTED",
            external_event_id=f"{order_id}:RETURN_REQUESTED",
            order_id=order_id,
            refund_amount=int(claim["refund_amount"]),
            occurred_at=now,
        )
        return {"claim": claim, "order": order_payload(connection, order_id)}


@app.get("/events")
async def list_events(
    order_id: str | None = None,
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, object]]:
    clauses: list[str] = []
    parameters: list[object] = []
    if order_id:
        clauses.append("order_id = ?")
        parameters.append(order_id)
    if event_type:
        clauses.append("event_type = ?")
        parameters.append(event_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with closing(connect()) as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM commerce_events {where}
            ORDER BY occurred_at DESC, rowid DESC LIMIT ?
            """,
            [*parameters, limit],
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/analytics/summary")
async def analytics_summary(
    period: str = Query(default_factory=current_period, pattern=PERIOD_PATTERN.pattern),
) -> dict[str, object]:
    with closing(connect()) as connection:
        return revenue_summary_with_comparison(connection, period)


@app.get("/analytics/products")
async def analytics_products(
    period: str = Query(default_factory=current_period, pattern=PERIOD_PATTERN.pattern),
) -> list[dict[str, object]]:
    with closing(connect()) as connection:
        return product_breakdown(connection, period)


@app.get("/policies/commerce")
async def commerce_policy() -> dict[str, object]:
    return {
        "shipping_fee": STANDARD_SHIPPING_FEE,
        "free_shipping_threshold": FREE_SHIPPING_THRESHOLD,
        "return_window_days": 7,
        "return_fee": 3_000,
        "exchange_fee": 6_000,
        "support_hours": "평일 10:00~17:00",
    }
