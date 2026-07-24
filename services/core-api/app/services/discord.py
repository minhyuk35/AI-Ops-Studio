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
