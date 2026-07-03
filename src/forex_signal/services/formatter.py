"""Telegram HTML formatter — clean, scannable, mobile-friendly output."""

from __future__ import annotations

from html import escape

from .indicators import IndicatorResult, SignalDirection
from .signal_service import SignalStrength, TradeSignal
from .sentiment import SentimentResult

TELEGRAM_MESSAGE_LIMIT = 4096
SEP = "━" * 28


# ── Helpers ──────────────────────────────────────────────────────────────────


def _dir_emoji(d: SignalDirection) -> str:
    return {SignalDirection.BUY: "🟢", SignalDirection.SELL: "🔴", SignalDirection.NEUTRAL: "🟡"}[d]


def _strength_icon(s: SignalStrength) -> str:
    return {SignalStrength.STRONG: "⚡⚡⚡", SignalStrength.MODERATE: "⚡⚡", SignalStrength.WEAK: "⚡", SignalStrength.NEUTRAL: "—"}[s]


def _strength_label(s: SignalStrength) -> str:
    return {SignalStrength.STRONG: "STRONG", SignalStrength.MODERATE: "MODERATE", SignalStrength.WEAK: "WEAK", SignalStrength.NEUTRAL: "NEUTRAL"}[s]


def _confidence_bar(pct: float, length: int = 10) -> str:
    p = max(0, min(100, float(pct)))
    filled = round(p / (100 / length))
    bar = "█" * filled + "░" * (length - filled)
    return f"<code>{bar}</code> {p:.0f}%"


def _sent_emoji(label: str) -> str:
    return {"Bullish": "🟢", "Bearish": "🔴", "Neutral": "🟡"}.get(label, "⚪")


def _risk_emoji(level: str) -> str:
    return {"High": "🔴", "Medium": "🟡", "Normal": "🟢"}.get(level, "🟢")


def _rr_emoji(ratio: float) -> str:
    return "🟢" if ratio >= 2 else ("🟡" if ratio >= 1 else "🔴")


def _one_line(text: str, max_len: int = 60) -> str:
    """Truncate to single line for compact display."""
    text = text.replace("\n", " ")
    return text[:max_len] + "…" if len(text) > max_len else text


# ── Signal Card ──────────────────────────────────────────────────────────────


def format_signal(signal: TradeSignal, sentiment: SentimentResult | None = None) -> str:
    """Beautiful, scannable telegram signal card."""
    emoji = _dir_emoji(signal.direction)
    strength_icon = _strength_icon(signal.strength)
    strength_text = _strength_label(signal.strength)
    s = signal  # shorthand

    lines = [
        # ── Header ────────────────────────────────────────────
        f"{emoji} <b>{s.direction.value} SIGNAL</b> — {s.pair}",
        SEP,
        f"⏱ <b>{escape(s.timeframe)}</b>  |  💪 {strength_icon} <b>{strength_text}</b>",
        f"🎚 {_confidence_bar(s.confidence)}",
        "",
        # ── Price / Entry / SL / TP ───────────────────────────
        f"💰 <code>{s.current_price:.5f}</code>",
    ]

    if s.direction != SignalDirection.NEUTRAL:
        lines.append(f"🎯 Entry: <code>{escape(s.entry_zone)}</code>")
        sl_tp = f"🛑 SL: <code>{escape(s.stop_loss)}</code>"
        if s.take_profit:
            tp_str = " | ".join(f"<code>{tp}</code>" for tp in s.take_profit)
            sl_tp += f"  |  🏁 TP: {tp_str}"
        lines.append(sl_tp)

    # ── Indicators (compact) ──────────────────────────────────
    if s.indicators:
        lines.append("")
        lines.append("📊 <b>Indicators</b>")
        for ind in s.indicators:
            icon = _dir_emoji(ind.direction)
            conf = f" ({ind.confidence:.0f}%)" if ind.confidence else ""
            detail = _one_line(ind.details, 50)
            lines.append(f"  {icon} <b>{escape(ind.name)}</b>{conf}")
            if detail:
                lines.append(f"    <i>{escape(detail)}</i>")

    # ── SMC ───────────────────────────────────────────────────
    if s.smc and (s.smc.bos_signals or s.smc.fvg_signals or s.smc.swing_highs or s.smc.swing_lows):
        smc = s.smc
        parts = []
        if smc.bos_signals:
            parts.append(f"🏗 BOS: <b>{smc.bos_signals}</b>")
        if smc.fvg_signals:
            parts.append(f"📐 FVG: <b>{smc.fvg_signals}</b>")
        lines.append("")
        lines.append("  " + "  |  ".join(parts))
        if smc.swing_highs or smc.swing_lows:
            swing = ""
            if smc.swing_highs:
                swing += f"⇈ {smc.swing_highs[-1]:.5f}"
            if smc.swing_lows:
                swing += f"  ⇊ {smc.swing_lows[-1]:.5f}"
            lines.append(f"  <i>Swing: {swing}</i>")

    # ── Divergence ────────────────────────────────────────────
    if s.divergence != SignalDirection.NEUTRAL:
        lines.append("")
        lines.append(f"⚠️ <b>RSI Divergence</b>: {s.divergence.value}")

    # ── Sentiment ─────────────────────────────────────────────
    if sentiment:
        lines.append("")
        sent_line = f"🗞 <b>Sentiment</b>: {_sent_emoji(sentiment.label)} {sentiment.label} ({sentiment.score:.0f})"
        risk_line = f"  {_risk_emoji(sentiment.risk_level)} Risk: <b>{sentiment.risk_level}</b>"
        lines.append(sent_line)
        lines.append(risk_line)
        if sentiment.headlines:
            for h in sentiment.headlines[:3]:
                h_emoji = _sent_emoji(h["sentiment"])
                lines.append(f"  {h_emoji} {escape(_one_line(h['title'], 70))}")

    # ── Risk Management ───────────────────────────────────────
    if s.risk_info and s.direction != SignalDirection.NEUTRAL:
        r = s.risk_info
        lines.append("")
        lines.append("🛡 <b>Risk</b>")
        if r.risk_amount > 0:
            lines.append(f"  💵 <b>${r.risk_amount:.0f}</b> ({r.risk_percent:.1f}% of ${r.account_balance:,.0f})")
        if r.position_size > 0:
            lines.append(f"  📏 Size: <b>{r.position_size:.4f}</b>")
        if r.risk_reward_ratio > 0:
            lines.append(f"  {_rr_emoji(r.risk_reward_ratio)} R:R <b>1:{r.risk_reward_ratio}</b>")
        trail = r.calc_trailing_stop(s.current_price, s.current_price, s.direction)
        lines.append(f"  🎯 Trail: <code>{trail:.5f}</code>")

    # ── Summary ───────────────────────────────────────────────
    lines.append("")
    lines.append(f"📝 {escape(_one_line(s.summary, 100))}")

    # ── Disclaimer ────────────────────────────────────────────
    lines.append("")
    lines.append("<i>⚠️ Not financial advice.</i>")

    return "\n".join(lines)


