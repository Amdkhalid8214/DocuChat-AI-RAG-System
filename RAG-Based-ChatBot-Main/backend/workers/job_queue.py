"""
DocuChat AI - Job Queue Dispatcher
Enqueues document ingestion jobs to Redis / ARQ if available,
or runs asynchronously in background task pool with persistent state tracking.
"""
import uuid
import asyncio
import logging
from typing import Optional
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from backend.config import settings
from backend.db.session import AsyncSessionLocal
from backend.db.models import IngestJobModel
from backend.workers.ingest_worker import process_document_job

logger = logging.getLogger("job_queue")

async def enqueue_document_ingestion(
    doc_id: str,
    file_path: str,
    ext: str,
    user_id: Optional[str] = None
) -> str:
    """
    Creates an IngestJobModel record in the database and launches background ingestion.
    Returns the persistent job_id.
    """
    job_id = str(uuid.uuid4())

    # 1. Create IngestJobModel in DB
    async with AsyncSessionLocal() as session:
        job = IngestJobModel(
            id=job_id,
            document_id=doc_id,
            user_id=user_id,
            status="queued",
            progress=5,
            message="Ingestion queued",
            created_at=datetime.utcnow()
        )
        session.add(job)
        await session.commit()

    # 2. Try Redis / ARQ dispatch if available, otherwise launch async background task
    dispatched_via_redis = False
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5
        )
        # Check connection with strict timeout
        await asyncio.wait_for(r.ping(), timeout=0.5)
        # Enqueue job payload in redis stream or list
        await asyncio.wait_for(r.rpush("docuchat_ingest_queue", f"{job_id}:{doc_id}:{file_path}:{ext}"), timeout=0.5)
        await r.aclose()
        dispatched_via_redis = True
        logger.info(f"Job {job_id} dispatched via Redis queue.")
    except Exception as e:
        logger.debug(f"Redis queue dispatch not active, running async background worker ({e})")

    # In standalone / dev mode or as fallback, run in non-blocking async task
    if not dispatched_via_redis:
        asyncio.create_task(process_document_job(job_id, doc_id, file_path, ext))

    return job_id
