import os
from pathlib import Path
try:
    from pydantic_settings import BaseSettings
except ImportError:
    try:
        from pydantic import BaseSettings
    except ImportError:
        try:
            from pydantic import BaseModel as BaseSettings
        except ImportError:
            class BaseSettings:
                def __init__(self, **kwargs):
                    for k, v in kwargs.items():
                        setattr(self, k, v)

BASE_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    # App info
    APP_NAME: str = "DocuChat Production RAG"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 5000

    # Paths & Storage
    DATA_DIR: str = str(BASE_DIR / "data")
    UPLOAD_DIR: str = str(BASE_DIR / "data" / "uploads")
    CONVERTED_DIR: str = str(BASE_DIR / "data" / "converted")
    BM25_DIR: str = str(BASE_DIR / "data" / "bm25")
    
    # Database
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BASE_DIR.as_posix()}/data/rag_app.db"

    # Vector DB (Qdrant)
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "doc_chunks"
    
    # Docling Parser
    DOCLING_URL: str = "http://localhost:5001"

    # LLM Settings (Ollama with Qwen)
    LLM_BASE_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "qwen2.5:1.5b"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 1024
    
    # Embeddings
    # Default to BAAI/bge-small-en-v1.5 (384 dim). Can switch to nomic-embed-text or sentence-transformers
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM: int = 384
    EMBEDDING_PROVIDER: str = "sentence-transformers" # "sentence-transformers" or "ollama"

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
    FINAL_TOP_K: int = 5
    SCORE_THRESHOLD: float = 0.25

    # Chunking
    CHUNK_TARGET_TOKENS: int = 400
    CHUNK_OVERLAP_TOKENS: int = 50

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()

# Ensure required directories exist
os.makedirs(settings.DATA_DIR, exist_ok=True)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.CONVERTED_DIR, exist_ok=True)
os.makedirs(settings.BM25_DIR, exist_ok=True)
