"""AI Ops Studio 판매자 연동 Discord 봇 (독립 실행, discord.py 2.x).

판매자가 자기 Discord 서버에 초대해서 쓰는 봇이다. 상시 실행(Gateway)되며
아래 슬래시 명령을 제공한다:

  /연동 <코드>     판매자 콘솔에서 발급받은 코드로 이 서버를 상점에 연결
  /생성            판매자 플랜에 맞는 카테고리·채널을 (재)생성하고 채널마다
                   웹훅을 만들어 사이트에 저장 — 실제 AI 리포트 발신은 노트북이
                   이 웹훅 URL로 담당한다(요구사항: "AI는 내 노트북에서")
  /수익 [기간]     이 상점의 월 매출 요약
  /조회수 [날짜]   이 상점의 오늘 상품 조회수
  /일일리포트 [날짜] 오늘의 조회·판매·환불·재고 스냅샷(코드 집계 숫자)
  /재고            품절·재고 임박 상품
  /연동상태        연동 여부와 생성된 채널 목록

봇은 DB에 직접 붙지 않고 커머스 API의 /internal/discord/* 만 호출한다
(api_client.CommerceClient). 실행에 필요한 환경변수는 README.md 참고.
"""

from __future__ import annotations

import logging
import os

import discord
from api_client import CommerceApiError, CommerceClient
from discord import app_commands
from formatting import (
    format_daily,
    format_revenue,
    format_status,
    format_stock,
    format_views,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ai-ops-bot")

# 봇이 채널에 남기는 웹훅 이름(사이트 노트북 AI가 이 이름으로 만든 웹훅을 쓴다).
WEBHOOK_NAME = "AI Ops Studio"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


class BotConfig:
    def __init__(self) -> None:
        self.token = _env("DISCORD_BOT_TOKEN")
        self.api_base = _env("DISCORD_BOT_API_BASE", "http://localhost:8001")
        self.shared_secret = _env("DISCORD_BOT_SHARED_SECRET")
        self.dev_guild_id = _env("DISCORD_DEV_GUILD_ID")

    def require(self) -> None:
        missing = [
            key
            for key, value in {
                "DISCORD_BOT_TOKEN": self.token,
                "DISCORD_BOT_SHARED_SECRET": self.shared_secret,
            }.items()
            if not value
        ]
        if missing:
            raise SystemExit(
                "필수 환경변수가 없습니다: " + ", ".join(missing) + " (.env 참고)"
            )


class AiOpsBot(discord.Client):
    def __init__(self, config: BotConfig) -> None:
        # 채널/웹훅 관리를 위해 guilds 인텐트만 있으면 된다(메시지 내용 인텐트 불필요).
        super().__init__(intents=discord.Intents.default())
        self.config = config
        self.api = CommerceClient(config.api_base, config.shared_secret)
        self.tree = app_commands.CommandTree(self)
        register_commands(self)

    async def setup_hook(self) -> None:
        # 개발용 길드가 지정되면 그 서버에만 즉시 등록(전역은 반영에 최대 1시간).
        if self.config.dev_guild_id:
            guild = discord.Object(id=int(self.config.dev_guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("dev 길드 %s 에 슬래시 명령 동기화", self.config.dev_guild_id)
        else:
            await self.tree.sync()
            log.info("전역 슬래시 명령 동기화(반영에 최대 1시간)")

    async def on_ready(self) -> None:
        log.info("로그인: %s (id=%s)", self.user, getattr(self.user, "id", "?"))

    async def on_guild_join(self, guild: discord.Guild) -> None:
        channel = guild.system_channel or next(
            (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
            None,
        )
        if channel is not None:
            await channel.send(
                "👋 **AI Ops Studio 봇**을 초대해주셔서 감사합니다!\n"
                "1) 판매자 콘솔에서 **연동 코드**를 발급받은 뒤\n"
                "2) 이 서버에서 `/연동 코드:<발급코드>` 를 입력하고\n"
                "3) `/생성` 을 실행하면 플랜에 맞는 채널과 웹훅이 자동으로 만들어집니다."
            )


async def _guild_id_str(interaction: discord.Interaction) -> str:
    assert interaction.guild_id is not None
    return str(interaction.guild_id)


def register_commands(bot: AiOpsBot) -> None:
    tree = bot.tree

    @tree.command(name="연동", description="발급받은 코드로 이 서버를 상점에 연결합니다.")
    @app_commands.describe(코드="판매자 콘솔에서 발급받은 연동 코드")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def link(interaction: discord.Interaction, 코드: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            data = await bot.api.link(await _guild_id_str(interaction), 코드.strip().upper())
        except CommerceApiError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ **{data.get('org_name', '상점')}** 연동 완료! 요금제: **{data.get('plan')}**\n"
            "이제 `/생성` 을 실행해 채널을 만드세요.",
            ephemeral=True,
        )

    @tree.command(name="생성", description="플랜에 맞는 카테고리·채널·웹훅을 (재)생성합니다.")
    @app_commands.describe(전체초기화="봇 카테고리 외 다른 채널까지 모두 삭제 후 재생성(주의)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def provision(interaction: discord.Interaction, 전체초기화: bool = False) -> None:
        await interaction.response.defer()
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("서버에서만 사용할 수 있습니다.")
            return
        try:
            org = await bot.api.org(await _guild_id_str(interaction))
        except CommerceApiError as exc:
            await interaction.followup.send(f"❌ {exc}\n먼저 `/연동` 을 실행하세요.")
            return

        category_name = str(org.get("category_name") or "AI OPS STUDIO")
        plan_channels = org.get("plan_channels") or []
        try:
            stored = await _provision_channels(
                guild, category_name, plan_channels, wipe_all=전체초기화
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ 권한이 부족합니다. 봇에 **채널 관리**와 **웹훅 관리** 권한을 주세요."
            )
            return

        await bot.api.save_channels(await _guild_id_str(interaction), stored)
        summary = "\n".join(
            f"· #{c['channel_name']}"
            + (f" — `{c['persona']}` 페르소나" if c.get("persona") else " — 봇 명령용")
            for c in stored
        )
        shop = org.get("org_name", "상점")
        header = f"✅ **{shop}**({org.get('plan')}) 채널 {len(stored)}개 생성 완료"
        await interaction.followup.send(
            f"{header}\n{summary}\n\n각 채널에 웹훅을 만들어 사이트에 저장했습니다. "
            "AI 리포트는 노트북에서 이 웹훅으로 전송하세요."
        )

    @tree.command(name="수익", description="이 상점의 월 매출 요약을 조회합니다.")
    @app_commands.describe(기간="YYYY-MM (비우면 이번 달)")
    async def revenue(interaction: discord.Interaction, 기간: str | None = None) -> None:
        await _metric_reply(bot, interaction, "revenue", format_revenue, period=기간)

    @tree.command(name="조회수", description="오늘(또는 지정일) 상품 조회수를 조회합니다.")
    @app_commands.describe(날짜="YYYY-MM-DD (비우면 오늘)")
    async def views(interaction: discord.Interaction, 날짜: str | None = None) -> None:
        await _metric_reply(bot, interaction, "views", format_views, date=날짜)

    @tree.command(name="일일리포트", description="오늘의 조회·판매·환불·재고 스냅샷.")
    @app_commands.describe(날짜="YYYY-MM-DD (비우면 오늘)")
    async def daily(interaction: discord.Interaction, 날짜: str | None = None) -> None:
        await _metric_reply(bot, interaction, "daily", format_daily, date=날짜)

    @tree.command(name="재고", description="품절·재고 임박 상품을 조회합니다.")
    async def stock(interaction: discord.Interaction) -> None:
        await _metric_reply(bot, interaction, "stock", format_stock)

    @tree.command(name="연동상태", description="연동 여부와 생성된 채널을 확인합니다.")
    async def status(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            data = await bot.api.org(await _guild_id_str(interaction))
        except CommerceApiError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        await interaction.followup.send(format_status(data), ephemeral=True)

    @tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "❌ 이 명령은 **서버 관리** 권한이 필요합니다."
        else:
            log.exception("명령 처리 오류", exc_info=error)
            message = "❌ 처리 중 오류가 발생했습니다."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def _metric_reply(bot, interaction, kind, formatter, *, period=None, date=None) -> None:
    await interaction.response.defer()
    try:
        data = await bot.api.metrics(
            await _guild_id_str(interaction), kind, period=period, date=date
        )
    except CommerceApiError as exc:
        hint = "\n먼저 `/연동` 을 실행하세요." if exc.status_code == 404 else ""
        await interaction.followup.send(f"❌ {exc}{hint}")
        return
    await interaction.followup.send(formatter(data))


async def _provision_channels(
    guild: discord.Guild,
    category_name: str,
    plan_channels: list[dict],
    *,
    wipe_all: bool,
) -> list[dict]:
    """봇 관리 카테고리를 지우고 플랜에 맞춰 다시 만든 뒤, 채널마다 웹훅 생성.

    기본값(wipe_all=False)은 봇이 관리하는 카테고리(category_name)와 그 하위
    채널만 초기화하므로 판매자가 따로 만든 다른 채널은 건드리지 않는다.
    wipe_all=True면 삭제 가능한 모든 카테고리/채널을 지워 완전히 새 서버처럼
    재구성한다(디스코드 샘플링 서버 용도).
    """
    me = guild.me

    if wipe_all:
        for channel in list(guild.channels):
            try:
                await channel.delete(reason="AI Ops Studio /생성 전체초기화")
            except (discord.Forbidden, discord.HTTPException):
                continue
    else:
        for category in list(guild.categories):
            if category.name == category_name:
                for channel in list(category.channels):
                    await channel.delete(reason="AI Ops Studio /생성 재생성")
                await category.delete(reason="AI Ops Studio /생성 재생성")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        me: discord.PermissionOverwrite(view_channel=True, manage_webhooks=True),
    }
    category = await guild.create_category(category_name, overwrites=overwrites)

    stored: list[dict] = []
    for spec in plan_channels:
        name = str(spec.get("name") or spec.get("channel_key"))
        topic = str(spec.get("topic") or "")
        channel = await guild.create_text_channel(name, category=category, topic=topic)
        webhook = await channel.create_webhook(name=WEBHOOK_NAME)
        stored.append(
            {
                "channel_key": spec.get("channel_key"),
                "channel_id": str(channel.id),
                "channel_name": name,
                "webhook_url": webhook.url,
                "persona": spec.get("persona"),
            }
        )
    return stored


def _load_env() -> None:
    """저장소 루트의 .env를 읽어 환경변수로 올린다(있으면). 없어도 조용히 넘어간다."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root_env = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    load_dotenv(root_env)


def main() -> None:
    _load_env()
    config = BotConfig()
    config.require()
    bot = AiOpsBot(config)
    bot.run(config.token)


if __name__ == "__main__":
    main()
