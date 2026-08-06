import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.auth import hash_password
from app.db_compat import Connection, PostgresConnection, database_url, is_postgres

DEFAULT_ORG_ID = "org_demo"
DEMO_CUSTOMER_PASSWORD = "demo1234"
TEST_ACCOUNT_PASSWORD = "test1234"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def database_path() -> Path:
    configured = os.getenv("COMMERCE_DB_PATH", "data/commerce.db")
    path = Path(configured)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> Connection:
    if is_postgres():
        url = database_url()
        assert url is not None
        return PostgresConnection(url)
    connection = sqlite3.connect(database_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def transaction() -> Iterator[Connection]:
    connection = connect()
    try:
        # Postgres begins a transaction implicitly on the first statement;
        # BEGIN IMMEDIATE is SQLite's write-lock-up-front syntax only.
        if not is_postgres():
            connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL DEFAULT '',
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    owner_customer_id TEXT NOT NULL UNIQUE REFERENCES customers(id),
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    commission_rate REAL NOT NULL DEFAULT 0.08,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    plan TEXT NOT NULL DEFAULT 'FREE',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    parent_id TEXT REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    category_id TEXT NOT NULL REFERENCES categories(id),
    org_id TEXT REFERENCES organizations(id),
    brand TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    material TEXT NOT NULL,
    care TEXT NOT NULL,
    image TEXT NOT NULL,
    price INTEGER NOT NULL,
    compare_at_price INTEGER,
    rating REAL NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    color_family TEXT,
    style_tags TEXT,
    images TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS variants (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    sku TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL,
    size TEXT NOT NULL,
    price INTEGER NOT NULL,
    stock INTEGER NOT NULL CHECK(stock >= 0)
);

CREATE TABLE IF NOT EXISTS carts (
    id TEXT PRIMARY KEY,
    customer_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cart_items (
    id TEXT PRIMARY KEY,
    cart_id TEXT NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    variant_id TEXT NOT NULL REFERENCES variants(id),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    UNIQUE(cart_id, variant_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT,
    email TEXT NOT NULL,
    recipient TEXT NOT NULL,
    phone TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    address1 TEXT NOT NULL,
    address2 TEXT NOT NULL,
    delivery_memo TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    subtotal INTEGER NOT NULL,
    discount INTEGER NOT NULL,
    shipping_fee INTEGER NOT NULL,
    total INTEGER NOT NULL,
    payment_status TEXT NOT NULL,
    ordered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    product_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    product_name TEXT NOT NULL,
    sku TEXT NOT NULL,
    option_text TEXT NOT NULL,
    unit_price INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    line_total INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
    payment_key TEXT NOT NULL UNIQUE,
    method TEXT NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL,
    approved_at TEXT
);

CREATE TABLE IF NOT EXISTS shipments (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
    carrier TEXT,
    tracking_number TEXT,
    status TEXT NOT NULL,
    eta TEXT,
    delivered_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    type TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    refund_amount INTEGER NOT NULL,
    return_fee INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coupons (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    discount_type TEXT NOT NULL,
    discount_value INTEGER NOT NULL,
    max_discount_amount INTEGER,
    min_purchase_amount INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    customer_id TEXT NOT NULL REFERENCES customers(id),
    customer_name TEXT NOT NULL,
    order_id TEXT NOT NULL REFERENCES orders(id),
    rating INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(customer_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id);

CREATE TABLE IF NOT EXISTS commerce_events (
    id TEXT PRIMARY KEY,
    external_event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    org_id TEXT NOT NULL,
    order_id TEXT,
    product_id TEXT,
    variant_id TEXT,
    customer_id TEXT,
    quantity INTEGER NOT NULL DEFAULT 0,
    amount INTEGER NOT NULL DEFAULT 0,
    discount INTEGER NOT NULL DEFAULT 0,
    shipping_fee INTEGER NOT NULL DEFAULT 0,
    refund_amount INTEGER NOT NULL DEFAULT 0,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_commerce_events_order ON commerce_events(order_id);
CREATE INDEX IF NOT EXISTS idx_commerce_events_type_time
    ON commerce_events(event_type, occurred_at);

CREATE TABLE IF NOT EXISTS discord_channels (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(id),
    channel_key TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    channel_name TEXT NOT NULL DEFAULT '',
    webhook_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(org_id, channel_key)
);

CREATE INDEX IF NOT EXISTS idx_discord_channels_org ON discord_channels(org_id);

CREATE TABLE IF NOT EXISTS combo_signals (
    id TEXT PRIMARY KEY,
    external_event_id TEXT NOT NULL UNIQUE,
    product_a_id TEXT NOT NULL,
    product_b_id TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    org_id TEXT,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_combo_signals_pair ON combo_signals(product_a_id, product_b_id);

CREATE TABLE IF NOT EXISTS product_affinity (
    product_a_id TEXT NOT NULL,
    product_b_id TEXT NOT NULL,
    seed_score REAL NOT NULL,
    signal_score REAL NOT NULL DEFAULT 0,
    final_score REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (product_a_id, product_b_id)
);
"""


# 2-tier consumer-facing catalog taxonomy (parent_id NULL = 대분류). Separate
# from organizations.category (the seller's own store category, e.g. "패션"),
# which stays untouched — see docs/ai-recommendation-plan.html#s2. "신발" has
# no subcategories, so products are filed directly under the parent.
CATEGORIES = [
    ("cat_top", "top", "상의", 1, None),
    ("cat_top_sweat", "top-sweatshirt", "맨투맨", 1, "cat_top"),
    ("cat_top_shirt", "top-shirt", "셔츠", 2, "cat_top"),
    ("cat_top_tee", "top-tee", "티셔츠", 3, "cat_top"),
    ("cat_top_knit", "top-knit", "니트", 4, "cat_top"),
    ("cat_bottom", "bottom", "하의", 2, None),
    ("cat_bottom_denim", "bottom-denim", "데님", 1, "cat_bottom"),
    ("cat_bottom_slacks", "bottom-slacks", "슬랙스", 2, "cat_bottom"),
    ("cat_bottom_cargo", "bottom-cargo", "카고", 3, "cat_bottom"),
    ("cat_bottom_shorts", "bottom-shorts", "숏팬츠", 4, "cat_bottom"),
    ("cat_outer", "outer", "아우터", 3, None),
    ("cat_outer_jacket", "outer-jacket", "자켓", 1, "cat_outer"),
    ("cat_outer_coat", "outer-coat", "코트", 2, "cat_outer"),
    ("cat_outer_hoodzip", "outer-hoodzip", "후드집업", 3, "cat_outer"),
    ("cat_shoes", "shoes", "신발", 4, None),
    ("cat_acc", "accessories", "악세사리", 5, None),
    ("cat_acc_bag", "accessories-bag", "가방", 1, "cat_acc"),
    ("cat_acc_belt", "accessories-belt", "벨트", 2, "cat_acc"),
    ("cat_acc_cap", "accessories-cap", "모자", 3, "cat_acc"),
    ("cat_acc_jewelry", "accessories-jewelry", "주얼리", 4, "cat_acc"),
]

PRODUCTS = [
    {
        "id": "prd_001",
        "slug": "everyday-hoodie",
        "category_id": "cat_outer_hoodzip",
        "brand": "EVERYDAY",
        "name": "Everyday Hoodie",
        "description": "매일 편안하게 입을 수 있는 탄탄한 코튼 후디입니다.",
        "material": "면 80%, 폴리에스터 20%",
        "care": "찬물 단독 세탁, 건조기 사용 금지",
        "image": "https://images.unsplash.com/photo-1556821840-3a63f95609a7?auto=format&fit=crop&w=1200&q=85",
        "price": 69000,
        "compare_at_price": 79000,
        "rating": 4.8,
        "review_count": 128,
        "color_family": "뉴트럴",
        "style_tags": "캐주얼,스트릿·힙",
        "variants": [
            ("var_001_s", "EV-HOODIE-GR-S", "그레이", "S", 69000, 8),
            ("var_001_m", "EV-HOODIE-GR-M", "그레이", "M", 69000, 12),
            ("var_001_l", "EV-HOODIE-GR-L", "그레이", "L", 69000, 5),
        ],
    },
    {
        "id": "prd_002",
        "slug": "canvas-daily-bag",
        "category_id": "cat_acc_bag",
        "brand": "EVERYDAY",
        "name": "Canvas Daily Bag",
        "description": "노트북과 일상용품을 넉넉하게 담는 캔버스 숄더백입니다.",
        "material": "면 캔버스 100%",
        "care": "오염 부위만 부드러운 천으로 닦아주세요.",
        "image": "https://images.unsplash.com/photo-1553062407-98eeb64c6a62?auto=format&fit=crop&w=1200&q=85",
        "price": 42000,
        "compare_at_price": None,
        "rating": 4.6,
        "review_count": 74,
        "color_family": "뉴트럴",
        "style_tags": "미니멀,캐주얼",
        "variants": [
            ("var_002_iv", "EV-BAG-IVORY", "아이보리", "FREE", 42000, 16),
            ("var_002_nv", "EV-BAG-NAVY", "네이비", "FREE", 42000, 7),
        ],
    },
    {
        "id": "prd_003",
        "slug": "minimal-leather-sneakers",
        "category_id": "cat_shoes",
        "brand": "FORM",
        "name": "Minimal Leather Sneakers",
        "description": "절제된 실루엣과 쿠셔닝을 갖춘 데일리 레더 스니커즈입니다.",
        "material": "천연가죽, 러버 아웃솔",
        "care": "전용 클리너로 오염 부위만 닦아주세요.",
        "image": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=1200&q=85",
        "price": 89000,
        "compare_at_price": 99000,
        "rating": 4.9,
        "review_count": 51,
        "color_family": "뉴트럴",
        "style_tags": "미니멀,캐주얼",
        "variants": [
            ("var_003_260", "FM-SNEAKER-WH-260", "오프화이트", "260", 89000, 9),
            ("var_003_270", "FM-SNEAKER-WH-270", "오프화이트", "270", 89000, 3),
        ],
    },
    {
        "id": "prd_004",
        "slug": "soft-cotton-shirt",
        "category_id": "cat_top_shirt",
        "brand": "FORM",
        "name": "Soft Cotton Shirt",
        "description": "사계절 활용하기 좋은 여유로운 실루엣의 코튼 셔츠입니다.",
        "material": "면 100%",
        "care": "30도 이하 세탁, 약하게 탈수",
        "image": "https://images.unsplash.com/photo-1598033129183-c4f50c736f10?auto=format&fit=crop&w=1200&q=85",
        "price": 54000,
        "compare_at_price": None,
        "rating": 4.7,
        "review_count": 39,
        "color_family": "뉴트럴",
        "style_tags": "미니멀,캐주얼",
        "variants": [
            ("var_004_m", "FM-SHIRT-WH-M", "화이트", "M", 54000, 10),
            ("var_004_l", "FM-SHIRT-WH-L", "화이트", "L", 54000, 6),
        ],
    },
    {
        "id": "prd_005",
        "slug": "washed-ball-cap",
        "category_id": "cat_acc_cap",
        "brand": "EVERYDAY",
        "name": "Washed Ball Cap",
        "description": "자연스럽게 워싱된 코튼과 깊은 크라운이 특징인 볼캡입니다.",
        "material": "면 100%",
        "care": "중성세제로 손세탁 후 그늘 건조",
        "image": "https://images.unsplash.com/photo-1588850561407-ed78c282e89b?auto=format&fit=crop&w=1200&q=85",
        "price": 36000,
        "compare_at_price": 40000,
        "rating": 4.5,
        "review_count": 22,
        "color_family": "뉴트럴",
        "style_tags": "캐주얼,스트릿·힙",
        "variants": [("var_005_one", "EV-CAP-NAVY", "네이비", "FREE", 36000, 14)],
    },
    {
        "id": "prd_006",
        "slug": "compact-cross-bag",
        "category_id": "cat_acc_bag",
        "brand": "FORM",
        "name": "Compact Cross Bag",
        "description": "필수품을 가볍게 수납하는 생활 방수 크로스백입니다.",
        "material": "재생 나일론 100%",
        "care": "물세탁 금지, 그늘 건조",
        "image": "https://images.unsplash.com/photo-1590874103328-eac38a683ce7?auto=format&fit=crop&w=1200&q=85",
        "price": 49000,
        "compare_at_price": None,
        "rating": 4.4,
        "review_count": 18,
        "color_family": "어스톤",
        "style_tags": "캐주얼,스트릿·힙",
        "variants": [
            ("var_006_bk", "FM-CROSS-BLACK", "블랙", "FREE", 49000, 0),
            ("var_006_ol", "FM-CROSS-OLIVE", "올리브", "FREE", 49000, 4),
        ],
    },
]


def _ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Add columns missing from a pre-existing local dev DB.

    CREATE TABLE IF NOT EXISTS is a no-op once a table already exists, so a
    local data/commerce.db created before a schema change never gets new
    columns without this. There's no real migration framework here, so this
    is a deliberately minimal stand-in for one.
    """
    if is_postgres():
        existing = {
            row["name"]
            for row in connection.execute(
                "SELECT column_name AS name FROM information_schema.columns WHERE table_name = ?",
                (table,),
            ).fetchall()
        }
    else:
        existing = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
    for name, ddl_type in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}")


def _seed_demo_data_enabled() -> bool:
    """Local SQLite dev always gets the demo catalog/accounts for convenience.

    On Postgres (production, and any future staging DB) demo/sample data is
    off by default -- a real deployment shouldn't have its catalog silently
    repopulated with fake products on every cold start. Set
    COMMERCE_SEED_DEMO_DATA=true to opt a Postgres environment back in (e.g.
    a throwaway demo/staging branch).
    """
    if not is_postgres():
        return True
    return os.getenv("COMMERCE_SEED_DEMO_DATA", "").strip().lower() == "true"


def initialize_database() -> None:
    # Every helper below is typed sqlite3.Connection for brevity even though
    # transaction() may hand it a PostgresConnection under DATABASE_URL --
    # both expose the same execute/executemany/executescript surface, so
    # this is a duck-typing mismatch mypy can't see through, not a bug.
    demo_data = _seed_demo_data_enabled()
    with transaction() as connection:
        connection.executescript(SCHEMA)
        customer_columns = {
            "password_hash": "TEXT NOT NULL DEFAULT ''",
            "is_admin": "INTEGER NOT NULL DEFAULT 0",
        }
        _ensure_columns(connection, "customers", customer_columns)  # type: ignore[arg-type]
        _ensure_columns(connection, "products", {"org_id": "TEXT"})  # type: ignore[arg-type]
        product_style_columns = {"color_family": "TEXT", "style_tags": "TEXT"}
        _ensure_columns(connection, "products", product_style_columns)  # type: ignore[arg-type]
        product_listing_columns = {
            "images": "TEXT",
            "is_active": "INTEGER NOT NULL DEFAULT 1",
        }
        _ensure_columns(connection, "products", product_listing_columns)  # type: ignore[arg-type]
        _ensure_columns(connection, "categories", {"parent_id": "TEXT"})  # type: ignore[arg-type]
        event_columns = {"customer_id": "TEXT"}
        _ensure_columns(connection, "commerce_events", event_columns)  # type: ignore[arg-type]
        organization_columns = {
            "plan": "TEXT NOT NULL DEFAULT 'FREE'",
            # Discord 봇 연동: 판매자 서버(guild) ↔ 조직 바인딩과 1회용 링크 코드.
            "discord_guild_id": "TEXT",
            "discord_link_code": "TEXT",
            "discord_linked_at": "TEXT",
        }
        _ensure_columns(connection, "organizations", organization_columns)  # type: ignore[arg-type]

        # Structural, not sample data -- product creation needs these to
        # exist regardless of whether demo seeding is on, so this always
        # runs (cheap: ~10-row idempotent upsert).
        connection.executemany(
            """
            INSERT INTO categories(id, slug, name, sort_order, parent_id) VALUES(?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                slug = excluded.slug,
                name = excluded.name,
                sort_order = excluded.sort_order,
                parent_id = excluded.parent_id
            """,
            CATEGORIES,
        )
        # WELCOME10 is real platform functionality (an ordinary row an admin
        # can deactivate from the coupon admin UI), not sample/demo data --
        # always seeded regardless of _seed_demo_data_enabled().
        _seed_default_coupon(connection)  # type: ignore[arg-type]

        # The catalog upsert loop below is one insert+delete+upsert per
        # product (~100 round trips for the 34-product seed catalog alone).
        # On SQLite that's free (local file), so it always runs there to
        # keep local dev's catalog fresh on every restart. On Postgres,
        # initialize_database() reruns on every Vercel cold start (no
        # persistent process to have already run it once) -- paying that
        # round-trip cost on every cold start, on top of real network
        # latency to the DB, is what made product listing feel slow. Skip
        # the whole seed cascade once the catalog already exists; schema
        # creation/_ensure_columns above still always run so a future
        # schema change still reaches an already-seeded Postgres DB.
        catalog_seeded = is_postgres() and connection.execute(
            "SELECT 1 FROM products WHERE id = ?", ("prd_001",)
        ).fetchone()
        if demo_data and not catalog_seeded:
            connection.execute(
                """
                INSERT INTO customers(id, email, name, phone, password_hash, is_admin, created_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    password_hash = CASE
                        WHEN customers.password_hash = '' THEN excluded.password_hash
                        ELSE customers.password_hash
                    END
                """,
                (
                    "cus_demo",
                    "demo@example.com",
                    "김민지",
                    "010-0000-0000",
                    hash_password(DEMO_CUSTOMER_PASSWORD),
                    0,
                    utc_now(),
                ),
            )
            for product in PRODUCTS:
                connection.execute(
                    """
                    INSERT INTO products(
                        id, slug, category_id, brand, name, description, material, care,
                        image, price, compare_at_price, rating, review_count, created_at,
                        color_family, style_tags
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        slug = excluded.slug,
                        category_id = excluded.category_id,
                        brand = excluded.brand,
                        name = excluded.name,
                        description = excluded.description,
                        material = excluded.material,
                        care = excluded.care,
                        image = excluded.image,
                        price = excluded.price,
                        compare_at_price = excluded.compare_at_price,
                        rating = excluded.rating,
                        review_count = excluded.review_count,
                        color_family = excluded.color_family,
                        style_tags = excluded.style_tags
                    """,
                    (
                        product["id"],
                        product["slug"],
                        product["category_id"],
                        product["brand"],
                        product["name"],
                        product["description"],
                        product["material"],
                        product["care"],
                        product["image"],
                        product["price"],
                        product["compare_at_price"],
                        product["rating"],
                        product["review_count"],
                        utc_now(),
                        product["color_family"],
                        product["style_tags"],
                    ),
                )
                variant_ids = [variant[0] for variant in product["variants"]]
                placeholders = ",".join("?" for _ in variant_ids)
                connection.execute(
                    f"DELETE FROM variants WHERE product_id = ? AND id NOT IN ({placeholders})",
                    [product["id"], *variant_ids],
                )
                connection.executemany(
                    """
                    INSERT INTO variants(
                        id, product_id, sku, color, size, price, stock
                    ) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        product_id = excluded.product_id,
                        sku = excluded.sku,
                        color = excluded.color,
                        size = excluded.size,
                        price = excluded.price
                    """,
                    [(v[0], product["id"], *v[1:]) for v in product["variants"]],
                )
            # No pruning here anymore: CATEGORIES is now a fixed, curated
            # 2-tier taxonomy (parents have no product pointing at them
            # directly -- only their leaf children do), not something
            # derived from whatever products happen to exist.
            _seed_orders(connection)  # type: ignore[arg-type]
            _sync_seed_orders(connection)  # type: ignore[arg-type]
            _seed_test_accounts(connection)  # type: ignore[arg-type]
        # These two seed demo sellers with hundreds of individual
        # PRODUCT_VIEWED/order events (one INSERT per view, per catalog
        # entry). On a persistent host that cost is paid once at process
        # startup; on Vercel, initialize_database() reruns on every cold
        # start, and replaying hundreds of round trips to Postgres blew past
        # the 30s function timeout even though every insert was a no-op
        # after the first run (504s on /api/commerce/*). Skip the whole
        # cascade once the demo orgs already exist -- cheap existence check
        # instead of hundreds of idempotent-but-still-a-round-trip inserts.
        if demo_data:
            demo_seeded = connection.execute(
                "SELECT 1 FROM organizations WHERE id = ?", ("org_test_seller2",)
            ).fetchone()
            if not demo_seeded:
                _seed_seller_daily_demo(connection)  # type: ignore[arg-type]
                _seed_market_share_demo_sellers(connection)  # type: ignore[arg-type]


def _seed_test_accounts(connection: sqlite3.Connection) -> None:
    """One login-ready account per marketplace role, for demoing the role split.

    Idempotent (INSERT OR IGNORE / ON CONFLICT DO NOTHING) so re-running
    initialize_database() on every app boot never duplicates or errors.
    """
    now = utc_now()
    accounts = [
        ("cus_test_consumer", "consumer@test.com", "이소비", "010-1111-2222", 0),
        ("cus_test_seller", "seller@test.com", "김판매", "010-2222-3333", 0),
        ("cus_test_admin", "admin@test.com", "박관리", "010-3333-4444", 1),
    ]
    for customer_id, email, name, phone, is_admin in accounts:
        connection.execute(
            """
            INSERT INTO customers(id, email, name, phone, password_hash, is_admin, created_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id) DO NOTHING
            """,
            (customer_id, email, name, phone, hash_password(TEST_ACCOUNT_PASSWORD), is_admin, now),
        )

    connection.execute(
        """
        INSERT INTO organizations(
            id, owner_customer_id, name, category, commission_rate, status, plan, created_at
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO NOTHING
        """,
        (
            "org_test_seller", "cus_test_seller", "테스트 스토어", "패션",
            0.08, "ACTIVE", "BASIC", now,
        ),
    )

    seller_products = [
        {
            "id": "prd_seller_001",
            "slug": "test-store-graphic-tee",
            "category_id": "cat_top_tee",
            "brand": "TEST STORE",
            "name": "Test Store Graphic Tee",
            "description": "테스트 판매자 계정이 등록한 샘플 상품입니다.",
            "material": "면 100%",
            "care": "찬물 세탁, 그늘 건조",
            "image": "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?auto=format&fit=crop&w=1200&q=85",
            "price": 39000,
            "color_family": "뉴트럴",
            "style_tags": "캐주얼,스트릿·힙",
            "variant": ("var_seller_001_m", "TEST-TEE-WH-M", "화이트", "M", 39000, 15),
        },
        {
            "id": "prd_seller_002",
            "slug": "test-store-canvas-tote",
            "category_id": "cat_acc_bag",
            "brand": "TEST STORE",
            "name": "Test Store Canvas Tote",
            "description": "테스트 판매자 계정이 등록한 샘플 상품입니다.",
            "material": "면 캔버스 100%",
            "care": "오염 부위만 부분 세탁",
            "image": "https://images.unsplash.com/photo-1591561954557-26941169b49e?auto=format&fit=crop&w=1200&q=85",
            "price": 27000,
            "color_family": "뉴트럴",
            "style_tags": "미니멀,캐주얼",
            "variant": ("var_seller_002_free", "TEST-TOTE-BK-FREE", "블랙", "FREE", 27000, 9),
        },
    ]
    for product in seller_products:
        connection.execute(
            """
            INSERT INTO products(
                id, slug, category_id, org_id, brand, name, description, material, care,
                image, price, compare_at_price, rating, review_count, created_at,
                color_family, style_tags
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                product["id"],
                product["slug"],
                product["category_id"],
                "org_test_seller",
                product["brand"],
                product["name"],
                product["description"],
                product["material"],
                product["care"],
                product["image"],
                product["price"],
                None,
                0,
                0,
                now,
                product["color_family"],
                product["style_tags"],
            ),
        )
        variant_id, sku, color, size, price, stock = product["variant"]
        connection.execute(
            """
            INSERT INTO variants(id, product_id, sku, color, size, price, stock)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id) DO NOTHING
            """,
            (variant_id, product["id"], sku, color, size, price, stock),
        )


def _seed_default_coupon(connection: sqlite3.Connection) -> None:
    """WELCOME10 used to be hardcoded in cart_payload()'s coupon check --
    now that real admin-created coupons exist, seed it as an ordinary row
    so the same code (and any existing marketing material referencing it)
    keeps working. ON CONFLICT DO NOTHING so an admin who edits/deactivates
    it later never gets overwritten by a restart.
    """
    connection.execute(
        """
        INSERT INTO coupons(
            id, code, discount_type, discount_value, max_discount_amount,
            min_purchase_amount, expires_at, is_active, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(code) DO NOTHING
        """,
        ("cpn_welcome10", "WELCOME10", "PERCENT", 10, 10_000, 50_000, None, 1, utc_now()),
    )


def _seed_seller_order(
    connection: sqlite3.Connection,
    *,
    order_id: str,
    org_id: str,
    product_id: str,
    product_name: str,
    variant_id: str,
    sku: str,
    color: str,
    size: str,
    price: int,
    quantity: int,
    now: str,
    refund: bool = False,
) -> None:
    """One already-completed order, backdated to today, for daily-report seed data.

    Unlike the live checkout flow, this never touches variants.stock — the
    seed catalog already lists each variant's final post-sale stock directly.
    """
    line_total = price * quantity
    status = "CANCELLED" if refund else "DELIVERED"
    payment_status = "REFUNDED" if refund else "PAID"
    connection.execute(
        """
        INSERT OR IGNORE INTO orders(
            id, customer_id, email, recipient, phone, postal_code, address1, address2,
            delivery_memo, status, subtotal, discount, shipping_fee, total,
            payment_status, ordered_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            order_id, "cus_demo", "demo@example.com", "김민지", "010-0000-0000",
            "04524", "서울특별시 중구 세종대로 110", "101호", "",
            status, line_total, 0, 0, line_total, payment_status, now, now,
        ),
    )
    connection.execute(
        "INSERT OR IGNORE INTO order_items VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            f"oi_{order_id}", order_id, product_id, variant_id,
            product_name, sku, f"{color} / {size}", price, quantity, line_total,
        ),
    )
    connection.execute(
        "INSERT OR IGNORE INTO payments VALUES(?,?,?,?,?,?,?)",
        (f"pay_{order_id}", order_id, f"seed_{order_id}", "CARD", line_total, payment_status, now),
    )
    record_event(
        connection,
        event_type="PAYMENT_CONFIRMED",
        external_event_id=f"{order_id}:PAYMENT_CONFIRMED",
        order_id=order_id,
        product_id=product_id,
        variant_id=variant_id,
        quantity=quantity,
        amount=line_total,
        occurred_at=now,
        org_id=org_id,
    )
    if refund:
        connection.execute(
            "INSERT OR IGNORE INTO claims VALUES(?,?,?,?,?,?,?,?,?)",
            (
                f"clm_{order_id}", order_id, "CANCEL", "테스트 시드 환불", "REFUNDED",
                line_total, 0, now, now,
            ),
        )
        record_event(
            connection,
            event_type="REFUND_COMPLETED",
            external_event_id=f"{order_id}:REFUND_COMPLETED",
            order_id=order_id,
            product_id=product_id,
            variant_id=variant_id,
            refund_amount=line_total,
            occurred_at=now,
            org_id=org_id,
        )


def _seed_seller_daily_demo(connection: sqlite3.Connection) -> None:
    """A second seller with rich, varied activity for the daily-seller-report persona.

    Ten fashion products spanning every branch the report and its AI feedback
    step are meant to react to: a clear bestseller, a low-stock item that's
    obviously in demand, an out-of-stock item that already sold out, two
    refunded orders, and exactly one product with zero views and zero sales —
    a genuinely untouched listing (docs/prompts/daily-seller-report.md calls
    this out explicitly). Views and sales are backdated to *today* (whenever
    the app happens to boot) so the daily snapshot always has something to
    report the first time this runs.
    """
    now = utc_now()
    seller_id = "cus_test_seller2"
    org_id = "org_test_seller2"

    connection.execute(
        """
        INSERT INTO customers(id, email, name, phone, password_hash, is_admin, created_at)
        VALUES(?,?,?,?,?,0,?)
        ON CONFLICT(id) DO NOTHING
        """,
        (
            seller_id, "seller2@test.com", "이무드", "010-4444-5555",
            hash_password(TEST_ACCOUNT_PASSWORD), now,
        ),
    )
    connection.execute(
        """
        INSERT INTO organizations(
            id, owner_customer_id, name, category, commission_rate, status, plan, created_at
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO NOTHING
        """,
        (org_id, seller_id, "무드 스토리", "패션", 0.08, "ACTIVE", "PRO", now),
    )

    # id, slug, category_id, name, price, image-slug, sku, color, size,
    # stock, views, sold_qty, refunded_qty (refunded_qty is part of sold_qty
    # — a refund happens to an order that was already counted as paid),
    # color_family, style_tags (AI 추천 코디 조합 엔진 속성 태그 — see
    # docs/ai-recommendation-plan.html#s3).
    catalog = [
        ("prd_s2_01", "mood-oversized-wool-knit", "cat_top_knit", "오버사이즈 울 니트", 68000,
         "1576871337622-98d48d1cf531", "MS-KNIT-CHAR-FR", "차콜", "FREE", 12, 45, 8, 0,
         "뉴트럴", "미니멀,캐주얼"),
        ("prd_s2_02", "mood-straight-denim-pants", "cat_bottom_denim",
         "스트레이트 데님 팬츠", 59000,
         "1541099649105-f69ad21f3246", "MS-DENIM-BLU-30", "블루", "30", 6, 30, 5, 0,
         "데님/인디고", "캐주얼"),
        ("prd_s2_03", "mood-cotton-long-sleeve-tee", "cat_top_tee", "코튼 롱슬리브 티셔츠", 29000,
         "1521572163474-6864f9cf17ab", "MS-TEE-WHT-M", "화이트", "M", 15, 22, 4, 1,
         "뉴트럴", "미니멀,캐주얼"),
        ("prd_s2_04", "mood-block-check-shirt", "cat_top_shirt", "블록 체크 셔츠", 49000,
         "1598033129183-c4f50c736f10", "MS-SHIRT-CHK-L", "체크", "L", 9, 18, 3, 0,
         "어스톤", "캐주얼"),
        ("prd_s2_05", "mood-wide-slacks", "cat_bottom_slacks", "와이드 슬랙스", 52000,
         "1594633312681-425c7b97ccd1", "MS-SLACKS-BLK-M", "블랙", "M", 2, 15, 2, 0,
         "뉴트럴", "미니멀,포멀"),
        ("prd_s2_06", "mood-minimal-leather-belt", "cat_acc_belt", "미니멀 레더 벨트", 32000,
         "1624222247344-550fb60583dc", "MS-BELT-BRN-FR", "브라운", "FREE", 25, 12, 2, 0,
         "어스톤", "미니멀,포멀"),
        ("prd_s2_07", "mood-wool-blend-coat", "cat_outer_coat", "울 블렌드 코트", 189000,
         "1539533018447-63fcce2678e3", "MS-COAT-CAM-M", "카멜", "M", 0, 9, 1, 0,
         "어스톤", "미니멀,포멀"),
        ("prd_s2_08", "mood-basic-crewneck-sweat", "cat_top_sweat", "베이직 크루넥 스웨트", 39000,
         "1556821840-3a63f95609a7", "MS-SWEAT-GRY-L", "그레이", "L", 10, 6, 1, 1,
         "뉴트럴", "캐주얼,스트릿·힙"),
        ("prd_s2_09", "mood-corduroy-ball-cap", "cat_acc_cap", "코듀로이 볼캡", 27000,
         "1588850561407-ed78c282e89b", "MS-CAP-BEIGE-FR", "베이지", "FREE", 14, 3, 0, 0,
         "뉴트럴", "캐주얼,스트릿·힙"),
        ("prd_s2_10", "mood-tailored-jacket", "cat_outer_jacket", "테일러드 재킷", 99000,
         "1591047139829-d91aecb6caea", "MS-JACKET-NVY-M", "네이비", "M", 20, 0, 0, 0,
         "뉴트럴", "포멀,미니멀"),
    ]

    for (
        product_id, slug, category_id, name, price, image_slug,
        sku, color, size, stock, views, sold_qty, refunded_qty,
        color_family, style_tags,
    ) in catalog:
        variant_id = f"var_{product_id[4:]}"
        image = f"https://images.unsplash.com/photo-{image_slug}?auto=format&fit=crop&w=1200&q=85"
        connection.execute(
            """
            INSERT INTO products(
                id, slug, category_id, org_id, brand, name, description, material, care,
                image, price, compare_at_price, rating, review_count, created_at,
                color_family, style_tags
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                product_id, slug, category_id, org_id, "MOOD STORY", name,
                "무드 스토리가 소개하는 시즌 아이템입니다.", "상세 참고", "상세 참고",
                image, price, None, 0, 0, now, color_family, style_tags,
            ),
        )
        connection.execute(
            """
            INSERT INTO variants(id, product_id, sku, color, size, price, stock)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id) DO NOTHING
            """,
            (variant_id, product_id, sku, color, size, price, stock),
        )

        for i in range(views):
            record_event(
                connection,
                event_type="PRODUCT_VIEWED",
                external_event_id=f"seed_view_{product_id}_{i:03d}",
                product_id=product_id,
                occurred_at=now,
                org_id=org_id,
            )

        kept_qty = sold_qty - refunded_qty
        common = {
            "org_id": org_id,
            "product_id": product_id,
            "product_name": name,
            "variant_id": variant_id,
            "sku": sku,
            "color": color,
            "size": size,
            "price": price,
            "now": now,
        }
        if kept_qty > 0:
            _seed_seller_order(
                connection, order_id=f"ord_seed_{product_id}_a", quantity=kept_qty, **common
            )
        if refunded_qty > 0:
            _seed_seller_order(
                connection,
                order_id=f"ord_seed_{product_id}_b",
                quantity=refunded_qty,
                refund=True,
                **common,
            )


# Three more stores so seller-market-share-report has enough sellers to
# actually compare (docs/ai-ops-studio-master-prd.html#plans). Each pairs a
# different subscription plan with a different sales volume on purpose:
# 무드 스토리(PRO, real GMV from _seed_seller_daily_demo) already exists;
# these three fill in a BUSINESS-plan seller with the highest platform
# contribution, a BASIC-plan seller with modest GMV, and a FREE-plan seller
# whose GMV is actually *larger* than the BASIC seller's but contributes
# less platform revenue — the plan fee, not raw sales, decides that.
MARKET_SHARE_SELLERS = [
    {
        "seller_id": "cus_test_seller3", "email": "seller3@test.com", "name": "박라인",
        "phone": "010-6666-7777", "org_id": "org_test_seller3", "org_name": "라인 클로젯",
        "plan": "BUSINESS",
        "products": [
            ("prd_s3_01", "실켓 코튼 셔츠", 45000, "화이트", "M", 10, 4, 0,
             "cat_top_shirt", "뉴트럴", "미니멀,포멀"),
            ("prd_s3_02", "테이퍼드 슬랙스", 58000, "블랙", "30", 8, 3, 1,
             "cat_bottom_slacks", "뉴트럴", "미니멀,포멀"),
            ("prd_s3_03", "니트 가디건", 72000, "베이지", "FREE", 6, 2, 0,
             "cat_top_knit", "뉴트럴", "미니멀,캐주얼"),
            ("prd_s3_04", "레더 스니커즈", 120000, "브라운", "270", 5, 2, 0,
             "cat_shoes", "어스톤", "캐주얼,미니멀"),
            ("prd_s3_05", "캔버스 백팩", 68000, "카키", "FREE", 9, 3, 0,
             "cat_acc_bag", "어스톤", "캐주얼,스트릿·힙"),
        ],
    },
    {
        "seller_id": "cus_test_seller4", "email": "seller4@test.com", "name": "정어반",
        "phone": "010-7777-8888", "org_id": "org_test_seller4", "org_name": "어반 무드",
        "plan": "BASIC",
        "products": [
            ("prd_s4_01", "오버핏 후드", 49000, "그레이", "L", 12, 3, 0,
             "cat_outer_hoodzip", "뉴트럴", "캐주얼,스트릿·힙"),
            ("prd_s4_02", "와이드 데님", 65000, "블루", "32", 7, 2, 0,
             "cat_bottom_denim", "데님/인디고", "캐주얼,스트릿·힙"),
            ("prd_s4_03", "스트라이프 셔츠", 39000, "네이비", "M", 10, 2, 1,
             "cat_top_shirt", "뉴트럴", "캐주얼"),
            ("prd_s4_04", "버킷햇", 25000, "블랙", "FREE", 15, 1, 0,
             "cat_acc_cap", "뉴트럴", "스트릿·힙,스포티"),
            ("prd_s4_05", "크로스백", 47000, "브라운", "FREE", 8, 1, 0,
             "cat_acc_bag", "어스톤", "캐주얼,스트릿·힙"),
        ],
    },
    {
        "seller_id": "cus_test_seller5", "email": "seller5@test.com", "name": "한소프트",
        "phone": "010-8888-9999", "org_id": "org_test_seller5", "org_name": "소프트 데일리",
        "plan": "FREE",
        "products": [
            ("prd_s5_01", "베이직 티셔츠", 19000, "화이트", "M", 20, 8, 0,
             "cat_top_tee", "뉴트럴", "미니멀,캐주얼"),
            ("prd_s5_02", "조거 팬츠", 39000, "그레이", "L", 14, 6, 1,
             "cat_bottom_cargo", "뉴트럴", "스포티,캐주얼"),
            ("prd_s5_03", "플리스 자켓", 59000, "네이비", "M", 10, 4, 0,
             "cat_outer_jacket", "뉴트럴", "스포티,캐주얼"),
            ("prd_s5_04", "니트 비니", 15000, "블랙", "FREE", 18, 5, 0,
             "cat_acc_cap", "뉴트럴", "캐주얼,스트릿·힙"),
            ("prd_s5_05", "에코백", 12000, "베이지", "FREE", 16, 6, 0,
             "cat_acc_bag", "뉴트럴", "미니멀,캐주얼"),
        ],
    },
]


def _seed_market_share_demo_sellers(connection: sqlite3.Connection) -> None:
    now = utc_now()
    for seller in MARKET_SHARE_SELLERS:
        connection.execute(
            """
            INSERT INTO customers(id, email, name, phone, password_hash, is_admin, created_at)
            VALUES(?,?,?,?,?,0,?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                seller["seller_id"], seller["email"], seller["name"], seller["phone"],
                hash_password(TEST_ACCOUNT_PASSWORD), now,
            ),
        )
        connection.execute(
            """
            INSERT INTO organizations(
                id, owner_customer_id, name, category, commission_rate, status, plan, created_at
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                seller["org_id"], seller["seller_id"], seller["org_name"], "패션",
                0.08, "ACTIVE", seller["plan"], now,
            ),
        )
        for (
            product_id, name, price, color, size, stock, sold_qty, refunded_qty,
            category_id, color_family, style_tags,
        ) in seller["products"]:
            slug = f"{seller['org_id']}-{product_id}".replace("_", "-")
            variant_id = f"var_{product_id[4:]}"
            connection.execute(
                """
                INSERT INTO products(
                    id, slug, category_id, org_id, brand, name, description, material, care,
                    image, price, compare_at_price, rating, review_count, created_at,
                    color_family, style_tags
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    product_id, slug, category_id, seller["org_id"], seller["org_name"],
                    name, f"{seller['org_name']}의 시즌 아이템입니다.", "상세 참고", "상세 참고",
                    "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab"
                    "?auto=format&fit=crop&w=1200&q=85",
                    price, None, 0, 0, now, color_family, style_tags,
                ),
            )
            connection.execute(
                """
                INSERT INTO variants(id, product_id, sku, color, size, price, stock)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(id) DO NOTHING
                """,
                (variant_id, product_id, f"{product_id.upper()}-SKU", color, size, price, stock),
            )

            kept_qty = sold_qty - refunded_qty
            common = {
                "org_id": seller["org_id"],
                "product_id": product_id,
                "product_name": name,
                "variant_id": variant_id,
                "sku": f"{product_id.upper()}-SKU",
                "color": color,
                "size": size,
                "price": price,
                "now": now,
            }
            if kept_qty > 0:
                _seed_seller_order(
                    connection, order_id=f"ord_seed_{product_id}_a", quantity=kept_qty, **common
                )
            if refunded_qty > 0:
                _seed_seller_order(
                    connection,
                    order_id=f"ord_seed_{product_id}_b",
                    quantity=refunded_qty,
                    refund=True,
                    **common,
                )


def _sync_seed_orders(connection: sqlite3.Connection) -> None:
    """Keep the portfolio demo's historical snapshots aligned with the fashion seed."""
    seed_variants = {
        "ord_1001": "var_001_m",
        "ord_1002": "var_002_iv",
        "ord_1003": "var_003_260",
    }
    for order_id, variant_id in seed_variants.items():
        variant = connection.execute(
            """
            SELECT v.*, p.name product_name, p.id product_id
            FROM variants v JOIN products p ON p.id = v.product_id WHERE v.id = ?
            """,
            (variant_id,),
        ).fetchone()
        if variant is None:
            continue
        connection.execute(
            """
            UPDATE order_items
            SET product_id = ?, variant_id = ?, product_name = ?, sku = ?,
                option_text = ?, unit_price = ?, line_total = ?
            WHERE id = ?
            """,
            (
                variant["product_id"],
                variant_id,
                variant["product_name"],
                variant["sku"],
                f"{variant['color']} / {variant['size']}",
                variant["price"],
                variant["price"],
                f"item_{order_id}",
            ),
        )
        connection.execute(
            """
            UPDATE orders
            SET subtotal = ?, discount = 0, shipping_fee = 0, total = ?, updated_at = ?
            WHERE id = ?
            """,
            (variant["price"], variant["price"], utc_now(), order_id),
        )


def _seed_orders(connection: sqlite3.Connection) -> None:
    if connection.execute("SELECT 1 FROM orders LIMIT 1").fetchone():
        return
    orders = [
        ("ord_1001", "SHIPPING", "PAID", "var_001_m", 69000, 2),
        ("ord_1002", "PREPARING", "PAID", "var_002_iv", 42000, 0),
        ("ord_1003", "DELIVERED", "PAID", "var_003_260", 89000, 12),
    ]
    for order_id, status, payment_status, variant_id, total, days_ago in orders:
        variant = connection.execute(
            """
            SELECT v.*, p.name product_name, p.id product_id
            FROM variants v JOIN products p ON p.id = v.product_id WHERE v.id = ?
            """,
            (variant_id,),
        ).fetchone()
        ordered_at = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
        connection.execute(
            """
            INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                order_id,
                "cus_demo",
                "demo@example.com",
                "김민지",
                "010-0000-0000",
                "04524",
                "서울특별시 중구 세종대로 110",
                "101호",
                "문 앞",
                status,
                total,
                0,
                0,
                total,
                payment_status,
                ordered_at,
                ordered_at,
            ),
        )
        connection.execute(
            "INSERT INTO order_items VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                f"item_{order_id}",
                order_id,
                variant["product_id"],
                variant_id,
                variant["product_name"],
                variant["sku"],
                f"{variant['color']} / {variant['size']}",
                total,
                1,
                total,
            ),
        )
        shipment_status = {
            "SHIPPING": "IN_TRANSIT",
            "PREPARING": "PREPARING",
            "DELIVERED": "DELIVERED",
        }[status]
        connection.execute(
            "INSERT INTO shipments VALUES(?,?,?,?,?,?,?,?)",
            (
                f"ship_{order_id}",
                order_id,
                "Everyday Express",
                f"ED-{order_id[4:]}",
                shipment_status,
                (datetime.now(UTC) + timedelta(days=2)).date().isoformat(),
                ordered_at if status == "DELIVERED" else None,
                utc_now(),
            ),
        )


def row_to_dict(row: sqlite3.Row | dict[str, object] | None) -> dict[str, object] | None:
    return dict(row) if row is not None else None


def json_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def infer_order_org_id(connection: sqlite3.Connection, order_id: str) -> str:
    """Which seller does this order belong to?

    Orders are single-seller (see docs/ai-ops-studio-master-prd.html —
    marketplace carts never mix products from two organizations), so any one
    item's product tells us the whole order's org. Platform seed products
    have org_id = NULL, which falls back to DEFAULT_ORG_ID.
    """
    row = connection.execute(
        """
        SELECT p.org_id FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = ? AND p.org_id IS NOT NULL
        LIMIT 1
        """,
        (order_id,),
    ).fetchone()
    return row["org_id"] if row else DEFAULT_ORG_ID


def record_event(
    connection: sqlite3.Connection,
    *,
    event_type: str,
    external_event_id: str,
    order_id: str | None = None,
    product_id: str | None = None,
    variant_id: str | None = None,
    customer_id: str | None = None,
    quantity: int = 0,
    amount: int = 0,
    discount: int = 0,
    shipping_fee: int = 0,
    refund_amount: int = 0,
    occurred_at: str | None = None,
    org_id: str = DEFAULT_ORG_ID,
) -> None:
    """Append one row to the commerce event ledger.

    ``external_event_id`` is the dedupe key: retried requests (e.g. a client
    resubmitting a cancel call) must not double-count revenue or refunds, so
    inserts are idempotent via INSERT OR IGNORE on that unique column.
    ``customer_id`` is optional (most event types don't need it -- it exists
    mainly so PRODUCT_VIEWED can be tied to a logged-in customer for the AI
    추천 엔진's browse-history taste profile; guests leave it NULL).
    """
    connection.execute(
        """
        INSERT OR IGNORE INTO commerce_events(
            id, external_event_id, event_type, org_id, order_id, product_id, variant_id,
            customer_id, quantity, amount, discount, shipping_fee, refund_amount,
            occurred_at, created_at
        ) VALUES(
            :id, :external_event_id, :event_type, :org_id, :order_id, :product_id, :variant_id,
            :customer_id, :quantity, :amount, :discount, :shipping_fee, :refund_amount,
            :occurred_at, :created_at
        )
        """,
        {
            "id": f"evt_{uuid4().hex[:16]}",
            "external_event_id": external_event_id,
            "event_type": event_type,
            "org_id": org_id,
            "order_id": order_id,
            "product_id": product_id,
            "variant_id": variant_id,
            "customer_id": customer_id,
            "quantity": quantity,
            "amount": amount,
            "discount": discount,
            "shipping_fee": shipping_fee,
            "refund_amount": refund_amount,
            "occurred_at": occurred_at or utc_now(),
            "created_at": utc_now(),
        },
    )


def record_combo_signal(
    connection: sqlite3.Connection,
    *,
    external_event_id: str,
    product_a_id: str,
    product_b_id: str,
    signal_type: str,
    org_id: str | None = None,
    occurred_at: str | None = None,
) -> None:
    """Append one row to the pairwise behavioral-signal ledger (AI 추천 엔진).

    Same idempotency pattern as record_event: external_event_id is the
    dedupe key. Pair order is normalized (see app.recommendation.pair_key)
    so (A,B) and (B,A) always land as the same pair regardless of which
    product was added to the cart/order first.
    """
    from app.recommendation import pair_key

    normalized_a, normalized_b = pair_key(product_a_id, product_b_id)
    connection.execute(
        """
        INSERT OR IGNORE INTO combo_signals(
            id, external_event_id, product_a_id, product_b_id, signal_type,
            org_id, occurred_at, created_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            f"cbs_{uuid4().hex[:16]}",
            external_event_id,
            normalized_a,
            normalized_b,
            signal_type,
            org_id,
            occurred_at or utc_now(),
            utc_now(),
        ),
    )
