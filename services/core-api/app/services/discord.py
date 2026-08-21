import json
from typing import Any
from urllib.parse import quote

import httpx

# Discord hard-limits a single webhook message's content field to 2000
# characters. AI-generated reports routinely run longer than that, so a
# naive content[:2000] slice used to cut a message off mid-word/mid-heading
# (e.g. a bare "###" with nothing after it). _chunk_content() instead splits
# into several sequential messages, breaking at paragraph/line boundaries.
_MAX_CONTENT_LENGTH = 2000


def _chunk_content(content: str, max_length: int = _MAX_CONTENT_LENGTH) -> list[str]:
    if len(content) <= max_length:
        return [content]

    chunks: list[str] = []
    remaining = content
    while len(remaining) > max_length:
        window = remaining[:max_length]
        split_at = window.rfind("\n\n")
        if split_at == -1:
            split_at = window.rfind("\n")
        if split_at == -1:
            split_at = max_length
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


def build_daily_revenue_chart_url(
    series: list[dict[str, Any]], title: str = "최근 매출 추이"
) -> str | None:
    """QuickChart.io render URL for a seller's daily gross revenue, attached
    to daily-report Discord messages alongside the AI's text narrative.

    QuickChart is a free third-party chart-image service: the chart config
    (day labels, revenue numbers, and the org's own store name in the title
    -- never customer PII) is sent to quickchart.io as a URL query param
    and it hands back a PNG -- no local rendering dependency (matplotlib
    etc.) needed. Returns None for an empty/all-zero series rather than
    link to a blank chart.
    """
    if not series or all(int(day.get("gross_revenue", 0)) == 0 for day in series):
        return None
    labels = [str(day["date"])[5:] for day in series]  # "YYYY-MM-DD" -> "MM-DD"
    values = [int(day.get("gross_revenue", 0)) for day in series]
    config = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [{"label": "매출", "data": values, "backgroundColor": "#2f6fed"}],
        },
        "options": {
            # QuickChart defaults to Chart.js v2, which reads the title from
            # options.title (not v3's options.plugins.title) -- set both so
            # it renders regardless of which version actually runs.
            "title": {"display": True, "text": title},
            "plugins": {"legend": {"display": False}, "title": {"display": True, "text": title}},
        },
    }
    encoded = quote(json.dumps(config, ensure_ascii=False))
    return f"https://quickchart.io/chart?c={encoded}&backgroundColor=white&width=600&height=300"


class DiscordNotifier:
    """Best-effort Discord webhook sender.

    Used to push sensitive-inquiry escalations, seller daily reports and
    admin-only platform reports out of the app. Never raises — a missing or
    unreachable webhook should not break the AI pipeline that triggered the
    notification. Takes the webhook URL directly (rather than a Settings
    object) so the app can run two independent notifiers — one for
    per-seller/escalation messages, one for admin-only platform reports —
    without either leaking into the wrong Discord channel.
    """

    def __init__(self, webhook_url: str, timeout_seconds: float = 10) -> None:
        self._webhook_url = webhook_url
        self._timeout = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self._webhook_url)

    def send(self, content: str) -> bool:
        if not self.enabled:
            return False
        sent_any = False
        for chunk in _chunk_content(content):
            try:
                response = httpx.post(
                    self._webhook_url,
                    json={"content": chunk},
                    timeout=self._timeout,
                )
                response.raise_for_status()
                sent_any = True
            except httpx.HTTPError:
                return sent_any
        return sent_any

    def send_with_chart(self, content: str, chart_image_url: str | None) -> bool:
        """Same chunked text as send(), plus a trailing embed whose image is
        a chart -- a separate webhook call rather than attaching the embed
        to the last text chunk, since send() can split into an arbitrary
        number of chunks and the chart should land after all of them
        regardless of how many that was. Silently skips the chart call
        (still sends the text) when chart_image_url is None -- e.g. an
        all-zero revenue series, where a blank chart adds nothing."""
        sent = self.send(content)
        if not sent or not chart_image_url:
            return sent
        self.send_embed({"image": {"url": chart_image_url}, "color": 0x2F6FED})
        return sent

    def send_embed(
        self, embed: dict[str, Any], components: list[dict[str, Any]] | None = None
    ) -> bool:
        """Support-inquiry notifications (escalation, approve/reply buttons,
        auto-resolution summaries) -- richer than a plain report string, so
        they get a real embed instead of _chunk_content()'s markdown text.
        Same never-raise contract as send().
        """
        if not self.enabled:
            return False
        payload: dict[str, Any] = {"embeds": [embed]}
        if components:
            payload["components"] = components
        try:
            response = httpx.post(self._webhook_url, json=payload, timeout=self._timeout)
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
