# Lazy/clean exports for retrieval package
def __getattr__(name):
    if name in ("VectorStore", "vector_store"):
        from backend.retrieval.vector_store import VectorStore, vector_store
        return vector_store if name == "vector_store" else VectorStore
    if name in ("BM25Index", "bm25_index"):
        from backend.retrieval.bm25 import BM25Index, bm25_index
        return bm25_index if name == "bm25_index" else BM25Index
    if name in ("Reranker", "reranker"):
        from backend.retrieval.reranker import Reranker, reranker
        return reranker if name == "reranker" else Reranker
    if name in ("RetrievalPipeline", "retrieval_pipeline"):
        from backend.retrieval.pipeline import RetrievalPipeline, retrieval_pipeline
        return retrieval_pipeline if name == "retrieval_pipeline" else RetrievalPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

from backend.retrieval.fusion import reciprocal_rank_fusion, weighted_score_fusion
from backend.retrieval.dedup import deduplicate_chunks

__all__ = [
    "VectorStore", "vector_store",
    "BM25Index", "bm25_index",
    "reciprocal_rank_fusion", "weighted_score_fusion",
    "deduplicate_chunks",
    "Reranker", "reranker",
    "RetrievalPipeline", "retrieval_pipeline"
]
