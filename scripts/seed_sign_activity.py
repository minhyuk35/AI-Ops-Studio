"""SIGN 매장 샘플 '오늘 활동' 시드 — 조회수·판매·환불 이벤트.

seed_sign_catalog.py가 넣은 SIGN의 실제 160개 상품/540개 옵션은 그대로 두고,
그 위에 오늘 날짜로 PRODUCT_VIEWED/PAYMENT_CONFIRMED/REFUND_COMPLETED 이벤트만
얹는다 — 새 상품을 만들지 않는다. 판매자 콘솔의 "오늘의 대시보드"(SVG 차트 포함)가
실제 서비스 오픈 전에도 데모 가능한 상태가 되도록 하기 위한 것.

전체 160개 중 일부러 소수(카테고리별 상위 몇 개)에만 활동을 넣는다 — 모든 상품이
활동을 갖는 건 "방금 오픈한 매장" 현실과 안 맞고, daily-seller-report 페르소나도
"아무도 안 본 상품"이 실제로 보여야 그 시그널을 언급할 수 있다.

배포(Neon/Postgres)와 로컬(SQLite) 양쪽에서 돌아간다(app.db 호환 레이어 사용).
멱등: external_event_id/주문 id가 결정론적이라 여러 번 돌려도 중복이 안 생긴다
(재실행 시 "오늘" 날짜가 바뀌면 새 이벤트가 추가로 쌓인다 — 그게 의도임: 실행한
그날의 대시보드를 채우는 스크립트).

실행:
  $env:PYTHONPATH="services/mock-commerce-api"
  $env:DATABASE_URL="postgresql://.../neondb?sslmode=require"
  python scripts/seed_sign_activity.py
  # 로컬 SQLite: DATABASE_URL 비우고 실행
"""

import os
import sys
from pathlib import Path

_SVC = Path(__file__).resolve().parents[1] / "services" / "mock-commerce-api"
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.auth import hash_password  # noqa: E402
from app.db import record_event, transaction, utc_now  # noqa: E402

DEMO_BUYER_ID = "cus_demo_buyer"
DEMO_BUYER_EMAIL = "demo-buyer@codilab.test"
DEMO_BUYER_NAME = "김코디"

# 상품마다: (조회수, 판매수량, 그중 환불수량). 이 개수만큼만 "오늘 활동 있음" —
# 나머지 상품은 손대지 않아 자연스럽게 조회수 0으로 남는다.
ACTIVITY_PATTERN = [
    (58, 9, 0),  # 확실한 베스트셀러
    (44, 6, 1),  # 잘 나가는데 환불 하나
    (35, 5, 0),
    (29, 4, 0),
    (22, 3, 0),
    (19, 2, 0),
    (15, 2, 1),  # 소량 판매 + 환불
    (12, 1, 0),
    (9, 1, 0),
    (7, 0, 0),  # 조회는 되는데 아직 안 팔림
    (5, 0, 0),
    (3, 0, 0),
]


def _ensure_demo_buyer(connection) -> None:
    connection.execute(
        """
        INSERT INTO customers(id, email, name, phone, password_hash, is_admin, created_at)
        VALUES(?,?,?,?,?,0,?)
        ON CONFLICT(id) DO NOTHING
        """,
        (DEMO_BUYER_ID, DEMO_BUYER_EMAIL, DEMO_BUYER_NAME, "010-1234-5678",
         hash_password("demo1234"), utc_now()),
    )


def _sign_org_id(connection) -> str:
    row = connection.execute("SELECT id FROM organizations WHERE name = ?", ("SIGN",)).fetchone()
    if row is None:
        raise SystemExit("SIGN 조직을 찾을 수 없습니다 — seed_sign_catalog.py를 먼저 실행하세요.")
    return str(row["id"])


def _pick_products(connection, org_id: str, count: int) -> list[dict]:
    """카테고리 전반에 고르게 퍼지도록, 카테고리별로 순서를 섞어 상위 N개를 고른다."""
    rows = connection.execute(
        """
        SELECT p.id, p.name, p.category_id, v.id AS variant_id, v.sku, v.color, v.size,
               v.price, v.stock
        FROM products p
        JOIN variants v ON v.product_id = p.id
        WHERE p.org_id = ?
        ORDER BY p.category_id, p.id, v.id
        """,
        (org_id,),
    ).fetchall()
    by_product: dict[str, dict] = {}
    for row in rows:
        pid = row["id"]
        if pid not in by_product:
            by_product[pid] = dict(row)  # first variant per product (has stock)
    # 카테고리별로 라운드로빈 돌면서 뽑아 다양한 카테고리가 섞이게 한다.
    from collections import defaultdict

    grouped: dict[str, list[dict]] = defaultdict(list)
    for p in by_product.values():
        grouped[p["category_id"]].append(p)
    picked: list[dict] = []
    cursors = dict.fromkeys(grouped, 0)
    cats = list(grouped)
    while len(picked) < count and cats:
        for cat in list(cats):
            i = cursors[cat]
            if i >= len(grouped[cat]):
                cats.remove(cat)
                continue
            picked.append(grouped[cat][i])
            cursors[cat] = i + 1
            if len(picked) >= count:
                break
    return picked


