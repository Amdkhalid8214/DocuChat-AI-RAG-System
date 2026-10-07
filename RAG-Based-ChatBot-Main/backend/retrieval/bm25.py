import os
import json
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
try:
    from rank_bm25 import BM25Plus as BM25Model
except ImportError:
    try:
        from rank_bm25 import BM25Okapi as BM25Model
    except ImportError:
        class BM25Model:
            def __init__(self, corpus):
                self.corpus = corpus
            def get_scores(self, query):
                return [0.0] * len(self.corpus)
from backend.config import settings
from backend.chunking.structure_chunker import Chunk

logger = logging.getLogger(__name__)

def tokenize(text: str) -> List[str]:
    """Simple alphanumeric tokenizer with lowercase normalization."""
    return re.findall(r"\b\w+\b", text.lower())

class BM25Index:
    def __init__(self, storage_dir: str = settings.BM25_DIR):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # In-memory cache of doc_id -> {"bm25": BM25Okapi, "chunks": List[Dict]}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load_existing_indices()

    def _load_existing_indices(self):
        for file in self.storage_dir.glob("*.json"):
            doc_id = file.stem
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                chunks = data.get("chunks", [])
                corpus = [tokenize(c["text"]) for c in chunks]
                if corpus:
                    bm25 = BM25Model(corpus)
                    self._cache[doc_id] = {"bm25": bm25, "chunks": chunks}
            except Exception as e:
                logger.warning(f"Failed to load BM25 index for {doc_id}: {e}")

    def add_document(self, doc_id: str, chunks: List[Chunk]):
        if not chunks:
            return

        chunk_data = [chunk.to_dict() for chunk in chunks]
        corpus = [tokenize(c["text"]) for c in chunk_data]
        bm25 = BM25Model(corpus)

        self._cache[doc_id] = {"bm25": bm25, "chunks": chunk_data}

        # Persist to disk
        file_path = self.storage_dir / f"{doc_id}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"doc_id": doc_id, "chunks": chunk_data}, f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to persist BM25 index for {doc_id}: {e}")

    def search(
        self,
        query: str,
        doc_ids: Optional[List[str]] = None,
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        tokens = tokenize(query)
        if not tokens:
            return []

        target_doc_ids = doc_ids if doc_ids else list(self._cache.keys())
        scored_results: List[Dict[str, Any]] = []

        for did in target_doc_ids:
            item = self._cache.get(did)
            if not item:
                # Try loading from disk if not yet in cache
                fpath = self.storage_dir / f"{did}.json"
                if fpath.exists():
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        c_data = data.get("chunks", [])
                        c_corpus = [tokenize(c["text"]) for c in c_data]
                        if c_corpus:
                            item = {"bm25": BM25Model(c_corpus), "chunks": c_data}
                            self._cache[did] = item
                    except Exception:
                        continue

            if not item:
                continue

            bm25: BM25Model = item["bm25"]
            chunks: List[Dict[str, Any]] = item["chunks"]
            scores = bm25.get_scores(tokens)

            for chunk_dict, score in zip(chunks, scores):
                if score > 0:
                    scored_results.append({
                        "chunk_id": chunk_dict["chunk_id"],
                        "doc_id": chunk_dict["doc_id"],
                        "text": chunk_dict["text"],
                        "page": chunk_dict.get("page", 1),
                        "bboxes": chunk_dict.get("bboxes", []),
                        "heading_path": chunk_dict.get("heading_path", []),
                        "bm25_score": float(score),
                        "score": float(score),
                    })

        # Sort descending by bm25_score
        scored_results.sort(key=lambda x: x["bm25_score"], reverse=True)
        return scored_results[:limit]

    def remove_document(self, doc_id: str):
        self._cache.pop(doc_id, None)
        file_path = self.storage_dir / f"{doc_id}.json"
        if file_path.exists():
            try:
                os.remove(file_path)
            except Exception as e:
                logger.error(f"Failed to delete BM25 file for {doc_id}: {e}")

bm25_index = BM25Index()
