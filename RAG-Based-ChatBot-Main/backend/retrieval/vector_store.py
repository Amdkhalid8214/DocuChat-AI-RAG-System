import os
import uuid
import logging
from typing import List, Dict, Any, Optional, Union
try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except ImportError:
    QdrantClient = None
    qmodels = None
from backend.config import settings
from backend.chunking.structure_chunker import Chunk

logger = logging.getLogger(__name__)

def _ensure_valid_qdrant_id(raw_id: Any) -> Union[int, str]:
    """
    Ensure the ID passed to Qdrant PointStruct conforms to Qdrant requirements:
    an unsigned integer (>= 0) or an RFC 4122 UUID string.
    Arbitrary strings like 'p20_c1' are deterministically mapped to UUID v5.
    """
    if isinstance(raw_id, int) and raw_id >= 0:
        return raw_id
    id_str = str(raw_id).strip()
    try:
        return str(uuid.UUID(id_str))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, id_str))

class VectorStore:
    def __init__(self):
        self.collection_name = settings.QDRANT_COLLECTION
        self.client = None
        self._init_client()

    def _init_client(self):
        if not QdrantClient:
            return
        # Test remote Qdrant with a short, non-blocking check
        try:
            import httpx
            with httpx.Client(timeout=1.5) as hclient:
                res = hclient.get(f"{settings.QDRANT_URL}/collections")
                if res.status_code == 200:
                    client = QdrantClient(url=settings.QDRANT_URL, timeout=3)
                    self.client = client
                    logger.info(f"Connected to Qdrant service at {settings.QDRANT_URL}")
                else:
                    self._use_local_storage(f"Remote Qdrant returned status {res.status_code}")
        except Exception as e:
            self._use_local_storage(f"Remote Qdrant unavailable: {e}")

        if self.client:
            self._ensure_collection()

    def _use_local_storage(self, reason: str = ""):
        local_qdrant_path = os.path.join(settings.DATA_DIR, "qdrant_storage")
        logger.info(f"Switching to embedded local Qdrant ({reason}) at {local_qdrant_path}")
        try:
            self.client = QdrantClient(path=local_qdrant_path)
        except Exception as lock_err:
            logger.warning(f"Disk storage locked ({lock_err}). Using in-memory Qdrant client.")
            self.client = QdrantClient(":memory:")
        self._ensure_collection()

    def _ensure_collection(self):
        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)
            if not exists:
                logger.info(f"Creating Qdrant collection: {self.collection_name} (dim: {settings.EMBEDDING_DIM})")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=settings.EMBEDDING_DIM,
                        distance=qmodels.Distance.COSINE
                    )
                )
        except Exception as e:
            logger.warning(f"Failed to ensure Qdrant collection ({e}).")

    def upsert_chunks(self, chunks: List[Chunk], vectors: List[List[float]]):
        if not chunks or not vectors or not self.client:
            return

        points = []
        for chunk, vector in zip(chunks, vectors):
            point_id = _ensure_valid_qdrant_id(chunk.chunk_id)
            points.append(qmodels.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "text": chunk.text,
                    "page": chunk.page,
                    "bboxes": chunk.bboxes,
                    "heading_path": chunk.heading_path,
                    "token_count": chunk.token_count,
                    "metadata": chunk.metadata,
                }
            ))

        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True
            )
        except Exception as e:
            err_str = str(e).lower()
            if "format error" in err_str or "bad request" in err_str or "validation" in err_str:
                logger.error(f"Qdrant validation error during upsert: {e}")
                return
            logger.warning(f"Qdrant upsert failed ({e}). Attempting local storage fallback...")
            self._use_local_storage(str(e))
            try:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                    wait=True
                )
                logger.info("Successfully upserted chunks into local Qdrant fallback.")
            except Exception as e2:
                logger.error(f"Fallback local Qdrant upsert also failed: {e2}")

    def search(
        self,
        query_vector: List[float],
        doc_ids: Optional[List[str]] = None,
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        if not self.client:
            return []

        query_filter = None
        if doc_ids:
            query_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="doc_id",
                        match=qmodels.MatchAny(any=doc_ids) if len(doc_ids) > 1 else qmodels.MatchValue(value=doc_ids[0])
                    )
                ]
            )

        def _do_search(client):
            if hasattr(client, "query_points"):
                res = client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True
                )
                return res.points if hasattr(res, "points") else res
            else:
                return client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True
                )

        try:
            results = _do_search(self.client)
        except Exception as e:
            err_str = str(e).lower()
            if "format error" in err_str or "validation" in err_str:
                logger.warning(f"Qdrant search validation error: {e}")
                return []
            logger.warning(f"Qdrant search failed ({e}). Retrying with local storage...")
            self._use_local_storage(str(e))
            try:
                results = _do_search(self.client)
            except Exception as e2:
                logger.error(f"Fallback local Qdrant search also failed: {e2}")
                return []

        hits = []
        for hit in results:
            payload = hit.payload or {}
            hits.append({
                "chunk_id": payload.get("chunk_id", str(hit.id)),
                "doc_id": payload.get("doc_id", ""),
                "text": payload.get("text", ""),
                "page": payload.get("page", 1),
                "bboxes": payload.get("bboxes", []),
                "heading_path": payload.get("heading_path", []),
                "vector_score": float(hit.score),
                "score": float(hit.score),
            })
        return hits

    def delete_by_doc_id(self, doc_id: str):
        if not self.client:
            return
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[qmodels.FieldCondition(key="doc_id", match=qmodels.MatchValue(value=doc_id))]
                    )
                )
            )
        except Exception as e:
            logger.warning(f"Qdrant delete failed ({e}). Trying local storage...")
            self._use_local_storage(str(e))
            try:
                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=qmodels.FilterSelector(
                        filter=qmodels.Filter(
                            must=[qmodels.FieldCondition(key="doc_id", match=qmodels.MatchValue(value=doc_id))]
                        )
                    )
                )
            except Exception:
                pass

vector_store = VectorStore()