def _seed_order(connection, *, order_id, org_id, product, quantity, refund, now) -> None:
    price = int(product["price"])
    line_total = price * quantity
    status = "CANCELLED" if refund else "DELIVERED"
    payment_status = "REFUNDED" if refund else "PAID"
    connection.execute(
        """
        INSERT INTO orders(
            id, customer_id, email, recipient, phone, postal_code, address1, address2,
            delivery_memo, status, subtotal, discount, shipping_fee, total,
            payment_status, ordered_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO NOTHING
        """,
        (
            order_id, DEMO_BUYER_ID, DEMO_BUYER_EMAIL, DEMO_BUYER_NAME, "010-1234-5678",
            "04524", "서울특별시 중구 세종대로 110", "101호", "",
            status, line_total, 0, 0, line_total, payment_status, now, now,
        ),
    )
    connection.execute(
        """
        INSERT INTO order_items(
            id, order_id, product_id, variant_id, product_name, sku, option_text,
            unit_price, quantity, line_total
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO NOTHING
        """,
        (
            f"oi_{order_id}", order_id, product["id"], product["variant_id"],
            product["name"], product["sku"], f"{product['color']} / {product['size']}",
            price, quantity, line_total,
        ),
    )
    connection.execute(
        """
        INSERT INTO payments(id, order_id, payment_key, method, amount, status, approved_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(id) DO NOTHING
        """,
        (f"pay_{order_id}", order_id, f"seed_{order_id}", "CARD", line_total, payment_status, now),
    )
    record_event(
        connection,
        event_type="PAYMENT_CONFIRMED",
        external_event_id=f"{order_id}:PAYMENT_CONFIRMED",
        order_id=order_id,
        product_id=product["id"],
        variant_id=product["variant_id"],
        quantity=quantity,
        amount=line_total,
        occurred_at=now,
        org_id=org_id,
    )
    if refund:
        connection.execute(
            """
            INSERT INTO claims(
                id, order_id, type, reason, status, refund_amount, return_fee,
                created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO NOTHING
            """,
            (f"clm_{order_id}", order_id, "CANCEL", "샘플 데모 환불", "REFUNDED",
             line_total, 0, now, now),
        )
        record_event(
            connection,
            event_type="REFUND_COMPLETED",
            external_event_id=f"{order_id}:REFUND_COMPLETED",
            order_id=order_id,
            product_id=product["id"],
            variant_id=product["variant_id"],
            refund_amount=line_total,
            occurred_at=now,
            org_id=org_id,
        )


def seed() -> None:
    with transaction() as connection:
        _ensure_demo_buyer(connection)
        org_id = _sign_org_id(connection)
        products = _pick_products(connection, org_id, len(ACTIVITY_PATTERN))
        now = utc_now()
        today_tag = now[:10].replace("-", "")

        total_views = total_sold = total_refunded = 0
        pairs = zip(products, ACTIVITY_PATTERN, strict=False)
        for product, (views, sold, refunded) in pairs:
            for i in range(views):
                record_event(
                    connection,
                    event_type="PRODUCT_VIEWED",
                    external_event_id=f"seed_act_{today_tag}_{product['id']}_view_{i:03d}",
                    product_id=product["id"],
                    occurred_at=now,
                    org_id=org_id,
                )
            total_views += views

            kept = sold - refunded
            if kept > 0:
                _seed_order(
                    connection,
                    order_id=f"ord_seed_act_{today_tag}_{product['id']}_a",
                    org_id=org_id, product=product, quantity=kept, refund=False, now=now,
                )
            if refunded > 0:
                _seed_order(
                    connection,
                    order_id=f"ord_seed_act_{today_tag}_{product['id']}_b",
                    org_id=org_id, product=product, quantity=refunded, refund=True, now=now,
                )
            total_sold += sold
            total_refunded += refunded
            print(f"  {product['name']}: 조회 {views} · 판매 {sold}(환불 {refunded})")

    print(
        f"완료 · org={org_id} · 상품 {len(products)}개에 활동 반영 "
        f"(조회 {total_views} · 판매 {total_sold} · 환불 {total_refunded})"
    )
    print("(멱등: 오늘 날짜 기준 external_event_id/주문 id로 재실행해도 중복 없음)")


if __name__ == "__main__":
    _db_url = os.getenv("DATABASE_URL", "")
    backend = "Postgres" if _db_url.startswith(("postgres://", "postgresql://")) else "SQLite"
    print(f"SIGN 샘플 활동 시드 시작 (backend={backend})")
    seed()
