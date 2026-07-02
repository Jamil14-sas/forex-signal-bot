"""Analysis orchestrator: combine data + indicators + sentiment + signals."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pandas as pd

import structlog

from ..config import Settings, get_settings
from .data_service import DataService, resolve_display_name, resolve_pair
from .indicators import SMCResult, compute_smc
from .sentiment import SentimentResult, SentimentService
from .signal_service import SignalService, TradeSignal

logger = structlog.get_logger(__name__)


@dataclass
class FullAnalysis:
    signal: TradeSignal
    sentiment: SentimentResult | None
    df: pd.DataFrame


class AnalysisService:
    """Orchestrate data fetching, indicator computation, and signal generation."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._data = DataService(self._settings)
        self._signals = SignalService()
        self._sentiment = SentimentService(self._settings)

    async def close(self) -> None:
        await self._data.close()
        await self._sentiment.close()

    async def analyze_sentiment(self, pair: str) -> SentimentResult:
        """Public method for sentiment-only analysis."""
        return await self._sentiment.analyze(pair)

    async def analyze(
        self,
        pair: str,
        timeframe: str = "1h",
        *,
        include_sentiment: bool = True,
    ) -> FullAnalysis:
        """Run a full analysis for a forex pair."""
        display = resolve_display_name(resolve_pair(pair) or pair)

        # Fetch data
        df = await self._data.fetch(pair, timeframe=timeframe)

        if len(df) < 30:
            raise ValueError(f"Not enough data ({len(df)} bars). Try a longer period or smaller timeframe.")

        # Sentiment (don't block on failure)
        sentiment: SentimentResult | None = None
        if include_sentiment:
            try:
                sentiment = await self._sentiment.analyze(pair)
            except Exception as exc:
                logger.warning("sentiment_analysis_failed", pair=pair, error=str(exc))

        # Compute SMC
        try:
            smc = compute_smc(df)
        except Exception:
            smc = SMCResult()

        # Generate signal
        sentiment_score = sentiment.score if sentiment else 0.0
        signal = self._signals.generate(
            df,
            pair=display,
            timeframe=timeframe,
            smc_result=smc,
            sentiment_score=sentiment_score,
        )

        return FullAnalysis(signal=signal, sentiment=sentiment, df=df)
