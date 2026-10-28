"""
DocuChat AI - Asynchronous Ingestion Worker & Progress Manager
Executes document conversion, Docling extraction, selective OCR, structure chunking,
dense embeddings, Qdrant indexing, and BM25 building without blocking the HTTP server.
Broadcasts real-time job status via Redis pub/sub and WebSocket channels.
"""
import os
import sys
import json
import asyncio
import logging
from typing import Optional, Dict, Any, Callable
from pathlib import Path

# Add project root to sys.path
root_dir = str(Path(__file__).resolve().parent.parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from sqlalchemy import select
from backend.config import settings
from backend.db.session import AsyncSessionLocal
from backend.db.models import DocumentModel, IngestJobModel
from backend.parsers.converter import convert_to_pdf
from backend.parsers.docling_parser import docling_parser
from backend.parsers.document_router import document_router
from backend.chunking.structure_chunker import structure_chunker
from backend.embeddings.embedder import embedder
from backend.retrieval.vector_store import vector_store
from backend.retrieval.bm25 import bm25_index

logger = logging.getLogger("ingest_worker")

# In-memory progress callback registry for active WebSocket connections
_progress_subscribers: Dict[str, list[Callable[[Dict[str, Any]], Any]]] = {}

def subscribe_progress(doc_id: str, callback: Callable[[Dict[str, Any]], Any]):
    """Registers a WebSocket callback for real-time document progress."""
    if doc_id not in _progress_subscribers:
        _progress_subscribers[doc_id] = []
    _progress_subscribers[doc_id].append(callback)

def unsubscribe_progress(doc_id: str, callback: Callable[[Dict[str, Any]], Any]):
    """Removes a WebSocket callback."""
    if doc_id in _progress_subscribers:
        if callback in _progress_subscribers[doc_id]:
            _progress_subscribers[doc_id].remove(callback)
        if not _progress_subscribers[doc_id]:
            del _progress_subscribers[doc_id]

async def broadcast_progress(job_id: str, doc_id: str, status: str, progress: int, message: str):
    """
    Broadcasts progress event to local WebSocket subscribers and Redis pub/sub.
    """
    event = {
        "job_id": job_id,
        "document_id": doc_id,
        "status": status,
        "progress": progress,
        "message": message,
    }
    
    # 1. Notify local subscribers
    subscribers = _progress_subscribers.get(doc_id, [])
    for cb in list(subscribers):
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(event)
            else:
                cb(event)
        except Exception as e:
            logger.debug(f"Subscriber notification error: {e}")

    # 2. Publish to Redis if available
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)
        await asyncio.wait_for(r.publish(f"ingest_progress:{doc_id}", json.dumps(event)), timeout=0.5)
        await r.aclose()
    except Exception:
        pass

