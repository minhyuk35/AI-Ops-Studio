import httpx


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
        try:
            response = httpx.post(
                self._webhook_url,
                json={"content": content[:2000]},
                timeout=self._timeout,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False
