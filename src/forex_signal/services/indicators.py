"""Technical indicators: SMA, RSI, MACD, Bollinger Bands, SMC patterns."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd


class SignalDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


@dataclass
class IndicatorResult:
    name: str
    direction: SignalDirection
    confidence: float  # 0-100
    value: float | None = None
    details: str = ""
    signal_line: float | None = None  # e.g. MACD signal line
    upper_band: float | None = None
    lower_band: float | None = None


@dataclass
class SMCResult:
    bos_signals: int = 0  # count of BOS signals
    fvg_signals: int = 0  # count of FVG signals
    swing_highs: list[float] = field(default_factory=list)
    swing_lows: list[float] = field(default_factory=list)
    order_blocks: list[dict] = field(default_factory=list)


def compute_indicators(df: pd.DataFrame) -> tuple[pd.DataFrame, list[IndicatorResult]]:
    """Compute all technical indicators and return signals for the latest bar."""
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    results: list[IndicatorResult] = []

    df = df.copy()

    # ---- SMA ----
    if len(close) >= 50:
        df["SMA_20"] = close.rolling(20).mean()
        df["SMA_50"] = close.rolling(50).mean()
        if len(close) >= 200:
            df["SMA_200"] = close.rolling(200).mean()

        sma20 = float(df["SMA_20"].iloc[-1])
        sma50 = float(df["SMA_50"].iloc[-1])
        current_price = float(close.iloc[-1])

        if pd.isna(sma20) or pd.isna(sma50):
            direction, confidence = SignalDirection.NEUTRAL, 10.0
            detail = "SMA not yet available — insufficient data"
        else:
            above_sma20 = current_price > sma20
            above_sma50 = current_price > sma50
            bullish_alignment = sma20 > sma50

            if above_sma20 and above_sma50 and bullish_alignment:
                direction, confidence = SignalDirection.BUY, 65.0
                detail = f"Price above SMA20 ({sma20:.5f}) & SMA50 ({sma50:.5f}), bullish alignment"
            elif not above_sma20 and not above_sma50 and not bullish_alignment:
                direction, confidence = SignalDirection.SELL, 65.0
                detail = f"Price below SMA20 ({sma20:.5f}) & SMA50 ({sma50:.5f}), bearish alignment"
            elif above_sma20:
                direction, confidence = SignalDirection.BUY, 45.0
                detail = f"Price above SMA20 ({sma20:.5f}), but mixed signals"
            else:
                direction, confidence = SignalDirection.NEUTRAL, 30.0
                detail = "Mixed SMA alignment — no clear direction"

        results.append(IndicatorResult(
            name="SMA Trend",
            direction=direction,
            confidence=confidence,
            value=current_price,
            details=detail,
        ))
    else:
        # Not enough data for SMA — emit neutral placeholder
        results.append(IndicatorResult(
            name="SMA Trend",
            direction=SignalDirection.NEUTRAL,
            confidence=0.0,
            value=float(close.iloc[-1]),
            details=f"Need {50 - len(close)} more bars for SMA (have {len(close)})",
        ))

    # ---- RSI (14) ----
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI_14"] = np.where(avg_loss == 0, 100, 100 - (100 / (1 + rs)))
    rsi = float(df["RSI_14"].iloc[-1])

    if rsi > 70:
        direction, confidence = SignalDirection.SELL, min(90.0, rsi)
        detail = f"RSI overbought at {rsi:.1f} — potential reversal down"
    elif rsi < 30:
        direction, confidence = SignalDirection.BUY, min(90.0, 100 - rsi)
        detail = f"RSI oversold at {rsi:.1f} — potential reversal up"
    elif rsi > 60:
        direction, confidence = SignalDirection.BUY, 50.0
        detail = f"RSI bullish momentum at {rsi:.1f}"
    elif rsi < 40:
        direction, confidence = SignalDirection.SELL, 50.0
        detail = f"RSI bearish momentum at {rsi:.1f}"
    else:
        direction, confidence = SignalDirection.NEUTRAL, 30.0
        detail = f"RSI neutral at {rsi:.1f}"

    results.append(IndicatorResult(
        name="RSI (14)",
        direction=direction,
        confidence=confidence,
        value=rsi,
        details=detail,
    ))

    # ---- MACD (12, 26, 9) ----
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_Signal"] = df["MACD"].ewm(span=9).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    macd_val = float(df["MACD"].iloc[-1])
    macd_signal = float(df["MACD_Signal"].iloc[-1])
    macd_hist = float(df["MACD_Hist"].iloc[-1])

    if macd_val > macd_signal and macd_hist > 0:
        rising = len(df) > 1 and macd_hist > float(df["MACD_Hist"].iloc[-2])
        if rising:
            direction, confidence = SignalDirection.BUY, 70.0
            detail = "MACD above signal, histogram rising — strong bullish momentum"
        else:
            direction, confidence = SignalDirection.BUY, 55.0
            detail = "MACD above signal, histogram weakening"
    elif macd_val < macd_signal and macd_hist < 0:
        direction, confidence = SignalDirection.SELL, 70.0
        detail = "MACD below signal, histogram negative — bearish momentum"
    else:
        direction, confidence = SignalDirection.NEUTRAL, 40.0
        detail = "MACD mixed — potential trend change"

    results.append(IndicatorResult(
        name="MACD",
        direction=direction,
        confidence=confidence,
        value=macd_val,
        signal_line=macd_signal,
        details=detail,
    ))

    # ---- Bollinger Bands (20, 2) ----
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["BB_Mid"] = bb_mid
    df["BB_Upper"] = bb_mid + 2 * bb_std
    df["BB_Lower"] = bb_mid - 2 * bb_std
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Mid"] * 100

    price = close.iloc[-1]
    bb_upper_val = float(df["BB_Upper"].iloc[-1])
    bb_lower_val = float(df["BB_Lower"].iloc[-1])
    bb_mid_val = float(df["BB_Mid"].iloc[-1])
    bb_width = float(df["BB_Width"].iloc[-1])

    if price >= bb_upper_val:
        direction, confidence = SignalDirection.SELL, 60.0
        detail = f"Price at upper band ({bb_upper_val:.5f}) — overbought, mean reversion likely"
    elif price <= bb_lower_val:
        direction, confidence = SignalDirection.BUY, 60.0
        detail = f"Price at lower band ({bb_lower_val:.5f}) — oversold, mean reversion likely"
    elif price > bb_mid_val:
        direction, confidence = SignalDirection.BUY, 45.0
        detail = f"Price above mid-band ({bb_mid_val:.5f}) — mild bullish bias"
    else:
        direction, confidence = SignalDirection.SELL, 45.0
        detail = f"Price below mid-band ({bb_mid_val:.5f}) — mild bearish bias"

    results.append(IndicatorResult(
        name="Bollinger Bands",
        direction=direction,
        confidence=confidence,
        value=price,
        upper_band=bb_upper_val,
        lower_band=bb_lower_val,
        details=detail,
    ))

    return df, results


def compute_smc(df: pd.DataFrame) -> SMCResult:
    """Compute Smart Money Concept patterns: swing points, BOS, FVG, order blocks."""
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)

    result = SMCResult()

    # Find swing points (lookback=5)
    lookback = 5
    swing_highs = []
    swing_lows = []
    for i in range(lookback, len(high) - lookback):
        if high.iloc[i] == high.iloc[i - lookback:i + lookback + 1].max():
            swing_highs.append(float(high.iloc[i]))
        if low.iloc[i] == low.iloc[i - lookback:i + lookback + 1].min():
            swing_lows.append(float(low.iloc[i]))

    result.swing_highs = swing_highs[-5:] if swing_highs else []
    result.swing_lows = swing_lows[-5:] if swing_lows else []

    # Break of Structure (BOS)
    last_high = None
    last_low = None
    trend = 0  # 1=uptrend, -1=downtrend
    bos_count = 0

    for i in range(1, len(high)):
        # Detect swing high
        if i >= lookback and i < len(high) - lookback:
            if high.iloc[i] == high.iloc[i - lookback:i + lookback + 1].max():
                sh = float(high.iloc[i])
                if last_high is not None and sh > last_high:
                    trend = 1
                last_high = sh
            if low.iloc[i] == low.iloc[i - lookback:i + lookback + 1].min():
                sl = float(low.iloc[i])
                if last_low is not None and sl < last_low:
                    trend = -1
                last_low = sl

        # Check BOS
        if trend == 1 and last_high is not None and close.iloc[i] > last_high:
            bos_count += 1
        elif trend == -1 and last_low is not None and close.iloc[i] < last_low:
            bos_count += 1

    result.bos_signals = bos_count

    # Fair Value Gaps (FVG)
    fvg_count = 0
    for i in range(3, len(high)):
        if low.iloc[i] > high.iloc[i - 2]:
            fvg_count += 1
        elif high.iloc[i] < low.iloc[i - 2]:
            fvg_count += 1
    result.fvg_signals = fvg_count

    # Order blocks: areas of strong buying/selling
    for i in range(lookback, len(high) - lookback):
        if high.iloc[i] == high.iloc[i - lookback:i + lookback + 1].max():
            result.order_blocks.append({
                "type": "bearish",
                "price": float(high.iloc[i]),
                "index": i,
            })
        if low.iloc[i] == low.iloc[i - lookback:i + lookback + 1].min():
            result.order_blocks.append({
                "type": "bullish",
                "price": float(low.iloc[i]),
                "index": i,
            })

    return result


def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Compute Average True Range for stop-loss placement."""
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(period).mean()

    return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else float(true_range.mean())


def detect_divergence(df: pd.DataFrame) -> SignalDirection:
    """Detect RSI divergence with price (simplified)."""
    if len(df) < 20 or "RSI_14" not in df.columns:
        return SignalDirection.NEUTRAL

    close = df["Close"].tail(20)
    rsi = df["RSI_14"].tail(20)

    # Find local peaks in price and RSI over last 20 bars
    price_higher = close.iloc[-1] > close.iloc[-11:-1].max() if len(close) > 10 else False
    price_lower = close.iloc[-1] < close.iloc[-11:-1].min() if len(close) > 10 else False
    rsi_higher = rsi.iloc[-1] > rsi.iloc[-11:-1].max() if len(rsi) > 10 else False
    rsi_lower = rsi.iloc[-1] < rsi.iloc[-11:-1].min() if len(rsi) > 10 else False

    # Bearish divergence: price makes higher high, RSI makes lower high
    if price_higher and not rsi_higher and rsi.iloc[-1] < 60:
        return SignalDirection.SELL
    # Bullish divergence: price makes lower low, RSI makes higher low
    if price_lower and not rsi_lower and rsi.iloc[-1] > 40:
        return SignalDirection.BUY

    return SignalDirection.NEUTRAL
