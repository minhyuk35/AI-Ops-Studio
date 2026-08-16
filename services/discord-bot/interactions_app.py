"""Discord HTTP Interactions endpoint (no Gateway connection).

bot.py runs discord.py's Gateway client -- a persistent WebSocket that has
to stay open to receive slash-command interactions, which cannot run
inside a Vercel Function (serverless functions only exist for the
duration of one request; there's nowhere for a persistent connection to
live between invocations). Discord's alternative is HTTP Interactions:
register an "Interactions Endpoint URL" in the Developer Portal instead of
relying on the Gateway, and Discord POSTs each slash-command invocation to
that URL directly, which is just an ordinary HTTP request/response --
exactly what a Vercel Function is built for.

Trade-off: this path has no Gateway session, so Gateway-only events like
on_guild_join (bot.py's welcome message when invited to a new server)
don't exist here -- the site's seller console already walks through the
same 3-step setup, so this isn't a functional gap, just a missing nicety.

Setup required in the Discord Developer Portal (manual, one-time):
  1. General Information > Interactions Endpoint URL =
     https://<배포 도메인>/api/discord
     Discord sends a PING here immediately and only saves the URL if this
     app answers it correctly (see verify_signature below) -- deploy this
     file first, then set the URL.
  2. General Information > Public Key -> DISCORD_PUBLIC_KEY in .env /
     Vercel env vars (this is DIFFERENT from DISCORD_BOT_TOKEN).
  3. Run `python register_commands.py` once (or after changing a command's
     name/options) to register the slash commands globally -- interaction
     handling and command *registration* are separate Discord APIs.
"""

from __future__ import annotations

import json
import os

import httpx
from api_client import CommerceApiError, CommerceClient
from discord_rest import DiscordApiError, DiscordRestClient
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from formatting import format_daily, format_revenue, format_status, format_stock, format_views
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from provisioning import provision_channels, sync_missing_channels

PING = 1
APPLICATION_COMMAND = 2
MESSAGE_COMPONENT = 3
MODAL_SUBMIT = 5
PONG = 1
CHANNEL_MESSAGE_WITH_SOURCE = 4
DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5
MODAL = 9
EPHEMERAL = 1 << 6
MANAGE_GUILD_PERMISSION = 1 << 5

app = FastAPI()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


PUBLIC_KEY = _env("DISCORD_PUBLIC_KEY")
BOT_TOKEN = _env("DISCORD_BOT_TOKEN")
APPLICATION_ID = _env("DISCORD_APPLICATION_ID")
COMMERCE_API_BASE = _env("DISCORD_BOT_API_BASE", "http://localhost:8001")


def _default_core_api_base() -> str:
    """core-api owns the inquiries endpoints (문의 승인/답변) -- a separate
    base from COMMERCE_API_BASE, but in production both live under the same
    Vercel deployment (see vercel.json), so derive it from
    DISCORD_BOT_API_BASE rather than requiring yet another env var to be
    set by hand: .../api/commerce -> .../api/core.
    """
    if COMMERCE_API_BASE.endswith("/api/commerce"):
        return COMMERCE_API_BASE[: -len("/api/commerce")] + "/api/core"
    return "http://localhost:8000"


CORE_API_BASE = _env("DISCORD_BOT_CORE_API_BASE") or _default_core_api_base()
SHARED_SECRET = _env("DISCORD_BOT_SHARED_SECRET")
CATEGORY_NAME = "AI OPS STUDIO"


def _commerce_client() -> CommerceClient:
    return CommerceClient(COMMERCE_API_BASE, SHARED_SECRET)


def _options_map(data: dict) -> dict[str, object]:
    return {opt["name"]: opt.get("value") for opt in data.get("options", [])}


def _has_manage_guild(interaction: dict) -> bool:
    member = interaction.get("member") or {}
    try:
        permissions = int(member.get("permissions", "0"))
    except (TypeError, ValueError):
        return False
    return bool(permissions & MANAGE_GUILD_PERMISSION)


def _message(content: str, *, response_type: int = CHANNEL_MESSAGE_WITH_SOURCE) -> dict:
    return {"type": response_type, "data": {"content": content}}


