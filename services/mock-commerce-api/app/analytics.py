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


def platform_daily_traffic(connection: sqlite3.Connection, date: str) -> dict[str, object]:
    """Site-wide product view traffic for one day, across every seller.

    Admin-only by design: which pages/products get traffic platform-wide is
    a site-operator concern, not something any one seller needs (or should
    see about competitors). Sellers get the same shape of number, but
    scoped to only their own products, via seller_daily_snapshot().
    """
    start, end = _day_bounds(date)
    rows = connection.execute(
        """
        SELECT
            p.id AS product_id, p.name AS product_name,
            COALESCE(o.name, '플랫폼 기본 상품') AS org_name,
            COALESCE(v.view_count, 0) AS views
        FROM products p
        LEFT JOIN organizations o ON o.id = p.org_id
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS view_count FROM commerce_events
            WHERE event_type = 'PRODUCT_VIEWED' AND occurred_at >= :start AND occurred_at < :end
            GROUP BY product_id
        ) v ON v.product_id = p.id
        ORDER BY views DESC, p.name ASC
        """,
        {"start": start, "end": end},
    ).fetchall()

    products = [dict(row) for row in rows]
    total_views = sum(row["views"] for row in products)

    by_store: dict[str, int] = {}
    for row in products:
        by_store[row["org_name"]] = by_store.get(row["org_name"], 0) + row["views"]
    store_ranking = sorted(
        ({"org_name": name, "views": views} for name, views in by_store.items()),
        key=lambda entry: entry["views"],
        reverse=True,
    )

    return {
        "date": date,
        "total_views": total_views,
        "top_products": products[:10],
        "least_viewed_products": list(reversed(products))[:5],
        "store_ranking": store_ranking,
    }


# The platform's own income model, not the sellers' — see
# docs/ai-ops-studio-master-prd.html#plans. Sellers keep their own gross
# sales; AI Ops Studio only earns a commission cut off each sale plus a
# flat monthly plan fee. No billing system exists yet, so these are fixed
# assumptions used purely to interpret "site revenue" correctly rather than
# conflating it with seller GMV.
PLAN_MONTHLY_FEES: dict[str, int] = {
    "FREE": 0,
    "BASIC": 35_000,
    "PRO": 150_000,
    "BUSINESS": 300_000,
}


def _seller_gross_revenue_by_org(
    connection: sqlite3.Connection, period: str
) -> list[dict[str, object]]:
    start, end = _month_bounds(period)
    rows = connection.execute(
        """
        SELECT
            o.id AS org_id, o.name AS org_name, o.commission_rate, o.plan,
            COALESCE(SUM(CASE WHEN ce.event_type = 'PAYMENT_CONFIRMED' THEN ce.amount END), 0)
                AS gross_revenue,
            COALESCE(
                SUM(CASE WHEN ce.event_type = 'REFUND_COMPLETED' THEN ce.refund_amount END), 0
            ) AS refund_amount
        FROM organizations o
        LEFT JOIN commerce_events ce
            ON ce.org_id = o.id AND ce.occurred_at >= :start AND ce.occurred_at < :end
        WHERE o.status = 'ACTIVE'
        GROUP BY o.id, o.name, o.commission_rate, o.plan
        ORDER BY gross_revenue DESC
        """,
        {"start": start, "end": end},
    ).fetchall()
    return [dict(row) for row in rows]


def _platform_revenue_breakdown(
    connection: sqlite3.Connection, period: str
) -> tuple[list[dict[str, object]], int, int]:
    """Per-seller platform revenue (commission + plan fee) for one month.

    Returns (sellers, platform_default_revenue, total_platform_revenue).
    total_gmv (every won that changed hands) comes from revenue_summary()
    — the single source of truth for "how much did the whole site sell".
    platform_default_revenue is GMV from the un-owned seed catalog
    (org_id IS NULL): nobody paid a commission on it because there's no
    third-party seller to take a cut from, so it counts as 100% platform
    revenue, same as a seller's plan fee does.
    """
    total_gmv = revenue_summary(connection, period)["gross_revenue"]
    accounted_gmv = 0
    sellers: list[dict[str, object]] = []
    for row in _seller_gross_revenue_by_org(connection, period):
        gross = int(row["gross_revenue"])
        refund = int(row["refund_amount"])
        accounted_gmv += gross
        plan = str(row["plan"] or "FREE")
        commission_revenue = round(gross * float(row["commission_rate"]))
        plan_fee = PLAN_MONTHLY_FEES.get(plan, 0)
        sellers.append(
            {
                "org_id": row["org_id"],
                "org_name": row["org_name"],
                "plan": plan,
                "gross_revenue": gross,
                "refund_amount": refund,
                "net_revenue": gross - refund,
                "commission_revenue": commission_revenue,
                "plan_fee": plan_fee,
                "platform_contribution": commission_revenue + plan_fee,
            }
        )
    platform_default_revenue = total_gmv - accounted_gmv
    total_platform_revenue = platform_default_revenue + sum(
        int(seller["platform_contribution"]) for seller in sellers
    )
    return sellers, platform_default_revenue, total_platform_revenue


def seller_market_share(connection: sqlite3.Connection, period: str) -> dict[str, object]:
    """Each active seller's share of *platform* revenue — not their own GMV.

    "매출의 몇 퍼센트를 차지하는가" means each seller's cut of what AI Ops
    Studio itself earns (commission + plan fee), because the site doesn't
    keep a seller's sales — it keeps a slice of them. A seller with huge
    GMV on a FREE plan can contribute less platform revenue than a smaller
    seller paying for BUSINESS.
    """
    sellers, platform_default_revenue, total_platform_revenue = _platform_revenue_breakdown(
        connection, period
    )
    for seller in sellers:
        contribution = int(seller["platform_contribution"])
        seller["share_pct"] = (
            round(contribution / total_platform_revenue * 100, 1)
            if total_platform_revenue
            else None
        )

    prev_period = previous_period(period)
    prev_sellers, _prev_default, prev_total_platform_revenue = _platform_revenue_breakdown(
        connection, prev_period
    )
    previous_shares = {
        seller["org_id"]: (
            round(int(seller["platform_contribution"]) / prev_total_platform_revenue * 100, 1)
            if prev_total_platform_revenue
            else None
        )
        for seller in prev_sellers
    }
    for seller in sellers:
        seller["previous_share_pct"] = previous_shares.get(seller["org_id"])

    return {
        "period": period,
        "previous_period": prev_period,
        "total_platform_revenue": total_platform_revenue,
        "platform_default_revenue": platform_default_revenue,
        "platform_default_share_pct": (
            round(platform_default_revenue / total_platform_revenue * 100, 1)
            if total_platform_revenue
            else None
        ),
        "sellers": sellers,
    }
