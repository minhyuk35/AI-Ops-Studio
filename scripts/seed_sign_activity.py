"""SIGN 매장 샘플 활동 데이터 시드 -- 최근 60일치(이번 달 + 지난달) 일별 조회·주문·환불.

일일 리포트의 전날 대비 비교, 월간 리포트의 이번 달 vs 지난달 비교, 판매자
콘솔의 일별 매출 추이 차트가 전부 commerce_events 원장에서 계산되므로, 이
스크립트 없이는 그 화면들이 전부 빈 상태로 보인다.

배포(Neon/Postgres)와 로컬(SQLite) 양쪽에서 돌아간다(app.db 호환 레이어 사용).
멱등: 날짜+인덱스로 결정되는 external_event_id라 여러 번 돌려도 중복이 안 생긴다.
지난달 대비 이번 달 판매량이 더 많도록 완만한 성장 추세를 넣어서 "이번 달 vs
지난달" 비교 서술이 실제로 의미 있는 숫자를 갖게 한다.

실행:
  # 배포 DB(Neon)에 넣기
  $env:PYTHONPATH="services/mock-commerce-api"
  $env:DATABASE_URL="postgresql://.../neondb?sslmode=require"
  python scripts/seed_sign_activity.py
  # 로컬 SQLite에 넣기(개발): DATABASE_URL 을 비우고 실행
"""
# ruff: noqa: E501  (SQL·안내 문자열이 많아 한 줄에 두는 게 읽기 쉬움 -- seed_sign_catalog.py와 동일 정책)

import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SVC = Path(__file__).resolve().parents[1] / "services" / "mock-commerce-api"
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.auth import hash_password  # noqa: E402
from app.db import record_event, transaction, utc_now  # noqa: E402

DAYS = 60
BUYER_ID = "cus_demo_buyer"
BUYER_EMAIL = "demo-buyer@codilab.local"
BUYER_NAME = "김코디"

# 요일 가중치(월=0..일=6) -- 주말이 평일보다 조회·구매가 조금 더 많다는 흔한 패턴.
WEEKDAY_WEIGHT = {0: 0.85, 1: 0.85, 2: 0.9, 3: 0.95, 4: 1.05, 5: 1.3, 6: 1.2}


def _ensure_buyer(connection) -> str:
    connection.execute(
        """
        INSERT INTO customers(id, email, name, phone, password_hash, is_admin, created_at)
        VALUES(?,?,?,?,?,0,?)
        ON CONFLICT(id) DO NOTHING
        """,
        (BUYER_ID, BUYER_EMAIL, BUYER_NAME, "010-0000-0002", hash_password("demo1234"), utc_now()),
    )
    return BUYER_ID


def _sign_org(connection) -> str:
    row = connection.execute("SELECT id FROM organizations WHERE name = ?", ("SIGN",)).fetchone()
    if row is None:
        raise SystemExit("SIGN 조직을 찾을 수 없습니다 -- scripts/seed_sign_catalog.py 를 먼저 실행하세요.")
    return str(row["id"])