async def _run_execute_and_followup(
    guild_id: str, code: str | None, wipe_all: bool, interaction_token: str
) -> None:
    """Runs after the deferred ack is sent -- does the actual /실행 work and
    posts the real result via the interaction's followup webhook. See the
    docstring on _handle_execute for why this has to be deferred at all.
    interaction_token is passed explicitly (not read from shared state) so
    two concurrent /실행 invocations on a warm, request-sharing instance
    (Vercel Fluid compute's "optimized concurrency") can't cross-post each
    other's results.
    """
    rest = DiscordRestClient(BOT_TOKEN)
    commerce = _commerce_client()
    try:
        try:
            org = await commerce.org(guild_id)
        except CommerceApiError as exc:
            if exc.status_code != 404:
                await rest.send_followup(APPLICATION_ID, interaction_token, f"❌ {exc}")
                return
            if not code:
                await rest.send_followup(
                    APPLICATION_ID,
                    interaction_token,
                    "❌ 아직 연동되지 않은 서버입니다. 판매자 콘솔에서 발급받은 연동 코드를 "
                    "`코드:` 옵션에 넣어 `/실행 코드:<코드>` 로 다시 실행해주세요.",
                )
                return
            try:
                await commerce.link(guild_id, code.strip().upper())
                org = await commerce.org(guild_id)
            except CommerceApiError as link_exc:
                await rest.send_followup(APPLICATION_ID, interaction_token, f"❌ {link_exc}")
                return

        category_name = str(org.get("category_name") or CATEGORY_NAME)
        plan_channels = org.get("plan_channels") or []
        # The bot's own user id equals its application id for a standard
        # single-bot application -- used for the category's permission
        # overwrite so the bot can manage webhooks in channels it creates.
        stored = await provision_channels(
            rest,
            guild_id=guild_id,
            bot_user_id=APPLICATION_ID,
            category_name=category_name,
            plan_channels=plan_channels,
            wipe_all=wipe_all,
        )
        await commerce.save_channels(guild_id, stored)
        summary = "\n".join(
            f"· #{c['channel_name']}"
            + (f" — `{c['persona']}` 페르소나" if c.get("persona") else " — 봇 명령용")
            for c in stored
        )
        shop = org.get("org_name", "상점")
        await rest.send_followup(
            APPLICATION_ID,
            interaction_token,
            f"✅ **{shop}** 세팅이 완료되었습니다!\n{summary}\n\n"
            "각 채널에 웹훅을 만들어 사이트에 저장했습니다. "
            "일일 리포트와 문의 이관 알림이 이제 이 채널들로 자동 전송됩니다.",
        )
    except DiscordApiError as exc:
        await rest.send_followup(
            APPLICATION_ID,
            interaction_token,
            f"❌ 권한 또는 API 오류: {exc}\n봇에 **채널 관리**와 **웹훅 관리** 권한을 주세요.",
        )


def _handle_execute(interaction: dict, background_tasks: BackgroundTasks) -> dict:
    if not _has_manage_guild(interaction):
        return _message("❌ 이 명령은 **서버 관리** 권한이 필요합니다.")
    guild_id = str(interaction.get("guild_id") or "")
    if not guild_id:
        return _message("서버에서만 사용할 수 있습니다.")
    options = _options_map(interaction.get("data", {}))
    code = options.get("코드")
    wipe_all = bool(options.get("전체초기화", False))
    background_tasks.add_task(
        _run_execute_and_followup, guild_id, code, wipe_all, interaction["token"]
    )
    return {"type": DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE}


async def _run_update_and_followup(guild_id: str, interaction_token: str) -> None:
    """/업데이트: unlike /실행, never wipes anything -- only adds channels
    the org's current plan unlocks but doesn't have yet (a plan upgrade, or
    a channel type added to discord_spec.CHANNEL_SPECS after the seller
    already ran /실행 once, e.g. 주문-알림)."""
    rest = DiscordRestClient(BOT_TOKEN)
    commerce = _commerce_client()
    try:
        org = await commerce.org(guild_id)
    except CommerceApiError as exc:
        hint = "\n먼저 `/실행`을 실행하세요." if exc.status_code == 404 else ""
        await rest.send_followup(APPLICATION_ID, interaction_token, f"❌ {exc}{hint}")
        return

    plan_channels = org.get("plan_channels") or []
    existing_channels = org.get("channels") or []
    existing_keys = {c.get("channel_key") for c in existing_channels}
    missing = [c for c in plan_channels if c.get("channel_key") not in existing_keys]
    if not missing:
        await rest.send_followup(
            APPLICATION_ID, interaction_token, "✅ 이미 최신 상태입니다 — 추가할 채널이 없습니다."
        )
        return

    try:
        category_name = str(org.get("category_name") or CATEGORY_NAME)
        updated = await sync_missing_channels(
            rest,
            guild_id=guild_id,
            bot_user_id=APPLICATION_ID,
            category_name=category_name,
            plan_channels=plan_channels,
            existing_channels=existing_channels,
        )
        await commerce.save_channels(guild_id, updated)
        added_names = ", ".join(f"#{c['name']}" for c in missing)
        await rest.send_followup(
            APPLICATION_ID, interaction_token, f"✅ 새 채널이 추가됐습니다: {added_names}"
        )
    except DiscordApiError as exc:
        await rest.send_followup(
            APPLICATION_ID,
            interaction_token,
            f"❌ 권한 또는 API 오류: {exc}\n봇에 **채널 관리**와 **웹훅 관리** 권한을 주세요.",
        )


