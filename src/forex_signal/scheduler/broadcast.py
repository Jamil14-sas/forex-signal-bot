"""Scheduled broadcast logic — analyze pairs and send signals to subscribers."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot

from ..config import get_settings
from ..db.base import get_db_session
from ..db import repository as repo
from ..services.analysis_service import AnalysisService
from ..services.formatter import format_signal, split_long_message

logger = logging.getLogger(__name__)

_settings = get_settings()


async def run_broadcast_scheduler(
    bot: Bot,
    analysis_service: AnalysisService,
    interval_seconds: int = 60,
) -> None:
    """Background task that checks every `interval_seconds` for due broadcasts.

    Runs until cancelled.
    """
    logger.info(
        "broadcast_scheduler_started",
        interval=interval_seconds,
    )

    try:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await _process_due_broadcasts(bot, analysis_service)
            except Exception as exc:
                logger.exception("broadcast_cycle_failed", error=str(exc))
    except asyncio.CancelledError:
        logger.info("broadcast_scheduler_stopped")
        raise


async def _process_due_broadcasts(
    bot: Bot,
    analysis_service: AnalysisService,
) -> None:
    """Find subscriptions due now and send broadcasts."""
    now_utc = datetime.now(timezone.utc)
    current_time_str = now_utc.strftime("%H:%M")

    async with await get_db_session() as session:
        due = await repo.get_due_subscriptions(session, current_time_str)

    if not due:
        return

    logger.info("broadcasts_due", count=len(due), time=current_time_str)

    for sub in due:
        try:
            await _send_broadcast(bot, analysis_service, sub)
            async with await get_db_session() as session:
                await repo.mark_broadcast_sent(session, sub.id)
        except Exception as exc:
            logger.exception(
                "broadcast_failed",
                user_id=sub.user_id,
                error=str(exc),
            )


async def _send_broadcast(
    bot: Bot,
    analysis_service: AnalysisService,
    sub,
) -> None:
    """Send scheduled signals to a subscribed user."""
    pairs = [p.strip() for p in sub.pairs.split(",") if p.strip()]
    pairs = pairs[:_settings.broadcast_max_pairs]

    if not pairs:
        return

    # Send intro message
    intro = (
        f"📊 <b>Daily Forex Signal Report</b>\n"
        f"⏱ {sub.broadcast_time} UTC\n"
        f"📈 Analyzing {len(pairs)} pair(s)...\n"
    )
    try:
        await bot.send_message(chat_id=sub.user_id, text=intro)
    except Exception as exc:
        logger.warning("broadcast_intro_failed", user_id=sub.user_id, error=str(exc))
        return

    for pair in pairs:
        try:
            analysis = await analysis_service.analyze(
                pair,
                timeframe="1h",
                account_balance=_settings.default_account_balance,
                risk_percent=_settings.default_risk_percent,
            )
            formatted = format_signal(analysis.signal, analysis.sentiment)
            chunks = split_long_message(formatted)

            for chunk in chunks:
                await bot.send_message(chat_id=sub.user_id, text=chunk)
                await asyncio.sleep(0.3)  # avoid hitting rate limits

        except Exception as exc:
            error_msg = f"❌ <b>Error analyzing {pair}</b>: {exc}"
            try:
                await bot.send_message(chat_id=sub.user_id, text=error_msg)
            except Exception:
                logger.exception("broadcast_error_notify_failed", user_id=sub.user_id, pair=pair)
