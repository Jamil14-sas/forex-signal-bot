"""SQLAlchemy ORM models for the Forex Signal Bot."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    subscription_tier: Mapped[str] = mapped_column(String(16), default="free")  # free | premium
    daily_usage_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reset_date: Mapped[date] = mapped_column(default=date.today)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    preferences: Mapped[list[UserPreference]] = relationship(
        "UserPreference", back_populates="user", cascade="all, delete-orphan"
    )
    signals: Mapped[list[SignalRecord]] = relationship(
        "SignalRecord", back_populates="user", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list[Subscription]] = relationship(
        "Subscription", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(telegram_id={self.telegram_id}, tier={self.subscription_tier})>"


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(Text, default="")

    user: Mapped[User] = relationship("User", back_populates="preferences")

    def __repr__(self) -> str:
        return f"<UserPreference(user={self.user_id}, key={self.key}={self.value})>"


class SignalRecord(Base):
    """Tracks every signal generated — used for win-rate analytics."""

    __tablename__ = "signal_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.telegram_id", ondelete="SET NULL"), nullable=True, index=True
    )
    pair: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    direction: Mapped[str] = mapped_column(String(8))  # BUY | SELL | NEUTRAL
    confidence: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    take_profit: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actual_outcome: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, default="pending"
    )  # won | lost | pending
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[Optional[User]] = relationship("User", back_populates="signals")

    def __repr__(self) -> str:
        return f"<SignalRecord({self.pair} {self.direction} @ {self.entry_price})>"


class Subscription(Base):
    """User subscription to scheduled signal broadcasts."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.telegram_id", ondelete="CASCADE"), unique=True, index=True
    )
    # Broadcast time in HH:MM (UTC)
    broadcast_time: Mapped[str] = mapped_column(String(5), default="08:00")
    # Comma-separated pair slugs (e.g. "EUR/USD,GBP/USD,USD/JPY")
    pairs: Mapped[str] = mapped_column(Text, default="EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD")
    broadcast_count: Mapped[int] = mapped_column(Integer, default=0)
    last_broadcast_date: Mapped[Optional[date]] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="subscriptions")

    def __repr__(self) -> str:
        return f"<Subscription(user={self.user_id}, time={self.broadcast_time})>"
