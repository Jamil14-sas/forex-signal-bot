"""Trading signal generation from indicator confluence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from dataclasses import dataclass

import pandas as pd

from .indicators import (
    IndicatorResult,
    SignalDirection,
    SMCResult,
    compute_atr,
    compute_indicators,
    compute_smc,
    detect_divergence,
)


class SignalStrength(Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NEUTRAL = "NEUTRAL"


@dataclass
class RiskInfo:
    """Risk management calculations for a trade."""
    account_balance: float
    risk_percent: float
    atr: float
    position_size: float = 0.0
    risk_amount: float = 0.0
    risk_reward_ratio: float = 0.0
    max_drawdown_warning: bool = False

    def calc_position_size(self, entry: float, stop_loss: float) -> None:
        """Calculate position size based on account risk."""
        risk_per_trade = self.account_balance * (self.risk_percent / 100.0)
        price_risk = abs(entry - stop_loss)
        if price_risk > 0:
            self.position_size = risk_per_trade / price_risk
        self.risk_amount = risk_per_trade

    def calc_risk_reward(self, entry: float, stop_loss: float, take_profit: float) -> None:
        """Calculate risk/reward ratio."""
        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)
        if risk > 0:
            self.risk_reward_ratio = round(reward / risk, 2)

    def calc_trailing_stop(self, entry: float, current_price: float, direction: SignalDirection) -> float:
        """Calculate trailing stop level using ATR."""
        atr_multiple = 2.0
        if direction == SignalDirection.BUY:
            return current_price - (self.atr * atr_multiple)
        else:
            return current_price + (self.atr * atr_multiple)


@dataclass
class TradeSignal:
    pair: str
    timeframe: str
    direction: SignalDirection
    strength: SignalStrength
    confidence: float  # 0-100
    current_price: float
    entry_zone: str
    stop_loss: str
    take_profit: list[str] = field(default_factory=list)
    indicators: list[IndicatorResult] = field(default_factory=list)
    smc: SMCResult | None = None
    divergence: SignalDirection = SignalDirection.NEUTRAL
    summary: str = ""
    sentiment_score: float = 0.0  # from sentiment analysis
    risk_info: RiskInfo | None = None  # risk management calculations


# Indicator weight for signal scoring
WEIGHTS = {
    "SMA Trend": 1.0,
    "RSI (14)": 1.2,
    "MACD": 1.1,
    "Bollinger Bands": 0.9,
}


class SignalService:
    """Generate trading signals from technical indicators and SMC."""

    def generate(
        self,
        df: pd.DataFrame,
        pair: str,
        timeframe: str,
        *,
        smc_result: SMCResult | None = None,
        sentiment_score: float = 0.0,
        risk_info: RiskInfo | None = None,
    ) -> TradeSignal:
        df_ind, indicators = compute_indicators(df)

        if smc_result is None:
            smc_result = compute_smc(df_ind)

        divergence = detect_divergence(df_ind)

        close = df_ind["Close"].astype(float)
        current_price = float(close.iloc[-1])
        atr = compute_atr(df)

        # Weighted scoring
        buy_score = 0.0
        sell_score = 0.0
        total_weight = 0.0

        for ind in indicators:
            w = WEIGHTS.get(ind.name, 0.8)
            if ind.direction == SignalDirection.BUY:
                buy_score += ind.confidence * w
            elif ind.direction == SignalDirection.SELL:
                sell_score += ind.confidence * w
            total_weight += w

        # Add SMC influence
        if smc_result.bos_signals > 0:
            buy_score += min(20, smc_result.bos_signals * 5) * 1.5
        if smc_result.fvg_signals > 0:
            # FVGs can be bullish or bearish — use context
            pass

        # Add divergence
        if divergence == SignalDirection.BUY:
            buy_score += 30
        elif divergence == SignalDirection.SELL:
            sell_score += 30

        # Normalize
        if total_weight > 0:
            buy_score = buy_score / total_weight
            sell_score = sell_score / total_weight

        # Determine direction
        net_score = buy_score - sell_score

        # Integrate sentiment into scoring
        if sentiment_score > 25:
            net_score += abs(sentiment_score) * 0.3
        elif sentiment_score < -25:
            net_score -= abs(sentiment_score) * 0.3

        if net_score > 25:
            direction = SignalDirection.BUY
        elif net_score < -25:
            direction = SignalDirection.SELL
        else:
            direction = SignalDirection.NEUTRAL

        # Confidence
        confidence = abs(net_score)
        if direction == SignalDirection.NEUTRAL:
            confidence = max(buy_score, sell_score) * 0.5
        confidence = min(95, max(10, confidence))

        # Strength
        if confidence >= 70:
            strength = SignalStrength.STRONG
        elif confidence >= 45:
            strength = SignalStrength.MODERATE
        elif confidence >= 25:
            strength = SignalStrength.WEAK
        else:
            strength = SignalStrength.NEUTRAL

        # Entry / SL / TP
        if direction == SignalDirection.BUY:
            sl_distance = atr * 2.0
            stop_loss = f"{current_price - sl_distance:.5f}"
            tp1 = f"{current_price + atr * 2:.5f}"
            tp2 = f"{current_price + atr * 3.5:.5f}"
            entry_zone = f"{current_price - atr * 0.5:.5f} – {current_price:.5f}"
        elif direction == SignalDirection.SELL:
            sl_distance = atr * 2.0
            stop_loss = f"{current_price + sl_distance:.5f}"
            tp1 = f"{current_price - atr * 2:.5f}"
            tp2 = f"{current_price - atr * 3.5:.5f}"
            entry_zone = f"{current_price:.5f} – {current_price + atr * 0.5:.5f}"
        else:
            stop_loss = "N/A"
            tp1 = tp2 = "N/A"
            entry_zone = f"{current_price:.5f}"

        take_profit = [tp1, tp2] if direction != SignalDirection.NEUTRAL else []

        # Summary
        buy_indicators = [i.name for i in indicators if i.direction == SignalDirection.BUY]
        sell_indicators = [i.name for i in indicators if i.direction == SignalDirection.SELL]

        parts = []
        if direction == SignalDirection.BUY:
            parts.append(f"🟢 BUY signal on {pair} ({timeframe})")
        elif direction == SignalDirection.SELL:
            parts.append(f"🔴 SELL signal on {pair} ({timeframe})")
        else:
            parts.append(f"🟡 NEUTRAL on {pair} ({timeframe}) — no clear direction")

        if buy_indicators:
            parts.append(f"Bullish: {', '.join(buy_indicators)}")
        if sell_indicators:
            parts.append(f"Bearish: {', '.join(sell_indicators)}")
        if smc_result.bos_signals > 0:
            parts.append(f"SMC: {smc_result.bos_signals} BOS signals detected")
        if divergence != SignalDirection.NEUTRAL:
            parts.append(f"⚠️ RSI divergence: {divergence.value}")

        summary = " | ".join(parts)

        # Risk management calculations
        if risk_info is not None and direction != SignalDirection.NEUTRAL:
            sl_price = float(stop_loss) if stop_loss != "N/A" else 0
            tp_prices = [float(tp) for tp in take_profit if tp != "N/A"]
            risk_info.calc_position_size(current_price, sl_price)
            if tp_prices:
                risk_info.calc_risk_reward(current_price, sl_price, tp_prices[0])
            # Check max drawdown
            if risk_info.risk_amount > 0:
                consecutive_losses = 5  # assume worst case
                total_risk = risk_info.risk_amount * consecutive_losses
                drawdown_pct = (total_risk / risk_info.account_balance) * 100
                if drawdown_pct > 20:  # configurable
                    risk_info.max_drawdown_warning = True

        return TradeSignal(
            pair=pair,
            timeframe=timeframe,
            direction=direction,
            strength=strength,
            confidence=round(confidence, 1),
            current_price=current_price,
            entry_zone=entry_zone,
            stop_loss=stop_loss,
            take_profit=take_profit,
            indicators=indicators,
            smc=smc_result,
            divergence=divergence,
            summary=summary,
            sentiment_score=sentiment_score,
            risk_info=risk_info,
        )
