import os
import secrets
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from app import discord_spec
from app.analytics import (
    DATE_PATTERN,
    PERIOD_PATTERN,
    current_period,
    is_valid_date,
    platform_daily_traffic,
    product_breakdown,
    revenue_summary_with_comparison,
    seller_daily_snapshot,
    seller_market_share,
    seller_revenue_summary,
    today,
)
from app.auth import (
    GoogleTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_google_id_token,
    verify_password,
)
from app.db import (
    DEFAULT_ORG_ID,
    connect,
    infer_order_org_id,
    initialize_database,
    record_event,
    row_to_dict,
    transaction,
    utc_now,
)

DEFAULT_COMMISSION_RATE = 0.08

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


def _cors_origins() -> list[str]:
    """Allowed browser origins.

    Same-origin Vercel deploys (frontend + /api/commerce on one domain) don't
    need CORS at all, but a split deployment or a preview domain does. Read a
    comma-separated COMMERCE_CORS_ORIGINS override; otherwise fall back to the
    local dev ports plus the known production domain so the deployed site
    isn't silently blocked.
    """
    configured = os.getenv("COMMERCE_CORS_ORIGINS", "")
    if configured.strip():
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://localhost:5174",
        "https://ai-ops-studio-demo-store.vercel.app",
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=r"https://.*\.vercel\.app",
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


class PaymentConfirm(BaseModel):
    order_id: str
    amount: int = Field(gt=0)
    method: Literal["CARD", "EASY_PAY"] = "CARD"


class OrderAction(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=4, max_length=100)


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    name: str = Field(min_length=1, max_length=50)
    phone: str = Field(min_length=9, max_length=20)
    as_seller: bool = False
    shop_name: str | None = Field(default=None, max_length=80)
    shop_category: str | None = Field(default=None, max_length=40)


class SellerActivateRequest(BaseModel):
    shop_name: str = Field(min_length=2, max_length=80)
    shop_category: str = Field(min_length=2, max_length=40)


class SellerProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    category_id: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=5, max_length=1000)
    material: str = Field(default="", max_length=200)
    care: str = Field(default="", max_length=200)
    image: str = Field(default="", max_length=500)
    price: int = Field(gt=0)
    compare_at_price: int | None = Field(default=None, gt=0)
    color: str = Field(min_length=1, max_length=30)
    size: str = Field(min_length=1, max_length=20)
    stock: int = Field(ge=0)


class SellerVariantUpdate(BaseModel):
    stock: int = Field(ge=0)
    price: int | None = Field(default=None, gt=0)


class OrganizationStatusUpdate(BaseModel):
    status: Literal["ACTIVE", "SUSPENDED"]


class GoogleAuthRequest(BaseModel):
    id_token: str = Field(min_length=10)
    as_seller: bool = False
    shop_name: str | None = Field(default=None, max_length=80)
    shop_category: str | None = Field(default=None, max_length=40)


class DiscordLinkRequest(BaseModel):
    guild_id: str = Field(min_length=1, max_length=32)
    code: str = Field(min_length=4, max_length=32)


class DiscordChannelUpsert(BaseModel):
    channel_key: str = Field(min_length=1, max_length=40)
    channel_id: str = Field(min_length=1, max_length=32)
    channel_name: str = Field(default="", max_length=100)
    webhook_url: str = Field(default="", max_length=300)


class DiscordChannelsRequest(BaseModel):
    guild_id: str = Field(min_length=1, max_length=32)
    channels: list[DiscordChannelUpsert] = Field(min_length=1, max_length=20)


