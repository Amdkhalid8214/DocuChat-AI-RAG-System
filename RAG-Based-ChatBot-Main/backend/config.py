import os
from typing import List
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    # App info
    APP_NAME: str = "DocuChat Production RAG"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 5000
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001"
    ]

    # Security & Auth
    SECRET_KEY: str = os.getenv("SECRET_KEY", "docuchat-production-secret-key-change-in-env-998877")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440 # 24 hours
    ALGORITHM: str = "HS256"

    # Paths & Storage
    DATA_DIR: str = str(BASE_DIR / "data")
    UPLOAD_DIR: str = str(BASE_DIR / "data" / "uploads")
    CONVERTED_DIR: str = str(BASE_DIR / "data" / "converted")
    BM25_DIR: str = str(BASE_DIR / "data" / "bm25")
    OUTPUT_DIR: str = str(BASE_DIR / "data" / "output")
    
    # Relational Database (PostgreSQL primary with seamless absolute SQLite fallback)
    DATABASE_URL: str = (
        os.getenv("DATABASE_URL")
        if os.getenv("DATABASE_URL") and not "sqlite" in os.getenv("DATABASE_URL")
        else f"sqlite+aiosqlite:///{(BASE_DIR / 'data' / 'rag_app.db').resolve().as_posix()}"
    )

    # Redis Cache & Message Broker
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Vector DB (Qdrant)
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "doc_chunks"
    
    # Docling Parser
    DOCLING_URL: str = "http://localhost:5001"

    # LLM Settings (Ollama with verified Qwen 2.5 7B)
    LLM_BASE_URL: str = "http://127.0.0.1:11434"
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen2.5:1.5b")
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 512
    LLM_TIMEOUT: float = 180.0
    LLM_NUM_THREADS: int = int(os.getenv("LLM_NUM_THREADS", "2"))
    LLM_NUM_CTX: int = int(os.getenv("LLM_NUM_CTX", "4096"))
    ENABLE_GROUNDING_VALIDATION: bool = os.getenv("ENABLE_GROUNDING_VALIDATION", "false").lower() in ("true", "1", "yes")
    MAX_VALIDATION_RETRIES: int = int(os.getenv("MAX_VALIDATION_RETRIES", "1"))
    CONTEXT_BUDGET_TOKENS: int = 2048

    # Web Search Settings (Local SearXNG Metasearch Engine)
    SEARXNG_URL: str = os.getenv("SEARXNG_URL", "http://127.0.0.1:8080/search")
    SEARXNG_TIMEOUT: float = float(os.getenv("SEARXNG_TIMEOUT", "10.0"))
    SEARXNG_MAX_RESULTS: int = int(os.getenv("SEARXNG_MAX_RESULTS", "5"))
    ENABLE_WEB_SEARCH: bool = os.getenv("ENABLE_WEB_SEARCH", "true").lower() in ("true", "1", "yes")


    # Embeddings (Default to ultra-fast, local BAAI/bge-small-en-v1.5 via FastEmbed)
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    EMBEDDING_DIM: int = 384 if "bge-small" in os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").lower() else (768 if "nomic" in os.getenv("EMBEDDING_MODEL", "").lower() else 384)
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "fastembed")

    # Reranker
    RERANKER_MODEL: str = "BAAI/bge-reranker-base"
    USE_RERANKER: bool = True

    # Retrieval Tuning
    ROUTER_MODE: str = "hybrid" # "hybrid", "rule", or "llm"
    RETRIEVAL_TOP_K: int = 30
    FUSION_METHOD: str = "rrf" # "rrf" or "weighted"
    RRF_K: int = 60
    FUSION_ALPHA: float = 0.5
    DEDUP_SIMILARITY_THRESHOLD: float = 0.88
    FINAL_TOP_K: int = int(os.getenv("FINAL_TOP_K", "4"))
    SCORE_THRESHOLD: float = float(os.getenv("SCORE_THRESHOLD", "0.25"))

    # Chunking & Tokenizer Limits
    CHUNK_TARGET_TOKENS: int = 400
    CHUNK_MAX_TOKENS: int = 450
    CHUNK_OVERLAP_TOKENS: int = 50

    model_config = SettingsConfigDict(
        env_file=[str(BASE_DIR / ".env"), str(BASE_DIR.parent / ".env"), ".env"],
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Ensure required directories exist
os.makedirs(settings.DATA_DIR, exist_ok=True)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.CONVERTED_DIR, exist_ok=True)
os.makedirs(settings.BM25_DIR, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

