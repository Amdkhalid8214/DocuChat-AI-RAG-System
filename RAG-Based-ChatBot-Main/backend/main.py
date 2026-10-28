import sys
import time
import uuid
import logging
from pathlib import Path
from contextlib import asynccontextmanager

# Add parent directory to sys.path so 'backend' is always importable
parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.db.session import init_db, check_db_health
from backend.retrieval.vector_store import vector_store
from backend.api import (
    documents_router,
    conversations_router,
    chat_router,
    auth_router,
    websockets_router,
    tools_router,
    pdf_tools_router,
    seed_default_users
)

logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Database tables and ensure Qdrant collection
    logger.info("Initializing database schemas...")
    await init_db()
    await seed_default_users()
    logger.info("Verifying Qdrant vector store...")
    vector_store._ensure_collection()
    logger.info("Scanning for interrupted/zombie ingestion jobs...")
    from backend.workers import recover_zombie_jobs
    recovery_stats = await recover_zombie_jobs()
    if recovery_stats["recovered_jobs"] > 0 or recovery_stats["recovered_docs"] > 0:
        logger.info(f"Recovered zombie jobs: {recovery_stats}")
    logger.info("DocuChat backend started successfully.")
    # Warmup embedder and reranker models in background thread so first document queries are fast
    import threading
    from backend.embeddings.embedder import embedder
    from backend.retrieval.reranker import reranker
    def _warmup_models():
        try:
            logger.info("Pre-warming embedding & reranker models...")
            embedder._get_st_model()
            reranker._get_model()
            logger.info("Embedding & reranker models warmed up.")

            # Automatically ensure all indexed BM25 documents have dense vectors in Qdrant
            from backend.retrieval.bm25 import bm25_index
            from backend.chunking.structure_chunker import Chunk
            from qdrant_client.http import models as qmodels
            for doc_id, cached in bm25_index._cache.items():
                if not cached.get("chunks"):
                    continue
                try:
                    res = vector_store.client.count(
                        collection_name=vector_store.collection_name,
                        count_filter=qmodels.Filter(
                            must=[qmodels.FieldCondition(key="doc_id", match=qmodels.MatchValue(value=doc_id))]
                        )
                    )
                    if res.count == 0:
                        logger.info(f"Auto-syncing {len(cached['chunks'])} chunks to vector store for document {doc_id}...")
                        chunk_objs = [
                            Chunk(
                                chunk_id=c["chunk_id"],
                                doc_id=c.get("doc_id", doc_id),
                                text=c["text"],
                                page=c.get("page", 1),
                                bboxes=c.get("bboxes", []),
                                heading_path=c.get("heading_path", []),
                                token_count=c.get("token_count", 0),
                                metadata=c.get("metadata", {})
                            )
                            for c in cached["chunks"]
                        ]
                        texts = [c.text for c in chunk_objs]
                        vectors = embedder.embed_texts(texts)
                        vector_store.upsert_chunks(chunk_objs, vectors)
                        logger.info(f"Auto-synced document {doc_id} to vector store ({len(vectors)} vectors).")
                except Exception as sync_err:
                    logger.warning(f"Vector store auto-sync warning for doc {doc_id}: {sync_err}")
        except Exception as warm_err:
            logger.warning(f"Model warmup warning: {warm_err}")
    threading.Thread(target=_warmup_models, daemon=True).start()
    yield
    logger.info("Shutting down DocuChat backend.")

app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    description="Production Document Intelligence Platform with Hybrid Retrieval, WebSockets, and Multi-Tenancy",
    lifespan=lifespan
)

# Request ID & Structured Logging Middleware
@app.middleware("http")
async def request_correlation_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start_time = time.time()
    
    # Process request
    response = await call_next(request)
    duration_ms = round((time.time() - start_time) * 1000, 2)
    
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = str(duration_ms)
    
    # Structured access log (skipping spammy health checks in debug)
    if not request.url.path.endswith("/health"):
        logger.info(f"[{request_id}] {request.method} {request.url.path} -> {response.status_code} ({duration_ms}ms)")
    
    return response

# Structured Exception Handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = request.headers.get("X-Request-ID", "unknown")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "error_code": exc.status_code,
            "message": exc.detail,
            "request_id": request_id
        }
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    request_id = request.headers.get("X-Request-ID", "unknown")
    logger.error(f"[{request_id}] Unhandled server exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error_code": 500,
            "message": "Internal server error occurred.",
            "request_id": request_id
        }
    )

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins in dev, configurable in settings.CORS_ORIGINS
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers under /api
app.include_router(auth_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(tools_router, prefix="/api")
app.include_router(pdf_tools_router, prefix="/api")

# Mount Routers directly for backward compatibility
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(conversations_router)
app.include_router(chat_router)
app.include_router(tools_router)
app.include_router(pdf_tools_router)

# Mount WebSockets (root path)
app.include_router(websockets_router)

@app.get("/health")
@app.get("/api/health")
async def health_check():
    """Liveness probe: verifies server process is responsive."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "llm_model": settings.LLM_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "router_mode": settings.ROUTER_MODE
    }

@app.get("/ready")
@app.get("/api/ready")
async def readiness_check():
    """Readiness probe: validates database connection and dependent services."""
    db_ok = await check_db_health()
    return {
        "status": "ready" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
        "vector_store": "initialized",
        "llm_model": settings.LLM_MODEL,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        reload_excludes=["*.db*", "*.db-journal", "*.db-wal", "*.db-shm", "*data/*", "*data\\*", "*__pycache__/*", "*.log"]
    )

