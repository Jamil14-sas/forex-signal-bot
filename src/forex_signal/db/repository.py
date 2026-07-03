"""Repository — high-level DB operations for the bot."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SignalRecord, Subscription, User, UserPreference


# ── User ────────────────────────────────────────────────────────────────────


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    """Get existing user or create a new one."""
    user = await session.get(User, telegram_id)
    if user is not None:
        # Update profile fields if changed
        dirty = False
        if username is not None and username != user.username:
            user.username = username
            dirty = True
        if first_name is not None and first_name != user.first_name:
            user.first_name = first_name
            dirty = True
        if dirty:
            await session.flush()
        return user

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
    )
    session.add(user)
    await session.flush()
    return user


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.get(User, telegram_id)


async def reset_daily_usage(session: AsyncSession) -> int:
    """Reset daily usage counters for all users (called at start of day).

    Returns the number of users reset.
    """
    today = date.today()
    result = await session.execute(
        select(User).where(User.last_reset_date < today)
    )
    users = result.scalars().all()
    for u in users:
        u.daily_usage_count = 0
        u.last_reset_date = today
    await session.flush()
    return len(users)


async def check_daily_limit(
    session: AsyncSession, user_id: int, limit: int
) -> tuple[bool, int]:
    """Check if user is within daily usage limit.

    Returns (within_limit, current_count).
    """
    user = await get_or_create_user(session, user_id)
    today = date.today()
    if user.last_reset_date < today:
        user.daily_usage_count = 0
        user.last_reset_date = today
    return user.daily_usage_count < limit, user.daily_usage_count


async def increment_usage(session: AsyncSession, user_id: int) -> None:
    """Increment daily usage counter for a user."""
    user = await get_or_create_user(session, user_id)
    user.daily_usage_count += 1
    await session.flush()


# ── Preferences ─────────────────────────────────────────────────────────────


async def set_preference(
    session: AsyncSession, user_id: int, key: str, value: str
) -> None:
    """Set a user preference (upsert)."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    user = await get_or_create_user(session, user_id)

    # Try to find existing
    result = await session.execute(
        select(UserPreference).where(
            UserPreference.user_id == user_id,
            UserPreference.key == key,
        )
    )
    pref = result.scalar_one_or_none()
    if pref is not None:
        pref.value = value
    else:
        session.add(UserPreference(user_id=user_id, key=key, value=value))
    await session.flush()


async def get_preference(
    session: AsyncSession, user_id: int, key: str, default: str = ""
) -> str:
    """Get a user preference by key."""
    result = await session.execute(
        select(UserPreference).where(
            UserPreference.user_id == user_id,
            UserPreference.key == key,
        )
    )
    pref = result.scalar_one_or_none()
    return pref.value if pref is not None else default


async def get_all_preferences(
    session: AsyncSession, user_id: int
) -> dict[str, str]:
    """Get all preferences for a user as a dict."""
    result = await session.execute(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )
    return {p.key: p.value for p in result.scalars().all()}


# ── Signal Records ──────────────────────────────────────────────────────────


async def save_signal(
    session: AsyncSession,
    user_id: int | None,
    pair: str,
    timeframe: str,
    direction: str,
    confidence: float,
    entry_price: float,
    stop_loss: str | None = None,
    take_profit: str | None = None,
) -> SignalRecord:
    """Save a generated signal to the database."""
    record = SignalRecord(
        user_id=user_id,
        pair=pair,
        timeframe=timeframe,
        direction=direction,
        confidence=confidence,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )
    session.add(record)
    await session.flush()
    return record


async def get_signal_history(
    session: AsyncSession,
    user_id: int | None = None,
    pair: str | None = None,
    limit: int = 20,
) -> list[SignalRecord]:
    """Get signal history, newest first."""
    stmt = select(SignalRecord)
    if user_id is not None:
        stmt = stmt.where(SignalRecord.user_id == user_id)
    if pair is not None:
        stmt = stmt.where(SignalRecord.pair == pair)
    stmt = stmt.order_by(SignalRecord.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_win_rate(
    session: AsyncSession,
    user_id: int | None = None,
    pair: str | None = None,
) -> dict:
    """Compute win/loss stats for signals."""
    stmt = select(SignalRecord).where(
        SignalRecord.actual_outcome.in_(["won", "lost"])
    )
    if user_id is not None:
        stmt = stmt.where(SignalRecord.user_id == user_id)
    if pair is not None:
        stmt = stmt.where(SignalRecord.pair == pair)

    result = await session.execute(stmt)
    signals = list(result.scalars().all())

    won = sum(1 for s in signals if s.actual_outcome == "won")
    lost = sum(1 for s in signals if s.actual_outcome == "lost")
    total = won + lost

    return {
        "total": total,
        "won": won,
        "lost": lost,
        "win_rate": round(won / total * 100, 1) if total > 0 else 0.0,
    }


# ── Subscriptions ───────────────────────────────────────────────────────────


async def set_subscription(
    session: AsyncSession,
    user_id: int,
    broadcast_time: str = "08:00",
    pairs: str = "EUR/USD,GBP/USD,USD/JPY,AUD/USD,USD/CAD",
    is_active: bool = True,
) -> Subscription:
    """Create or update a subscription schedule."""
    result = await session.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    sub = result.scalar_one_or_none()
    if sub is not None:
        sub.broadcast_time = broadcast_time
        sub.pairs = pairs
        sub.is_active = is_active
    else:
        sub = Subscription(
            user_id=user_id,
            broadcast_time=broadcast_time,
            pairs=pairs,
            is_active=is_active,
        )
        session.add(sub)
    await session.flush()
    return sub


async def get_subscription(
    session: AsyncSession, user_id: int
) -> Subscription | None:
    result = await session.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_subscription(session: AsyncSession, user_id: int) -> bool:
    """Remove a subscription. Returns True if one was deleted."""
    result = await session.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    sub = result.scalar_one_or_none()
    if sub is not None:
        await session.delete(sub)
        await session.flush()
        return True
    return False


async def get_due_subscriptions(
    session: AsyncSession, current_time_str: str
) -> list[Subscription]:
    """Get active subscriptions whose broadcast time matches current time.

    current_time_str should be "HH:MM" in UTC.
    """
    # Also skip users who already got their broadcast today
    today = date.today()
    result = await session.execute(
        select(Subscription).where(
            Subscription.is_active.is_(True),
            Subscription.broadcast_time == current_time_str,
            (
                (Subscription.last_broadcast_date != today)
                | (Subscription.last_broadcast_date.is_(None))
            ),
        )
    )
    return list(result.scalars().all())


async def mark_broadcast_sent(
    session: AsyncSession, subscription_id: int
) -> None:
    """Mark a broadcast as sent (update count + date)."""
    sub = await session.get(Subscription, subscription_id)
    if sub is not None:
        sub.broadcast_count += 1
        sub.last_broadcast_date = date.today()
        await session.flush()
