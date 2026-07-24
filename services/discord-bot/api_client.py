"""커머스 API의 /internal/discord/* 엔드포인트를 부르는 얇은 비동기 클라이언트.

봇은 DB에 직접 붙지 않는다. 모든 데이터(연동 상태, 플랜별 채널 스펙, 매출·
조회수 등 지표)를 이 클라이언트를 통해 커머스 API에서 받는다. 공유 비밀은
X-Internal-Token 헤더로 실어 보낸다(서버의 require_internal_token과 짝).
"""

from typing import Any

import httpx


class CommerceApiError(Exception):
    """커머스 API가 2xx가 아닌 응답을 줬을 때. message는 사용자에게 보여줄 안내."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CommerceClient:
    def __init__(self, base_url: str, shared_secret: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-Internal-Token": shared_secret}
        self._timeout = timeout

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(method, url, headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise CommerceApiError("커머스 서버에 연결하지 못했습니다.") from exc
        if response.status_code >= 400:
            detail = "요청을 처리하지 못했습니다."
            try:
                detail = response.json().get("detail", detail)
            except Exception:  # noqa: BLE001 - body may be empty/non-JSON
                pass
            raise CommerceApiError(detail, status_code=response.status_code)
        return response.json()

    async def link(self, guild_id: str, code: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/internal/discord/link", json={"guild_id": guild_id, "code": code}
        )

    async def org(self, guild_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", "/internal/discord/org", params={"guild_id": guild_id}
        )

    async def save_channels(
        self, guild_id: str, channels: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            "/internal/discord/channels",
            json={"guild_id": guild_id, "channels": channels},
        )

    async def metrics(
        self, guild_id: str, kind: str, *, period: str | None = None, date: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"guild_id": guild_id, "kind": kind}
        if period:
            params["period"] = period
        if date:
            params["date"] = date
        return await self._request("GET", "/internal/discord/metrics", params=params)
