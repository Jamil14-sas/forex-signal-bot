"""Fetch forex data from OANDA (primary) with yfinance fallback."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import pandas as pd

from ..config import Settings, get_settings

# Major forex pairs
FOREX_PAIRS: dict[str, str] = {
    "EUR/USD": "EUR_USD",
    "GBP/USD": "GBP_USD",
    "USD/JPY": "USD_JPY",
    "AUD/USD": "AUD_USD",
    "NZD/USD": "NZD_USD",
    "USD/CAD": "USD_CAD",
    "USD/CHF": "USD_CHF",
    "EUR/GBP": "EUR_GBP",
    "EUR/JPY": "EUR_JPY",
    "GBP/JPY": "GBP_JPY",
    "EUR/CHF": "EUR_CHF",
    "AUD/JPY": "AUD_JPY",
    "NZD/JPY": "NZD_JPY",
    "GBP/AUD": "GBP_AUD",
    "GBP/CAD": "GBP_CAD",
    "EUR/AUD": "EUR_AUD",
    "EUR/CAD": "EUR_CAD",
    "AUD/CAD": "AUD_CAD",
    "AUD/NZD": "AUD_NZD",
    "NZD/CAD": "NZD_CAD",
    "USD/SGD": "USD_SGD",
    "USD/HKD": "USD_HKD",
    "EUR/NZD": "EUR_NZD",
    "GBP/NZD": "GBP_NZD",
    "USD/NOK": "USD_NOK",
    "USD/SEK": "USD_SEK",
    "USD/MXN": "USD_MXN",
    "USD/ZAR": "USD_ZAR",
}

OANDA_GRANULARITY = {
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "4h": "H4",
    "1d": "D",
    "1wk": "W",
}

YFINANCE_INTERVAL_MAP = {
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "1h",
    "1d": "1d",
    "1wk": "1wk",
}

YFINANCE_PERIOD_MAP = {
    "5m": "5d",
    "15m": "5d",
    "30m": "5d",
    "1h": "7d",
    "4h": "30d",
    "1d": "90d",
    "1wk": "1y",
}


def resolve_pair(query: str) -> str | None:
    """Normalize a user-entered pair string to an OANDA instrument name."""
    q = query.upper().replace(" ", "").replace("-", "/")
    if q in FOREX_PAIRS:
        return FOREX_PAIRS[q]
    # Try OANDA format directly
    for display, oanda in FOREX_PAIRS.items():
        if q == oanda:
            return oanda
        if q == display.replace("/", ""):
            return oanda
    return None


def resolve_display_name(oanda_name: str) -> str:
    for display, oanda in FOREX_PAIRS.items():
        if oanda == oanda_name:
            return display
    return oanda_name.replace("_", "/")


@dataclass
class CachedData:
    df: pd.DataFrame
    fetched_at: float = field(default_factory=time.monotonic)


class DataService:
    """Fetch OHLC forex data, OANDA first, yfinance fallback."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._cache: dict[str, CachedData] = {}
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={"Authorization": f"Bearer {self._settings.oanda_api_key}"}
            if self._settings.oanda_api_key
            else {},
        )

    async def close(self) -> None:
        await self._http.aclose()

    # ---- Public API ------------------------------------------------------

    async def fetch(
        self,
        pair: str,
        timeframe: str = "1h",
        period_days: int | None = None,
        *,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Fetch OHLC data for a forex pair. Returns DataFrame with OHLCV columns."""
        oanda_pair = resolve_pair(pair)
        if oanda_pair is None:
            raise ValueError(
                f"Unknown pair: {pair}. Try EUR/USD, GBP/USD, USD/JPY, etc."
            )

        period = period_days or self._settings.default_period_days
        cache_key = f"{oanda_pair}:{timeframe}:{period}"

        if not force_refresh:
            cached = self._cache.get(cache_key)
            if cached and (time.monotonic() - cached.fetched_at) < self._settings.cache_ttl_seconds:
                return cached.df.copy()

        # Try OANDA first
        if self._settings.oanda_api_key:
            try:
                df = await self._fetch_oanda(oanda_pair, timeframe, period)
                self._cache[cache_key] = CachedData(df)
                return df.copy()
            except Exception:
                pass

        # Fallback to yfinance
        df = await self._fetch_yfinance(oanda_pair, timeframe, period)
        self._cache[cache_key] = CachedData(df)
        return df.copy()

    # ---- OANDA -----------------------------------------------------------

    async def _fetch_oanda(self, pair: str, timeframe: str, period_days: int) -> pd.DataFrame:
        granularity = OANDA_GRANULARITY.get(timeframe, "H1")
        to_time = datetime.now(timezone.utc)
        from_time = to_time - timedelta(days=period_days)
        fmt = "%Y-%m-%dT%H:%M:%SZ"

        url = f"{self._settings.oanda_api_url}/instruments/{pair}/candles"
        params = {
            "from": from_time.strftime(fmt),
            "to": to_time.strftime(fmt),
            "granularity": granularity,
            "price": "M",  # midpoint prices
        }

        resp = await self._http.get(url, params=params)
        if resp.status_code == 401:
            raise ValueError("OANDA API key rejected. Check your token.")
        resp.raise_for_status()

        data = resp.json()
        candles = data.get("candles", [])
        if not candles:
            raise ValueError(f"No OANDA data for {pair} (timeframe={timeframe}).")

        rows, idx = [], []
        for c in candles:
            mid = c.get("mid", c)
            rows.append({
                "Open": float(mid["o"]),
                "High": float(mid["h"]),
                "Low": float(mid["l"]),
                "Close": float(mid["c"]),
                "Volume": int(c.get("volume", 0)),
            })
            idx.append(pd.to_datetime(c["time"][:19]))

        df = pd.DataFrame(rows, index=pd.Index(idx, name="Date"))
        df.sort_index(inplace=True)
        return df

    # ---- Yahoo Finance ---------------------------------------------------

    async def _fetch_yfinance(self, pair: str, timeframe: str, period_days: int) -> pd.DataFrame:
        ticker = f"{pair}=X"
        yf_interval = YFINANCE_INTERVAL_MAP.get(timeframe, "1h")
        yf_period = YFINANCE_PERIOD_MAP.get(timeframe, "90d")

        def _download():
            df = yf.download(
                ticker,
                period=yf_period,
                interval=yf_interval,
                progress=False,
                auto_adjust=True,
            )
            if df.empty:
                raise ValueError(f"No yfinance data for {pair}")
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df

        df = await asyncio.to_thread(_download)

        # Rename to standard OHLCV columns
        col_map = {
            "Open": "Open", "High": "High", "Low": "Low",
            "Close": "Close", "Volume": "Volume",
        }
        df = df.rename(columns={c: col_map.get(c, c) for c in df.columns})
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                df[col] = 0.0

        df.sort_index(inplace=True)
        return df