# ── Multi-Timeframe Analysis ────────────────────────────────────────────────


def format_multi_timeframe_analysis(
    pair: str,
    timeframes: list[str],
    results: list,
) -> str:
    """Compact multi-timeframe view with confluence."""
    lines = [
        f"📊 <b>Multi-TF — {pair}</b>",
        SEP,
    ]

    # Confluence
    direction_map = {}
    for i, r in enumerate(results):
        if isinstance(r, Exception) or r.signal is None:
            continue
        direction_map[timeframes[i]] = r.signal.direction.value

    buy_c = sum(1 for d in direction_map.values() if d == "BUY")
    sell_c = sum(1 for d in direction_map.values() if d == "SELL")
    neutral_c = sum(1 for d in direction_map.values() if d == "NEUTRAL")
    total = len(direction_map) or 1

    if buy_c > sell_c and buy_c >= 2:
        con_label, con_color = "🟢 BULLISH CONFLUENCE", "🟢"
        con_pct = buy_c / total * 100
    elif sell_c > buy_c and sell_c >= 2:
        con_label, con_color = "🔴 BEARISH CONFLUENCE", "🔴"
        con_pct = sell_c / total * 100
    else:
        con_label = "🟡 MIXED / NEUTRAL"
        con_pct = max(buy_c, sell_c) / total * 100

    bar = _confidence_bar(con_pct)
    lines.append(f"{con_label}")
    lines.append(f"  {bar}")
    lines.append(f"  🟢{buy_c}  🔴{sell_c}  🟡{neutral_c}")
    lines.append(SEP)

    # Per-timeframe
    for i, tf in enumerate(timeframes):
        r = results[i]
        if isinstance(r, Exception):
            lines.append(f"❌ <b>{tf}</b> — {r}")
            lines.append("")
            continue
        if r.signal is None:
            lines.append(f"❌ <b>{tf}</b> — {r.error}")
            lines.append("")
            continue

        sig = r.signal
        emoji = _dir_emoji(sig.direction)
        rr = f"  R:R 1:{sig.risk_info.risk_reward_ratio}" if sig.risk_info and sig.risk_info.risk_reward_ratio > 0 else ""
        sl_info = f"  SL {sig.stop_loss}" if sig.direction != SignalDirection.NEUTRAL else ""

        lines.append(
            f"{emoji} <b>{tf}</b> — {sig.direction.value} "
            f"({sig.confidence:.0f}%){rr}"
        )
        lines.append(
            f"   💰 <code>{sig.current_price:.5f}</code>{sl_info}"
        )
        lines.append("")

    lines.append("<i>⚠️ Not financial advice.</i>")
    return "\n".join(lines)


