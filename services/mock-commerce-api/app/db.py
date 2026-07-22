import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def database_path() -> Path:
    configured = os.getenv("COMMERCE_DB_PATH", "data/commerce.db")
    path = Path(configured)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
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
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    category_id TEXT NOT NULL REFERENCES categories(id),
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
    created_at TEXT NOT NULL
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
"""


CATEGORIES = [
    ("cat_fashion", "fashion", "의류", 1),
    ("cat_bags", "bags", "가방·잡화", 2),
    ("cat_accessories", "accessories", "슈즈·액세서리", 3),
]

PRODUCTS = [
    {
        "id": "prd_001",
        "slug": "everyday-hoodie",
        "category_id": "cat_fashion",
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
        "variants": [
            ("var_001_s", "EV-HOODIE-GR-S", "그레이", "S", 69000, 8),
            ("var_001_m", "EV-HOODIE-GR-M", "그레이", "M", 69000, 12),
            ("var_001_l", "EV-HOODIE-GR-L", "그레이", "L", 69000, 5),
        ],
    },
    {
        "id": "prd_002",
        "slug": "canvas-daily-bag",
        "category_id": "cat_bags",
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
        "variants": [
            ("var_002_iv", "EV-BAG-IVORY", "아이보리", "FREE", 42000, 16),
            ("var_002_nv", "EV-BAG-NAVY", "네이비", "FREE", 42000, 7),
        ],
    },
    {
        "id": "prd_003",
        "slug": "minimal-leather-sneakers",
        "category_id": "cat_accessories",
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
        "variants": [
            ("var_003_260", "FM-SNEAKER-WH-260", "오프화이트", "260", 89000, 9),
            ("var_003_270", "FM-SNEAKER-WH-270", "오프화이트", "270", 89000, 3),
        ],
    },
    {
        "id": "prd_004",
        "slug": "soft-cotton-shirt",
        "category_id": "cat_fashion",
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
        "variants": [
            ("var_004_m", "FM-SHIRT-WH-M", "화이트", "M", 54000, 10),
            ("var_004_l", "FM-SHIRT-WH-L", "화이트", "L", 54000, 6),
        ],
    },
    {
        "id": "prd_005",
        "slug": "washed-ball-cap",
        "category_id": "cat_accessories",
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
        "variants": [("var_005_one", "EV-CAP-NAVY", "네이비", "FREE", 36000, 14)],
    },
    {
        "id": "prd_006",
        "slug": "compact-cross-bag",
        "category_id": "cat_bags",
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
        "variants": [
            ("var_006_bk", "FM-CROSS-BLACK", "블랙", "FREE", 49000, 0),
            ("var_006_ol", "FM-CROSS-OLIVE", "올리브", "FREE", 49000, 4),
        ],
    },
]


def initialize_database() -> None:
    with transaction() as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR IGNORE INTO customers(id, email, name, phone, created_at) VALUES(?,?,?,?,?)",
            ("cus_demo", "demo@example.com", "김민지", "010-0000-0000", utc_now()),
        )
        connection.executemany(
            """
            INSERT INTO categories(id, slug, name, sort_order) VALUES(?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                slug = excluded.slug,
                name = excluded.name,
                sort_order = excluded.sort_order
            """,
            CATEGORIES,
        )
        for product in PRODUCTS:
            connection.execute(
                """
                INSERT INTO products(
                    id, slug, category_id, brand, name, description, material, care,
                    image, price, compare_at_price, rating, review_count, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    review_count = excluded.review_count
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
        connection.execute(
            "DELETE FROM categories WHERE id NOT IN (SELECT DISTINCT category_id FROM products)"
        )
        _seed_orders(connection)
        _sync_seed_orders(connection)


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


def row_to_dict(row: sqlite3.Row | None) -> dict[str, object] | None:
    return dict(row) if row is not None else None


def json_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)
