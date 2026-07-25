"""Raw Discord REST API calls (httpx), no discord.py/Gateway involved.

bot.py's _provision_channels() does the same thing through discord.py's
Guild/Channel objects, which only exist once you're connected to the
Gateway. The HTTP Interactions path (interactions_app.py) never opens a
Gateway connection, so channel/category/webhook management here is done
with plain REST calls using the bot token -- Discord's REST API doesn't
require a Gateway session for any of this.
"""

from typing import Any

import httpx

API_BASE = "https://discord.com/api/v10"
CATEGORY_TYPE = 4
TEXT_CHANNEL_TYPE = 0


class DiscordApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DiscordRestClient:
    def __init__(self, bot_token: str, timeout: float = 15.0) -> None:
        self._headers = {"Authorization": f"Bot {bot_token}"}
        self._timeout = timeout

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{API_BASE}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.request(method, url, headers=self._headers, **kwargs)
        if response.status_code >= 400:
            raise DiscordApiError(
                f"Discord API {method} {path} -> {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def list_channels(self, guild_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/guilds/{guild_id}/channels")

    async def delete_channel(self, channel_id: str, *, reason: str = "") -> None:
        headers = {"X-Audit-Log-Reason": reason} if reason else {}
        try:
            await self._request("DELETE", f"/channels/{channel_id}", headers=headers)
        except DiscordApiError as exc:
            if exc.status_code != 404:
                raise

    async def create_category(
        self, guild_id: str, name: str, *, permission_overwrites: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/channels",
            json={
                "name": name,
                "type": CATEGORY_TYPE,
                "permission_overwrites": permission_overwrites,
            },
        )

    async def create_text_channel(
        self, guild_id: str, name: str, *, parent_id: str, topic: str = ""
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/guilds/{guild_id}/channels",
            json={
                "name": name,
                "type": TEXT_CHANNEL_TYPE,
                "parent_id": parent_id,
                "topic": topic[:1024],
            },
        )

    async def create_webhook(self, channel_id: str, *, name: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/channels/{channel_id}/webhooks", json={"name": name}
        )

    async def send_followup(
        self,
        application_id: str,
        interaction_token: str,
        content: str,
        *,
        ephemeral: bool = False,
    ) -> None:
        """Post the deferred reply -- interaction_token is valid for 15 minutes.
        ephemeral=True (flags 1<<6) makes it visible only to the seller who
        clicked the button/submitted the modal, not the whole channel."""
        payload: dict[str, Any] = {"content": content[:2000]}
        if ephemeral:
            payload["flags"] = 1 << 6
        await self._request(
            "POST",
            f"/webhooks/{application_id}/{interaction_token}",
            json=payload,
        )
