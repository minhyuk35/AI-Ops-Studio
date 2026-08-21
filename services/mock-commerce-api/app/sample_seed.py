"""Keeps SIGN's sample activity data covering "today" going forward.

scripts/seed_sign_activity.py (repo root, not deployed -- outside
services/mock-commerce-api/** so Vercel's includeFiles never bundles it)
seeds a fixed 60-day window *as of whenever someone runs it by hand*. That
window silently falls behind as real time passes: every day that goes by
without a manual re-run is a day with no sample data, which is exactly the
"오늘 데이터가 없다" gap reported repeatedly. This module is the deployed,
cron-callable equivalent -- see app/main.py's /internal/cron/extend-sign-seed
and vercel.json's cron entry (runs daily). It only seeds a small recent
window (not the full 60 days) so a single invocation comfortably finishes
within Vercel's 30s function budget; idempotent inserts mean days already
covered are nearly free to re-touch.

Because RECENT_DAYS is a *rolling* window, the same date gets re-seeded on
several consecutive days' cron runs (e.g. "yesterday" is touched by both
today's and tomorrow's run). Each day's random event count/choices must
therefore be a deterministic function of the date, not of global RNG state
-- otherwise a re-run for an already-seeded date would roll a *different*
view/order count than last time, and every count above the smaller of the
two runs would insert as new (non-conflicting) rows instead of being a true
no-op, so daily totals would silently keep growing for as long as a date
stays inside the rolling window.
"""

import random
from datetime import UTC, datetime, timedelta

from app.auth import hash_password
from app.db import record_event, utc_now

RECENT_DAYS = 5
BUYER_ID = "cus_demo_buyer"
BUYER_EMAIL = "demo-buyer@codilab.local"
BUYER_NAME = "김코디"

# 요일 가중치(월=0..일=6) -- 주말이 평일보다 조회·구매가 조금 더 많다는 흔한 패턴.
WEEKDAY_WEIGHT = {0: 0.85, 1: 0.85, 2: 0.9, 3: 0.95, 4: 1.05, 5: 1.3, 6: 1.2}


def _ensure_buyer(connection) -> None:
    connection.execute(
        """
        INSERT INTO customers(id, email, name, phone, password_hash, is_admin, created_at)
        VALUES(?,?,?,?,?,0,?)
        ON CONFLICT(id) DO NOTHING
        """,
        (BUYER_ID, BUYER_EMAIL, BUYER_NAME, "010-0000-0002", hash_password("demo1234"), utc_now()),
    )


def _sign_org(connection) -> str | None:
    row = connection.execute("SELECT id FROM organizations WHERE name = ?", ("SIGN",)).fetchone()
    return str(row["id"]) if row is not None else None


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


def _random_time_on(rng: random.Random, date: str) -> str:
    day = datetime.fromisoformat(date).replace(tzinfo=UTC)
    offset = timedelta(seconds=rng.randint(8 * 3600, 23 * 3600))
    return (day + offset).isoformat()


def _seed_day(connection, org_id: str, variants: list[dict], date: str) -> None:
    # Seeded per-date (not the global random module) so re-seeding the same
    # date on a later cron run reproduces the exact same event count/choices
    # -- see module docstring.
    rng = random.Random(date)
    weekday = datetime.fromisoformat(date).weekday()
    weight = WEEKDAY_WEIGHT[weekday] * rng.uniform(1.0, 1.2)  # current-month growth factor

    view_count = max(3, round(rng.randint(18, 42) * weight))
    for i in range(view_count):
        variant = rng.choice(variants)
        record_event(
            connection,
            event_type="PRODUCT_VIEWED",
            external_event_id=f"seed_sign_act_view_{date}_{i:03d}",
            product_id=variant["product_id"],
            occurred_at=_random_time_on(rng, date),
            org_id=org_id,
        )

    order_count = max(0, round(rng.uniform(1.5, 5.5) * weight))
    for i in range(order_count):
        order_id = f"ord_seed_sign_act_{date}_{i:03d}"
        variant = rng.choice(variants)
        quantity = rng.choice([1, 1, 1, 2])
        unit_price = int(variant["price"])
        line_total = unit_price * quantity
        occurred_at = _random_time_on(rng, date)

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
            (
                f"pay_{order_id}", order_id, f"seed_{order_id}", "CARD",
                line_total, "PAID", occurred_at,
            ),
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

        if rng.random() < 0.08:
            refund_at = _random_time_on(rng, date)
            connection.execute(
                """
                INSERT INTO claims(
                    id, order_id, type, reason, status,
                    refund_amount, return_fee, created_at, updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    f"clm_{order_id}", order_id, "RETURN", "샘플 환불(사이즈 불일치)",
                    "REFUNDED", line_total, 0, refund_at, refund_at,
                ),
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


def extend_sign_seed(connection, days: int = RECENT_DAYS) -> dict[str, object]:
    """Idempotently (re-)seeds the last `days` days for SIGN. Safe to call
    on a schedule -- days already covered by a previous run just re-hit
    ON CONFLICT DO NOTHING and cost one cheap query each."""
    org_id = _sign_org(connection)
    if org_id is None:
        return {"seeded": False, "reason": "org 'SIGN' not found"}
    variants = _sign_variants(connection, org_id)
    if not variants:
        return {"seeded": False, "reason": "SIGN has no products/variants yet"}

    _ensure_buyer(connection)
    today = datetime.now(UTC).date()
    dates = []
    for offset in range(days - 1, -1, -1):
        date = (today - timedelta(days=offset)).isoformat()
        _seed_day(connection, org_id, variants, date)
        dates.append(date)
    return {"seeded": True, "org_id": org_id, "dates": dates}
