import logging
import requests
from typing import List
from backend.config import settings

logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self):
        self.model_name = settings.EMBEDDING_MODEL
        self._fastembed_model = None
        self._st_model = None

    def _get_fastembed(self):
        if self._fastembed_model is None:
            try:
                from fastembed import TextEmbedding
                # Normalize model name for FastEmbed (defaults to BAAI/bge-small-en-v1.5)
                mname = self.model_name
                if "bge-small" in mname.lower():
                    mname = "BAAI/bge-small-en-v1.5"
                logger.info(f"Loading FastEmbed model: {mname}")
                self._fastembed_model = TextEmbedding(model_name=mname)
            except Exception as e:
                logger.warning(f"Could not load FastEmbed ({e}).")
        return self._fastembed_model

    def _get_st_model(self):
        if self._st_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading SentenceTransformer embedding model: {self.model_name}")
                self._st_model = SentenceTransformer(self.model_name)
            except Exception as e:
                logger.warning(f"Could not load SentenceTransformer ({e}).")
        return self._st_model

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        # 1. Try FastEmbed (fastest, ONNX, zero CUDA conflict)
        fast_m = self._get_fastembed()
        if fast_m is not None:
            try:
                embeddings = list(fast_m.embed(texts))
                return [e.tolist() for e in embeddings]
            except Exception as e:
                logger.warning(f"FastEmbed failed ({e}). Trying SentenceTransformer.")

        # 2. Try SentenceTransformers
        st_m = self._get_st_model()
        if st_m is not None:
            try:
                embeddings = st_m.encode(texts, normalize_embeddings=True, show_progress_bar=False)
                return embeddings.tolist()
            except Exception as e:
                logger.warning(f"SentenceTransformer encoding failed ({e}). Falling back to Ollama.")

        # 3. Ollama Fallback
        return self._embed_via_ollama(texts)

    def embed_query(self, query: str) -> List[float]:
        # For BGE models, query instruction helps retrieval quality
        formatted_query = query
        if "bge" in self.model_name.lower() and not query.startswith("Represent this"):
            formatted_query = f"Represent this sentence for searching relevant passages: {query}"
        results = self.embed_texts([formatted_query])
        return results[0] if results else [0.0] * settings.EMBEDDING_DIM

    def _embed_via_ollama(self, texts: List[str]) -> List[List[float]]:
        vectors = []
        for text in texts:
            try:
                resp = requests.post(
                    f"{settings.LLM_BASE_URL}/api/embed",
                    json={"model": settings.LLM_MODEL, "input": text},
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    embeds = data.get("embeddings") or [data.get("embedding")]
                    vectors.append(embeds[0])
                    continue
            except Exception:
                pass

            # Fallback zero vector
            vectors.append([0.0] * settings.EMBEDDING_DIM)

        return vectors

embedder = EmbeddingService()
