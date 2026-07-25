"""판매자 지표를 Discord 메시지 문자열로 바꾸는 순수 함수들.

디스코드 의존성이 전혀 없어서 봇을 실행하지 않고도 단위 테스트할 수 있다.
숫자는 전부 커머스 API가 SQL로 계산한 값(analytics.py)이며, 여기서는 표시
형식만 만든다. 절대 새 수치를 만들어내지 않는다.
"""

from typing import Any

_DISCORD_LIMIT = 2000


def won(value: Any) -> str:
    try:
        return f"{int(value):,}원"
    except (TypeError, ValueError):
        return "0원"


def _pct(value: Any) -> str:
    """percent_change() 결과(%): None이면 비교 불가(전월 0)."""
    if value is None:
        return "—"
    number = float(value)
    sign = "▲" if number > 0 else ("▼" if number < 0 else "→")
    return f"{sign}{abs(number):.1f}%"


def clip(text: str, limit: int = _DISCORD_LIMIT) -> str:
    """Discord 단일 메시지 2000자 제한에 맞춰 안전하게 자른다."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def format_revenue(data: dict[str, Any]) -> str:
    lines = [
        f"## 💰 매출 요약 · {data.get('period', '')}",
        f"- 총결제액: **{won(data.get('gross_revenue'))}**",
        f"- 환불액: {won(data.get('refund_amount'))}",
        f"- 순매출: **{won(data.get('net_revenue'))}**",
        f"- 주문수: {int(data.get('order_count', 0)):,}건",
        f"- 객단가: {won(data.get('average_order_value'))}",
    ]
    return clip("\n".join(lines))


def format_views(data: dict[str, Any]) -> str:
    top = data.get("top_products") or []
    lines = [
        f"## 👀 조회수 · {data.get('date', '')}",
        f"- 오늘 전체 조회수: **{int(data.get('total_views', 0)):,}회**",
    ]
    if top:
        lines.append("**상위 상품**")
        for i, product in enumerate(top[:10], start=1):
            name = product.get("product_name", "")
            lines.append(f"{i}. {name} — {int(product.get('views', 0)):,}회")
    else:
        lines.append("_오늘 조회된 상품이 아직 없습니다._")
    return clip("\n".join(lines))


def format_daily(data: dict[str, Any]) -> str:
    revenue = data.get("revenue") or {}
    highlights = data.get("highlights") or {}
    most_viewed = highlights.get("most_viewed")
    most_purchased = highlights.get("most_purchased")
    out_of_stock = highlights.get("out_of_stock") or []
    low_stock = highlights.get("low_stock") or []

    lines = [
        f"## 📊 {data.get('org_name', '')} · {data.get('date', '')} 일일 스냅샷",
        f"- 순매출: **{won(revenue.get('net_revenue'))}** "
        f"(결제 {won(revenue.get('gross_revenue'))} / 환불 {won(revenue.get('refund_amount'))})",
        f"- 주문수: {int(revenue.get('order_count', 0)):,}건",
    ]
    if most_viewed:
        lines.append(
            f"- 가장 많이 본 상품: {most_viewed.get('product_name', '')} "
            f"({int(most_viewed.get('views', 0)):,}회)"
        )
    if most_purchased:
        lines.append(
            f"- 가장 많이 팔린 상품: {most_purchased.get('product_name', '')} "
            f"({int(most_purchased.get('units_sold', 0)):,}개)"
        )
    if out_of_stock:
        names = ", ".join(p.get("product_name", "") for p in out_of_stock[:5])
        lines.append(f"- ⛔ 품절: {names}")
    if low_stock:
        names = ", ".join(
            f"{p.get('product_name', '')}({int(p.get('stock', 0))})" for p in low_stock[:5]
        )
        lines.append(f"- ⚠️ 재고 임박: {names}")
    lines.append("")
    lines.append("_숫자는 사이트 집계값입니다. AI 해석 리포트는 연동 웹훅으로 별도 전송됩니다._")
    return clip("\n".join(lines))


def format_stock(data: dict[str, Any]) -> str:
    out_of_stock = data.get("out_of_stock") or []
    low_stock = data.get("low_stock") or []
    lines = [f"## 📦 재고 현황 · {data.get('date', '')}"]
    if out_of_stock:
        lines.append("**⛔ 품절**")
        for product in out_of_stock[:15]:
            lines.append(f"- {product.get('product_name', '')}")
    if low_stock:
        lines.append("**⚠️ 재고 임박(3개 이하)**")
        for product in low_stock[:15]:
            lines.append(f"- {product.get('product_name', '')} — {int(product.get('stock', 0))}개")
    if not out_of_stock and not low_stock:
        lines.append("_품절·임박 상품이 없습니다. 재고가 안정적입니다._")
    return clip("\n".join(lines))


def format_status(data: dict[str, Any]) -> str:
    channels = data.get("channels") or []
    plan_channels = data.get("plan_channels") or []
    lines = [
        "## 🔗 연동 상태",
        f"- 연동됨: {'✅ 예' if data.get('linked') else '❌ 아니오'}",
        f"- 요금제: **{data.get('plan', 'FREE')}**",
    ]
    if channels:
        lines.append(f"- 생성된 채널: {len(channels)}개")
        for channel in channels:
            name = channel.get("channel_name") or channel.get("channel_key")
            has_hook = "🪝" if channel.get("webhook_url") else "—"
            lines.append(f"  · {name} {has_hook}")
    else:
        plan_names = ", ".join(str(c.get("name")) for c in plan_channels)
        lines.append(f"- 아직 `/생성`을 실행하지 않았습니다. 생성될 채널: {plan_names}")
    return clip("\n".join(lines))