def _handle_update(interaction: dict, background_tasks: BackgroundTasks) -> dict:
    if not _has_manage_guild(interaction):
        return _message("❌ 이 명령은 **서버 관리** 권한이 필요합니다.")
    guild_id = str(interaction.get("guild_id") or "")
    if not guild_id:
        return _message("서버에서만 사용할 수 있습니다.")
    background_tasks.add_task(_run_update_and_followup, guild_id, interaction["token"])
    return {"type": DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE}


async def _run_metric_and_followup(
    guild_id: str, kind: str, formatter, period: str | None, date: str | None,
    interaction_token: str,
) -> None:
    """Runs after the deferred ack -- see _handle_metric for why this can't
    respond synchronously: it calls mock-commerce-api (a separate Vercel
    function, its own possible cold start) and for kind="daily" that call
    itself triggers an OpenRouter completion -- easily past Discord's 3s
    initial-response budget even when nothing is actually broken."""
    rest = DiscordRestClient(BOT_TOKEN)
    try:
        data = await _commerce_client().metrics(guild_id, kind, period=period, date=date)
    except CommerceApiError as exc:
        hint = "\n먼저 `/실행` 을 실행하세요." if exc.status_code == 404 else ""
        await rest.send_followup(APPLICATION_ID, interaction_token, f"❌ {exc}{hint}")
        return
    await rest.send_followup(APPLICATION_ID, interaction_token, formatter(data))


def _handle_metric(
    interaction: dict, kind: str, formatter, background_tasks: BackgroundTasks
) -> dict:
    guild_id = str(interaction.get("guild_id") or "")
    if not guild_id:
        return _message("서버에서만 사용할 수 있습니다.")
    options = _options_map(interaction.get("data", {}))
    period = options.get("기간")
    date = options.get("날짜")
    background_tasks.add_task(
        _run_metric_and_followup, guild_id, kind, formatter, period, date, interaction["token"]
    )
    return {"type": DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE}


async def _run_status_and_followup(guild_id: str, interaction_token: str) -> None:
    """Runs after the deferred ack -- see _handle_metric's docstring; the
    same cross-function-call latency risk applies here."""
    rest = DiscordRestClient(BOT_TOKEN)
    try:
        data = await _commerce_client().org(guild_id)
    except CommerceApiError as exc:
        await rest.send_followup(APPLICATION_ID, interaction_token, f"❌ {exc}")
        return
    await rest.send_followup(APPLICATION_ID, interaction_token, format_status(data))


def _handle_status(interaction: dict, background_tasks: BackgroundTasks) -> dict:
    guild_id = str(interaction.get("guild_id") or "")
    if not guild_id:
        return _message("서버에서만 사용할 수 있습니다.")
    background_tasks.add_task(_run_status_and_followup, guild_id, interaction["token"])
    return {"type": DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE}


def _reply_modal(inquiry_id: str) -> dict:
    return {
        "type": MODAL,
        "data": {
            "custom_id": f"reply_modal:{inquiry_id}",
            "title": "고객에게 답변 보내기",
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 4,
                            "custom_id": "reply_text",
                            "style": 2,
                            "label": "답변 내용",
                            "min_length": 1,
                            "max_length": 1000,
                            "required": True,
                        }
                    ],
                }
            ],
        },
    }


def _handle_component(interaction: dict, background_tasks: BackgroundTasks) -> dict:
    custom_id = str(interaction.get("data", {}).get("custom_id") or "")
    kind, _, inquiry_id = custom_id.partition(":")
    if not inquiry_id:
        return _message("❌ 알 수 없는 버튼입니다.", response_type=CHANNEL_MESSAGE_WITH_SOURCE)
    if kind == "reply":
        return _reply_modal(inquiry_id)
    if kind == "approve":
        background_tasks.add_task(_run_approve_and_followup, inquiry_id, interaction["token"])
        return {
            "type": DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE,
            "data": {"flags": EPHEMERAL},
        }
    return _message("❌ 알 수 없는 버튼입니다.", response_type=CHANNEL_MESSAGE_WITH_SOURCE)


def _extract_modal_value(interaction: dict, custom_id: str) -> str:
    for row in interaction.get("data", {}).get("components", []):
        for component in row.get("components", []):
            if component.get("custom_id") == custom_id:
                return str(component.get("value", ""))
    return ""


def _handle_modal_submit(interaction: dict, background_tasks: BackgroundTasks) -> dict:
    custom_id = str(interaction.get("data", {}).get("custom_id") or "")
    kind, _, inquiry_id = custom_id.partition(":")
    if kind != "reply_modal" or not inquiry_id:
        return _message("❌ 처리할 수 없는 제출입니다.", response_type=CHANNEL_MESSAGE_WITH_SOURCE)
    reply_text = _extract_modal_value(interaction, "reply_text").strip()
    if not reply_text:
        return _message("❌ 답변 내용을 입력해주세요.", response_type=CHANNEL_MESSAGE_WITH_SOURCE)
    background_tasks.add_task(
        _run_reply_and_followup, inquiry_id, reply_text, interaction["token"]
    )
    return {"type": DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE, "data": {"flags": EPHEMERAL}}


