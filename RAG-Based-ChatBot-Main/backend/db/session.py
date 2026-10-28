import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from backend.config import settings
from backend.db.models import Base

logger = logging.getLogger(__name__)

# Determine if Postgres or SQLite
is_sqlite = "sqlite" in settings.DATABASE_URL.lower()

# Setup async engine with connection pooling
engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,
}

if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Production PostgreSQL connection pool configuration
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20
    engine_kwargs["pool_timeout"] = 30
    engine_kwargs["pool_recycle"] = 1800

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

async def init_db():
    """Initializes tables using SQLAlchemy metadata and applies SQLite schema compatibility patches."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def _migrate_columns(sync_conn):
            from sqlalchemy import inspect
            inspector = inspect(sync_conn)
            tables = inspector.get_table_names()

            if "documents" in tables:
                columns = [c["name"] for c in inspector.get_columns("documents")]
                if "user_id" not in columns:
                    logger.info("Auto-migrating: adding user_id to documents")
                    sync_conn.exec_driver_sql("ALTER TABLE documents ADD COLUMN user_id VARCHAR(64)")
                    sync_conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_documents_user_id ON documents (user_id)")

            if "conversations" in tables:
                columns = [c["name"] for c in inspector.get_columns("conversations")]
                if "user_id" not in columns:
                    logger.info("Auto-migrating: adding user_id to conversations")
                    sync_conn.exec_driver_sql("ALTER TABLE conversations ADD COLUMN user_id VARCHAR(64)")
                    sync_conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id)")

            if "messages" in tables:
                columns = [c["name"] for c in inspector.get_columns("messages")]
                if "weather" not in columns:
                    logger.info("Auto-migrating: adding weather to messages")
                    sync_conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN weather JSON")
                if "excel_artifact" not in columns:
                    logger.info("Auto-migrating: adding excel_artifact to messages")
                    sync_conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN excel_artifact JSON")

        await conn.run_sync(_migrate_columns)

async def check_db_health() -> bool:
    """Verifies that the database pool and connection are responsive."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for acquiring a transactional async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

