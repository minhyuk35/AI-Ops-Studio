import os
import secrets
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, UploadFile
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
    seller_daily_series,
    seller_daily_snapshot_with_comparison,
    seller_market_share,
    seller_revenue_summary_with_comparison,
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
    generate_referral_code,
    infer_order_org_id,
    initialize_database,
    record_combo_signal,
    record_event,
    row_to_dict,
    transaction,
    utc_now,
)
from app.recommendation import combo_score, pair_key
from app.sample_seed import extend_sign_seed

DEFAULT_COMMISSION_RATE = 0.08

FREE_SHIPPING_THRESHOLD = 100_000
STANDARD_SHIPPING_FEE = 3_000


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="CodiLab Commerce API",
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
    referral_code: str | None = Field(default=None, max_length=8)


class SellerActivateRequest(BaseModel):
    shop_name: str = Field(min_length=2, max_length=80)
    shop_category: str = Field(min_length=2, max_length=40)


class AddressInput(BaseModel):
    label: str = Field(min_length=1, max_length=30)
    recipient: str = Field(min_length=1, max_length=50)
    phone: str = Field(min_length=9, max_length=20)
    postal_code: str = Field(min_length=1, max_length=10)
    address1: str = Field(min_length=1, max_length=200)
    address2: str = Field(default="", max_length=200)
    is_default: bool = False


class PaymentMethodInput(BaseModel):
    label: str = Field(min_length=1, max_length=30)
    card_brand: str = Field(min_length=1, max_length=30)
    # 데모용 -- 실제 카드번호는 절대 받지 않는다. 마지막 4자리만 표시용으로 저장.
    last4: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    is_default: bool = False


class SellerVariantInput(BaseModel):
    color: str = Field(min_length=1, max_length=30)
    size: str = Field(min_length=1, max_length=20)
    stock: int = Field(ge=0)
    # None = 상품 기준가(SellerProductCreate.price)를 그대로 사용 -- 옵션마다
    # 다른 가격을 매기고 싶을 때만 채운다.
    price: int | None = Field(default=None, gt=0)


class SellerProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    category_id: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=5, max_length=1000)
    material: str = Field(default="", max_length=200)
    care: str = Field(default="", max_length=200)
    images: list[str] = Field(default_factory=list, max_length=8)
    price: int = Field(gt=0)
    compare_at_price: int | None = Field(default=None, gt=0)
    variants: list[SellerVariantInput] = Field(min_length=1, max_length=20)


class SellerProductUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    category_id: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=5, max_length=1000)
    material: str = Field(default="", max_length=200)
    care: str = Field(default="", max_length=200)
    images: list[str] = Field(default_factory=list, max_length=8)
    price: int = Field(gt=0)
    compare_at_price: int | None = Field(default=None, gt=0)
    is_active: bool = True


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


def _images_list(product: dict[str, object]) -> list[str]:
    """products.images is a comma-separated URL list (same pattern as
    style_tags); products.image stays the single "cover" image so every
    existing call site that reads it (cards, cart, orders, recommendations)
    keeps working untouched. Falls back to the cover image alone when a
    product predates multi-image support.
    """
    raw = str(product.get("images") or "")
    urls = [url.strip() for url in raw.split(",") if url.strip()]
    if urls:
        return urls
    cover = product.get("image")
    return [str(cover)] if cover else []


def fetch_product(connection, identifier: str) -> dict[str, object]:
    product = connection.execute(
        """
        SELECT p.*, c.name category_name, c.slug category_slug,
               COALESCE(SUM(v.stock), 0) total_stock
        FROM products p
        JOIN categories c ON c.id = p.category_id
        LEFT JOIN variants v ON v.product_id = p.id
        WHERE (p.id = ? OR p.slug = ?) AND p.is_active = 1
        GROUP BY p.id, c.name, c.slug
        """,
        (identifier, identifier),
    ).fetchone()
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
    result = dict(product)
    result["in_stock"] = int(result.pop("total_stock")) > 0
    result["images"] = _images_list(result)
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


def _apply_coupon(connection, code: str, subtotal: int) -> tuple[int, str, bool]:
    """(discount_amount, message, ok) for one coupon code against one
    cart's subtotal. Never raises -- an invalid/expired/ineligible coupon
    is a normal cart state (discount=0, valid=False), not an error.
    """
    coupon = connection.execute(
        "SELECT * FROM coupons WHERE code = ? AND is_active = 1", (code,)
    ).fetchone()
    if coupon is None:
        return 0, "사용할 수 없는 쿠폰입니다.", False
    if coupon["expires_at"] and str(coupon["expires_at"]) < utc_now():
        return 0, "만료된 쿠폰입니다.", False
    min_purchase = int(coupon["min_purchase_amount"])
    if subtotal < min_purchase:
        return 0, f"{min_purchase:,}원 이상 구매 시 사용할 수 있는 쿠폰입니다.", False
    if coupon["discount_type"] == "PERCENT":
        discount = subtotal * int(coupon["discount_value"]) // 100
    else:
        discount = int(coupon["discount_value"])
    if coupon["max_discount_amount"] is not None:
        discount = min(discount, int(coupon["max_discount_amount"]))
    discount = min(discount, subtotal)
    return discount, f"{code} 쿠폰이 적용되었습니다.", True


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
    if normalized_coupon:
        discount, coupon_message, coupon_ok = _apply_coupon(connection, normalized_coupon, subtotal)
        valid = valid and coupon_ok
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


def order_payloads(connection, order_ids: list[str]) -> list[dict[str, object]]:
    """Batched counterpart to order_payload() -- 5 queries total instead of
    5 queries per order. A seller/customer with hundreds of orders (e.g.
    SIGN's seeded 60-day activity history) made the per-order version slow
    enough to time out, since it was originally written when every account
    only ever had a handful of orders."""
    if not order_ids:
        return []
    placeholders = ",".join("?" for _ in order_ids)
    orders = {
        row["id"]: dict(row)
        for row in connection.execute(
            f"SELECT * FROM orders WHERE id IN ({placeholders})", order_ids
        ).fetchall()
    }
    items_by_order: dict[str, list[dict]] = {}
    for row in connection.execute(
        f"SELECT * FROM order_items WHERE order_id IN ({placeholders})", order_ids
    ).fetchall():
        items_by_order.setdefault(row["order_id"], []).append(dict(row))
    shipment_by_order = {
        row["order_id"]: row_to_dict(row)
        for row in connection.execute(
            f"SELECT * FROM shipments WHERE order_id IN ({placeholders})", order_ids
        ).fetchall()
    }
    payment_by_order = {
        row["order_id"]: row_to_dict(row)
        for row in connection.execute(
            f"SELECT * FROM payments WHERE order_id IN ({placeholders})", order_ids
        ).fetchall()
    }
    claims_by_order: dict[str, list[dict]] = {}
    for row in connection.execute(
        f"SELECT * FROM claims WHERE order_id IN ({placeholders}) ORDER BY created_at DESC",
        order_ids,
    ).fetchall():
        claims_by_order.setdefault(row["order_id"], []).append(dict(row))

    results = []
    for order_id in order_ids:
        order = orders.get(order_id)
        if order is None:
            continue
        result = dict(order)
        result["items"] = items_by_order.get(order_id, [])
        result["shipment"] = shipment_by_order.get(order_id)
        result["payment"] = payment_by_order.get(order_id)
        result["claims"] = claims_by_order.get(order_id, [])
        results.append(result)
    return results


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


def _verify_cron_request(authorization: str | None) -> None:
    """Same posture as core-api's cron routes: Vercel Cron sends
    `Authorization: Bearer $CRON_SECRET` automatically once CRON_SECRET is
    set as a project env var. Unset secret fails closed."""
    expected = os.getenv("CRON_SECRET", "")
    if not expected or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="내부 인증에 실패했습니다.")