async def process_document_job(job_id: str, doc_id: str, file_path: str, ext: str):
    """
    Full pipeline execution for a document ingestion job.
    Updates IngestJobModel and DocumentModel persistently.
    """
    async with AsyncSessionLocal() as session:
        # Load records
        doc_res = await session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        doc = doc_res.scalar_one_or_none()
        job_res = await session.execute(select(IngestJobModel).where(IngestJobModel.id == job_id))
        job = job_res.scalar_one_or_none()

        if not doc:
            logger.error(f"Document {doc_id} not found for job {job_id}")
            return

        # Resolve file_path across OS boundaries (e.g. host Windows paths vs container Linux paths)
        if not os.path.exists(file_path):
            filename = Path(file_path).name
            candidate = os.path.join(settings.UPLOAD_DIR, filename)
            if os.path.exists(candidate):
                file_path = candidate
                logger.info(f"Resolved file_path to container location: {file_path}")

        try:
            # 1. Queued
            logger.info(f"[Job {job_id}] Processing started for '{doc.filename}' (ID: {doc_id})")
            if job:
                job.status = "queued"
                job.progress = 10
                job.message = "Job accepted into processing queue"
                await session.commit()
            await broadcast_progress(job_id, doc_id, "queued", 10, "Job accepted into processing queue")

            # 2. Conversion to PDF if needed
            if job:
                job.status = "converting"
                job.progress = 25
                job.message = "Converting format to layout PDF"
                await session.commit()
            await broadcast_progress(job_id, doc_id, "converting", 25, "Converting format to layout PDF")

            pdf_path = convert_to_pdf(file_path, settings.CONVERTED_DIR)
            doc.pdf_path = pdf_path

            page_count = 1
            if pdf_path.endswith(".pdf") and os.path.exists(pdf_path):
                try:
                    import fitz
                    pdoc = fitz.open(pdf_path)
                    page_count = len(pdoc)
                    pdoc.close()
                except Exception:
                    pass
            doc.page_count = page_count

            # 3. Parsing & Structure extraction (with intelligent digital vs. PaddleOCR routing)
            if job:
                job.status = "parsing"
                job.progress = 45
                job.message = f"Parsing {page_count} page(s) with conditional Docling/PaddleOCR routing"
                await session.commit()
            await broadcast_progress(job_id, doc_id, "parsing", 45, f"Parsing {page_count} page(s)")

            elements, parse_stats = document_router.parse_document(file_path, pdf_path=pdf_path)
            if not elements:
                raise ValueError("No text, tables, or structural elements could be extracted from document.")

            logger.info(
                f"[Job {job_id}] Parsing complete: {len(elements)} elements, digital={parse_stats.get('digital_pages')}, "
                f"scanned={parse_stats.get('scanned_pages')}, ocr={parse_stats.get('ocr_pages_executed')}, "
                f"methods={parse_stats.get('extraction_methods')}"
            )

            # 4. Tokenizer-aware chunking
            if job:
                job.status = "chunking"
                job.progress = 65
                job.message = f"Splitting {len(elements)} structural elements into tokenizer-safe chunks"
                await session.commit()
            await broadcast_progress(job_id, doc_id, "chunking", 65, "Chunking elements")

            # Sanitize character artifacts (e.g. \ufffd, Wingdings \uf0b7, private use \ue000-\uf8ff)
            import re
            for el in elements:
                if el.text:
                    if "\ufffd" in el.text:
                        el.text = el.text.replace("\ufffd", "•")
                    el.text = re.sub(r'[\ue000-\uf8ff]', '•', el.text)

            chunks = structure_chunker.chunk_elements(elements, doc_id=doc_id)
            if not chunks:
                raise ValueError("Chunking produced 0 valid chunks.")

            for c in chunks:
                if c.text:
                    if "\ufffd" in c.text:
                        c.text = c.text.replace("\ufffd", "•")
                    c.text = re.sub(r'[\ue000-\uf8ff]', '•', c.text)

            # 5. Embeddings generation
            if job:
                job.status = "embedding"
                job.progress = 80
                job.message = f"Generating vector embeddings for {len(chunks)} chunks"
                await session.commit()
            await broadcast_progress(job_id, doc_id, "embedding", 80, f"Embedding {len(chunks)} chunks")

            chunk_texts = [c.text for c in chunks]
            vectors = embedder.embed_texts(chunk_texts)

            # 6. Idempotent Indexing: Clean existing entries before upserting into Qdrant & BM25
            if job:
                job.status = "indexing"
                job.progress = 92
                job.message = "Indexing dense vectors in Qdrant and updating BM25 lexical index"
                await session.commit()
            await broadcast_progress(job_id, doc_id, "indexing", 92, "Indexing vectors and BM25")

            # Always index into BM25 lexical store
            try:
                bm25_index.remove_document(doc_id)
                bm25_index.add_document(doc_id, chunks)
            except Exception as bm_err:
                logger.error(f"BM25 index update error: {bm_err}")

            # Upsert into dense vector store
            try:
                vector_store.delete_by_doc_id(doc_id)
                vector_store.upsert_chunks(chunks, vectors)
            except Exception as vs_err:
                logger.error(f"Vector store upsert error: {vs_err}")

            # 7. Complete & Ready
            doc.status = "ready"
            doc.chunk_count = len(chunks)
            doc.status_message = None
            if job:
                job.status = "ready"
                job.progress = 100
                job.message = f"Document ready. Indexed {len(chunks)} chunks across {page_count} page(s)."
            await session.commit()

            await broadcast_progress(
                job_id, doc_id, "ready", 100,
                f"Document ready. Indexed {len(chunks)} chunks across {page_count} page(s)."
            )
            logger.info(f"[Job {job_id}] Successfully finished for '{doc.filename}' ({len(chunks)} chunks).")

        except Exception as e:
            logger.error(f"[Job {job_id}] Processing failed for doc {doc_id}: {e}", exc_info=True)
            doc.status = "failed"
            doc.status_message = str(e)
            if job:
                job.status = "failed"
                job.progress = 0
                job.message = str(e)
            await session.commit()

            await broadcast_progress(job_id, doc_id, "failed", 0, f"Error: {e}")

