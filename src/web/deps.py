"""FastAPI dependencies."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.engine import async_session


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield an async DB session per request."""
    async with async_session() as session:
        yield session
