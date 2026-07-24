import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.services.commerce_ai import SellerDailyReportService
from app.services.commerce_client import CommerceClient
from app.services.discord import DiscordNotifier

logger = logging.getLogger(__name__)


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
            await asyncio.sleep(self._seconds_until_next_run())
            try:
                await self.run_once()
            except Exception:
                logger.exception("daily seller report run failed")

    def _seconds_until_next_run(self) -> float:
        now = datetime.now(UTC)
        target = now.replace(
            hour=self.settings.daily_report_hour_utc, minute=0, second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def run_once(self) -> list[dict[str, object]]:
        """Generate + (if configured) send today's report for every active seller."""
        orgs = await self.commerce.list_active_organizations()
        results: list[dict[str, object]] = []
        for org in orgs:
            try:
                snapshot = await self.commerce.get_seller_daily_snapshot(org["id"], None)
                report = await asyncio.to_thread(self.report_service.generate_report, snapshot)
                sent = False
                if self.notifier.enabled:
                    header = f"**{report.org_name} · {report.date} 일일 리포트**"
                    message = f"{header}\n\n{report.report}"
                    sent = await asyncio.to_thread(self.notifier.send, message)
                results.append({"org_id": org["id"], "discord_sent": sent})
            except Exception:
                logger.exception("daily seller report failed for org %s", org["id"])
        return results