async def recover_zombie_jobs() -> Dict[str, int]:
    """
    Scans for orphaned/zombie ingestion jobs left in non-terminal states
    from a prior server crash or restart, and marks them as failed with
    a clear diagnostic message so users can safely retry them.
    """
    active_statuses = ["queued", "converting", "parsing", "chunking", "embedding", "indexing", "processing"]
    async with AsyncSessionLocal() as session:
        # 1. Recover IngestJobModel
        stmt = select(IngestJobModel).where(IngestJobModel.status.in_(active_statuses))
        result = await session.execute(stmt)
        zombie_jobs = result.scalars().all()
        for job in zombie_jobs:
            job.status = "failed"
            job.message = "Process interrupted by server restart; ready for retry."
            logger.warning(f"Recovered orphaned job {job.id} for document {job.document_id}.")

        # 2. Recover DocumentModel
        doc_stmt = select(DocumentModel).where(DocumentModel.status.in_(active_statuses))
        doc_res = await session.execute(doc_stmt)
        zombie_docs = doc_res.scalars().all()
        for doc in zombie_docs:
            doc.status = "failed"
            doc.status_message = "Ingestion interrupted by server restart; click to re-process."
            logger.warning(f"Recovered orphaned document status for {doc.id} ({doc.filename}).")

        if zombie_jobs or zombie_docs:
            await session.commit()
            logger.info(f"Zombie job recovery complete: {len(zombie_jobs)} jobs, {len(zombie_docs)} documents updated.")

        return {"recovered_jobs": len(zombie_jobs), "recovered_docs": len(zombie_docs)}

async def run_worker():
    """
    Continuous background loop for dedicated worker container.
    Consumes document ingestion tasks from Redis queue 'docuchat_ingest_queue'.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info("DocuChat Ingest Worker initialized.")
    try:
        await recover_zombie_jobs()
    except Exception as e:
        logger.warning(f"Initial zombie job recovery warning: {e}")

    import redis.asyncio as aioredis
    while True:
        try:
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            logger.info(f"Worker connected to Redis at {settings.REDIS_URL}. Waiting for ingestion jobs...")
            while True:
                item = await r.blpop("docuchat_ingest_queue", timeout=5)
                if item:
                    _, payload = item
                    parts = payload.split(":", 3)
                    if len(parts) == 4:
                        job_id, doc_id, f_path, ext = parts
                        logger.info(f"Worker picked up job {job_id} for doc {doc_id}")
                        await process_document_job(job_id, doc_id, f_path, ext)
                    else:
                        logger.warning(f"Malformed queue payload: {payload}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Redis worker connection error: {e}. Retrying in 3 seconds...")
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(run_worker())


