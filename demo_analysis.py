#!/usr/bin/env python3
"""Demo: fetch EUR/USD data from OANDA, compute indicators, generate a signal."""
import os, sys, json
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

# Parse .env
with open(os.path.join(os.path.dirname(__file__), ".env")) as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            if k in ("OANDA_API_KEY", "OANDA_API_URL"):
                os.environ[k] = v

API_KEY = os.environ.get("OANDA_API_KEY", "")
API_URL = os.environ.get("OANDA_API_URL", "https://api-fxpractice.oanda.com/v3")

if not API_KEY:
    print("OANDA_API_KEY not set in .env")
    sys.exit(1)

# --- 1. Fetch EUR/USD candles ---
to_time = datetime.now(timezone.utc)
from_time = to_time - timedelta(days=90)
fmt = "%Y-%m-%dT%H:%M:%SZ"

url = f"{API_URL}/instruments/EUR_USD/candles"
params = f"from={from_time.strftime(fmt)}&to={to_time.strftime(fmt)}&granularity=H1&price=M"

print(f"📡 Fetching EUR/USD data (H1, 90 days)...")
req = Request(f"{url}?{params}", headers={"Authorization": f"Bearer {API_KEY}"})
with urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read())

candles = data["candles"]
print(f"   Got {len(candles)} candles")

# --- 2. Compute indicators (pure Python + numpy) ---
import numpy as np

closes = np.array([float(c["mid"]["c"]) for c in candles])
highs = np.array([float(c["mid"]["h"]) for c in candles])
lows = np.array([float(c["mid"]["l"]) for c in candles])

print(f"\n📊 Computing indicators...")
current_price = closes[-1]

# RSI (14)
def compute_rsi(prices, period=14):
    deltas = np.diff(prices, prepend=prices[0])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.convolve(gains, np.ones(period)/period, mode='valid')
    avg_loss = np.convolve(losses, np.ones(period)/period, mode='valid')
    rs = np.divide(avg_gain, avg_loss, out=np.ones_like(avg_gain)*100, where=avg_loss!=0)
    return 100 - (100 / (1 + rs))[-1]

rsi = compute_rsi(closes)
print(f"   RSI (14): {rsi:.1f}")

# SMA
sma20 = np.mean(closes[-20:])
sma50 = np.mean(closes[-50:]) if len(closes) >= 50 else None
print(f"   SMA 20: {sma20:.5f}")
if sma50:
    print(f"   SMA 50: {sma50:.5f}")

# Bollinger Bands
bb_mid = np.mean(closes[-20:])
bb_std = np.std(closes[-20:])
bb_upper = bb_mid + 2 * bb_std
bb_lower = bb_mid - 2 * bb_std
print(f"   BB Upper: {bb_upper:.5f}, BB Lower: {bb_lower:.5f}")

# MACD
def ema(data, span):
    alpha = 2 / (span + 1)
    result = data[0]
    for val in data[1:]:
        result = alpha * val + (1 - alpha) * result
    return result

ema12 = ema(closes[-26:], 12)
ema26 = ema(closes[-26:], 26)
macd = ema12 - ema26
signal_line = ema(np.array([macd] * 9), 9)  # simplified
print(f"   MACD: {macd:.6f}")

# ATR
tr = np.maximum(highs[-14:] - lows[-14:],
                np.maximum(np.abs(highs[-14:] - np.roll(closes[-14:], 1)),
                           np.abs(lows[-14:] - np.roll(closes[-14:], 1))))
atr = np.mean(tr[1:])
print(f"   ATR (14): {atr:.5f}")

# --- 3. Generate signal ---
print(f"\n🎯 Signal Generation:")
print(f"   Pair: EUR/USD")
print(f"   Timeframe: 1H")
print(f"   Current price: {current_price:.5f}")

buy_signals = 0
sell_signals = 0

# RSI
if rsi < 30:
    buy_signals += 1
    print(f"   🟢 RSI oversold ({rsi:.1f})")
elif rsi > 70:
    sell_signals += 1
    print(f"   🔴 RSI overbought ({rsi:.1f})")
else:
    print(f"   🟡 RSI neutral ({rsi:.1f})")

# Price vs SMA
if sma50:
    if current_price > sma20 > sma50:
        buy_signals += 1
        print(f"   🟢 Price above SMA20 & SMA50 (bullish alignment)")
    elif current_price < sma20 < sma50:
        sell_signals += 1
        print(f"   🔴 Price below SMA20 & SMA50 (bearish alignment)")
    else:
        print(f"   🟡 Mixed SMA alignment")

# Bollinger Bands
if current_price >= bb_upper:
    sell_signals += 1
    print(f"   🔴 Price at upper BB band")
elif current_price <= bb_lower:
    buy_signals += 1
    print(f"   🟢 Price at lower BB band")
else:
    band_pct = (current_price - bb_lower) / (bb_upper - bb_lower) * 100
    print(f"   🟡 Price at {band_pct:.0f}% of BB range")

# MACD
if macd > 0:
    buy_signals += 1
    print(f"   🟢 MACD positive ({macd:.6f})")
else:
    sell_signals += 1
    print(f"   🔴 MACD negative ({macd:.6f})")

# Final signal
print(f"\n{'='*45}")
net = buy_signals - sell_signals
if net >= 2:
    direction = "🟢 BUY"
    sl = current_price - atr * 2
    tp = current_price + atr * 3
elif net <= -2:
    direction = "🔴 SELL"
    sl = current_price + atr * 2
    tp = current_price - atr * 3
else:
    direction = "🟡 NEUTRAL"
    sl = tp = 0

confidence = min(95, max(10, abs(net) / 4 * 100))
print(f"   SIGNAL: {direction}")
print(f"   Confidence: {confidence:.0f}%")
print(f"   Price: {current_price:.5f}")
if direction != "🟡 NEUTRAL":
    print(f"   Stop Loss: {sl:.5f}")
    print(f"   Take Profit: {tp:.5f}")
print(f"   Buy signals: {buy_signals}, Sell signals: {sell_signals}")
print(f"{'='*45}")
