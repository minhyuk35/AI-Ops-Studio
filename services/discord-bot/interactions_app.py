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

from api_client import CommerceApiError, CommerceClient
from discord_rest import DiscordApiError, DiscordRestClient
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from formatting import format_daily, format_revenue, format_status, format_stock, format_views
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from provisioning import provision_channels

PING = 1
APPLICATION_COMMAND = 2
PONG = 1
CHANNEL_MESSAGE_WITH_SOURCE = 4
DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5
MANAGE_GUILD_PERMISSION = 1 << 5

app = FastAPI()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


PUBLIC_KEY = _env("DISCORD_PUBLIC_KEY")
BOT_TOKEN = _env("DISCORD_BOT_TOKEN")
APPLICATION_ID = _env("DISCORD_APPLICATION_ID")
COMMERCE_API_BASE = _env("DISCORD_BOT_API_BASE", "http://localhost:8001")
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
            "AI 리포트는 노트북에서 이 웹훅으로 전송하세요.",
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


async def _handle_metric(interaction: dict, kind: str, formatter) -> dict:
    guild_id = str(interaction.get("guild_id") or "")
    if not guild_id:
        return _message("서버에서만 사용할 수 있습니다.")
    options = _options_map(interaction.get("data", {}))
    period = options.get("기간")
    date = options.get("날짜")
    try:
        data = await _commerce_client().metrics(guild_id, kind, period=period, date=date)
    except CommerceApiError as exc:
        hint = "\n먼저 `/실행` 을 실행하세요." if exc.status_code == 404 else ""
        return _message(f"❌ {exc}{hint}")
    return _message(formatter(data))


async def _handle_status(interaction: dict) -> dict:
    guild_id = str(interaction.get("guild_id") or "")
    if not guild_id:
        return _message("서버에서만 사용할 수 있습니다.")
    try:
        data = await _commerce_client().org(guild_id)
    except CommerceApiError as exc:
        return _message(f"❌ {exc}")
    return _message(format_status(data))


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

    if interaction_type != APPLICATION_COMMAND:
        return Response(content='{"type":1}', media_type="application/json")

    name = interaction.get("data", {}).get("name")
    handlers = {
        "수익": lambda: _handle_metric(interaction, "revenue", format_revenue),
        "조회수": lambda: _handle_metric(interaction, "views", format_views),
        "일일리포트": lambda: _handle_metric(interaction, "daily", format_daily),
        "재고": lambda: _handle_metric(interaction, "stock", format_stock),
        "연동상태": lambda: _handle_status(interaction),
    }

    if name == "실행":
        payload = _handle_execute(interaction, background_tasks)
    elif name in handlers:
        payload = await handlers[name]()
    else:
        payload = _message(f"❌ 알 수 없는 명령입니다: {name}")

    return Response(content=json.dumps(payload, ensure_ascii=False), media_type="application/json")
