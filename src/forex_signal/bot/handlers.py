"""Telegram bot message and callback handlers."""

from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..config import get_settings
from ..db.base import get_db_session
from ..db import repository as repo
from ..services.analysis_service import AnalysisService
from ..services.data_service import FOREX_PAIRS, resolve_pair
from ..services.formatter import (
    format_error,
    format_help,
    format_signal,
    split_long_message,
)

router = Router(name="forex-signal")

_settings = get_settings()

# Lightweight in-memory rate limiter (per-second burst)
_rate_limit_store: dict[int, list[float]] = {}
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 30


def _check_burst_rate_limit(user_id: int | None) -> bool:
    """In-memory burst rate limiter (per-second). Returns True if allowed."""
    import time

    if user_id is None:
        return True
    now = time.monotonic()
    if user_id not in _rate_limit_store:
        _rate_limit_store[user_id] = []
    _rate_limit_store[user_id] = [
        t for t in _rate_limit_store[user_id] if now - t < _RATE_LIMIT_WINDOW
    ]
    if len(_rate_limit_store[user_id]) >= _RATE_LIMIT_MAX:
        return False
    _rate_limit_store[user_id].append(now)
    return True


async def _get_user_timeframe(user_id: int) -> str:
    async with await get_db_session() as session:
        return await repo.get_preference(session, user_id, "timeframe", "1h")


async def _set_user_timeframe(user_id: int, tf: str) -> None:
    async with await get_db_session() as session:
        await repo.set_preference(session, user_id, "timeframe", tf)


async def _check_daily_limit(user_id: int) -> tuple[bool, int]:
    async with await get_db_session() as session:
        return await repo.check_daily_limit(
            session, user_id, _settings.user_daily_limit
        )


async def _increment_usage(user_id: int) -> None:
    async with await get_db_session() as session:
        await repo.increment_usage(session, user_id)


async def _ensure_user(
    user_id: int, username: str | None = None, first_name: str | None = None
) -> None:
    async with await get_db_session() as session:
        await repo.get_or_create_user(session, user_id, username, first_name)


# ---- Commands ---------------------------------------------------------------


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    name = message.from_user.first_name or "trader"
    # Ensure user exists in DB
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    text = (
        f"👋 <b>Welcome, {name}!</b>\n\n"
        "I'm a forex signal bot. I analyze live forex data, compute technical "
        "indicators (SMA, RSI, MACD, Bollinger Bands, SMC), and combine it with "
        "market sentiment to generate trading signals.\n\n"
        "<b>Quick start:</b>\n"
        "  /signal EUR/USD — get a trading signal\n"
        "  /analysis EUR/USD — full technical breakdown\n"
        "  /multianalysis EUR/USD — multi-timeframe analysis\n"
        "  /sentiment EUR/USD — news & event sentiment\n"
        "  /pairs — list all available pairs\n"
        "  /subscribe — scheduled daily signals\n"
        "  /help — full command reference"
    )
    await message.answer(text)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await message.answer(format_help())


@router.message(Command("pairs"))
async def cmd_pairs(message: Message) -> None:
    await message.answer(format_pairs_list(FOREX_PAIRS))


@router.message(Command("timeframe"))
async def cmd_timeframe(message: Message) -> None:
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        valid = "5m, 15m, 30m, 1h, 4h, 1d"
        current = await _get_user_timeframe(message.from_user.id)
        await message.answer(
            f"⏱ Current timeframe: <b>{current}</b>\n"
            f"Usage: /timeframe <i>tf</i>\n"
            f"Options: {valid}"
        )
        return

    tf = args[1].strip().lower()
    valid_tfs = {"5m", "15m", "30m", "1h", "4h", "1d", "1wk"}
    if tf not in valid_tfs:
        await message.answer(f"❌ Invalid timeframe. Options: {', '.join(sorted(valid_tfs))}")
        return

    await _set_user_timeframe(message.from_user.id, tf)
    await message.answer(f"✅ Timeframe set to <b>{tf}</b>")


# ---- Signal command ---------------------------------------------------------


