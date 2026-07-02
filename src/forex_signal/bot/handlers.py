"""Telegram bot message and callback handlers."""

from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..services.analysis_service import AnalysisService
from ..services.data_service import FOREX_PAIRS, resolve_pair
from ..services.formatter import (
    format_error,
    format_help,
    format_pairs_list,
    format_signal,
    split_long_message,
)

router = Router(name="forex-signal")

# In-memory user preferences: {telegram_id: {"timeframe": "1h"}}
_user_prefs: dict[int, dict[str, str]] = {}

# Simple in-memory rate limiter: {user_id: [timestamps]}
_rate_limit_store: dict[int, list[float]] = {}
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 15  # max requests per window


def _check_rate_limit(user_id: int | None) -> bool:
    """Returns True if the user is within their rate limit, False if rate limited."""
    if user_id is None:
        return True  # allow through, can't track anonymous messages
    now = time.monotonic()
    if user_id not in _rate_limit_store:
        _rate_limit_store[user_id] = []
    # Prune old entries
    _rate_limit_store[user_id] = [
        t for t in _rate_limit_store[user_id] if now - t < _RATE_LIMIT_WINDOW
    ]
    if len(_rate_limit_store[user_id]) >= _RATE_LIMIT_MAX:
        return False
    _rate_limit_store[user_id].append(now)
    return True


def _get_user_timeframe(user_id: int) -> str:
    return _user_prefs.get(user_id, {}).get("timeframe", "1h")


def _set_user_timeframe(user_id: int, timeframe: str) -> None:
    if user_id not in _user_prefs:
        _user_prefs[user_id] = {}
    _user_prefs[user_id]["timeframe"] = timeframe


# ---- Commands -----------------------------------------------------------


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    name = message.from_user.first_name or "trader"
    text = (
        f"👋 <b>Welcome, {name}!</b>\n\n"
        "I'm a forex signal bot. I analyze live forex data, compute technical "
        "indicators (SMA, RSI, MACD, Bollinger Bands, SMC), and combine it with "
        "market sentiment to generate trading signals.\n\n"
        "<b>Quick start:</b>\n"
        "  /signal EUR/USD — get a trading signal\n"
        "  /analysis EUR/USD — full technical breakdown\n"
        "  /sentiment EUR/USD — news & event sentiment\n"
        "  /pairs — list all available pairs\n"
        "  /help — full command reference"
    )
    await message.answer(text)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(format_help())


@router.message(Command("pairs"))
async def cmd_pairs(message: Message) -> None:
    await message.answer(format_pairs_list(FOREX_PAIRS))


@router.message(Command("timeframe"))
async def cmd_timeframe(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        valid = "5m, 15m, 30m, 1h, 4h, 1d"
        current = _get_user_timeframe(message.from_user.id)
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

    _set_user_timeframe(message.from_user.id, tf)
    await message.answer(f"✅ Timeframe set to <b>{tf}</b>")


# ---- Signal command -----------------------------------------------------


@router.message(Command("signal"))
async def cmd_signal(message: Message, analysis_service: AnalysisService) -> None:
    if not _check_rate_limit(message.from_user.id):
        await message.answer("⏳ Rate limit reached. Please wait before requesting another analysis.")
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
        tf = _get_user_timeframe(message.from_user.id)
        analysis = await analysis_service.analyze(pair, timeframe=tf)

        formatted = format_signal(analysis.signal, analysis.sentiment)
        chunks = split_long_message(formatted)

        await status.edit_text(chunks[0])
        for chunk in chunks[1:]:
            await message.answer(chunk)

    except ValueError as e:
        await status.edit_text(format_error(str(e)))
    except Exception as e:
        await status.edit_text(format_error(f"Unexpected error: {e.__class__.__name__}: {e}"))


# ---- Analysis command ---------------------------------------------------


@router.message(Command("analysis"))
async def cmd_analysis(message: Message, analysis_service: AnalysisService) -> None:
    if not _check_rate_limit(message.from_user.id):
        await message.answer("⏳ Rate limit reached. Please wait before requesting another analysis.")
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
        tf = _get_user_timeframe(message.from_user.id)
        analysis = await analysis_service.analyze(pair, timeframe=tf)

        formatted = format_signal(analysis.signal, analysis.sentiment)
        chunks = split_long_message(formatted)

        await status.edit_text(chunks[0])
        for chunk in chunks[1:]:
            await message.answer(chunk)

    except ValueError as e:
        await status.edit_text(format_error(str(e)))
    except Exception as e:
        await status.edit_text(format_error(f"Unexpected error: {e.__class__.__name__}: {e}"))


# ---- Sentiment command --------------------------------------------------


@router.message(Command("sentiment"))
async def cmd_sentiment(message: Message, analysis_service: AnalysisService) -> None:
    if not _check_rate_limit(message.from_user.id):
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


# ---- Callback: refresh signal ------------------------------------------

@router.callback_query(F.data == "refresh_signal")
async def on_refresh(call: CallbackQuery, analysis_service: AnalysisService) -> None:
    # The pair is stored in the message text — simple approach
    await call.answer("Refresh not yet implemented — use /signal <pair> again", show_alert=True)
