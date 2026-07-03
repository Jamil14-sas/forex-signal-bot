"""Telegram HTML formatter for trading signals and analysis."""

from __future__ import annotations

from html import escape

from .indicators import IndicatorResult, SignalDirection
from .signal_service import RiskInfo, SignalStrength, TradeSignal
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

    # Risk management
    if signal.risk_info and signal.direction != SignalDirection.NEUTRAL:
        r = signal.risk_info
        lines.append("")
        lines.append("🛡 <b>Risk Management</b>")
        if r.risk_amount > 0:
            lines.append(f"  💵 Risk per trade: <b>${r.risk_amount:.2f}</b> ({r.risk_percent:.1f}% of ${r.account_balance:,.0f})")
        if r.position_size > 0:
            lines.append(f"  📐 Position size: <b>{r.position_size:.4f}</b> units")
        if r.risk_reward_ratio > 0:
            rr_emoji = "🟢" if r.risk_reward_ratio >= 2 else ("🟡" if r.risk_reward_ratio >= 1 else "🔴")
            lines.append(f"  {rr_emoji} Risk/Reward: <b>1:{r.risk_reward_ratio}</b>")
        if r.max_drawdown_warning:
            lines.append(f"  ⚠️ <b>Drawdown warning:</b> 5 consecutive losses would exceed safe limits")
        # Trailing stop
        trail = r.calc_trailing_stop(signal.current_price, signal.current_price, signal.direction)
        lines.append(f"  🎯 Trailing stop activation: <code>{trail:.5f}</code>")

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
  /signal <i>pair</i> — Trading signal (e.g., /signal EUR/USD)
  /analysis <i>pair</i> — Full technical analysis
  /multianalysis <i>pair</i> — Multi-timeframe analysis (3 TFs)
  /sentiment <i>pair</i> — News & event sentiment
  /pairs — List all available forex pairs

<b>History & Stats</b>
  /history — Your recent signal history
  /stats — Win rate & performance
  /resolve <i>won|lost</i> <i>id</i> — Mark signal outcome

<b>Scheduled Signals</b>
  /subscribe [time] [pairs] — Daily signal broadcasts
  /unsubscribe — Cancel broadcasts
  /mytime HH:MM — Change broadcast time (UTC)
  /mypairs EUR/USD,GBP/USD — Change tracked pairs

<b>Settings</b>
  /timeframe <i>tf</i> — Set timeframe: 5m, 15m, 1h, 4h, 1d
  /help — Show this help

<b>How it works</b>
1. Fetches live forex data from OANDA (Yahoo Finance fallback)
2. Computes SMA, RSI, MACD, Bollinger Bands, SMC patterns
3. Analyzes market sentiment from news headlines
4. Generates signal with entry/SL/TP + risk management (R:R, position sizing)

<i>⚠️ Not financial advice. Trade responsibly.</i>"""


def format_error(error_msg: str) -> str:
    return f"❌ <b>Error</b>: {escape(error_msg)}"


def format_multi_timeframe_analysis(
    pair: str,
    timeframes: list[str],
    results: list,
) -> str:
    """Format a multi-timeframe analysis showing all timeframes + confluence."""
    lines = [
        f"📊 <b>Multi-Timeframe Analysis — {pair}</b>",
        f"Analyzed across: {', '.join(f'<code>{tf}</code>' for tf in timeframes)}",
        "",
    ]

    # Confluence score
    direction_map = {}
    for i, r in enumerate(results):
        if isinstance(r, Exception) or r.signal is None:
            continue
        direction_map[timeframes[i]] = r.signal.direction.value

    buy_count = sum(1 for d in direction_map.values() if d == "BUY")
    sell_count = sum(1 for d in direction_map.values() if d == "SELL")
    neutral_count = sum(1 for d in direction_map.values() if d == "NEUTRAL")
    total = len(direction_map) or 1

    if buy_count > sell_count and buy_count >= 2:
        confluence = "🟢 <b>BULLISH CONFLUENCE</b>"
        con_pct = buy_count / total * 100
    elif sell_count > buy_count and sell_count >= 2:
        confluence = "🔴 <b>BEARISH CONFLUENCE</b>"
        con_pct = sell_count / total * 100
    else:
        confluence = "🟡 <b>MIXED / NEUTRAL</b>"
        con_pct = max(buy_count, sell_count) / total * 100

    bar_filled = round(con_pct / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)
    lines.append(f"{confluence}")
    lines.append(f"   <code>{bar}</code> {con_pct:.0f}% agreement")
    lines.append(f"   🟢{buy_count}  🔴{sell_count}  🟡{neutral_count}")
    lines.append("")

    # Individual timeframe results
    for i, tf in enumerate(timeframes):
        r = results[i]
        lines.append(f"─── <b>{tf}</b> {'─' * (20 - len(tf))}")

        if isinstance(r, Exception):
            lines.append(f"   ❌ Error: {r}")
            lines.append("")
            continue

        if r.signal is None:
            lines.append(f"   ❌ Error: {r.error}")
            lines.append("")
            continue

        emoji = "🟢" if r.signal.direction == SignalDirection.BUY else (
            "🔴" if r.signal.direction == SignalDirection.SELL else "🟡"
        )
        conf_bar = format_confidence_bar(r.signal.confidence)
        lines.append(f"   {emoji} <b>{r.signal.direction.value}</b> — {conf_bar}")
        lines.append(f"   💰 <code>{r.signal.current_price:.5f}</code>")
        if r.signal.direction != SignalDirection.NEUTRAL:
            lines.append(f"   🛑 SL: <code>{r.signal.stop_loss}</code>")
            if r.signal.take_profit:
                lines.append(f"   🏁 TP: <code>{', '.join(r.signal.take_profit)}</code>")
        if r.signal.risk_info and r.signal.risk_info.risk_reward_ratio > 0:
            lines.append(f"   📊 R:R 1:{r.signal.risk_info.risk_reward_ratio}")
        lines.append("")

    lines.append("<i>⚠️ Not financial advice. Trade responsibly.</i>")
    return "\n".join(lines)


def format_confidence_bar(percent: float) -> str:
    """Format a confidence bar (reusable outside signal context)."""
    p = max(0, min(100, float(percent)))
    filled = round(p / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"<code>{bar}</code> {p:.0f}%"


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
