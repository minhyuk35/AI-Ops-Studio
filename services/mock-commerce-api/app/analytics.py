"""Code-computed revenue and product analytics over the commerce event ledger.

Per the product principle in docs/ai-ops-studio-master-prd.html: numbers here
are plain SQL aggregation, never an LLM guess. AI only narrates these once
they exist (commerce-insight / commerce-monthly-report personas).
"""

import re
import sqlite3
from datetime import UTC, datetime

PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

REVENUE_EVENT_TYPES = ("PAYMENT_CONFIRMED", "REFUND_COMPLETED")


def current_period() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


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
