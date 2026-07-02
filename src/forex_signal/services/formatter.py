"""Telegram HTML formatter for trading signals and analysis."""

from __future__ import annotations

from html import escape

from .indicators import IndicatorResult, SignalDirection
from .signal_service import SignalStrength, TradeSignal
from .sentiment import SentimentResult

TELEGRAM_MESSAGE_LIMIT = 4096


def _direction_emoji(direction: SignalDirection) -> str:
    return {
        SignalDirection.BUY: "🟢",
        SignalDirection.SELL: "🔴",
        SignalDirection.NEUTRAL: "🟡",
    }[direction]


def _strength_emoji(strength: SignalStrength) -> str:
    return {
        SignalStrength.STRONG: "⚡⚡⚡",
        SignalStrength.MODERATE: "⚡⚡",
        SignalStrength.WEAK: "⚡",
        SignalStrength.NEUTRAL: "—",
    }[strength]


def _strength_label(strength: SignalStrength) -> str:
    return {
        SignalStrength.STRONG: "STRONG",
        SignalStrength.MODERATE: "MODERATE",
        SignalStrength.WEAK: "WEAK",
        SignalStrength.NEUTRAL: "NEUTRAL",
    }[strength]


def _confidence_bar(percent: float) -> str:
    p = max(0, min(100, float(percent)))
    filled = round(p / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"<code>{bar}</code> {p:.0f}%"


def format_signal(signal: TradeSignal, sentiment: SentimentResult | None = None) -> str:
    """Format a trade signal as a beautiful Telegram HTML message."""
    emoji = _direction_emoji(signal.direction)
    strength_icon = _strength_emoji(signal.strength)
    strength_text = _strength_label(signal.strength)

    lines = [
        f"{emoji} <b>{signal.direction.value} SIGNAL</b> — {signal.pair}",
        f"⏱ Timeframe: <code>{escape(signal.timeframe)}</code>",
        f"💪 Strength: {strength_icon} <b>{strength_text}</b>",
        f"🎚 Confidence: {_confidence_bar(signal.confidence)}",
        "",
        f"💰 Current price: <code>{signal.current_price:.5f}</code>",
    ]

    if signal.direction != SignalDirection.NEUTRAL:
        lines += [
            f"🎯 Entry zone: <code>{escape(signal.entry_zone)}</code>",
            f"🛑 Stop loss: <code>{escape(signal.stop_loss)}</code>",
        ]
        if signal.take_profit:
            tp_str = ", ".join(f"<code>{tp}</code>" for tp in signal.take_profit)
            lines.append(f"🏁 Take profit: {tp_str}")

    # Indicator details
    lines.append("")
    lines.append("📊 <b>Technical Indicators</b>")
    for ind in signal.indicators:
        icon = _direction_emoji(ind.direction)
        conf_str = f" (conf: {ind.confidence:.0f}%)" if ind.confidence else ""
        lines.append(f"  {icon} <b>{escape(ind.name)}</b>{conf_str}")
        if ind.details:
            lines.append(f"     <i>{escape(ind.details)}</i>")

    # SMC
    if signal.smc:
        lines.append("")
        lines.append("🏗 <b>Smart Money Concepts</b>")
        smc = signal.smc
        if smc.bos_signals > 0:
            lines.append(f"  • Break of Structure: <b>{smc.bos_signals}</b> signals")
        if smc.fvg_signals > 0:
            lines.append(f"  • Fair Value Gaps: <b>{smc.fvg_signals}</b> detected")
        if smc.swing_highs:
            sh = ", ".join(f"{s:.5f}" for s in smc.swing_highs[-3:])
            lines.append(f"  • Recent swing highs: {sh}")
        if smc.swing_lows:
            sl = ", ".join(f"{s:.5f}" for s in smc.swing_lows[-3:])
            lines.append(f"  • Recent swing lows: {sl}")

    # Divergence
    if signal.divergence != SignalDirection.NEUTRAL:
        lines.append("")
        lines.append(f"⚠️ <b>RSI Divergence</b>: {signal.divergence.value}")

    # Sentiment
    if sentiment:
        lines.append("")
        lines.append("🗞 <b>Market Sentiment</b>")
        sent_emoji = "🟢" if sentiment.label == "Bullish" else ("🔴" if sentiment.label == "Bearish" else "🟡")
        lines.append(f"  {sent_emoji} Overall: <b>{sentiment.label}</b> (score: {sentiment.score:.0f})")

        risk_emoji = {"High": "🔴", "Medium": "🟡", "Normal": "🟢"}.get(sentiment.risk_level, "🟢")
        lines.append(f"  {risk_emoji} Risk level: <b>{sentiment.risk_level}</b>")

        if sentiment.headlines:
            lines.append(f"  📰 Top headlines ({len(sentiment.headlines)}):")
            for h in sentiment.headlines[:5]:
                h_emoji = {"Bullish": "🟢", "Bearish": "🔴", "Neutral": "🟡"}.get(h["sentiment"], "⚪")
                lines.append(f"    {h_emoji} {escape(h['title'][:80])}")

        if sentiment.events:
            high_events = [e for e in sentiment.events if e["impact"] == "High"]
            if high_events:
                lines.append(f"  📅 <b>Upcoming high-impact events</b>:")
                for ev in high_events[:5]:
                    lines.append(f"    • {escape(ev['currency'])}: {escape(ev['event'])} ({escape(ev['frequency'])})")

    # Summary
    lines.append("")
    lines.append(f"📝 <b>Summary</b>: {escape(signal.summary)}")

    # Disclaimer
    lines.append("")
    lines.append("<i>⚠️ This is not financial advice. Always do your own research.</i>")

    return "\n".join(lines)


def format_pairs_list(pairs: dict[str, str]) -> str:
    """Format the available forex pairs list."""
    lines = ["📋 <b>Available Forex Pairs</b>\n"]
    lines.append("<b>Majors:</b>")
    majors = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "NZD/USD", "USD/CAD", "USD/CHF"]
    for pair in majors:
        if pair in pairs:
            lines.append(f"  • {pair}")
    lines.append("\n<b>Crosses:</b>")
    crosses = [p for p in pairs if p not in majors and p != "USD/SGD" and p != "USD/HKD"]
    for pair in crosses[:15]:
        lines.append(f"  • {pair}")
    lines.append(f"\n<i>Use /signal {'<pair>'} to get a trading signal.</i>")
    return "\n".join(lines)


def format_help() -> str:
    return """🧭 <b>Forex Signal Bot — Commands</b>

<b>Analysis</b>
  /signal <i>pair</i> — Get a trading signal (e.g., /signal EUR/USD)
  /analysis <i>pair</i> — Full technical analysis with all indicators
  /sentiment <i>pair</i> — Market sentiment analysis
  /pairs — List available forex pairs

<b>Settings</b>
  /timeframe <i>tf</i> — Set timeframe: 5m, 15m, 1h, 4h, 1d
  /help — Show this help

<b>How it works</b>
1. The bot fetches live forex data from OANDA (or Yahoo Finance as fallback)
2. Computes technical indicators: SMA, RSI, MACD, Bollinger Bands, SMC
3. Analyzes market sentiment from news headlines
4. Generates a trading signal with entry, stop loss, and take profit levels

<i>⚠️ Not financial advice. Trade responsibly.</i>"""


def format_error(error_msg: str) -> str:
    return f"❌ <b>Error</b>: {escape(error_msg)}"


def split_long_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split a long message into Telegram-safe chunks."""
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
