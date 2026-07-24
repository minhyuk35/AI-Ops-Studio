"""Code-computed revenue and product analytics over the commerce event ledger.

Per the product principle in docs/ai-ops-studio-master-prd.html: numbers here
are plain SQL aggregation, never an LLM guess. AI only narrates these once
they exist (commerce-insight / commerce-monthly-report personas).
"""

import re
import sqlite3
from datetime import UTC, datetime, timedelta

PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

REVENUE_EVENT_TYPES = ("PAYMENT_CONFIRMED", "REFUND_COMPLETED")


def current_period() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def is_valid_date(date: str) -> bool:
    return bool(DATE_PATTERN.match(date))


def _day_bounds(date: str) -> tuple[str, str]:
    start = datetime.fromisoformat(date).replace(tzinfo=UTC)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def is_valid_period(period: str) -> bool:
    return bool(PERIOD_PATTERN.match(period))


def _month_bounds(period: str) -> tuple[str, str]:
    year, month = (int(part) for part in period.split("-"))
    start = datetime(year, month, 1, tzinfo=UTC)
    end = (
        datetime(year + 1, 1, 1, tzinfo=UTC)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=UTC)
    )
    return start.isoformat(), end.isoformat()


def previous_period(period: str) -> str:
    year, month = (int(part) for part in period.split("-"))
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _percent_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None  # undefined growth rate with a zero baseline; don't fabricate one
    return round((current - previous) / previous * 100, 1)


