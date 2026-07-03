"""Analysis orchestrator: combine data + indicators + sentiment + signals."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import pandas as pd

import structlog

from ..config import Settings, get_settings
from .data_service import DataService, resolve_display_name, resolve_pair
from .indicators import SMCResult, compute_smc
from .sentiment import SentimentResult, SentimentService
from .signal_service import RiskInfo, SignalService, TradeSignal

logger = structlog.get_logger(__name__)


@dataclass
class FullAnalysis:
    signal: TradeSignal
    sentiment: SentimentResult | None
    df: pd.DataFrame


@dataclass
class TimeframeAnalysis:
    timeframe: str
    signal: TradeSignal
    sentiment: SentimentResult | None
    error: str | None = None


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
        account_balance: Optional[float] = None,
        risk_percent: Optional[float] = None,
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

        # Compute risk info
        risk_info = None
        if account_balance is not None and risk_percent is not None:
            atr = None
            try:
                from .indicators import compute_atr
                atr = compute_atr(df)
            except Exception:
                pass
            if atr:
                risk_info = RiskInfo(
                    account_balance=account_balance,
                    risk_percent=risk_percent,
                    atr=atr,
                )

        # Generate signal
        sentiment_score = sentiment.score if sentiment else 0.0
        signal = self._signals.generate(
            df,
            pair=display,
            timeframe=timeframe,
            smc_result=smc,
            sentiment_score=sentiment_score,
            risk_info=risk_info,
        )

        return FullAnalysis(signal=signal, sentiment=sentiment, df=df)

    async def analyze_multi_timeframe(
        self,
        pair: str,
        timeframes: list[str],
        *,
        include_sentiment: bool = True,
    ) -> list[TimeframeAnalysis]:
        """Run analysis concurrently across multiple timeframes."""
        display = resolve_display_name(resolve_pair(pair) or pair)

        async def _analyze_one(tf: str) -> TimeframeAnalysis:
            try:
                full = await self.analyze(pair, timeframe=tf, include_sentiment=include_sentiment)
                return TimeframeAnalysis(
                    timeframe=tf,
                    signal=full.signal,
                    sentiment=full.sentiment,
                )
            except Exception as exc:
                logger.warning("multianalysis_failed", pair=pair, timeframe=tf, error=str(exc))
                return TimeframeAnalysis(
                    timeframe=tf,
                    signal=None,  # type: ignore[arg-type]
                    sentiment=None,
                    error=str(exc),
                )

        tasks = [_analyze_one(tf) for tf in timeframes]
        return await asyncio.gather(*tasks)