@router.message(Command("signal"))
async def cmd_signal(message: Message, analysis_service: AnalysisService) -> None:
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    if not _check_burst_rate_limit(message.from_user.id):
        await message.answer("⏳ Rate limit reached. Please wait before requesting another analysis.")
        return

    within_limit, count = await _check_daily_limit(message.from_user.id)
    if not within_limit:
        await message.answer(
            f"⚠️ You've reached your daily limit of {_settings.user_daily_limit} analyses. "
            "Upgrade to premium for unlimited access."
        )
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "Usage: /signal <i>pair</i>\n"
            "Example: /signal EUR/USD\n\n"
            "Use /pairs to see all available pairs."
        )
        return

    pair = args[1].strip()
    if resolve_pair(pair) is None:
        await message.answer(
            f"❌ Unknown pair: <b>{pair}</b>\n"
            "Use /pairs to see available pairs."
        )
        return

    status = await message.answer(f"🔎 Analyzing <b>{pair}</b>... Fetching live data, computing indicators...")

    try:
        tf = await _get_user_timeframe(message.from_user.id)
        analysis = await analysis_service.analyze(pair, timeframe=tf)

        # Save to DB
        async with await get_db_session() as session:
            await repo.save_signal(
                session,
                user_id=message.from_user.id,
                pair=analysis.signal.pair,
                timeframe=tf,
                direction=analysis.signal.direction.value,
                confidence=analysis.signal.confidence,
                entry_price=analysis.signal.current_price,
                stop_loss=analysis.signal.stop_loss,
                take_profit=", ".join(analysis.signal.take_profit) if analysis.signal.take_profit else None,
            )
            await repo.increment_usage(session, message.from_user.id)

        formatted = format_signal(analysis.signal, analysis.sentiment)
        chunks = split_long_message(formatted)

        await status.edit_text(chunks[0])
        for chunk in chunks[1:]:
            await message.answer(chunk)

    except ValueError as e:
        await status.edit_text(format_error(str(e)))
    except Exception as e:
        await status.edit_text(format_error(f"Unexpected error: {e.__class__.__name__}: {e}"))


# ---- Analysis command -------------------------------------------------------


@router.message(Command("analysis"))
async def cmd_analysis(message: Message, analysis_service: AnalysisService) -> None:
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    if not _check_burst_rate_limit(message.from_user.id):
        await message.answer("⏳ Rate limit reached. Please wait before requesting another analysis.")
        return

    within_limit, count = await _check_daily_limit(message.from_user.id)
    if not within_limit:
        await message.answer("⚠️ Daily limit reached.")
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Usage: /analysis <i>pair</i>\nExample: /analysis EUR/USD")
        return

    pair = args[1].strip()
    if resolve_pair(pair) is None:
        await message.answer(f"❌ Unknown pair: <b>{pair}</b>. Use /pairs to see available pairs.")
        return

    status = await message.answer(f"🔎 Running full analysis on <b>{pair}</b>...")

    try:
        tf = await _get_user_timeframe(message.from_user.id)
        analysis = await analysis_service.analyze(pair, timeframe=tf)

        async with await get_db_session() as session:
            await repo.save_signal(
                session,
                user_id=message.from_user.id,
                pair=analysis.signal.pair,
                timeframe=tf,
                direction=analysis.signal.direction.value,
                confidence=analysis.signal.confidence,
                entry_price=analysis.signal.current_price,
                stop_loss=analysis.signal.stop_loss,
                take_profit=", ".join(analysis.signal.take_profit) if analysis.signal.take_profit else None,
            )
            await repo.increment_usage(session, message.from_user.id)

        formatted = format_signal(analysis.signal, analysis.sentiment)
        chunks = split_long_message(formatted)

        await status.edit_text(chunks[0])
        for chunk in chunks[1:]:
            await message.answer(chunk)

    except ValueError as e:
        await status.edit_text(format_error(str(e)))
    except Exception as e:
        await status.edit_text(format_error(f"Unexpected error: {e.__class__.__name__}: {e}"))


# ---- Sentiment command ------------------------------------------------------