def revenue_summary(connection: sqlite3.Connection, period: str) -> dict[str, object]:
    """총결제액·환불액·순매출·주문수·객단가 for one calendar month.

    Based on when each event *occurred*, not current order status, so a
    refund recorded next month never rewrites this month's paid revenue.
    """
    start, end = _month_bounds(period)
    row = connection.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN event_type = 'PAYMENT_CONFIRMED' THEN amount END), 0)
                AS gross_revenue,
            COALESCE(SUM(CASE WHEN event_type = 'REFUND_COMPLETED' THEN refund_amount END), 0)
                AS refund_amount,
            COUNT(DISTINCT CASE WHEN event_type = 'PAYMENT_CONFIRMED' THEN order_id END)
                AS order_count
        FROM commerce_events
        WHERE occurred_at >= ? AND occurred_at < ?
        """,
        (start, end),
    ).fetchone()
    gross_revenue = int(row["gross_revenue"])
    refund_amount = int(row["refund_amount"])
    order_count = int(row["order_count"])
    net_revenue = gross_revenue - refund_amount
    average_order_value = net_revenue // order_count if order_count else 0
    return {
        "period": period,
        "gross_revenue": gross_revenue,
        "refund_amount": refund_amount,
        "net_revenue": net_revenue,
        "order_count": order_count,
        "average_order_value": average_order_value,
    }


def revenue_summary_with_comparison(
    connection: sqlite3.Connection, period: str
) -> dict[str, object]:
    current = revenue_summary(connection, period)
    previous = revenue_summary(connection, previous_period(period))
    current["previous_period"] = previous
    current["change"] = {
        "gross_revenue_pct": _percent_change(
            current["gross_revenue"], previous["gross_revenue"]
        ),
        "net_revenue_pct": _percent_change(current["net_revenue"], previous["net_revenue"]),
        "order_count_pct": _percent_change(current["order_count"], previous["order_count"]),
        "average_order_value_pct": _percent_change(
            current["average_order_value"], previous["average_order_value"]
        ),
    }
    return current


def product_breakdown(connection: sqlite3.Connection, period: str) -> list[dict[str, object]]:
    """Per-product units/revenue/refunds for one calendar month.

    Every product is included, even with zero activity, so 부진 상품
    (worst performers) shows up rather than silently disappearing.

    refund_rate is refund_units / units_sold *within this same period*. If a
    product refunds more units than it sold this month (e.g. it was bought
    last month and returned this month), units_sold is 0 and refund_rate is
    left as None rather than an inflated or divide-by-zero number — a true
    cohort-based rate would need to track refunds against their original
    sale, which this ledger doesn't do yet.
    """
    start, end = _month_bounds(period)
    placeholders = ",".join("?" for _ in REVENUE_EVENT_TYPES)
    rows = connection.execute(
        f"""
        SELECT
            p.id AS product_id,
            p.name AS product_name,
            COALESCE(SUM(CASE WHEN ce.event_type = 'PAYMENT_CONFIRMED' THEN oi.quantity END), 0)
                AS units_sold,
            COALESCE(SUM(CASE WHEN ce.event_type = 'PAYMENT_CONFIRMED' THEN oi.line_total END), 0)
                AS revenue,
            COALESCE(SUM(CASE WHEN ce.event_type = 'REFUND_COMPLETED' THEN oi.quantity END), 0)
                AS refund_units,
            COALESCE(SUM(CASE WHEN ce.event_type = 'REFUND_COMPLETED' THEN oi.line_total END), 0)
                AS refund_amount
        FROM products p
        LEFT JOIN order_items oi ON oi.product_id = p.id
        LEFT JOIN commerce_events ce
            ON ce.order_id = oi.order_id
            AND ce.event_type IN ({placeholders})
            AND ce.occurred_at >= ? AND ce.occurred_at < ?
        GROUP BY p.id, p.name
        ORDER BY revenue DESC, p.name ASC
        """,
        (*REVENUE_EVENT_TYPES, start, end),
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        units_sold = int(row["units_sold"])
        refund_units = int(row["refund_units"])
        refund_rate = round(refund_units / units_sold, 4) if units_sold else None
        result.append(
            {
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "units_sold": units_sold,
                "revenue": int(row["revenue"]),
                "refund_units": refund_units,
                "refund_amount": int(row["refund_amount"]),
                "refund_rate": refund_rate,
            }
        )
    return result


def seller_daily_snapshot(
    connection: sqlite3.Connection, org_id: str, date: str
) -> dict[str, object]:
    """One seller's single-day activity: views, sales, refunds, and current stock.

    Feeds the daily-seller-report AI persona. Every product owned by the org
    is included even with zero activity, so "아무도 안 본 상품" and "완전히
    안 팔린 상품" show up instead of silently disappearing — that's exactly
    the signal the AI feedback step is meant to react to.
    """
    start, end = _day_bounds(date)
    org_row = connection.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
    rows = connection.execute(
        """
        SELECT
            p.id AS product_id, p.name AS product_name,
            COALESCE(stock.total_stock, 0) AS stock,
            COALESCE(views.view_count, 0) AS views,
            COALESCE(sales.units_sold, 0) AS units_sold,
            COALESCE(sales.revenue, 0) AS revenue,
            COALESCE(refunds.refund_units, 0) AS refund_units,
            COALESCE(refunds.refund_amount, 0) AS refund_amount
        FROM products p
        LEFT JOIN (
            SELECT product_id, SUM(stock) AS total_stock FROM variants GROUP BY product_id
        ) stock ON stock.product_id = p.id
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS view_count FROM commerce_events
            WHERE event_type = 'PRODUCT_VIEWED' AND occurred_at >= :start AND occurred_at < :end
            GROUP BY product_id
        ) views ON views.product_id = p.id
        LEFT JOIN (
            SELECT oi.product_id, SUM(oi.quantity) AS units_sold, SUM(oi.line_total) AS revenue
            FROM order_items oi
            JOIN commerce_events ce ON ce.order_id = oi.order_id
                AND ce.event_type = 'PAYMENT_CONFIRMED'
                AND ce.occurred_at >= :start AND ce.occurred_at < :end
            GROUP BY oi.product_id
        ) sales ON sales.product_id = p.id
        LEFT JOIN (
            SELECT oi.product_id, SUM(oi.quantity) AS refund_units,
                   SUM(oi.line_total) AS refund_amount
            FROM order_items oi
            JOIN commerce_events ce ON ce.order_id = oi.order_id
                AND ce.event_type = 'REFUND_COMPLETED'
                AND ce.occurred_at >= :start AND ce.occurred_at < :end
            GROUP BY oi.product_id
        ) refunds ON refunds.product_id = p.id
        WHERE p.org_id = :org_id
        ORDER BY p.name
        """,
        {"start": start, "end": end, "org_id": org_id},
    ).fetchall()

    products = [dict(row) for row in rows]
    order_count_row = connection.execute(
        """
        SELECT COUNT(DISTINCT order_id) AS order_count FROM commerce_events
        WHERE org_id = ? AND event_type = 'PAYMENT_CONFIRMED'
          AND occurred_at >= ? AND occurred_at < ?
        """,
        (org_id, start, end),
    ).fetchone()

    gross_revenue = sum(int(row["revenue"]) for row in products)
    refund_amount = sum(int(row["refund_amount"]) for row in products)

    viewed = [row for row in products if row["views"] > 0]
    purchased = [row for row in products if row["units_sold"] > 0]
    refunded = [row for row in products if row["refund_units"] > 0]

    return {
        "date": date,
        "org_id": org_id,
        "org_name": org_row["name"] if org_row else org_id,
        "revenue": {
            "gross_revenue": gross_revenue,
            "refund_amount": refund_amount,
            "net_revenue": gross_revenue - refund_amount,
            "order_count": int(order_count_row["order_count"]),
        },
        "products": products,
        "highlights": {
            "most_viewed": max(viewed, key=lambda r: r["views"], default=None),
            "least_viewed": min(products, key=lambda r: r["views"], default=None),
            "most_purchased": max(purchased, key=lambda r: r["units_sold"], default=None),
            "most_refunded": max(refunded, key=lambda r: r["refund_units"], default=None),
            "out_of_stock": [row for row in products if row["stock"] == 0],
            "low_stock": [row for row in products if 0 < row["stock"] <= 3],
        },
    }