@app.get("/internal/cron/extend-sign-seed")
async def cron_extend_sign_seed(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """Runs daily (see vercel.json) so SIGN's sample activity data always
    covers "today" -- without this, the fixed-window manual seed script
    silently falls behind by exactly one day every day it isn't re-run by
    hand, which is why the dashboard/charts kept showing gaps for "today"
    each time this was checked. See app/sample_seed.py for why this exists
    as a small deployed module instead of importing scripts/seed_sign_activity.py."""
    _verify_cron_request(authorization)
    with transaction() as connection:
        return extend_sign_seed(connection)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "CodiLab Commerce API", "docs": "/docs"}


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
        # 토큰 단위 매칭: 검색어를 공백으로 쪼개서 각 토큰이 이름·브랜드·설명·
        # 카테고리명 중 어딘가에는 있어야 함(토큰끼리는 AND, 필드끼리는 OR).
        # "블랙 후드"처럼 단어 순서·위치가 달라도 걸리게 하기 위함 — 예전에는
        # 전체 문자열을 한 덩어리로만 비교해서 이런 경우를 못 찾았음.
        tokens = [token for token in q.strip().split() if token][:6]
        for token in tokens:
            clauses.append(
                "(p.name LIKE ? OR p.brand LIKE ? OR p.description LIKE ? OR c.name LIKE ?)"
            )
            term = f"%{token}%"
            parameters.extend([term, term, term, term])
    if category:
        # `category` can be a leaf slug/id (직접 매칭) or a parent slug/id --
        # in the latter case match any leaf whose parent_id resolves to it,
        # so picking a 대분류 (e.g. "상의") shows every 소분류 under it.
        clauses.append(
            "(c.slug = ? OR c.id = ? OR c.parent_id = "
            "(SELECT id FROM categories WHERE slug = ? OR id = ?))"
        )
        parameters.extend([category, category, category, category])
    if in_stock:
        clauses.append(
            "EXISTS(SELECT 1 FROM variants sv WHERE sv.product_id = p.id AND sv.stock > 0)"
        )
    # A suspended seller's listings disappear from the public catalog, even
    # though the rows stay in the DB (so reactivating the seller restores them).
    clauses.append("(p.org_id IS NULL OR o.status IS NULL OR o.status != 'SUSPENDED')")
    # A seller-paused listing (판매 중지) also disappears from the public
    # catalog without deleting the row -- same "hide, don't destroy" pattern.
    clauses.append("p.is_active = 1")
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
            product["images"] = _images_list(product)
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
        referral_code = generate_referral_code()
        while connection.execute(
            "SELECT 1 FROM customers WHERE referral_code = ?", (referral_code,)
        ).fetchone():
            referral_code = generate_referral_code()
        # A referred_by code just needs to exist -- an invalid/typo'd code is
        # silently dropped rather than failing the whole signup over it.
        referred_by = None
        if payload.referral_code:
            candidate = payload.referral_code.strip().upper()
            if connection.execute(
                "SELECT 1 FROM customers WHERE referral_code = ?", (candidate,)
            ).fetchone():
                referred_by = candidate
        connection.execute(
            """
            INSERT INTO customers(id, email, name, phone, password_hash, is_admin, referral_code, referred_by, created_at)
            VALUES(?,?,?,?,?,0,?,?,?)
            """,
            (
                customer_id,
                payload.email,
                payload.name,
                payload.phone,
                hash_password(payload.password),
                referral_code,
                referred_by,
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


@app.get("/customers/me/addresses")
async def list_my_addresses(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    with closing(connect()) as connection:
        customer = require_customer(connection, authorization)
        rows = connection.execute(
            "SELECT * FROM addresses WHERE customer_id = ? ORDER BY is_default DESC, created_at DESC",
            (customer["id"],),
        ).fetchall()
        return [dict(row) for row in rows]


@app.post("/customers/me/addresses", status_code=201)
async def create_my_address(
    payload: AddressInput, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    with transaction() as connection:
        customer = require_customer(connection, authorization)
        address_id = f"addr_{uuid4().hex[:12]}"
        now = utc_now()
        if payload.is_default:
            connection.execute(
                "UPDATE addresses SET is_default = 0 WHERE customer_id = ?", (customer["id"],)
            )
        connection.execute(
            """
            INSERT INTO addresses(
                id, customer_id, label, recipient, phone, postal_code, address1, address2, is_default, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                address_id, customer["id"], payload.label, payload.recipient, payload.phone,
                payload.postal_code, payload.address1, payload.address2, int(payload.is_default), now,
            ),
        )
        return dict(connection.execute("SELECT * FROM addresses WHERE id = ?", (address_id,)).fetchone())


@app.post("/customers/me/addresses/{address_id}/default")
async def set_default_address(
    address_id: str, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    with transaction() as connection:
        customer = require_customer(connection, authorization)
        address = connection.execute(
            "SELECT * FROM addresses WHERE id = ? AND customer_id = ?", (address_id, customer["id"])
        ).fetchone()
        if address is None:
            raise HTTPException(status_code=404, detail="배송지를 찾을 수 없습니다.")
        connection.execute(
            "UPDATE addresses SET is_default = 0 WHERE customer_id = ?", (customer["id"],)
        )
        connection.execute("UPDATE addresses SET is_default = 1 WHERE id = ?", (address_id,))
        return dict(connection.execute("SELECT * FROM addresses WHERE id = ?", (address_id,)).fetchone())


@app.delete("/customers/me/addresses/{address_id}", status_code=204)
async def delete_my_address(
    address_id: str, authorization: str | None = Header(default=None)
) -> None:
    with transaction() as connection:
        customer = require_customer(connection, authorization)
        connection.execute(
            "DELETE FROM addresses WHERE id = ? AND customer_id = ?", (address_id, customer["id"])
        )


@app.get("/customers/me/payment-methods")
async def list_my_payment_methods(
    authorization: str | None = Header(default=None),
) -> list[dict[str, object]]:
    with closing(connect()) as connection:
        customer = require_customer(connection, authorization)
        rows = connection.execute(
            "SELECT * FROM payment_methods WHERE customer_id = ? ORDER BY is_default DESC, created_at DESC",
            (customer["id"],),
        ).fetchall()
        return [dict(row) for row in rows]


@app.post("/customers/me/payment-methods", status_code=201)
async def create_my_payment_method(
    payload: PaymentMethodInput, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    with transaction() as connection:
        customer = require_customer(connection, authorization)
        method_id = f"pm_{uuid4().hex[:12]}"
        now = utc_now()
        if payload.is_default:
            connection.execute(
                "UPDATE payment_methods SET is_default = 0 WHERE customer_id = ?", (customer["id"],)
            )
        connection.execute(
            """
            INSERT INTO payment_methods(id, customer_id, label, card_brand, last4, is_default, created_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (method_id, customer["id"], payload.label, payload.card_brand, payload.last4, int(payload.is_default), now),
        )
        return dict(connection.execute("SELECT * FROM payment_methods WHERE id = ?", (method_id,)).fetchone())


@app.post("/customers/me/payment-methods/{method_id}/default")
async def set_default_payment_method(
    method_id: str, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    with transaction() as connection:
        customer = require_customer(connection, authorization)
        method = connection.execute(
            "SELECT * FROM payment_methods WHERE id = ? AND customer_id = ?", (method_id, customer["id"])
        ).fetchone()
        if method is None:
            raise HTTPException(status_code=404, detail="결제 수단을 찾을 수 없습니다.")
        connection.execute(
            "UPDATE payment_methods SET is_default = 0 WHERE customer_id = ?", (customer["id"],)
        )
        connection.execute("UPDATE payment_methods SET is_default = 1 WHERE id = ?", (method_id,))
        return dict(connection.execute("SELECT * FROM payment_methods WHERE id = ?", (method_id,)).fetchone())


@app.delete("/customers/me/payment-methods/{method_id}", status_code=204)
async def delete_my_payment_method(
    method_id: str, authorization: str | None = Header(default=None)
) -> None:
    with transaction() as connection:
        customer = require_customer(connection, authorization)
        connection.execute(
            "DELETE FROM payment_methods WHERE id = ? AND customer_id = ?", (method_id, customer["id"])
        )


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
    product["images"] = _images_list(product)
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


_DEFAULT_PRODUCT_IMAGE = (
    "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab"
    "?auto=format&fit=crop&w=1200&q=85"
)

_VERCEL_BLOB_API_BASE = "https://blob.vercel-storage.com"
_UPLOAD_MAX_BYTES = 4 * 1024 * 1024  # Vercel 서버리스 함수 요청 본문 한도(4.5MB)보다 여유 있게
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@app.get("/uploads/status")
async def uploads_status() -> dict[str, bool]:
    """프론트가 파일 업로드 버튼을 보여줄지 말지 판단하는 용도.

    BLOB_READ_WRITE_TOKEN이 없으면 업로드 자체를 시도하지 않고 기존
    URL 붙여넣기 방식만 노출한다 -- 토큰을 나중에 연결하면 코드 변경 없이
    이 값만 true로 바뀌면서 업로드 버튼이 자동으로 나타난다.
    """
    return {"enabled": bool(os.getenv("BLOB_READ_WRITE_TOKEN"))}


async def _upload_to_vercel_blob(filename: str, content: bytes, content_type: str) -> str:
    """Vercel Blob REST API로 서버 사이드 업로드.

    NOTE: 이 프로젝트엔 BLOB_READ_WRITE_TOKEN이 아직 없어서(2026-08-06 기준)
    이 함수는 실제 Vercel Blob에 대고 라이브 테스트를 해보지 못했다 -- 토큰을
    연결한 뒤 실제 업로드 한 번은 꼭 확인해볼 것. 공식 SDK(@vercel/blob)는
    Node 전용이라, 이 서비스(Python/FastAPI)에서는 REST 스펙을 직접
    호출한다.
    """
    token = os.getenv("BLOB_READ_WRITE_TOKEN", "")
    if not token:
        raise HTTPException(
            status_code=503,
            detail="이미지 업로드가 아직 설정되지 않았습니다. 이미지 URL을 직접 입력해주세요.",
        )
    safe_name = f"{uuid4().hex[:12]}-{filename}"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.put(
            f"{_VERCEL_BLOB_API_BASE}/{safe_name}",
            content=content,
            headers={
                "Authorization": f"Bearer {token}",
                "x-content-type": content_type,
                "x-add-random-suffix": "1",
            },
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="이미지 업로드에 실패했습니다.")
    return str(response.json()["url"])


@app.post("/sellers/me/uploads")
async def upload_product_image(
    file: UploadFile,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    with closing(connect()) as connection:
        require_seller_org(connection, authorization)
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400, detail="이미지 파일만 업로드할 수 있습니다(JPEG/PNG/WEBP/GIF)."
        )
    content = await file.read()
    if len(content) > _UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=400, detail="이미지 용량은 4MB 이하만 가능합니다.")
    url = await _upload_to_vercel_blob(file.filename or "image", content, file.content_type)
    return {"url": url}


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
        images = [url.strip() for url in payload.images if url.strip()]
        cover_image = images[0] if images else _DEFAULT_PRODUCT_IMAGE
        connection.execute(
            """
            INSERT INTO products(
                id, slug, category_id, org_id, brand, name, description, material, care,
                image, images, price, compare_at_price, rating, review_count, created_at,
                is_active
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
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
                cover_image,
                ",".join(images),
                payload.price,
                payload.compare_at_price,
                0,
                0,
                now,
            ),
        )
        for variant in payload.variants:
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
                    variant.color,
                    variant.size,
                    variant.price or payload.price,
                    variant.stock,
                ),
            )
        product_row = connection.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        return seller_product_payload(connection, product_row)


@app.patch("/sellers/me/products/{product_id}")
async def update_my_product(
    product_id: str,
    payload: SellerProductUpdate,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    with transaction() as connection:
        org = require_seller_org(connection, authorization)
        product = connection.execute(
            "SELECT id FROM products WHERE id = ? AND org_id = ?", (product_id, org["id"])
        ).fetchone()
        if product is None:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
        category = connection.execute(
            "SELECT id FROM categories WHERE id = ?", (payload.category_id,)
        ).fetchone()
        if category is None:
            raise HTTPException(status_code=400, detail="존재하지 않는 카테고리입니다.")
        images = [url.strip() for url in payload.images if url.strip()]
        cover_image = images[0] if images else _DEFAULT_PRODUCT_IMAGE
        connection.execute(
            """
            UPDATE products SET
                name = ?, category_id = ?, description = ?, material = ?, care = ?,
                image = ?, images = ?, price = ?, compare_at_price = ?, is_active = ?
            WHERE id = ?
            """,
            (
                payload.name,
                payload.category_id,
                payload.description,
                payload.material,
                payload.care,
                cover_image,
                ",".join(images),
                payload.price,
                payload.compare_at_price,
                1 if payload.is_active else 0,
                product_id,
            ),
        )
        _recompute_affinity_for_product(connection, product_id)
        product_row = connection.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        return seller_product_payload(connection, product_row)


@app.post("/sellers/me/products/{product_id}/variants", status_code=201)
async def create_my_product_variant(
    product_id: str,
    payload: SellerVariantInput,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    with transaction() as connection:
        org = require_seller_org(connection, authorization)
        product = connection.execute(
            "SELECT id, price FROM products WHERE id = ? AND org_id = ?",
            (product_id, org["id"]),
        ).fetchone()
        if product is None:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
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
                payload.price or product["price"],
                payload.stock,
            ),
        )
        product_row = connection.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        return seller_product_payload(connection, product_row)


@app.delete("/sellers/me/products/{product_id}/variants/{variant_id}")
async def delete_my_product_variant(
    product_id: str,
    variant_id: str,
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
        remaining = connection.execute(
            "SELECT COUNT(*) c FROM variants WHERE product_id = ?", (product_id,)
        ).fetchone()
        if int(remaining["c"]) <= 1:
            raise HTTPException(status_code=409, detail="최소 1개의 옵션은 남아 있어야 합니다.")
        ordered = connection.execute(
            "SELECT 1 FROM order_items WHERE variant_id = ? LIMIT 1", (variant_id,)
        ).fetchone()
        if ordered is not None:
            raise HTTPException(
                status_code=409,
                detail="주문 이력이 있는 옵션은 삭제할 수 없습니다. 재고를 0으로 설정해주세요.",
            )
        connection.execute("DELETE FROM cart_items WHERE variant_id = ?", (variant_id,))
        connection.execute("DELETE FROM variants WHERE id = ?", (variant_id,))
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


class CouponCreate(BaseModel):
    code: str = Field(min_length=3, max_length=30)
    discount_type: Literal["PERCENT", "FIXED"]
    discount_value: int = Field(gt=0)
    max_discount_amount: int | None = Field(default=None, gt=0)
    min_purchase_amount: int = Field(default=0, ge=0)
    expires_at: str | None = Field(default=None, max_length=40)


class CouponUpdate(BaseModel):
    is_active: bool


@app.get("/admin/coupons")
async def list_coupons(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    with closing(connect()) as connection:
        require_admin(connection, authorization)
        rows = connection.execute("SELECT * FROM coupons ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


@app.post("/admin/coupons", status_code=201)
async def create_coupon(
    payload: CouponCreate, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    with transaction() as connection:
        require_admin(connection, authorization)
        code = payload.code.strip().upper()
        existing = connection.execute("SELECT 1 FROM coupons WHERE code = ?", (code,)).fetchone()
        if existing is not None:
            raise HTTPException(status_code=409, detail="이미 존재하는 쿠폰 코드입니다.")
        if payload.discount_type == "PERCENT" and payload.discount_value > 100:
            raise HTTPException(status_code=400, detail="퍼센트 할인은 100을 넘을 수 없습니다.")
        coupon_id = f"cpn_{uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO coupons(
                id, code, discount_type, discount_value, max_discount_amount,
                min_purchase_amount, expires_at, is_active, created_at
            ) VALUES(?,?,?,?,?,?,?,1,?)
            """,
            (
                coupon_id,
                code,
                payload.discount_type,
                payload.discount_value,
                payload.max_discount_amount,
                payload.min_purchase_amount,
                payload.expires_at,
                utc_now(),
            ),
        )
        row = connection.execute("SELECT * FROM coupons WHERE id = ?", (coupon_id,)).fetchone()
        return dict(row)


@app.patch("/admin/coupons/{coupon_id}")
async def update_coupon(
    coupon_id: str, payload: CouponUpdate, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    with transaction() as connection:
        require_admin(connection, authorization)
        coupon = connection.execute("SELECT id FROM coupons WHERE id = ?", (coupon_id,)).fetchone()
        if coupon is None:
            raise HTTPException(status_code=404, detail="쿠폰을 찾을 수 없습니다.")
        connection.execute(
            "UPDATE coupons SET is_active = ? WHERE id = ?",
            (1 if payload.is_active else 0, coupon_id),
        )
        row = connection.execute("SELECT * FROM coupons WHERE id = ?", (coupon_id,)).fetchone()
        return dict(row)


@app.get("/coupons/active")
async def list_active_coupons() -> list[dict[str, object]]:
    """소비자 접속 시 팝업 배너용 — 지금 실제로 쓸 수 있는 쿠폰만(비활성·
    만료 제외), 로그인 여부와 무관하게 공개."""
    with closing(connect()) as connection:
        now = utc_now()
        rows = connection.execute(
            """
            SELECT * FROM coupons
            WHERE is_active = 1 AND (expires_at IS NULL OR expires_at >= ?)
            ORDER BY created_at DESC
            """,
            (now,),
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/carts/{cart_id}")
async def get_cart(cart_id: str, coupon_code: str | None = None) -> dict[str, object]:
    with transaction() as connection:
        return cart_payload(connection, cart_id, coupon_code)


@app.post("/carts/{cart_id}/items")
async def add_cart_item(cart_id: str, payload: CartItemCreate) -> dict[str, object]:
    with transaction() as connection:
        ensure_cart(connection, cart_id)
        variant = connection.execute(
            "SELECT stock, product_id FROM variants WHERE id = ?", (payload.variant_id,)
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
        is_new_to_cart = current is None
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
        if is_new_to_cart:
            # AI 추천 엔진의 CO_CART 신호 — 처음으로 이 상품이 이 장바구니에 담긴 순간에만
            # 기록(수량만 늘어나는 경우는 새로운 "같이 담아봄" 신호가 아님).
            _record_cart_combo_signals(connection, cart_id, str(variant["product_id"]))
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
        order_org_id = infer_order_org_id(connection, payload.order_id)
        record_event(
            connection,
            event_type="PAYMENT_CONFIRMED",
            external_event_id=f"{payload.order_id}:PAYMENT_CONFIRMED",
            order_id=payload.order_id,
            amount=payload.amount,
            occurred_at=now,
            org_id=order_org_id,
        )
        _record_order_combo_signals(
            connection,
            order_id=payload.order_id,
            org_id=order_org_id,
            occurred_at=now,
            signal_type="CO_PURCHASED",
        )
        _notify_new_order(connection, payload.order_id, order_org_id)
        return {"payment": payment, "order": order_payload(connection, payload.order_id)}


@app.get("/orders")
async def list_orders() -> list[dict[str, object]]:
    with closing(connect()) as connection:
        ids = connection.execute("SELECT id FROM orders ORDER BY ordered_at DESC").fetchall()
        return order_payloads(connection, [row["id"] for row in ids])


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
        return order_payloads(connection, [row["id"] for row in ids])


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
        _record_order_combo_signals(
            connection,
            order_id=order_id,
            org_id=order_org_id,
            occurred_at=now,
            signal_type="REFUND_NEGATIVE",
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


def _recompute_product_rating(connection, product_id: str) -> None:
    row = connection.execute(
        "SELECT AVG(rating) avg_rating, COUNT(*) c FROM reviews WHERE product_id = ?",
        (product_id,),
    ).fetchone()
    avg_rating = float(row["avg_rating"]) if row and row["avg_rating"] is not None else 0.0
    count = int(row["c"]) if row else 0
    connection.execute(
        "UPDATE products SET rating = ?, review_count = ? WHERE id = ?",
        (round(avg_rating, 2), count, product_id),
    )


class ReviewCreate(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    product_id: str = Field(min_length=1, max_length=64)
    rating: int = Field(ge=1, le=5)
    content: str = Field(min_length=5, max_length=1000)


@app.post("/reviews", status_code=201)
async def create_review(
    payload: ReviewCreate, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    """배송 완료된 주문에 실제로 포함된 상품에 대해서만, 고객 1명당 상품 1개당
    리뷰 1개까지 작성할 수 있다. 등록 즉시 products.rating/review_count를
    실제 리뷰 집계로 재계산 -- 이 상품에 처음 달리는 실제 리뷰라면, 그동안
    보여주던 시드 데이터의 가짜 평점·리뷰수는 이 시점부터 완전히 대체된다.
    """
    with transaction() as connection:
        customer = require_customer(connection, authorization)
        order = connection.execute(
            "SELECT * FROM orders WHERE id = ? AND customer_id = ?",
            (payload.order_id, customer["id"]),
        ).fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="본인 주문만 리뷰를 작성할 수 있습니다.")
        if order["status"] != "DELIVERED":
            raise HTTPException(
                status_code=409, detail="배송 완료된 주문만 리뷰를 작성할 수 있습니다."
            )
        item = connection.execute(
            "SELECT 1 FROM order_items WHERE order_id = ? AND product_id = ?",
            (payload.order_id, payload.product_id),
        ).fetchone()
        if item is None:
            raise HTTPException(status_code=400, detail="이 주문에 포함된 상품이 아닙니다.")
        existing = connection.execute(
            "SELECT 1 FROM reviews WHERE customer_id = ? AND product_id = ?",
            (customer["id"], payload.product_id),
        ).fetchone()
        if existing is not None:
            raise HTTPException(status_code=409, detail="이미 이 상품에 리뷰를 작성했습니다.")
        review_id = f"rev_{uuid4().hex[:12]}"
        now = utc_now()
        connection.execute(
            """
            INSERT INTO reviews(
                id, product_id, customer_id, customer_name, order_id, rating, content, created_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                review_id,
                payload.product_id,
                customer["id"],
                customer["name"],
                payload.order_id,
                payload.rating,
                payload.content,
                now,
            ),
        )
        _recompute_product_rating(connection, payload.product_id)
        review_row = connection.execute(
            "SELECT * FROM reviews WHERE id = ?", (review_id,)
        ).fetchone()
        return dict(review_row)


@app.get("/products/{product_id}/reviews")
async def list_product_reviews(product_id: str) -> list[dict[str, object]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM reviews WHERE product_id = ? ORDER BY created_at DESC LIMIT 100",
            (product_id,),
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/customers/me/reviews")
async def list_my_reviews(
    authorization: str | None = Header(default=None),
) -> list[dict[str, object]]:
    with closing(connect()) as connection:
        customer = require_customer(connection, authorization)
        rows = connection.execute(
            "SELECT * FROM reviews WHERE customer_id = ? ORDER BY created_at DESC",
            (customer["id"],),
        ).fetchall()
        return [dict(row) for row in rows]


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
        return seller_daily_snapshot_with_comparison(connection, org_id, date)


@app.get("/sellers/me/revenue-summary")
async def get_seller_revenue_summary(
    period: str = Query(default_factory=current_period, pattern=PERIOD_PATTERN.pattern),
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """이번 달 vs 지난달 매출 비교 -- 판매자 콘솔 '이번 달 요약' 카드용."""
    with closing(connect()) as connection:
        org = require_seller_org(connection, authorization)
        return seller_revenue_summary_with_comparison(connection, str(org["id"]), period)


@app.get("/sellers/me/daily-series")
async def get_seller_daily_series(
    days: int = Query(default=60, ge=1, le=120),
    authorization: str | None = Header(default=None),
) -> list[dict[str, object]]:
    """최근 N일(기본 60일 = 이번 달 + 지난달 비교분) 일별 매출·주문수·조회수 추이."""
    with closing(connect()) as connection:
        org = require_seller_org(connection, authorization)
        end_date = datetime.now(UTC).date()
        start_date = end_date - timedelta(days=days - 1)
        series_end = end_date + timedelta(days=1)
        return seller_daily_series(
            connection, str(org["id"]), start_date.isoformat(), series_end.isoformat()
        )


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
    customer_id: str | None = Field(default=None, max_length=64)


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
            customer_id=payload.customer_id,
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


def _record_cart_combo_signals(connection, cart_id: str, new_product_id: str) -> None:
    """CO_CART: pair a newly-cart-added product against every other distinct
    product already in the same cart (docs/ai-recommendation-plan.html#s3).
    """
    rows = connection.execute(
        """
        SELECT DISTINCT v.product_id FROM cart_items ci
        JOIN variants v ON v.id = ci.variant_id
        WHERE ci.cart_id = ? AND v.product_id != ?
        """,
        (cart_id, new_product_id),
    ).fetchall()
    now = utc_now()
    for row in rows:
        other_product_id = str(row["product_id"])
        record_combo_signal(
            connection,
            external_event_id=f"cart:{cart_id}:{new_product_id}:{other_product_id}",
            product_a_id=new_product_id,
            product_b_id=other_product_id,
            signal_type="CO_CART",
            occurred_at=now,
        )
        _recompute_affinity_for_pair(connection, new_product_id, other_product_id)


def _record_order_combo_signals(
    connection, *, order_id: str, org_id: str, occurred_at: str, signal_type: str
) -> None:
    """CO_PURCHASED/REFUND_NEGATIVE: pair every distinct product in an order.

    Refunds in this demo's data model are whole-order (claims/returns don't
    track which specific order_item was returned -- see request_return), so
    a refund on a multi-product order applies REFUND_NEGATIVE to every pair
    in it rather than just the one item's pairings.
    """
    rows = connection.execute(
        "SELECT DISTINCT product_id FROM order_items WHERE order_id = ?", (order_id,)
    ).fetchall()
    product_ids = sorted({str(row["product_id"]) for row in rows})
    for i, product_a in enumerate(product_ids):
        for product_b in product_ids[i + 1 :]:
            record_combo_signal(
                connection,
                external_event_id=f"{order_id}:{signal_type}:{product_a}:{product_b}",
                product_a_id=product_a,
                product_b_id=product_b,
                signal_type=signal_type,
                org_id=org_id,
                occurred_at=occurred_at,
            )
            _recompute_affinity_for_pair(connection, product_a, product_b)


# --- AI 추천 · 코디 조합 엔진 (docs/ai-recommendation-plan.html) ---------------
# 조합 점수 자체는 app.recommendation의 순수 함수(코드)가 결정적으로 계산한다.
# 여기 있는 함수들은 그 계산에 필요한 데이터(카탈로그 속성, 행동 신호 집계,
# 취향 프로필 앵커)를 DB에서 모아주는 조회 전담 계층일 뿐이다.

_SIGNAL_WEIGHTS = {"CO_PURCHASED": 8.0, "CO_CART": 3.0, "REFUND_NEGATIVE": -10.0}
_MAX_SIGNAL_INFLUENCE = 5  # 같은 쌍이 아무리 많이 반복돼도 가중치는 5회분에서 포화


def _load_catalog_attrs(connection) -> dict[str, dict[str, object]]:
    rows = connection.execute(
        """
        SELECT p.id, p.slug, p.name, p.brand, p.image, p.price, p.compare_at_price,
               p.category_id, p.color_family, p.style_tags,
               c.name category_name, c.slug category_slug, c.parent_id category_parent_id,
               COALESCE(SUM(v.stock), 0) total_stock
        FROM products p
        JOIN categories c ON c.id = p.category_id
        LEFT JOIN variants v ON v.product_id = p.id
        LEFT JOIN organizations o ON o.id = p.org_id
        WHERE (p.org_id IS NULL OR o.status IS NULL OR o.status != 'SUSPENDED')
              AND p.is_active = 1
        GROUP BY p.id, c.name, c.slug, c.parent_id
        """
    ).fetchall()
    catalog: dict[str, dict[str, object]] = {}
    for row in rows:
        item = dict(row)
        item["in_stock"] = int(item.pop("total_stock")) > 0
        item["top_level_id"] = item["category_parent_id"] or item["category_id"]
        catalog[str(item["id"])] = item
    return catalog


def _load_signal_map(connection) -> dict[tuple[str, str], dict[str, int]]:
    rows = connection.execute(
        """
        SELECT product_a_id, product_b_id, signal_type, COUNT(*) c
        FROM combo_signals GROUP BY product_a_id, product_b_id, signal_type
        """
    ).fetchall()
    signal_map: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        key = (str(row["product_a_id"]), str(row["product_b_id"]))
        signal_map.setdefault(key, {})[str(row["signal_type"])] = int(row["c"])
    return signal_map


def _seed_and_signal_score(
    catalog: dict[str, dict[str, object]],
    signal_map: dict[tuple[str, str], dict[str, int]],
    product_a: str,
    product_b: str,
) -> tuple[float, float, float]:
    """(seed_score, signal_adjustment, final_score) -- the actual math behind
    one product_affinity row. Only called by the recompute path below; the
    request-time read path (_pair_score) reads the cached result instead.
    """
    a, b = catalog[product_a], catalog[product_b]
    seed = combo_score(
        color_family_a=a["color_family"],  # type: ignore[arg-type]
        color_family_b=b["color_family"],  # type: ignore[arg-type]
        style_tags_a=a["style_tags"],  # type: ignore[arg-type]
        style_tags_b=b["style_tags"],  # type: ignore[arg-type]
        top_level_a=a["top_level_id"],  # type: ignore[arg-type]
        top_level_b=b["top_level_id"],  # type: ignore[arg-type]
    )
    signals = signal_map.get(pair_key(product_a, product_b), {})
    adjustment = sum(
        _SIGNAL_WEIGHTS[signal_type] * min(count, _MAX_SIGNAL_INFLUENCE)
        for signal_type, count in signals.items()
    )
    final = max(0.0, min(100.0, seed + adjustment))
    return seed, adjustment, final


def _upsert_pair_affinity(
    connection,
    catalog: dict[str, dict[str, object]],
    signal_map: dict[tuple[str, str], dict[str, int]],
    product_a: str,
    product_b: str,
    now: str,
) -> None:
    seed, adjustment, final = _seed_and_signal_score(catalog, signal_map, product_a, product_b)
    key_a, key_b = pair_key(product_a, product_b)
    connection.execute(
        """
        INSERT INTO product_affinity(
            product_a_id, product_b_id, seed_score, signal_score, final_score, updated_at
        ) VALUES(?,?,?,?,?,?)
        ON CONFLICT(product_a_id, product_b_id) DO UPDATE SET
            seed_score = excluded.seed_score,
            signal_score = excluded.signal_score,
            final_score = excluded.final_score,
            updated_at = excluded.updated_at
        """,
        (key_a, key_b, seed, adjustment, final, now),
    )


def _recompute_affinity_for_product(connection, product_id: str) -> None:
    """상품 하나가 새로 태깅되거나(color_family/style_tags) 카테고리가
    바뀌었을 때, 그 상품이 낀 모든 쌍만 다시 계산 -- 전체 카탈로그를 매번
    다시 계산하지 않도록 O(N)으로 제한(전체 재계산은 O(N^2)).
    """
    catalog = _load_catalog_attrs(connection)
    if product_id not in catalog:
        return
    signal_map = _load_signal_map(connection)
    now = utc_now()
    for other_id in catalog:
        if other_id != product_id:
            _upsert_pair_affinity(connection, catalog, signal_map, product_id, other_id, now)


def _recompute_affinity_for_pair(connection, product_a: str, product_b: str) -> None:
    """행동 신호(combo_signals) 하나가 새로 기록됐을 때 그 쌍 하나만 갱신."""
    catalog = _load_catalog_attrs(connection)
    if product_a not in catalog or product_b not in catalog:
        return
    signal_map = _load_signal_map(connection)
    _upsert_pair_affinity(connection, catalog, signal_map, product_a, product_b, utc_now())


def _recompute_all_affinity(connection) -> None:
    """전체 카탈로그 쌍을 처음부터 다시 계산 -- 부트스트랩(테이블이 비어있을
    때) 전용. O(N^2)이라 카탈로그가 작을 때만 값싸다.
    """
    catalog = _load_catalog_attrs(connection)
    signal_map = _load_signal_map(connection)
    now = utc_now()
    ids = sorted(catalog.keys())
    for i, product_a in enumerate(ids):
        for product_b in ids[i + 1 :]:
            _upsert_pair_affinity(connection, catalog, signal_map, product_a, product_b, now)


def _ensure_affinity_backfilled() -> None:
    """First-ever recommendation request after this cache table shipped:
    the table is empty, so populate it once. Runs its own transaction()
    (not the caller's read-only connect()) so the backfill actually
    persists -- connect()-only connections never commit.
    """
    with closing(connect()) as connection:
        exists = connection.execute("SELECT 1 FROM product_affinity LIMIT 1").fetchone()
    if exists is not None:
        return
    with transaction() as connection:
        exists = connection.execute("SELECT 1 FROM product_affinity LIMIT 1").fetchone()
        if exists is None:
            _recompute_all_affinity(connection)


def _load_affinity_map(connection) -> dict[tuple[str, str], float]:
    rows = connection.execute(
        "SELECT product_a_id, product_b_id, final_score FROM product_affinity"
    ).fetchall()
    return {
        (str(row["product_a_id"]), str(row["product_b_id"])): float(row["final_score"])
        for row in rows
    }


def _pair_score(
    catalog: dict[str, dict[str, object]],
    affinity_map: dict[tuple[str, str], float],
    signal_map: dict[tuple[str, str], dict[str, int]],
    product_a: str,
    product_b: str,
) -> float:
    key = pair_key(product_a, product_b)
    cached = affinity_map.get(key)
    if cached is not None:
        return cached
    # 캐시에 없는 쌍(예: 태깅 직후 재계산이 아직 안 붙은 경우) -- 요청을
    # 막지 않고 그 자리에서 계산해서 응답한다. 다음 태깅/신호 이벤트가 오면
    # 정식으로 캐시에 들어간다.
    _, _, final = _seed_and_signal_score(catalog, signal_map, product_a, product_b)
    return final


def _customer_size_preferences(connection, customer_id: str) -> dict[str, str]:
    """최상위 카테고리별로 이 고객이 가장 많이 구매한 사이즈(주문 이력 기반).

    order_items.option_text는 체크아웃에서 항상 "{color} / {size}" 형식으로
    저장되므로, size는 그 뒤쪽 절반을 파싱해서 얻는다 -- 주문 이후 옵션이
    삭제돼도 이 텍스트는 그 시점의 스냅샷이라 안전하다.
    """
    rows = connection.execute(
        """
        SELECT COALESCE(c.parent_id, c.id) top_level_id, oi.option_text, COUNT(*) c
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        JOIN categories c ON c.id = p.category_id
        JOIN orders o ON o.id = oi.order_id
        WHERE o.customer_id = ?
        GROUP BY top_level_id, oi.option_text
        """,
        (customer_id,),
    ).fetchall()
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        top_level = str(row["top_level_id"])
        option_text = str(row["option_text"])
        if " / " in option_text:
            size = option_text.rsplit(" / ", 1)[-1].strip()
        else:
            size = option_text.strip()
        bucket = counts.setdefault(top_level, {})
        bucket[size] = bucket.get(size, 0) + int(row["c"])
    return {
        top_level: max(sizes, key=lambda size: sizes[size])
        for top_level, sizes in counts.items()
        if sizes
    }


def _load_in_stock_sizes(connection) -> dict[str, set[str]]:
    rows = connection.execute("SELECT product_id, size FROM variants WHERE stock > 0").fetchall()
    sizes: dict[str, set[str]] = {}
    for row in rows:
        sizes.setdefault(str(row["product_id"]), set()).add(str(row["size"]))
    return sizes


_SIZE_MATCH_BONUS = 6.0


def _resolve_recommendation_basis(
    connection, customer: dict[str, object] | None, cart_id: str | None
) -> tuple[int, list[str]]:
    """3단계 개인화 폴백(docs/ai-recommendation-plan.html#s4)의 앵커 상품 결정.

    장바구니는 어느 단계든 항상 최우선으로 포함된다. 반환하는 anchor_ids의
    첫 항목이 "기준 상품"(추천 근거 문구에 쓰임)이다.
    """
    cart_product_ids: list[str] = []
    if cart_id:
        rows = connection.execute(
            """
            SELECT DISTINCT v.product_id FROM cart_items ci
            JOIN variants v ON v.id = ci.variant_id WHERE ci.cart_id = ?
            """,
            (cart_id,),
        ).fetchall()
        cart_product_ids = [str(row["product_id"]) for row in rows]

    purchased_ids: list[str] = []
    viewed_ids: list[str] = []
    if customer:
        purchased_rows = connection.execute(
            """
            SELECT oi.product_id, MAX(o.ordered_at) latest FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.customer_id = ? GROUP BY oi.product_id ORDER BY latest DESC
            """,
            (customer["id"],),
        ).fetchall()
        purchased_ids = [str(row["product_id"]) for row in purchased_rows]
        viewed_rows = connection.execute(
            """
            SELECT product_id, MAX(occurred_at) latest FROM commerce_events
            WHERE event_type = 'PRODUCT_VIEWED' AND customer_id = ? AND product_id IS NOT NULL
            GROUP BY product_id ORDER BY latest DESC LIMIT 20
            """,
            (customer["id"],),
        ).fetchall()
        viewed_ids = [str(row["product_id"]) for row in viewed_rows]

    if purchased_ids:
        tier, basis_ids = 3, purchased_ids[:5]
    elif viewed_ids:
        tier, basis_ids = 2, viewed_ids[:5]
    else:
        tier, basis_ids = 1, []

    anchor_ids = list(dict.fromkeys(cart_product_ids + basis_ids))
    return tier, anchor_ids


def _bestseller_product_ids(connection, limit: int) -> list[str]:
    rows = connection.execute(
        """
        SELECT oi.product_id, SUM(oi.quantity) qty FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.payment_status = 'PAID'
        GROUP BY oi.product_id ORDER BY qty DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [str(row["product_id"]) for row in rows]


def _rank_candidates(
    catalog: dict[str, dict[str, object]],
    affinity_map: dict[tuple[str, str], float],
    signal_map: dict[tuple[str, str], dict[str, int]],
    anchor_ids: list[str],
    exclude_ids: set[str],
    preferred_sizes: dict[str, str],
    product_sizes: dict[str, set[str]],
) -> list[tuple[str, float, bool]]:
    scored: list[tuple[str, float, bool]] = []
    for product_id, item in catalog.items():
        if product_id in exclude_ids or not item["in_stock"]:
            continue
        best = 0.0
        for anchor_id in anchor_ids:
            if anchor_id not in catalog:
                continue
            best = max(best, _pair_score(catalog, affinity_map, signal_map, product_id, anchor_id))
        preferred_size = preferred_sizes.get(str(item["top_level_id"]))
        size_match = bool(preferred_size and preferred_size in product_sizes.get(product_id, set()))
        if size_match:
            best = min(100.0, best + _SIZE_MATCH_BONUS)
        scored.append((product_id, best, size_match))
    scored.sort(key=lambda entry: entry[1], reverse=True)
    return scored


def _recommendation_product_summary(
    item: dict[str, object], score: float | None, size_match: bool = False
) -> dict[str, object]:
    return {
        "id": item["id"],
        "slug": item["slug"],
        "name": item["name"],
        "brand": item["brand"],
        "image": item["image"],
        "price": item["price"],
        "compare_at_price": item["compare_at_price"],
        "category_name": item["category_name"],
        "category_slug": item["category_slug"],
        "in_stock": item["in_stock"],
        "match_score": round(score, 1) if score is not None else None,
        "preferred_size_match": size_match,
    }


@app.get("/recommendations/home")
async def get_home_recommendations(
    cart_id: str | None = Query(default=None, max_length=64),
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """홈 화면 'AI 추천' 섹션용 — 최대 5개, 카테고리 구분 없는 플랫 목록."""
    with closing(connect()) as connection:
        customer = authenticate(connection, authorization)
        catalog = _load_catalog_attrs(connection)
        tier, anchor_ids = _resolve_recommendation_basis(connection, customer, cart_id)
        basis_name = (
            catalog[anchor_ids[0]]["name"] if anchor_ids and anchor_ids[0] in catalog else None
        )
        if anchor_ids:
            _ensure_affinity_backfilled()
            affinity_map = _load_affinity_map(connection)
            signal_map = _load_signal_map(connection)
            preferred_sizes = (
                _customer_size_preferences(connection, str(customer["id"])) if customer else {}
            )
            product_sizes = _load_in_stock_sizes(connection)
            ranked = _rank_candidates(
                catalog, affinity_map, signal_map, anchor_ids, set(anchor_ids),
                preferred_sizes, product_sizes,
            )
            items = [
                _recommendation_product_summary(catalog[pid], score, size_match)
                for pid, score, size_match in ranked[:5]
            ]
        else:
            items = []
        if not items:
            fallback_ids = _bestseller_product_ids(connection, limit=5 + len(anchor_ids))
            items = [
                _recommendation_product_summary(catalog[pid], None)
                for pid in fallback_ids
                if pid in catalog and pid not in anchor_ids
            ][:5]
        return {"tier": tier, "basis_product_name": basis_name, "items": items}


_RECOMMENDATION_TOP_LEVELS = ["cat_top", "cat_bottom", "cat_outer", "cat_shoes", "cat_acc"]


@app.get("/recommendations")
async def get_recommendations(
    cart_id: str | None = Query(default=None, max_length=64),
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """'AI 추천' 전용 페이지용 — 대분류별로 묶어 각 최대 3개(최소 1개)."""
    with closing(connect()) as connection:
        customer = authenticate(connection, authorization)
        catalog = _load_catalog_attrs(connection)
        tier, anchor_ids = _resolve_recommendation_basis(connection, customer, cart_id)
        basis_name = (
            catalog[anchor_ids[0]]["name"] if anchor_ids and anchor_ids[0] in catalog else None
        )
        top_level_names = {
            str(row["id"]): str(row["name"])
            for row in connection.execute(
                "SELECT id, name FROM categories WHERE parent_id IS NULL ORDER BY sort_order"
            ).fetchall()
        }
        if anchor_ids:
            _ensure_affinity_backfilled()
            affinity_map = _load_affinity_map(connection)
            signal_map = _load_signal_map(connection)
            preferred_sizes = (
                _customer_size_preferences(connection, str(customer["id"])) if customer else {}
            )
            product_sizes = _load_in_stock_sizes(connection)
            ranked = _rank_candidates(
                catalog, affinity_map, signal_map, anchor_ids, set(anchor_ids),
                preferred_sizes, product_sizes,
            )
        else:
            ranked = [
                (pid, 0.0, False)
                for pid in _bestseller_product_ids(connection, limit=200)
                if pid in catalog
            ]
        sections = []
        for top_level_id in _RECOMMENDATION_TOP_LEVELS:
            if top_level_id not in top_level_names:
                continue
            picks = [
                _recommendation_product_summary(
                    catalog[pid], score if anchor_ids else None, size_match
                )
                for pid, score, size_match in ranked
                if catalog[pid]["top_level_id"] == top_level_id
            ][:3]
            if picks:
                sections.append(
                    {
                        "category_id": top_level_id,
                        "category_name": top_level_names[top_level_id],
                        "items": picks,
                    }
                )
        return {"tier": tier, "basis_product_name": basis_name, "sections": sections}


_LOW_STOCK_THRESHOLD = 3  # matches analytics.py's seller_daily_snapshot low_stock cutoff


def _notify_new_order(connection, order_id: str, org_id: str) -> None:
    """Posts a confirmation to the seller's own 주문-알림 Discord channel
    once payment is confirmed. Deliberately not AI-narrated (no LLM call,
    no Langfuse persona) -- this is exactly the kind of fact a template can
    state precisely, so it's cheaper and faster than routing it through
    core-api's AI pipeline. Best-effort: a missing webhook or a Discord
    hiccup must never fail the payment confirmation that triggered this.
    """
    webhook_row = connection.execute(
        "SELECT webhook_url FROM discord_channels WHERE org_id = ? AND channel_key = 'orders'",
        (org_id,),
    ).fetchone()
    webhook_url = webhook_row["webhook_url"] if webhook_row else None
    if not webhook_url:
        return

    items = connection.execute(
        """
        SELECT oi.product_name, oi.option_text, oi.quantity, v.stock
        FROM order_items oi
        LEFT JOIN variants v ON v.id = oi.variant_id
        WHERE oi.order_id = ?
        """,
        (order_id,),
    ).fetchall()
    order = connection.execute(
        "SELECT total FROM orders WHERE id = ?", (order_id,)
    ).fetchone()

    lines = ["🛒 **새 주문이 들어왔어요!** 재고 확인 후 자동 승인 완료.\n"]
    low_stock_names: list[str] = []
    for item in items:
        stock = item["stock"]
        stock_note = f"재고 {stock}개 남음" if stock is not None else "재고 확인 불가"
        name, option, qty = item["product_name"], item["option_text"], item["quantity"]
        lines.append(f"· {name} ({option}) {qty}개 · {stock_note}")
        if stock is not None and 0 <= stock <= _LOW_STOCK_THRESHOLD:
            low_stock_names.append(str(name))
    if order:
        lines.append(f"\n주문 금액: {int(order['total']):,}원 · 주문번호 {order_id}")
    if low_stock_names:
        restock_names = ", ".join(low_stock_names)
        lines.append(f"\n⚠️ 재고가 얼마 안 남았어요 — {restock_names} 채워주시는 게 좋을 것 같아요!")

    try:
        httpx.post(webhook_url, json={"content": "\n".join(lines)}, timeout=10)
    except httpx.HTTPError:
        pass


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


@app.get("/sellers/me/orders")
async def list_my_orders_as_seller(
    authorization: str | None = Header(default=None),
) -> list[dict[str, object]]:
    """Which orders were placed for *this seller's* products -- who ordered,
    what they ordered, and where it's shipping. Orders are single-seller
    (see infer_order_org_id), so this is a straight join, not a per-item
    filter of a mixed-seller order.
    """
    with closing(connect()) as connection:
        org = require_seller_org(connection, authorization)
        ids = connection.execute(
            """
            SELECT DISTINCT oi.order_id, o.ordered_at FROM order_items oi
            JOIN products p ON p.id = oi.product_id
            JOIN orders o ON o.id = oi.order_id
            WHERE p.org_id = ?
            ORDER BY o.ordered_at DESC
            """,
            (org["id"],),
        ).fetchall()
        return order_payloads(connection, [row["order_id"] for row in ids])


@app.post("/sellers/me/orders/{order_id}/complete-refund")
async def seller_complete_refund(
    order_id: str, authorization: str | None = Header(default=None)
) -> dict[str, object]:
    """Seller-side counterpart to the customer's return request
    (POST /orders/{id}/returns): approves the most recent pending RETURN
    claim, actually completing the refund. request_return() explicitly
    stops short of this -- "REFUND_COMPLETED is emitted separately once a
    return actually finishes" -- this endpoint is that missing second step.
    """
    with transaction() as connection:
        org = require_seller_org(connection, authorization)
        order = connection.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
        if infer_order_org_id(connection, order_id) != org["id"]:
            raise HTTPException(status_code=403, detail="본인 상점의 주문만 처리할 수 있습니다.")
        claim = connection.execute(
            """
            SELECT * FROM claims WHERE order_id = ? AND type = 'RETURN' AND status = 'REQUESTED'
            ORDER BY created_at DESC LIMIT 1
            """,
            (order_id,),
        ).fetchone()
        if claim is None:
            raise HTTPException(status_code=409, detail="처리할 반품·환불 신청이 없습니다.")
        now = utc_now()
        connection.execute(
            "UPDATE claims SET status = 'REFUNDED', updated_at = ? WHERE id = ?",
            (now, claim["id"]),
        )
        connection.execute(
            "UPDATE orders SET status = 'REFUNDED', updated_at = ? WHERE id = ?",
            (now, order_id),
        )
        connection.execute(
            "UPDATE payments SET status = 'REFUNDED' WHERE order_id = ?", (order_id,)
        )
        record_event(
            connection,
            event_type="REFUND_COMPLETED",
            external_event_id=f"{order_id}:REFUND_COMPLETED:RETURN",
            order_id=order_id,
            refund_amount=int(claim["refund_amount"]),
            occurred_at=now,
            org_id=org["id"],
        )
        _record_order_combo_signals(
            connection,
            order_id=order_id,
            org_id=org["id"],
            occurred_at=now,
            signal_type="REFUND_NEGATIVE",
        )
        return order_payload(connection, order_id)


@app.get("/orgs/{org_id}/discord-link-status")
async def get_org_discord_link_status(org_id: str) -> dict[str, object]:
    """공개(비인증) 엔드포인트 — QA 문의 테스트 페이지가 '연동돼 있어야 테스트
    가능' 게이트를 보여주기 위해 로그인 없이 확인하는 용도. linked/org_name
    외에는 아무것도 안 준다(guild_id·채널·웹훅 URL 등은 여전히 인증 필요한
    /sellers/me/discord 에서만)."""
    with closing(connect()) as connection:
        org = connection.execute(
            "SELECT name, discord_guild_id FROM organizations WHERE id = ?", (org_id,)
        ).fetchone()
        if org is None:
            raise HTTPException(status_code=404, detail="조직을 찾을 수 없습니다.")
        return {"org_id": org_id, "org_name": org["name"], "linked": bool(org["discord_guild_id"])}


@app.get("/sellers/me/discord")
async def get_discord_status(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    with closing(connect()) as connection:
        org = require_seller_org(connection, authorization)
        return _discord_status_payload(connection, org)


@app.post("/sellers/me/discord/unlink")
async def unlink_discord(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """Reverses /실행's link: clears the guild link and drops this org's
    channel/webhook rows, so a future re-link (to the same or a different
    server) starts clean instead of reusing stale webhook URLs."""
    with transaction() as connection:
        org = require_seller_org(connection, authorization)
        connection.execute(
            """
            UPDATE organizations
            SET discord_guild_id = NULL, discord_linked_at = NULL, discord_link_code = ''
            WHERE id = ?
            """,
            (org["id"],),
        )
        connection.execute("DELETE FROM discord_channels WHERE org_id = ?", (org["id"],))
        refreshed = connection.execute(
            "SELECT * FROM organizations WHERE id = ?", (org["id"],)
        ).fetchone()
        return _discord_status_payload(connection, dict(refreshed))


@app.post("/sellers/me/discord/test-notification")
async def send_discord_test_notification(
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """Lets a linked seller confirm the connection actually works end-to-end
    without waiting for a real order/AI report -- posts one throwaway
    message to whichever of the org's channels has a webhook registered
    (prefers 주문-알림 since it always exists once /실행 has run)."""
    with closing(connect()) as connection:
        org = require_seller_org(connection, authorization)
        if not org.get("discord_guild_id"):
            raise HTTPException(status_code=400, detail="아직 디스코드가 연동되지 않았습니다.")
        row = connection.execute(
            """
            SELECT channel_name, webhook_url FROM discord_channels
            WHERE org_id = ? AND webhook_url != ''
            ORDER BY (channel_key = 'orders') DESC, channel_key
            LIMIT 1
            """,
            (org["id"],),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=400,
                detail="등록된 웹훅이 없습니다. 서버에서 /실행 을 먼저 실행해주세요.",
            )
        message = (
            f"🔔 **테스트 알림입니다.** {org['name']} 판매자 콘솔에서 "
            "연동 확인을 위해 직접 보냈어요 — 이 메시지가 보이면 정상 연동된 것입니다."
        )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(row["webhook_url"], json={"content": message})
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"디스코드 전송에 실패했습니다: {exc}"
            ) from exc
        return {"status": "sent", "channel_name": row["channel_name"]}


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


@app.get("/internal/discord/channels-by-org")
async def internal_discord_channels_by_org(
    org_id: str = Query(min_length=1, max_length=64),
    x_internal_token: str | None = Header(default=None),
) -> dict[str, object]:
    """Same channel/webhook lookup as /internal/discord/org, but keyed by
    org_id -- used by core-api's scheduled cron reports (app/services/
    scheduler.py), which iterate every active org and don't have a
    per-seller guild_id or customer JWT to work with.
    """
    require_internal_token(x_internal_token)
    with closing(connect()) as connection:
        org = connection.execute(
            "SELECT * FROM organizations WHERE id = ?", (org_id,)
        ).fetchone()
        if org is None:
            raise HTTPException(status_code=404, detail="존재하지 않는 상점입니다.")
        return _discord_status_payload(connection, dict(org))


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


class ProductAttributesUpdate(BaseModel):
    color_family: str = Field(min_length=1, max_length=30)
    style_tags: list[str] = Field(min_length=1, max_length=3)


@app.patch("/internal/products/{product_id}/attributes")
async def internal_update_product_attributes(
    product_id: str,
    payload: ProductAttributesUpdate,
    x_internal_token: str | None = Header(default=None),
) -> dict[str, object]:
    """Writes back the AI 추천 tagger's one-time color/mood classification
    (core-api's ProductStyleTaggerService) -- see
    docs/ai-recommendation-plan.html#s3. Internal-token authed: this isn't
    something a seller's own bearer token calls directly, only core-api.
    """
    require_internal_token(x_internal_token)
    with transaction() as connection:
        product = connection.execute(
            "SELECT id FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if product is None:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")
        connection.execute(
            "UPDATE products SET color_family = ?, style_tags = ? WHERE id = ?",
            (payload.color_family, ",".join(payload.style_tags), product_id),
        )
        _recompute_affinity_for_product(connection, product_id)
        return {
            "product_id": product_id,
            "color_family": payload.color_family,
            "style_tags": payload.style_tags,
        }


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
            return seller_revenue_summary_with_comparison(connection, org_id, period)
        if not is_valid_date(date):
            raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다.")
        snapshot = seller_daily_snapshot_with_comparison(connection, org_id, date)
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
