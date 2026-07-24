import httpx

from app.config import Settings


class DiscordNotifier:
    """Best-effort Discord webhook sender.

    Used to push sensitive-inquiry escalations and monthly reports out of
    the app. Never raises — a missing or unreachable webhook should not
    break the AI pipeline that triggered the notification.
    """

    def __init__(self, settings: Settings) -> None:
        self._webhook_url = settings.discord_webhook_url
        self._timeout = settings.discord_timeout_seconds

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
