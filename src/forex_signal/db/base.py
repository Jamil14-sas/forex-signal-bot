"""Async SQLAlchemy engine, session factory, and utilities."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import get_settings


def _build_database_url(raw: str) -> str:
    """Convert a raw DATABASE_URL to an async-compatible URL.

    - If it's a SQLite path (no scheme), use aiosqlite.
    - If it already has a scheme (postgresql://...), replace with
      postgresql+asyncpg://...
    - If it has no scheme and isn't a bare path, default to sqlite.
    """
    if not raw or raw.startswith("sqlite"):
        return raw or "sqlite+aiosqlite:///./forex_signal.db"
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    if raw.startswith("postgresql+asyncpg://"):
        return raw
    # Treat bare path as SQLite
    return f"sqlite+aiosqlite:///{raw.lstrip('/')}"


_settings = get_settings()
_engine = create_async_engine(
    _build_database_url(_settings.database_url),
    echo=_settings.db_echo,
    future=True,
    pool_pre_ping=True,
)

_async_session_factory = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, Any]:
    """Yield an async session — use as a FastAPI/aiogram-style dependency."""
    async with _async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_db_session() -> AsyncSession:
    """Get a new async session directly (for non-dependency usage)."""
    return _async_session_factory()


async def init_db() -> None:
    """Create all tables on startup (idempotent)."""
    from .models import Base  # noqa: F401 — import to register models
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose the engine on shutdown."""
    await _engine.dispose()