def fetch_product(connection, identifier: str) -> dict[str, object]:
    product = connection.execute(
        """
        SELECT p.*, c.name category_name, c.slug category_slug,
               COALESCE(SUM(v.stock), 0) total_stock
        FROM products p
        JOIN categories c ON c.id = p.category_id
        LEFT JOIN variants v ON v.product_id = p.id
        WHERE p.id = ? OR p.slug = ?
        GROUP BY p.id, c.name, c.slug
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
        WHERE ci.cart_id = ? ORDER BY ci.id
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


def customer_profile(connection, customer_row) -> dict[str, object]:
    """Customer row + derived marketplace role (see docs/ai-ops-studio-master-prd.html#personas).

    GUEST has no row at all (caller just gets None back). Everyone with an
    account is CONSUMER unless they own an organization (SELLER) or carry
    the platform is_admin flag (ADMIN).
    """
    customer = dict(customer_row)
    customer.pop("password_hash", None)
    organization = row_to_dict(
        connection.execute(
            "SELECT * FROM organizations WHERE owner_customer_id = ?", (customer["id"],)
        ).fetchone()
    )
    if customer.get("is_admin"):
        role = "ADMIN"
    elif organization is not None:
        role = "SELLER"
    else:
        role = "CONSUMER"
    customer["is_admin"] = bool(customer.get("is_admin"))
    customer["role"] = role
    customer["organization"] = organization
    return customer


def authenticate(connection, authorization: str | None) -> dict[str, object] | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    customer_id = decode_access_token(token)
    if not customer_id:
        return None
    row = connection.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    return dict(row) if row is not None else None


def require_customer(connection, authorization: str | None) -> dict[str, object]:
    customer = authenticate(connection, authorization)
    if customer is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return customer


def require_seller_org(connection, authorization: str | None) -> dict[str, object]:
    customer = require_customer(connection, authorization)
    org = connection.execute(
        "SELECT * FROM organizations WHERE owner_customer_id = ?", (customer["id"],)
    ).fetchone()
    if org is None:
        raise HTTPException(status_code=403, detail="판매자로 활성화된 계정만 이용할 수 있습니다.")
    return dict(org)


def require_admin(connection, authorization: str | None) -> dict[str, object]:
    customer = require_customer(connection, authorization)
    if not customer.get("is_admin"):
        raise HTTPException(status_code=403, detail="총관리자만 이용할 수 있습니다.")
    return customer


def require_internal_token(x_internal_token: str | None) -> None:
    """Shared-secret gate for the Discord bot's /internal/discord/* calls.

    The bot (a separate process, often on the seller's own machine) sends
    DISCORD_BOT_SHARED_SECRET as the X-Internal-Token header. If the server
    has no secret configured, every internal call is refused — a closed
    default, same posture as the cron endpoints. secrets.compare_digest keeps
    the check constant-time.
    """
    expected = os.getenv("DISCORD_BOT_SHARED_SECRET", "")
    if not expected or not x_internal_token or not secrets.compare_digest(
        x_internal_token, expected
    ):
        raise HTTPException(status_code=401, detail="내부 인증에 실패했습니다.")


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
    # A suspended seller's listings disappear from the public catalog, even
    # though the rows stay in the DB (so reactivating the seller restores them).
    clauses.append("(p.org_id IS NULL OR o.status IS NULL OR o.status != 'SUSPENDED')")
    where = f"WHERE {' AND '.join(clauses)}"
    with closing(connect()) as connection:
        rows = connection.execute(
            f"""
            SELECT p.*, c.name category_name, c.slug category_slug,
                   COALESCE(SUM(v.stock), 0) total_stock
            FROM products p JOIN categories c ON c.id = p.category_id
            LEFT JOIN variants v ON v.product_id = p.id
            LEFT JOIN organizations o ON o.id = p.org_id
            {where} GROUP BY p.id, c.name, c.slug ORDER BY {order_by}
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


@app.post("/auth/signup", status_code=201)
async def signup(payload: SignupRequest) -> dict[str, object]:
    if payload.as_seller and not (payload.shop_name and payload.shop_category):
        raise HTTPException(
            status_code=400, detail="판매자로 가입하려면 상점명과 카테고리가 필요합니다."
        )
    with transaction() as connection:
        existing = connection.execute(
            "SELECT id FROM customers WHERE email = ?", (payload.email,)
        ).fetchone()
        if existing is not None:
            raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다.")
        customer_id = f"cus_{uuid4().hex[:12]}"
        now = utc_now()
        connection.execute(
            """
            INSERT INTO customers(id, email, name, phone, password_hash, is_admin, created_at)
            VALUES(?,?,?,?,?,0,?)
            """,
            (
                customer_id,
                payload.email,
                payload.name,
                payload.phone,
                hash_password(payload.password),
                now,
            ),
        )
        if payload.as_seller:
            connection.execute(
                """
                INSERT INTO organizations(
                    id, owner_customer_id, name, category, commission_rate, status, created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    f"org_{uuid4().hex[:12]}",
                    customer_id,
                    payload.shop_name,
                    payload.shop_category,
                    DEFAULT_COMMISSION_RATE,
                    "ACTIVE",
                    now,
                ),
            )
        customer_row = connection.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        profile = customer_profile(connection, customer_row)
    return {
        "access_token": create_access_token(customer_id),
        "token_type": "bearer",
        "customer": profile,
    }


@app.post("/auth/login")
async def login(payload: LoginRequest) -> dict[str, object]:
    with closing(connect()) as connection:
        customer_row = connection.execute(
            "SELECT * FROM customers WHERE email = ?", (payload.email,)
        ).fetchone()
        if customer_row is None or not verify_password(
            payload.password, customer_row["password_hash"]
        ):
            raise HTTPException(status_code=401, detail="이메일 또는 비밀번호를 확인해주세요.")
        profile = customer_profile(connection, customer_row)
    return {
        "access_token": create_access_token(profile["id"]),
        "token_type": "bearer",
        "customer": profile,
    }


@app.post("/auth/google")
async def google_auth(payload: GoogleAuthRequest) -> dict[str, object]:
    try:
        claims = verify_google_id_token(payload.id_token)
    except GoogleTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    email = str(claims["email"])
    name = str(claims.get("name") or email.split("@")[0])
    with transaction() as connection:
        customer_row = connection.execute(
            "SELECT * FROM customers WHERE email = ?", (email,)
        ).fetchone()
        if customer_row is None:
            customer_id = f"cus_{uuid4().hex[:12]}"
            now = utc_now()
            connection.execute(
                """
                INSERT INTO customers(id, email, name, phone, password_hash, is_admin, created_at)
                VALUES(?,?,?,?,?,0,?)
                """,
                (customer_id, email, name, "", "", now),
            )
            if payload.as_seller and payload.shop_name and payload.shop_category:
                connection.execute(
                    """
                    INSERT INTO organizations(
                        id, owner_customer_id, name, category, commission_rate, status, created_at
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        f"org_{uuid4().hex[:12]}",
                        customer_id,
                        payload.shop_name,
                        payload.shop_category,
                        DEFAULT_COMMISSION_RATE,
                        "ACTIVE",
                        now,
                    ),
                )
            customer_row = connection.execute(
                "SELECT * FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
        profile = customer_profile(connection, customer_row)
    return {
        "access_token": create_access_token(profile["id"]),
        "token_type": "bearer",
        "customer": profile,
    }


@app.get("/customers/me")
async def current_customer(authorization: str | None = Header(default=None)) -> dict[str, object]:
    with closing(connect()) as connection:
        customer = require_customer(connection, authorization)
        return customer_profile(connection, customer)


@app.post("/sellers/activate", status_code=201)
async def activate_seller(
    payload: SellerActivateRequest, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    with transaction() as connection:
        customer = require_customer(connection, authorization)
        existing_org = connection.execute(
            "SELECT id FROM organizations WHERE owner_customer_id = ?", (customer["id"],)
        ).fetchone()
        if existing_org is not None:
            raise HTTPException(status_code=409, detail="이미 판매자로 활성화된 계정입니다.")
        connection.execute(
            """
            INSERT INTO organizations(
                id, owner_customer_id, name, category, commission_rate, status, created_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                f"org_{uuid4().hex[:12]}",
                customer["id"],
                payload.shop_name,
                payload.shop_category,
                DEFAULT_COMMISSION_RATE,
                "ACTIVE",
                utc_now(),
            ),
        )
        updated = connection.execute(
            "SELECT * FROM customers WHERE id = ?", (customer["id"],)
        ).fetchone()
        return customer_profile(connection, updated)


def seller_product_payload(connection, product_row) -> dict[str, object]:
    product = dict(product_row)
    product["variants"] = [
        dict(row)
        for row in connection.execute(
            "SELECT id, sku, color, size, price, stock FROM variants WHERE product_id = ?",
            (product["id"],),
        ).fetchall()
    ]
    return product


@app.get("/sellers/me/products")
async def list_my_products(
    authorization: str | None = Header(default=None),
) -> list[dict[str, object]]:
    with closing(connect()) as connection:
        org = require_seller_org(connection, authorization)
        rows = connection.execute(
            "SELECT * FROM products WHERE org_id = ? ORDER BY created_at DESC", (org["id"],)
        ).fetchall()
        return [seller_product_payload(connection, row) for row in rows]


@app.post("/sellers/me/products", status_code=201)
async def create_my_product(
    payload: SellerProductCreate, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    with transaction() as connection:
        org = require_seller_org(connection, authorization)
        category = connection.execute(
            "SELECT id FROM categories WHERE id = ?", (payload.category_id,)
        ).fetchone()
        if category is None:
            raise HTTPException(status_code=400, detail="존재하지 않는 카테고리입니다.")
        product_id = f"prd_{uuid4().hex[:12]}"
        slug = f"{product_id}-{uuid4().hex[:6]}"
        now = utc_now()
        default_image = (
            "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab"
            "?auto=format&fit=crop&w=1200&q=85"
        )
        connection.execute(
            """
            INSERT INTO products(
                id, slug, category_id, org_id, brand, name, description, material, care,
                image, price, compare_at_price, rating, review_count, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                product_id,
                slug,
                payload.category_id,
                org["id"],
                org["name"],
                payload.name,
                payload.description,
                payload.material,
                payload.care,
                payload.image.strip() or default_image,
                payload.price,
                payload.compare_at_price,
                0,
                0,
                now,
            ),
        )
        variant_id = f"var_{uuid4().hex[:12]}"
        sku = f"{product_id[:10]}-{uuid4().hex[:6]}".upper()
        connection.execute(
            """
            INSERT INTO variants(id, product_id, sku, color, size, price, stock)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                variant_id,
                product_id,
                sku,
                payload.color,
                payload.size,
                payload.price,
                payload.stock,
            ),
        )
        product_row = connection.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        return seller_product_payload(connection, product_row)


@app.patch("/sellers/me/products/{product_id}/variants/{variant_id}")
async def update_my_product_variant(
    product_id: str,
    variant_id: str,
    payload: SellerVariantUpdate,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    with transaction() as connection:
        org = require_seller_org(connection, authorization)
        product = connection.execute(
            "SELECT id FROM products WHERE id = ? AND org_id = ?", (product_id, org["id"])
        ).fetchone()
        if product is None:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
        variant = connection.execute(
            "SELECT id FROM variants WHERE id = ? AND product_id = ?", (variant_id, product_id)
        ).fetchone()
        if variant is None:
            raise HTTPException(status_code=404, detail="옵션을 찾을 수 없습니다.")
        connection.execute(
            "UPDATE variants SET stock = ?, price = COALESCE(?, price) WHERE id = ?",
            (payload.stock, payload.price, variant_id),
        )
        product_row = connection.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        return seller_product_payload(connection, product_row)


def organization_payload(connection, org_row) -> dict[str, object]:
    org = dict(org_row)
    owner = connection.execute(
        "SELECT id, email, name FROM customers WHERE id = ?", (org["owner_customer_id"],)
    ).fetchone()
    org["owner"] = dict(owner) if owner else None
    counts = connection.execute(
        "SELECT COUNT(*) AS product_count FROM products WHERE org_id = ?", (org["id"],)
    ).fetchone()
    org["product_count"] = int(counts["product_count"])
    return org


@app.get("/admin/organizations")
async def list_organizations(
    authorization: str | None = Header(default=None),
) -> list[dict[str, object]]:
    with closing(connect()) as connection:
        require_admin(connection, authorization)
        rows = connection.execute("SELECT * FROM organizations ORDER BY created_at DESC").fetchall()
        return [organization_payload(connection, row) for row in rows]


@app.patch("/admin/organizations/{org_id}")
async def update_organization_status(
    org_id: str,
    payload: OrganizationStatusUpdate,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    with transaction() as connection:
        require_admin(connection, authorization)
        org = connection.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
        if org is None:
            raise HTTPException(status_code=404, detail="조직을 찾을 수 없습니다.")
        connection.execute(
            "UPDATE organizations SET status = ? WHERE id = ?", (payload.status, org_id)
        )
        updated = connection.execute(
            "SELECT * FROM organizations WHERE id = ?", (org_id,)
        ).fetchone()
        return organization_payload(connection, updated)


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
async def create_order(
    payload: CheckoutRequest, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    with transaction() as connection:
        # Identity comes from the token, never from the request body — a guest
        # checkout (no/invalid token) still works and is just left unattributed.
        customer = authenticate(connection, authorization)
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
                customer["id"] if customer else None,
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
        order_org_id = infer_order_org_id(connection, order_id)
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
            org_id=order_org_id,
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
                org_id=order_org_id,
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
            org_id=infer_order_org_id(connection, payload.order_id),
        )
        return {"payment": payment, "order": order_payload(connection, payload.order_id)}


@app.get("/orders")
async def list_orders() -> list[dict[str, object]]:
    with closing(connect()) as connection:
        ids = connection.execute("SELECT id FROM orders ORDER BY ordered_at DESC").fetchall()
        return [order_payload(connection, row["id"]) for row in ids]


@app.get("/customers/me/orders")
async def list_my_orders(
    authorization: str | None = Header(default=None),
) -> list[dict[str, object]]:
    with closing(connect()) as connection:
        customer = require_customer(connection, authorization)
        ids = connection.execute(
            "SELECT id FROM orders WHERE customer_id = ? ORDER BY ordered_at DESC",
            (customer["id"],),
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
        order_org_id = infer_order_org_id(connection, order_id)
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
                org_id=order_org_id,
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
            org_id=order_org_id,
        )
        record_event(
            connection,
            event_type="REFUND_COMPLETED",
            external_event_id=f"{order_id}:REFUND_COMPLETED:CANCEL",
            order_id=order_id,
            refund_amount=claim["refund_amount"],
            occurred_at=now,
            org_id=order_org_id,
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
            org_id=infer_order_org_id(connection, order_id),
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
            ORDER BY occurred_at DESC, created_at DESC LIMIT ?
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


@app.get("/analytics/seller-daily")
async def analytics_seller_daily(
    org_id: str = Query(min_length=1, max_length=64),
    date: str = Query(default_factory=today, pattern=DATE_PATTERN.pattern),
) -> dict[str, object]:
    if not is_valid_date(date):
        raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다.")
    with closing(connect()) as connection:
        org = connection.execute("SELECT id FROM organizations WHERE id = ?", (org_id,)).fetchone()
        if org is None:
            raise HTTPException(status_code=404, detail="조직을 찾을 수 없습니다.")
        return seller_daily_snapshot(connection, org_id, date)


@app.get("/analytics/platform-daily-traffic")
async def analytics_platform_daily_traffic(
    date: str = Query(default_factory=today, pattern=DATE_PATTERN.pattern),
) -> dict[str, object]:
    if not is_valid_date(date):
        raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다.")
    with closing(connect()) as connection:
        return platform_daily_traffic(connection, date)


@app.get("/analytics/seller-market-share")
async def analytics_seller_market_share(
    period: str = Query(default_factory=current_period, pattern=PERIOD_PATTERN.pattern),
) -> dict[str, object]:
    with closing(connect()) as connection:
        return seller_market_share(connection, period)


class ProductViewEvent(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)


@app.post("/events/product-view", status_code=202)
async def record_product_view(payload: ProductViewEvent) -> dict[str, object]:
    with transaction() as connection:
        product = connection.execute(
            "SELECT org_id FROM products WHERE id = ?", (payload.product_id,)
        ).fetchone()
        if product is None:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
        record_event(
            connection,
            event_type="PRODUCT_VIEWED",
            external_event_id=f"view_{uuid4().hex}",
            product_id=payload.product_id,
            org_id=product["org_id"] or DEFAULT_ORG_ID,
        )
    return {"status": "recorded"}


@app.get("/internal/organizations")
async def internal_organizations() -> list[dict[str, object]]:
    """Unauthenticated, service-to-service only (never exposed to a browser).

    Lets core-api's daily scheduler and inquiry-routing logic enumerate
    active sellers without going through the customer JWT auth model, which
    only makes sense for a human sitting at a browser.
    """
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT id, name FROM organizations WHERE status = 'ACTIVE' ORDER BY name"
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/internal/orders/{order_id}/org")
async def internal_order_org(order_id: str) -> dict[str, object]:
    with closing(connect()) as connection:
        order = connection.execute("SELECT id FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
        return {"order_id": order_id, "org_id": infer_order_org_id(connection, order_id)}


# ─────────────────────────── Discord 봇 연동 ───────────────────────────
# 판매자가 자기 Discord 서버에 봇을 초대해 쓰는 흐름을 위한 엔드포인트들.
#   1) 판매자 콘솔에서 POST /sellers/me/discord/link-code 로 1회용 코드 발급
#   2) 봇 초대 후 서버에서 /연동 <코드>  → 봇이 POST /internal/discord/link
#   3) 서버에서 /생성            → 봇이 GET /internal/discord/org 로 플랜별
#      채널 스펙을 받아 채널·웹훅을 만들고 PUT /internal/discord/channels 로 저장
#   4) 슬래시 명령(/수익 등)     → 봇이 GET /internal/discord/metrics 로 숫자 조회
# 내부(/internal/discord/*) 엔드포인트는 require_internal_token 으로 보호한다.


def _org_by_guild(connection, guild_id: str) -> dict[str, object] | None:
    row = connection.execute(
        "SELECT * FROM organizations WHERE discord_guild_id = ?", (guild_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def _discord_channels_payload(connection, org_id: str) -> list[dict[str, object]]:
    rows = connection.execute(
        "SELECT channel_key, channel_id, channel_name, webhook_url "
        "FROM discord_channels WHERE org_id = ? ORDER BY created_at",
        (org_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _discord_status_payload(connection, org: dict[str, object]) -> dict[str, object]:
    plan = discord_spec.normalize_plan(str(org.get("plan") or "FREE"))
    return {
        "linked": bool(org.get("discord_guild_id")),
        "guild_id": org.get("discord_guild_id"),
        "linked_at": org.get("discord_linked_at"),
        "plan": plan,
        "plan_channels": discord_spec.channels_for_plan(plan),
        "channels": _discord_channels_payload(connection, str(org["id"])),
    }


@app.post("/sellers/me/discord/link-code", status_code=201)
async def create_discord_link_code(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """Issue (or reissue) a one-time code the seller types into `/연동` in Discord."""
    with transaction() as connection:
        org = require_seller_org(connection, authorization)
        code = secrets.token_hex(4).upper()  # 8-char, e.g. "3F9A1C77"
        connection.execute(
            "UPDATE organizations SET discord_link_code = ? WHERE id = ?", (code, org["id"])
        )
        refreshed = connection.execute(
            "SELECT * FROM organizations WHERE id = ?", (org["id"],)
        ).fetchone()
        payload = _discord_status_payload(connection, dict(refreshed))
        payload["link_code"] = code
        return payload


@app.get("/sellers/me/discord")
async def get_discord_status(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    with closing(connect()) as connection:
        org = require_seller_org(connection, authorization)
        return _discord_status_payload(connection, org)


@app.post("/internal/discord/link")
async def internal_discord_link(
    payload: DiscordLinkRequest,
    x_internal_token: str | None = Header(default=None),
) -> dict[str, object]:
    require_internal_token(x_internal_token)
    with transaction() as connection:
        org = connection.execute(
            "SELECT * FROM organizations WHERE discord_link_code = ? AND discord_link_code != ''",
            (payload.code.upper(),),
        ).fetchone()
        if org is None:
            raise HTTPException(status_code=404, detail="유효하지 않은 연동 코드입니다.")
        # 판매자 계정 하나 = 디스코드 서버 하나로 고정한다. 이미 다른 서버에
        # 연동된 상점이 새 코드로 재연동을 시도하면 거부한다(같은 서버로의
        # 재연동은 멱등하게 허용 — 봇 재시작 등으로 /실행을 다시 돌리는 경우).
        current_guild_id = org["discord_guild_id"]
        if current_guild_id and current_guild_id != payload.guild_id:
            raise HTTPException(
                status_code=409,
                detail="이 상점은 이미 다른 디스코드 서버에 연동되어 있습니다.",
            )
        existing = _org_by_guild(connection, payload.guild_id)
        if existing is not None and existing["id"] != org["id"]:
            raise HTTPException(
                status_code=409, detail="이 디스코드 서버는 이미 다른 상점에 연동돼 있습니다."
            )
        connection.execute(
            """
            UPDATE organizations
            SET discord_guild_id = ?, discord_linked_at = ?, discord_link_code = ''
            WHERE id = ?
            """,
            (payload.guild_id, utc_now(), org["id"]),
        )
        refreshed = connection.execute(
            "SELECT * FROM organizations WHERE id = ?", (org["id"],)
        ).fetchone()
        return _discord_status_payload(connection, dict(refreshed))


@app.get("/internal/discord/org")
async def internal_discord_org(
    guild_id: str = Query(min_length=1, max_length=32),
    x_internal_token: str | None = Header(default=None),
) -> dict[str, object]:
    require_internal_token(x_internal_token)
    with closing(connect()) as connection:
        org = _org_by_guild(connection, guild_id)
        if org is None:
            raise HTTPException(status_code=404, detail="연동되지 않은 서버입니다.")
        payload = _discord_status_payload(connection, org)
        payload["org_id"] = org["id"]
        payload["org_name"] = org["name"]
        payload["category_name"] = discord_spec.CATEGORY_NAME
        return payload


@app.put("/internal/discord/channels")
async def internal_discord_channels(
    payload: DiscordChannelsRequest,
    x_internal_token: str | None = Header(default=None),
) -> dict[str, object]:
    require_internal_token(x_internal_token)
    with transaction() as connection:
        org = _org_by_guild(connection, payload.guild_id)
        if org is None:
            raise HTTPException(status_code=404, detail="연동되지 않은 서버입니다.")
        # /생성은 채널을 지우고 다시 만드므로, 기존 매핑을 비우고 새로 채운다.
        connection.execute("DELETE FROM discord_channels WHERE org_id = ?", (org["id"],))
        now = utc_now()
        for channel in payload.channels:
            connection.execute(
                """
                INSERT INTO discord_channels(
                    id, org_id, channel_key, channel_id, channel_name, webhook_url, created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    f"dch_{uuid4().hex[:12]}",
                    org["id"],
                    channel.channel_key,
                    channel.channel_id,
                    channel.channel_name,
                    channel.webhook_url,
                    now,
                ),
            )
        return _discord_status_payload(connection, org)


@app.get("/internal/discord/metrics")
async def internal_discord_metrics(
    guild_id: str = Query(min_length=1, max_length=32),
    kind: Literal["daily", "views", "revenue", "stock"] = "daily",
    period: str = Query(default_factory=current_period, pattern=PERIOD_PATTERN.pattern),
    date: str = Query(default_factory=today, pattern=DATE_PATTERN.pattern),
    x_internal_token: str | None = Header(default=None),
) -> dict[str, object]:
    """Code-computed numbers for the bot's slash commands (never an AI guess)."""
    require_internal_token(x_internal_token)
    with closing(connect()) as connection:
        org = _org_by_guild(connection, guild_id)
        if org is None:
            raise HTTPException(status_code=404, detail="연동되지 않은 서버입니다.")
        org_id = str(org["id"])
        if kind == "revenue":
            return seller_revenue_summary(connection, org_id, period)
        if not is_valid_date(date):
            raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다.")
        snapshot = seller_daily_snapshot(connection, org_id, date)
        if kind == "daily":
            return snapshot
        if kind == "views":
            products = [p for p in snapshot["products"] if int(p["views"]) > 0]
            products.sort(key=lambda p: int(p["views"]), reverse=True)
            return {
                "date": date,
                "org_id": org_id,
                "org_name": snapshot["org_name"],
                "total_views": sum(int(p["views"]) for p in snapshot["products"]),
                "top_products": products[:10],
            }
        # kind == "stock"
        highlights = snapshot["highlights"]
        return {
            "date": date,
            "org_id": org_id,
            "org_name": snapshot["org_name"],
            "out_of_stock": highlights["out_of_stock"],
            "low_stock": highlights["low_stock"],
            "products": snapshot["products"],
        }


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