# ── Pairs List ───────────────────────────────────────────────────────────────


def format_pairs_list(pairs: dict[str, str]) -> str:
    """Compact pairs listing with major / cross groups."""
    majors = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "NZD/USD", "USD/CAD", "USD/CHF"]
    crosses = sorted(p for p in pairs if p not in majors)

    lines = ["📋 <b>Forex Pairs</b>\n"]
    lines.append("🇺🇳 <b>Majors</b>")
    for p in majors:
        if p in pairs:
            lines.append(f"  • {p}")
    lines.append("")
    lines.append("🔗 <b>Crosses</b>")
    for p in crosses[:20]:
        lines.append(f"  • {p}")
    if len(crosses) > 20:
        lines.append(f"  <i>… and {len(crosses) - 20} more</i>")
    lines.append("")
    lines.append("💡 /signal EUR/USD to start")
    return "\n".join(lines)


# ── Help ─────────────────────────────────────────────────────────────────────


def format_help() -> str:
    return """🧭 <b>Forex Signal Bot — Commands</b>

<b>📈 Analysis</b>
  /signal EUR/USD        — Trading signal
  /analysis EUR/USD      — Full technical analysis
  /multianalysis EUR/USD — Across 3 timeframes
  /sentiment EUR/USD     — News & event sentiment
  /pairs                 — List all pairs

<b>📊 History</b>
  /history               — Recent signals
  /stats                 — Win rate
  /resolve won/lost <id> — Mark outcome

<b>📡 Scheduled</b>
  /subscribe [time]      — Daily broadcasts
  /unsubscribe           — Cancel
  /mytime HH:MM          — Change time
  /mypairs A,B,C         — Change pairs

<b>⚙️ Settings</b>
  /timeframe 1h/4h/1d   — Analysis TF
  /help                  — This menu

<i>⚠️ Not financial advice. Trade responsibly.</i>"""


# ── Welcome ──────────────────────────────────────────────────────────────────


def format_welcome(name: str) -> str:
    return (
        f"👋 <b>Hey {escape(name)}!</b>\n\n"
        "I analyze live forex data and generate trading signals with:\n\n"
        f"{_dir_emoji(SignalDirection.BUY)} Technical indicators (SMA, RSI, MACD, BB)\n"
        f"{_dir_emoji(SignalDirection.BUY)} Smart Money Concepts (BOS, FVG, Order Blocks)\n"
        f"{_dir_emoji(SignalDirection.BUY)} Market sentiment + economic calendar\n"
        f"{_dir_emoji(SignalDirection.BUY)} Risk management (sizing, R:R, trailing stop)\n\n"
        "<b>Quick start:</b>\n"
        "  /signal EUR/USD\n"
        "  /multianalysis EUR/USD\n"
        "  /pairs\n\n"
        "Or tap a button below 👇"
    )


# ── Error ────────────────────────────────────────────────────────────────────


_ERROR_TIPS: dict[str, str] = {
    "Unknown pair": "Use /pairs to see all supported pairs.",
    "Not enough data": "Try a larger timeframe (1h, 4h, 1d) or shorter period.",
    "OANDA API key rejected": "Check your OANDA_API_KEY in .env",
    "401": "API authentication failed. Check your tokens in .env",
    "timeout": "The data source timed out. Try again shortly.",
}


def format_error(error_msg: str) -> str:
    """Error message with actionable tip."""
    tip = "Try again or use /help."
    for key, hint in _ERROR_TIPS.items():
        if key.lower() in error_msg.lower():
            tip = hint
            break
    return f"❌ <b>Error</b>: {escape(error_msg)}\n\n💡 <i>{tip}</i>"


# ── Misc ─────────────────────────────────────────────────────────────────────


def format_confidence_bar(pct: float) -> str:
    """Standalone confidence bar."""
    return _confidence_bar(pct)


def format_subscription_status(sub) -> str:
    """Format subscription info."""
    return (
        f"✅ <b>Subscribed</b>\n"
        f"⏱ Time: <b>{sub.broadcast_time}</b> UTC\n"
        f"📊 Pairs: <b>{sub.pairs}</b>\n"
        f"📬 Broadcasts sent: <b>{sub.broadcast_count}</b>\n"
        f"📅 Last: {sub.last_broadcast_date or 'N/A'}"
    )


def split_long_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split into Telegram-safe chunks."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut == -1:
            cut = remaining.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        parts.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    if remaining:
        parts.append(remaining)

    return [f"({idx + 1}/{len(parts)})\n{part}" for idx, part in enumerate(parts)]