@router.message(Command("sentiment"))
async def cmd_sentiment(message: Message, analysis_service: AnalysisService) -> None:
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    if not _check_burst_rate_limit(message.from_user.id):
        await message.answer("⏳ Rate limit reached. Please wait before requesting another analysis.")
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Usage: /sentiment <i>pair</i>\nExample: /sentiment EUR/USD")
        return

    pair = args[1].strip()
    if resolve_pair(pair) is None:
        await message.answer(f"❌ Unknown pair: <b>{pair}</b>. Use /pairs to see available pairs.")
        return

    status = await message.answer(f"📰 Analyzing sentiment for <b>{pair}</b>...")

    try:
        result = await analysis_service.analyze_sentiment(pair)

        sent_emoji = {"Bullish": "🟢", "Bearish": "🔴", "Neutral": "🟡"}.get(result.label, "🟡")
        risk_emoji = {"High": "🔴", "Medium": "🟡", "Normal": "🟢"}.get(result.risk_level, "🟢")

        lines = [
            f"🗞 <b>Sentiment Analysis — {pair}</b>",
            f"{sent_emoji} Overall: <b>{result.label}</b> (score: {result.score:.0f})",
            f"{risk_emoji} Risk level: <b>{result.risk_level}</b>",
            "",
        ]

        if result.headlines:
            lines.append(f"📰 <b>News Headlines</b> ({len(result.headlines)}):")
            for h in result.headlines[:10]:
                h_emoji = {"Bullish": "🟢", "Bearish": "🔴", "Neutral": "🟡"}.get(h["sentiment"], "⚪")
                lines.append(f"  {h_emoji} {h['title'][:100]}")
                lines.append(f"     <i>Source: {h['source']} | Score: {h['score']:.0f}</i>")

        if result.events:
            lines.append("")
            lines.append(f"📅 <b>Economic Events</b> ({len(result.events)}):")
            for ev in result.events:
                impact_icon = {"High": "🔴", "Medium": "🟡", "Normal": "🟢"}.get(ev["impact"], "⚪")
                lines.append(f"  {impact_icon} {ev['currency']}: {ev['event']} ({ev['frequency']})")

        lines.append("")
        lines.append("<i>⚠️ Not financial advice. Sentiment based on automated analysis.</i>")

        await status.edit_text("\n".join(lines))

    except Exception as e:
        await status.edit_text(format_error(f"Sentiment analysis failed: {e}"))


# ---- Multi-timeframe analysis -----------------------------------------------


