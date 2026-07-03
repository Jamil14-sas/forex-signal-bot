"""Main entry point for Forex Signal Bot."""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .bot.handlers import router
from .bot.middleware import AnalysisServiceMiddleware
from .config import get_settings
from .db.base import close_db, init_db
from .scheduler.broadcast import run_broadcast_scheduler
from .services.analysis_service import AnalysisService


async def main() -> None:
    settings = get_settings()

    if not settings.telegram_bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Create a .env file with your bot token from @BotFather."
        )

    # Initialize database
    print("🗄️  Initializing database...")
    await init_db()
    print("   Database ready.")

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    analysis_service = AnalysisService(settings)

    dp = Dispatcher()
    dp.message.middleware(AnalysisServiceMiddleware(analysis_service))
    dp.callback_query.middleware(AnalysisServiceMiddleware(analysis_service))
    dp.include_router(router)

    print(f"🤖 Forex Signal Bot starting...")
    print(f"   OANDA API: {'configured' if settings.oanda_api_key else 'not set (using yfinance fallback)'}")
    print(f"   News API: {'configured' if settings.news_api_key else 'not set (sentiment disabled)'}")

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        print("\n🛑 Shutdown signal received...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _signal_handler)

    # Start polling
    polling_task = asyncio.create_task(
        dp.start_polling(bot, handle_signals=False),
        name="bot-polling",
    )

    # Start broadcast scheduler (if enabled)
    broadcast_task: asyncio.Task | None = None
    if settings.broadcast_enabled:
        broadcast_task = asyncio.create_task(
            run_broadcast_scheduler(bot, analysis_service, interval_seconds=60),
            name="broadcast-scheduler",
        )
        print("   📡 Broadcast scheduler enabled.")
    else:
        print("   📡 Broadcast scheduler disabled (broadcast_enabled=False).")

    print("✅ Bot is running. Press Ctrl+C to stop.\n")

    await stop_event.wait()

    # Shutdown
    await dp.stop_polling()
    polling_task.cancel()
    with suppress(asyncio.CancelledError):
        await polling_task

    if broadcast_task is not None:
        broadcast_task.cancel()
        with suppress(asyncio.CancelledError):
            await broadcast_task

    await bot.session.close()
    await analysis_service.close()
    await close_db()
    print("✅ Bot stopped.")


def run() -> None:
    """Synchronous entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
