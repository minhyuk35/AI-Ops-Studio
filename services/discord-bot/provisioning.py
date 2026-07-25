"""Channel/webhook (re)provisioning for /실행, built on discord_rest.py.

Mirrors bot.py's _provision_channels() (used by the Gateway-based bot) but
through plain REST calls instead of discord.py's Guild/Channel objects, so
it works from interactions_app.py's HTTP-only handler (no Gateway
connection, so no discord.py guild/channel cache to operate on).
"""

from discord_rest import DiscordRestClient

VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
MANAGE_WEBHOOKS = 1 << 29


async def provision_channels(
    client: DiscordRestClient,
    *,
    guild_id: str,
    bot_user_id: str,
    category_name: str,
    plan_channels: list[dict],
    wipe_all: bool,
) -> list[dict]:
    existing = await client.list_channels(guild_id)

    if wipe_all:
        for channel in existing:
            await client.delete_channel(channel["id"], reason="AI Ops Studio /실행 전체초기화")
    else:
        managed_category = next(
            (c for c in existing if c.get("type") == 4 and c.get("name") == category_name),
            None,
        )
        if managed_category is not None:
            for channel in existing:
                if channel.get("parent_id") == managed_category["id"]:
                    await client.delete_channel(
                        channel["id"], reason="AI Ops Studio /실행 재생성"
                    )
            await client.delete_channel(
                managed_category["id"], reason="AI Ops Studio /실행 재생성"
            )

    category = await client.create_category(
        guild_id,
        category_name,
        permission_overwrites=[
            {
                "id": guild_id,  # @everyone role id == guild id
                "type": 0,
                "allow": str(VIEW_CHANNEL | SEND_MESSAGES),
                "deny": "0",
            },
            {
                "id": bot_user_id,
                "type": 1,
                "allow": str(VIEW_CHANNEL | MANAGE_WEBHOOKS),
                "deny": "0",
            },
        ],
    )

    stored: list[dict] = []
    for spec in plan_channels:
        name = str(spec.get("name") or spec.get("channel_key"))
        topic = str(spec.get("topic") or "")
        channel = await client.create_text_channel(
            guild_id, name, parent_id=category["id"], topic=topic
        )
        webhook = await client.create_webhook(channel["id"], name="AI Ops Studio")
        webhook_url = f"https://discord.com/api/webhooks/{webhook['id']}/{webhook['token']}"
        stored.append(
            {
                "channel_key": spec.get("channel_key"),
                "channel_id": str(channel["id"]),
                "channel_name": name,
                "webhook_url": webhook_url,
                "persona": spec.get("persona"),
            }
        )
    return stored


async def sync_missing_channels(
    client: DiscordRestClient,
    *,
    guild_id: str,
    bot_user_id: str,
    category_name: str,
    plan_channels: list[dict],
    existing_channels: list[dict],
) -> list[dict]:
    """/업데이트: adds channels newly unlocked by a plan upgrade (or newly
    added to discord_spec.CHANNEL_SPECS entirely, e.g. 주문-알림) without
    touching anything that already exists -- unlike /실행, which always
    wipes and rebuilds the whole managed category from scratch. Returns the
    full channel list (existing + newly added) ready to save via
    PUT /internal/discord/channels.
    """
    existing_keys = {channel.get("channel_key") for channel in existing_channels}
    missing = [spec for spec in plan_channels if spec.get("channel_key") not in existing_keys]
    if not missing:
        return existing_channels

    guild_channels = await client.list_channels(guild_id)
    category = next(
        (c for c in guild_channels if c.get("type") == 4 and c.get("name") == category_name),
        None,
    )
    if category is None:
        category = await client.create_category(
            guild_id,
            category_name,
            permission_overwrites=[
                {
                    "id": guild_id,
                    "type": 0,
                    "allow": str(VIEW_CHANNEL | SEND_MESSAGES),
                    "deny": "0",
                },
                {
                    "id": bot_user_id,
                    "type": 1,
                    "allow": str(VIEW_CHANNEL | MANAGE_WEBHOOKS),
                    "deny": "0",
                },
            ],
        )

    added: list[dict] = []
    for spec in missing:
        name = str(spec.get("name") or spec.get("channel_key"))
        topic = str(spec.get("topic") or "")
        channel = await client.create_text_channel(
            guild_id, name, parent_id=category["id"], topic=topic
        )
        webhook = await client.create_webhook(channel["id"], name="AI Ops Studio")
        webhook_url = f"https://discord.com/api/webhooks/{webhook['id']}/{webhook['token']}"
        added.append(
            {
                "channel_key": spec.get("channel_key"),
                "channel_id": str(channel["id"]),
                "channel_name": name,
                "webhook_url": webhook_url,
                "persona": spec.get("persona"),
            }
        )
    return existing_channels + added