@router.message(Command("multianalysis"))
async def cmd_multianalysis(message: Message, analysis_service: AnalysisService) -> None:
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    if not _check_burst_rate_limit(message.from_user.id):
        await message.answer("⏳ Rate limit reached.")
        return

    within_limit, count = await _check_daily_limit(message.from_user.id)
    if not within_limit:
        await message.answer("⚠️ Daily limit reached.")
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Usage: /multianalysis <i>pair</i>\nExample: /multianalysis EUR/USD")
        return

    pair = args[1].strip()
    if resolve_pair(pair) is None:
        await message.answer(f"❌ Unknown pair: <b>{pair}</b>")
        return

    user_tf = await _get_user_timeframe(message.from_user.id)
    # Pick 3 timeframes: user's default, 4h, 1d (skip duplicates)
    timeframes = list(dict.fromkeys([user_tf, "4h", "1d"]))[:3]

    status = await message.answer(
        f"🔎 Analyzing <b>{pair}</b> across {', '.join(timeframes)}..."
    )

    try:
        import asyncio

        tasks = [
            analysis_service.analyze(pair, timeframe=tf)
            for tf in timeframes
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build response
        from ..services.formatter import format_multi_timeframe_analysis

        response = format_multi_timeframe_analysis(pair, timeframes, results)
        chunks = split_long_message(response)

        await status.edit_text(chunks[0])
        for chunk in chunks[1:]:
            await message.answer(chunk)

        # Save signals to DB
        async with await get_db_session() as session:
            for i, analysis in enumerate(results):
                if isinstance(analysis, Exception):
                    continue
                await repo.save_signal(
                    session,
                    user_id=message.from_user.id,
                    pair=analysis.signal.pair,
                    timeframe=timeframes[i],
                    direction=analysis.signal.direction.value,
                    confidence=analysis.signal.confidence,
                    entry_price=analysis.signal.current_price,
                    stop_loss=analysis.signal.stop_loss,
                    take_profit=", ".join(analysis.signal.take_profit) if analysis.signal.take_profit else None,
                )
            await repo.increment_usage(session, message.from_user.id)

    except Exception as e:
        await status.edit_text(format_error(f"Multi-analysis failed: {e}"))


# ---- Signal history & stats -------------------------------------------------


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    """Show recent signal history."""
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    async with await get_db_session() as session:
        signals = await repo.get_signal_history(
            session, user_id=message.from_user.id, limit=10
        )

    if not signals:
        await message.answer("📭 No signal history yet. Try /signal EUR/USD to generate one.")
        return

    lines = [f"📊 <b>Your Recent Signals</b> (last {len(signals)}):\n"]
    for s in signals:
        emoji = "🟢" if s.direction == "BUY" else ("🔴" if s.direction == "SELL" else "🟡")
        outcome_emoji = {"won": "✅", "lost": "❌", "pending": "⏳"}
        outcome = outcome_emoji.get(s.actual_outcome or "pending", "⏳")
        date_str = s.created_at.strftime("%b %d %H:%M") if s.created_at else ""
        lines.append(
            f"{emoji} <b>{s.pair}</b> {s.direction} ({s.confidence:.0f}%) "
            f"— {s.timeframe} — {outcome}"
        )
        lines.append(f"   <i>{date_str}</i>")

    await message.answer("\n".join(lines))


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Show signal win rate statistics."""
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    async with await get_db_session() as session:
        stats = await repo.get_win_rate(session, user_id=message.from_user.id)

    if stats["total"] == 0:
        await message.answer(
            "📊 No completed signals yet. Signals are marked as 'won' or 'lost' "
            "when you resolve them with /resolve."
        )
        return

    bar_filled = round(stats["win_rate"] / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    lines = [
        "📊 <b>Your Signal Statistics</b>",
        f"Total signals: <b>{stats['total']}</b>",
        f"✅ Won: <b>{stats['won']}</b>",
        f"❌ Lost: <b>{stats['lost']}</b>",
        f"🎯 Win rate: <code>{bar}</code> <b>{stats['win_rate']}%</b>",
    ]
    await message.answer("\n".join(lines))


# ---- Subscription commands --------------------------------------------------


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message) -> None:
    """Subscribe to daily signal broadcasts."""
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    args = (message.text or "").split(maxsplit=2)
    # Usage: /subscribe [time] [pairs]
    # time: HH:MM in UTC, pairs: comma-separated
    time = "08:00"
    pairs = "EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD"

    if len(args) >= 2 and args[1].strip():
        time = args[1].strip()
    if len(args) >= 3 and args[2].strip():
        pairs = args[2].strip()

    if not _validate_time(time):
        await message.answer(
            "❌ Invalid time format. Use HH:MM in UTC, e.g. /subscribe 08:00\n"
            "Or /subscribe 08:00 EUR/USD,GBP/USD"
        )
        return

    async with await get_db_session() as session:
        await repo.set_subscription(
            session, message.from_user.id, broadcast_time=time, pairs=pairs
        )

    await message.answer(
        f"✅ <b>Subscribed to daily signals!</b>\n"
        f"⏱ Time: <b>{time}</b> UTC\n"
        f"📊 Pairs: <b>{pairs}</b>\n\n"
        f"You'll receive analysis for these pairs daily at {time} UTC.\n"
        f"Use /mypairs to change pairs, /mytime to change time, "
        f"or /unsubscribe to cancel."
    )


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message) -> None:
    """Unsubscribe from daily signal broadcasts."""
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    async with await get_db_session() as session:
        deleted = await repo.delete_subscription(session, message.from_user.id)

    if deleted:
        await message.answer("✅ <b>Unsubscribed.</b> You'll no longer receive daily signal broadcasts.")
    else:
        await message.answer("ℹ️ You're not currently subscribed. Use /subscribe to start.")


@router.message(Command("mytime"))
async def cmd_mytime(message: Message) -> None:
    """Set broadcast time for subscriptions."""
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        async with await get_db_session() as session:
            sub = await repo.get_subscription(session, message.from_user.id)
        if sub:
            await message.answer(
                f"⏱ Current broadcast time: <b>{sub.broadcast_time}</b> UTC\n"
                "Usage: /mytime HH:MM (UTC)"
            )
        else:
            await message.answer("You're not subscribed. Use /subscribe first.")
        return

    time = args[1].strip()
    if not _validate_time(time):
        await message.answer("❌ Invalid time. Use HH:MM format in UTC (e.g. 08:00, 16:30).")
        return

    async with await get_db_session() as session:
        sub = await repo.get_subscription(session, message.from_user.id)
        if sub:
            await repo.set_subscription(
                session, message.from_user.id, broadcast_time=time, pairs=sub.pairs
            )
            await message.answer(f"✅ Broadcast time updated to <b>{time}</b> UTC")
        else:
            await message.answer("You're not subscribed. Use /subscribe first.")


@router.message(Command("mypairs"))
async def cmd_mypairs(message: Message) -> None:
    """Set which pairs to receive signals for."""
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        async with await get_db_session() as session:
            sub = await repo.get_subscription(session, message.from_user.id)
        if sub:
            await message.answer(
                f"📊 Current pairs: <b>{sub.pairs}</b>\n"
                "Usage: /mypairs EUR/USD,GBP/USD,USD/JPY\n"
                "Separate pairs with commas."
            )
        else:
            await message.answer("You're not subscribed. Use /subscribe first.")
        return

    pairs_str = args[1].strip()
    # Validate at least one pair
    pair_list = [p.strip() for p in pairs_str.split(",")]
    valid_pairs = []
    invalid = []
    for p in pair_list:
        if resolve_pair(p):
            valid_pairs.append(p)
        else:
            invalid.append(p)

    if not valid_pairs:
        await message.answer("❌ None of those pairs are valid. Use /pairs to see available pairs.")
        return

    valid_str = ",".join(valid_pairs)
    async with await get_db_session() as session:
        sub = await repo.get_subscription(session, message.from_user.id)
        if sub:
            await repo.set_subscription(
                session, message.from_user.id, broadcast_time=sub.broadcast_time, pairs=valid_str
            )
            msg = f"✅ Pairs updated to <b>{valid_str}</b>"
            if invalid:
                msg += f"\n⚠️ Skipped (invalid): {', '.join(invalid)}"
            await message.answer(msg)
        else:
            await message.answer("You're not subscribed. Use /subscribe first.")


# ---- Resolve signal outcome -------------------------------------------------


@router.message(Command("resolve"))
async def cmd_resolve(message: Message) -> None:
    """Mark a signal as won or lost: /resolve won <signal_id>"""
    await _ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "Usage: /resolve won|lost <signal_id>\n"
            "Find signal IDs with /history"
        )
        return

    outcome = args[1].strip().lower()
    if outcome not in ("won", "lost"):
        await message.answer("❌ Outcome must be 'won' or 'lost'.")
        return

    try:
        signal_id = int(args[2].strip())
    except ValueError:
        await message.answer("❌ Signal ID must be a number. Use /history to find IDs.")
        return

    from datetime import datetime, timezone

    async with await get_db_session() as session:
        from sqlalchemy import select
        from ..db.models import SignalRecord

        result = await session.execute(
            select(SignalRecord).where(
                SignalRecord.id == signal_id,
                SignalRecord.user_id == message.from_user.id,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            await message.answer("❌ Signal not found. Use /history to see your signals.")
            return

        record.actual_outcome = outcome
        record.resolved_at = datetime.now(timezone.utc)
        await session.flush()

    emoji = "✅" if outcome == "won" else "❌"
    await message.answer(
        f"{emoji} <b>Signal #{signal_id} marked as {outcome}!</b>\n"
        f"{record.pair} {record.direction} — {record.confidence:.0f}% confidence."
    )


# ---- Helpers ----------------------------------------------------------------


def _validate_time(time_str: str) -> bool:
    """Validate HH:MM format."""
    import re
    return bool(re.match(r"^([01]\d|2[0-3]):[0-5]\d$", time_str))


def _format_pairs_list(pairs: dict[str, str]) -> str:
    """Format the available forex pairs list."""
    lines = ["📋 <b>Available Forex Pairs</b>\n"]
    lines.append("<b>Majors:</b>")
    majors = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "NZD/USD", "USD/CAD", "USD/CHF"]
    for pair in majors:
        if pair in pairs:
            lines.append(f"  • {pair}")
    lines.append("\n<b>Crosses:</b>")
    crosses = [p for p in pairs if p not in majors and p not in ("USD/SGD", "USD/HKD")]
    for pair in crosses[:15]:
        lines.append(f"  • {pair}")
    lines.append(f"\n<i>Use /signal {'<pair>'} to get a trading signal.</i>")
    return "\n".join(lines)


# ---- Callback: refresh signal ------------------------------------------------

@router.callback_query(F.data == "refresh_signal")
async def on_refresh(call: CallbackQuery, analysis_service: AnalysisService) -> None:
    await call.answer("Refresh not yet implemented — use /signal <pair> again", show_alert=True)
