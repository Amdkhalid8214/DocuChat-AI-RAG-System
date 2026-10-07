import sys
import logging
from pathlib import Path
from contextlib import asynccontextmanager

# Add parent directory to sys.path so 'backend' is always importable
parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.db.session import init_db
from backend.retrieval.vector_store import vector_store
from backend.api import documents_router, conversations_router, chat_router, auth_router, seed_default_users

logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Database tables and ensure Qdrant collection
    logger.info("Initializing database schemas...")
    await init_db()
    await seed_default_users()
    logger.info("Verifying Qdrant vector store...")
    vector_store._ensure_collection()
    logger.info("DocuChat backend started successfully.")
    yield
    logger.info("Shutting down DocuChat backend.")

app = FastAPI(
    title=settings.APP_NAME,
    version="2.0.0",
    description="Production Document Chat with Hybrid Fusion, Docling Provenance, and Small-Model Grounding",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers under /api and also root for versatility
app.include_router(auth_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(chat_router, prefix="/api")

# Also include directly without /api for direct endpoint specs
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(conversations_router)
app.include_router(chat_router)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "llm_model": settings.LLM_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "router_mode": settings.ROUTER_MODE
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, reload=False)
