"""Sentiment analysis: news headlines + economic calendar risk scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import httpx

from ..config import Settings, get_settings

# Economic calendar: high-impact event keywords for forex
HIGH_IMPACT_KEYWORDS = [
    "Nonfarm Payrolls", "NFP", "FOMC", "Federal Reserve", "Interest Rate Decision",
    "CPI", "Inflation", "GDP", "Unemployment", "Retail Sales", "PMI",
    "Central Bank", "ECB", "BOE", "BOJ", "RBA", "RBNZ",
    "Trade Balance", "Consumer Confidence", "Manufacturing", "Services PMI",
]

# Forex-related news keywords for filtering
FOREX_KEYWORDS = [
    "forex", "USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF",
    "dollar", "euro", "pound", "yen", "fed", "ecb", "boe", "boj",
    "currency", "exchange rate", "fx",
]


@dataclass
class SentimentResult:
    score: float  # -100 (bearish) to +100 (bullish)
    label: str  # "Bullish", "Bearish", "Neutral"
    headlines: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    risk_level: str = "Normal"  # "High", "Medium", "Normal"


class SentimentService:
    """Analyze forex sentiment from news and economic calendar."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    async def close(self) -> None:
        await self._http.aclose()

    async def analyze(self, pair: str) -> SentimentResult:
        """Run sentiment analysis for a forex pair."""
        headlines = []
        events = []
        score = 0.0
        count = 0

        # Extract currencies from pair
        base, quote = self._split_pair(pair)

        # Try NewsAPI
        if self._settings.news_enabled and self._settings.news_api_key:
            try:
                news_data = await self._fetch_news(pair, base, quote)
                for article in news_data:
                    headline_text = article.get("title", "")
                    desc = article.get("description", "")
                    full_text = f"{headline_text}. {desc}"

                    s = self._analyze_text_sentiment(full_text)
                    headlines.append({
                        "title": headline_text,
                        "sentiment": s["label"],
                        "score": s["score"],
                        "source": article.get("source", {}).get("name", "Unknown"),
                    })
                    if s["score"] != 0:
                        score += s["score"]
                        count += 1
            except Exception:
                pass

        # Economic calendar risk
        events = self._get_economic_events(base, quote)
        high_risk_events = [e for e in events if e["impact"] == "High"]
        if high_risk_events:
            # Clamp sentiment when high-impact events ahead
            if score > 0:
                score = max(score * 0.7, 0)  # Reduce bullish bias
            elif score < 0:
                score = min(score * 0.7, 0)  # Reduce bearish bias

        # Normalize score
        if count > 0:
            score = score / count
        score = max(-100, min(100, score))

        # Label
        if score > 25:
            label = "Bullish"
        elif score < -25:
            label = "Bearish"
        else:
            label = "Neutral"

        # Risk level
        if len(high_risk_events) >= 2:
            risk_level = "High"
        elif len(high_risk_events) == 1:
            risk_level = "Medium"
        else:
            risk_level = "Normal"

        return SentimentResult(
            score=score,
            label=label,
            headlines=headlines,
            events=events,
            risk_level=risk_level,
        )

    async def _fetch_news(self, pair: str, base: str, quote: str) -> list[dict]:
        """Fetch forex-related news from NewsAPI."""
        url = "https://newsapi.org/v2/everything"
        query = f"forex {base} {quote} currency"
        params = {
            "q": query,
            "apiKey": self._settings.news_api_key,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 10,
        }

        resp = await self._http.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("articles", [])[:10]

    def _analyze_text_sentiment(self, text: str) -> dict:
        """Run VADER sentiment on text."""
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            analyzer = SentimentIntensityAnalyzer()
            scores = analyzer.polarity_scores(text)
            compound = scores["compound"]
            if compound >= 0.2:
                return {"label": "Bullish", "score": compound * 100}
            elif compound <= -0.2:
                return {"label": "Bearish", "score": compound * 100}
            else:
                return {"label": "Neutral", "score": 0}
        except ImportError:
            # Fallback: simple keyword matching
            bullish_words = ["bullish", "surge", "rally", "gain", "rise", "up", "strong", "boost", "growth"]
            bearish_words = ["bearish", "plunge", "fall", "drop", "decline", "weak", "loss", "crash", "fears"]
            text_lower = text.lower()
            bull_count = sum(1 for w in bullish_words if w in text_lower)
            bear_count = sum(1 for w in bearish_words if w in text_lower)
            if bull_count > bear_count:
                return {"label": "Bullish", "score": 50}
            elif bear_count > bull_count:
                return {"label": "Bearish", "score": -50}
            return {"label": "Neutral", "score": 0}

    def _get_economic_events(self, base: str, quote: str) -> list[dict]:
        """Get upcoming high-impact economic events for the currencies."""
        events = []

        # Map currencies to their events
        currency_events = {
            "USD": [
                ("NFP", "First Friday", "High"),
                ("FOMC Meeting", "Every 6 weeks", "High"),
                ("CPI", "Monthly, mid-month", "High"),
                ("GDP", "Monthly, end of month", "Medium"),
                ("Retail Sales", "Monthly, mid-month", "Medium"),
                ("ISM PMI", "Monthly, first week", "Medium"),
            ],
            "EUR": [
                ("ECB Rate Decision", "Every 6 weeks", "High"),
                ("CPI Flash", "Monthly, end of month", "High"),
                ("GDP", "Monthly", "Medium"),
            ],
            "GBP": [
                ("BOE Rate Decision", "Every 6 weeks", "High"),
                ("CPI", "Monthly, mid-month", "High"),
                ("GDP", "Monthly", "Medium"),
            ],
            "JPY": [
                ("BOJ Rate Decision", "Every 6-8 weeks", "High"),
                ("CPI", "Monthly", "Medium"),
            ],
            "AUD": [
                ("RBA Rate Decision", "Monthly", "High"),
                ("Employment Change", "Monthly", "High"),
            ],
            "NZD": [
                ("RBNZ Rate Decision", "Every 6 weeks", "High"),
                ("CPI", "Quarterly", "Medium"),
            ],
            "CAD": [
                ("BOC Rate Decision", "Every 6 weeks", "High"),
                ("CPI", "Monthly", "Medium"),
                ("Employment", "Monthly", "High"),
            ],
            "CHF": [
                ("SNB Rate Decision", "Quarterly", "High"),
                ("CPI", "Monthly", "Medium"),
            ],
        }

        for currency in (base, quote):
            for event_name, frequency, impact in currency_events.get(currency, []):
                events.append({
                    "currency": currency,
                    "event": event_name,
                    "frequency": frequency,
                    "impact": impact,
                })

        return events

    @staticmethod
    def _split_pair(pair: str) -> tuple[str, str]:
        """Extract base and quote currency from pair."""
        pair = pair.replace("/", "_").upper()
        # Common forex pairs
        known = ["EUR", "GBP", "USD", "JPY", "AUD", "NZD", "CAD", "CHF", "SGD", "HKD", "NOK", "SEK", "MXN", "ZAR"]
        for cur in known:
            if pair.startswith(cur):
                rest = pair[len(cur):].lstrip("_")
                for cur2 in known:
                    if rest == cur2:
                        return cur, cur2
        # Fallback
        parts = pair.split("_")
        return parts[0][:3] if len(parts) > 0 else "XXX", parts[1][:3] if len(parts) > 1 else "YYY"
