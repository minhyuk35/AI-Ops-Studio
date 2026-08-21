import asyncio
import calendar
import logging
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.services.commerce_ai import (
    PlatformTrafficService,
    SellerDailyReportService,
    SellerMarketShareService,
)
from app.services.commerce_client import CommerceClient
from app.services.discord import DiscordNotifier, build_daily_revenue_chart_url

logger = logging.getLogger(__name__)


def _seconds_until_daily(hour_utc: int) -> float:
    now = datetime.now(UTC)
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _seconds_until_monthly(day_utc: int, hour_utc: int) -> float:
    now = datetime.now(UTC)
    last_day_this_month = calendar.monthrange(now.year, now.month)[1]
    target = now.replace(
        day=min(day_utc, last_day_this_month), hour=hour_utc, minute=0, second=0, microsecond=0
    )
    if target <= now:
        next_month = now.month + 1 if now.month < 12 else 1
        next_year = now.year if now.month < 12 else now.year + 1
        last_day_next_month = calendar.monthrange(next_year, next_month)[1]
        target = now.replace(
            year=next_year,
            month=next_month,
            day=min(day_utc, last_day_next_month),
            hour=hour_utc,
            minute=0,
            second=0,
            microsecond=0,
        )
    return (target - now).total_seconds()


class DailySellerReportScheduler:
    """Runs the daily-seller-report persona for every active seller, once a day.

    A plain asyncio background task rather than a task-queue dependency —
    this is a single-process demo service, so a loop that sleeps until the
    next scheduled UTC hour and then walks every active org is enough, and
    it reads start-to-finish without extra infrastructure. Failures for one
    seller are logged and skipped rather than aborting the whole run.
    """

    def __init__(
        self,
        settings: Settings,
        commerce: CommerceClient,
        report_service: SellerDailyReportService,
    ) -> None:
        self.settings = settings
        self.commerce = commerce
        self.report_service = report_service
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run_forever())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _run_forever(self) -> None:
        while True:
            await asyncio.sleep(_seconds_until_daily(self.settings.daily_report_hour_utc))
            try:
                await self.run_once()
            except Exception:
                logger.exception("daily seller report run failed")

    async def run_once(self) -> list[dict[str, object]]:
        """Generate + (if linked) send today's report for every active seller.

        Each org's own "일일-리포트" channel webhook, looked up by org_id --
        never a single fixed webhook, or every seller's report would land in
        the same (someone else's, or the platform's dev/test) channel.
        """
        orgs = await self.commerce.list_active_organizations()
        results: list[dict[str, object]] = []
        for org in orgs:
            try:
                snapshot = await self.commerce.get_seller_daily_snapshot(org["id"], None)
                report = await asyncio.to_thread(self.report_service.generate_report, snapshot)
                sent = False
                webhook_url = await self.commerce.get_org_discord_webhook(org["id"], "daily")
                if webhook_url:
                    notifier = DiscordNotifier(webhook_url, self.settings.discord_timeout_seconds)
                    header = f"**{report.org_name} · {report.date} 일일 리포트**"
                    message = f"{header}\n\n{report.report}"
                    series = await self.commerce.get_seller_daily_series(org["id"], days=14)
                    chart_url = build_daily_revenue_chart_url(
                        series, title=f"{report.org_name} 최근 14일 매출 추이"
                    )
                    sent = await asyncio.to_thread(notifier.send_with_chart, message, chart_url)
                results.append({"org_id": org["id"], "discord_sent": sent})
            except Exception:
                logger.exception("daily seller report failed for org %s", org["id"])
        return results


class PlatformTrafficScheduler:
    """Runs the platform-daily-traffic persona once a day, admin Discord only.

    Deliberately a separate scheduler (and a separate, admin-only Discord
    webhook) from DailySellerReportScheduler — site-wide traffic is not data
    any single seller should receive.
    """

    def __init__(
        self,
        settings: Settings,
        commerce: CommerceClient,
        report_service: PlatformTrafficService,
        notifier: DiscordNotifier,
    ) -> None:
        self.settings = settings
        self.commerce = commerce
        self.report_service = report_service
        self.notifier = notifier
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run_forever())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _run_forever(self) -> None:
        while True:
            hour = self.settings.platform_traffic_report_hour_utc
            await asyncio.sleep(_seconds_until_daily(hour))
            try:
                await self.run_once()
            except Exception:
                logger.exception("platform daily traffic report run failed")

    async def run_once(self) -> bool:
        snapshot = await self.commerce.get_platform_daily_traffic(None)
        report = await asyncio.to_thread(self.report_service.generate_report, snapshot)
        if not self.notifier.enabled:
            return False
        message = f"**{report.date} 플랫폼 트래픽 리포트**\n\n{report.report}"
        return await asyncio.to_thread(self.notifier.send, message)


class SellerMarketShareScheduler:
    """Runs the seller-market-share-report persona once a month, admin Discord only."""

    def __init__(
        self,
        settings: Settings,
        commerce: CommerceClient,
        report_service: SellerMarketShareService,
        notifier: DiscordNotifier,
    ) -> None:
        self.settings = settings
        self.commerce = commerce
        self.report_service = report_service
        self.notifier = notifier
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run_forever())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _run_forever(self) -> None:
        while True:
            seconds = _seconds_until_monthly(
                self.settings.monthly_report_day_utc, self.settings.platform_traffic_report_hour_utc
            )
            await asyncio.sleep(seconds)
            try:
                await self.run_once()
            except Exception:
                logger.exception("seller market share report run failed")

    async def run_once(self) -> bool:
        snapshot = await self.commerce.get_seller_market_share(None)
        report = await asyncio.to_thread(self.report_service.generate_report, snapshot)
        if not self.notifier.enabled:
            return False
        message = f"**{report.period} 판매자 매출 점유율 리포트**\n\n{report.report}"
        return await asyncio.to_thread(self.notifier.send, message)