def _sign_variants(connection, org_id: str) -> list[dict]:
    rows = connection.execute(
        """
        SELECT v.id AS variant_id, v.sku, v.color, v.size, v.price,
               p.id AS product_id, p.name AS product_name
        FROM variants v
        JOIN products p ON p.id = v.product_id
        WHERE p.org_id = ?
        """,
        (org_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _random_time_on(date: str) -> str:
    day = datetime.fromisoformat(date).replace(tzinfo=UTC)
    offset = timedelta(seconds=random.randint(8 * 3600, 23 * 3600))
    return (day + offset).isoformat()


def _seed_day(connection, org_id: str, variants: list[dict], date: str, month_factor: float) -> None:
    weekday = datetime.fromisoformat(date).weekday()
    weight = WEEKDAY_WEIGHT[weekday] * month_factor

    view_count = max(3, round(random.randint(18, 42) * weight))
    for i in range(view_count):
        variant = random.choice(variants)
        record_event(
            connection,
            event_type="PRODUCT_VIEWED",
            external_event_id=f"seed_sign_act_view_{date}_{i:03d}",
            product_id=variant["product_id"],
            occurred_at=_random_time_on(date),
            org_id=org_id,
        )

    order_count = max(0, round(random.uniform(1.5, 5.5) * weight))
    for i in range(order_count):
        order_id = f"ord_seed_sign_act_{date}_{i:03d}"
        variant = random.choice(variants)
        quantity = random.choice([1, 1, 1, 2])
        unit_price = int(variant["price"])
        line_total = unit_price * quantity
        occurred_at = _random_time_on(date)

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
                order_id, BUYER_ID, BUYER_EMAIL, BUYER_NAME, "010-0000-0002",
                "04524", "서울특별시 중구 세종대로 110", "101호", "",
                "DELIVERED", line_total, 0, 0, line_total, "PAID", occurred_at, occurred_at,
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
                f"oi_{order_id}", order_id, variant["product_id"], variant["variant_id"],
                variant["product_name"], variant["sku"],
                f"{variant['color']} / {variant['size']}", unit_price, quantity, line_total,
            ),
        )
        connection.execute(
            """
            INSERT INTO payments(id, order_id, payment_key, method, amount, status, approved_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id) DO NOTHING
            """,
            (f"pay_{order_id}", order_id, f"seed_{order_id}", "CARD", line_total, "PAID", occurred_at),
        )
        record_event(
            connection,
            event_type="PAYMENT_CONFIRMED",
            external_event_id=f"{order_id}:PAYMENT_CONFIRMED",
            order_id=order_id,
            product_id=variant["product_id"],
            variant_id=variant["variant_id"],
            quantity=quantity,
            amount=line_total,
            occurred_at=occurred_at,
            org_id=org_id,
        )

        # ~8%는 환불까지 이어진다 -- 리포트의 환불 관련 서술에 실제 데이터가 있도록.
        if random.random() < 0.08:
            refund_at = _random_time_on(date)
            connection.execute(
                """
                INSERT INTO claims(id, order_id, type, reason, status, refund_amount, return_fee, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO NOTHING
                """,
                (f"clm_{order_id}", order_id, "RETURN", "샘플 환불(사이즈 불일치)", "REFUNDED", line_total, 0, refund_at, refund_at),
            )
            record_event(
                connection,
                event_type="REFUND_COMPLETED",
                external_event_id=f"{order_id}:REFUND_COMPLETED",
                order_id=order_id,
                product_id=variant["product_id"],
                variant_id=variant["variant_id"],
                refund_amount=line_total,
                occurred_at=refund_at,
                org_id=org_id,
            )


def seed() -> None:
    with transaction() as connection:
        _ensure_buyer(connection)
        org_id = _sign_org(connection)
        variants = _sign_variants(connection, org_id)
        if not variants:
            raise SystemExit("SIGN 상품/옵션이 없습니다 -- scripts/seed_sign_catalog.py 를 먼저 실행하세요.")

        today = datetime.now(UTC).date()
        current_month = today.strftime("%Y-%m")
        for offset in range(DAYS - 1, -1, -1):
            date = (today - timedelta(days=offset)).isoformat()
            is_current_month = date.startswith(current_month)
            # 완만한 성장 추세: 지난달은 기준선의 약 65~85%, 이번 달은 100~120%.
            month_factor = random.uniform(1.0, 1.2) if is_current_month else random.uniform(0.65, 0.85)
            _seed_day(connection, org_id, variants, date, month_factor)
        print(f"완료 · org={org_id} · {DAYS}일치 조회/주문/환불 시드 (오늘={today.isoformat()})")
        print("(멱등: 이미 있는 날짜는 external_event_id/PK 충돌로 건너뜀)")


if __name__ == "__main__":
    random.seed(20260817)  # 재실행해도 같은 날짜엔 같은 분포가 나오도록 고정
    backend = "Postgres" if os.getenv("DATABASE_URL", "").startswith(("postgres://", "postgresql://")) else "SQLite"
    print(f"SIGN 활동 데이터 시드 시작 (backend={backend})")
    seed()
