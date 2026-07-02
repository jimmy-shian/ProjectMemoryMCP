"""Database connection management for Project Memory MCP."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from project_memory_mcp.db.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get the database engine (singleton)."""
    global _engine
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the session factory (singleton)."""
    global _session_factory
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory


async def init_db(
    db_path: str = ".project-memory/project_knowledge.db",
    pool_size: int = 5,
    max_overflow: int = 10,
    use_null_pool: bool = False,
) -> AsyncEngine:
    """
    Initialize the database connection.

    Args:
        db_path: Path to SQLite database file
        pool_size: Connection pool size (for HTTP transport)
        max_overflow: Max overflow connections
        use_null_pool: Use NullPool (for stdio transport, single connection)

    Returns:
        The initialized AsyncEngine
    """
    global _engine, _session_factory

    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    # Create engine with appropriate pool
    if use_null_pool:
        # For stdio transport - single connection, no pooling
        _engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            poolclass=NullPool,
            connect_args={
                "check_same_thread": False,
                "timeout": 30,
            },
            echo=False,
        )
    else:
        # For HTTP transport - connection pooling
        _engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}",
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            connect_args={
                "check_same_thread": False,
                "timeout": 30,
            },
            echo=False,
        )

    # Enable WAL mode and other pragmas for better concurrency
    @asynccontextmanager
    async def _set_pragmas(conn) -> AsyncGenerator[None, None]:
        async with conn:
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA busy_timeout=5000;")
            await conn.execute("PRAGMA synchronous=NORMAL;")
            await conn.execute("PRAGMA cache_size=-32768;")  # 32MB cache
            await conn.execute("PRAGMA temp_store=MEMORY;")
            await conn.execute("PRAGMA mmap_size=268435456;")  # 256MB mmap
        yield

    async with _engine.begin() as conn:
        await conn.run_sync(_set_pragmas)
        # Create all tables - checkfirst=True to avoid errors on existing tables
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True))

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    return _engine


async def close_db() -> None:
    """Close the database connection."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get a database session.

    Usage:
        async with get_session() as session:
            result = await session.execute(select(File))
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def run_migrations() -> None:
    """Run Alembic migrations."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    # Override sqlalchemy.url to use our engine's URL
    engine = get_engine()
    alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url).replace("+aiosqlite", ""))

    # Run upgrade to head
    command.upgrade(alembic_cfg, "head")