async def _run_approve_and_followup(inquiry_id: str, interaction_token: str) -> None:
    """POST /api/v1/inquiries/{id}/approve on core-api -- accepts the AI's
    proposed answer as final, and for a CANCEL-category inquiry tied to an
    order, actually executes that cancellation (see the endpoint's own
    docstring). Protected by the same shared secret as every other bot ->
    server call, since unlike a reply this can mutate a real order.
    """
    rest = DiscordRestClient(BOT_TOKEN)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{CORE_API_BASE}/api/v1/inquiries/{inquiry_id}/approve",
                headers={"X-Internal-Token": SHARED_SECRET},
            )
            response.raise_for_status()
            data = response.json()
        action = data.get("action")
        text = (
            "✅ 승인 처리되었습니다 — 주문이 취소·환불 처리되었습니다."
            if action == "CANCELLED"
            else "✅ 승인 처리되었습니다 — 문의가 해결됨으로 표시되었습니다."
        )
        await rest.send_followup(APPLICATION_ID, interaction_token, text, ephemeral=True)
    except httpx.HTTPError as exc:
        await rest.send_followup(
            APPLICATION_ID, interaction_token, f"❌ 승인 처리에 실패했습니다: {exc}", ephemeral=True
        )


async def _run_reply_and_followup(inquiry_id: str, reply_text: str, interaction_token: str) -> None:
    """PATCH /api/v1/inquiries/{id} on core-api -- appends the seller's own
    reply to the inquiry (role "agent") and marks it resolved. The customer
    sees it appear in their own 문의 내역 chat panel (polls every 5s)."""
    rest = DiscordRestClient(BOT_TOKEN)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.patch(
                f"{CORE_API_BASE}/api/v1/inquiries/{inquiry_id}",
                json={"status": "RESOLVED", "note": reply_text},
            )
            response.raise_for_status()
        await rest.send_followup(
            APPLICATION_ID, interaction_token, "✅ 고객에게 답변을 전송했습니다.", ephemeral=True
        )
    except httpx.HTTPError as exc:
        await rest.send_followup(
            APPLICATION_ID, interaction_token, f"❌ 답변 전송에 실패했습니다: {exc}", ephemeral=True
        )


def verify_signature(signature: str | None, timestamp: str | None, body: bytes) -> bool:
    if not signature or not timestamp or not PUBLIC_KEY:
        return False
    try:
        VerifyKey(bytes.fromhex(PUBLIC_KEY)).verify(
            timestamp.encode() + body, bytes.fromhex(signature)
        )
        return True
    except (BadSignatureError, ValueError):
        return False


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "discord-interactions"}


@app.post("/")
async def interactions(request: Request, background_tasks: BackgroundTasks) -> Response:
    body = await request.body()
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")
    if not verify_signature(signature, timestamp, body):
        raise HTTPException(status_code=401, detail="invalid request signature")

    interaction = await request.json()
    interaction_type = interaction.get("type")

    if interaction_type == PING:
        return Response(content='{"type":1}', media_type="application/json")

    if interaction_type == MESSAGE_COMPONENT:
        payload = _handle_component(interaction, background_tasks)
        body_out = json.dumps(payload, ensure_ascii=False)
        return Response(content=body_out, media_type="application/json")

    if interaction_type == MODAL_SUBMIT:
        payload = _handle_modal_submit(interaction, background_tasks)
        body_out = json.dumps(payload, ensure_ascii=False)
        return Response(content=body_out, media_type="application/json")

    if interaction_type != APPLICATION_COMMAND:
        return Response(content='{"type":1}', media_type="application/json")

    name = interaction.get("data", {}).get("name")
    metric_handlers = {
        "수익": ("revenue", format_revenue),
        "조회수": ("views", format_views),
        "일일리포트": ("daily", format_daily),
        "재고": ("stock", format_stock),
    }

    if name == "실행":
        payload = _handle_execute(interaction, background_tasks)
    elif name == "업데이트":
        payload = _handle_update(interaction, background_tasks)
    elif name in metric_handlers:
        kind, formatter = metric_handlers[name]
        payload = _handle_metric(interaction, kind, formatter, background_tasks)
    elif name == "연동상태":
        payload = _handle_status(interaction, background_tasks)
    else:
        payload = _message(f"❌ 알 수 없는 명령입니다: {name}")

    return Response(content=json.dumps(payload, ensure_ascii=False), media_type="application/json")
