"""Middleware to inject AnalysisService into aiogram handlers."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from ..services.analysis_service import AnalysisService


class AnalysisServiceMiddleware(BaseMiddleware):
    """Injects AnalysisService into the handler data dict so handlers can receive it as a kwarg."""

    def __init__(self, analysis_service: AnalysisService) -> None:
        self._analysis_service = analysis_service

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        data["analysis_service"] = self._analysis_service
        return await handler(event, data)
