import logging
import math
from typing import List, Dict, Any
from backend.config import settings

logger = logging.getLogger(__name__)

class Reranker:
    def __init__(self):
        self.model_name = settings.RERANKER_MODEL
        self.enabled = settings.USE_RERANKER
        self._model = None

    def _get_model(self):
        if self._model is None and self.enabled:
            try:
                from sentence_transformers import CrossEncoder
                logger.info(f"Loading CrossEncoder reranker model: {self.model_name}")
                self._model = CrossEncoder(self.model_name, max_length=512)
            except Exception as e:
                logger.warning(f"Could not load CrossEncoder model {self.model_name} ({e}). Falling back to fusion scores.")
                self.enabled = False
        return self._model

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_n: int = 40
    ) -> List[Dict[str, Any]]:
        """
        Rescores top candidate passages using Cross-Encoder.
        """
        if not candidates:
            return []

        subset = candidates[:top_n]
        model = self._get_model()

        if model is not None and self.enabled:
            try:
                pairs = [[query, item.get("text", "")] for item in subset]
                scores = model.predict(pairs)

                # Convert numpy array / logits to normalized probability with sigmoid
                rescored = []
                for item, score in zip(subset, scores):
                    val = float(score)
                    # Apply sigmoid if score is raw logit
                    norm_score = 1.0 / (1.0 + math.exp(-val)) if -20 < val < 20 else (1.0 if val >= 20 else 0.0)
                    copied = dict(item)
                    copied["rerank_score"] = norm_score
                    copied["score"] = norm_score
                    rescored.append(copied)

                rescored.sort(key=lambda x: x["score"], reverse=True)
                return rescored
            except Exception as e:
                logger.error(f"CrossEncoder reranking error: {e}")

        # Fallback: Normalize fusion scores to [0, 1] using max-scaling (preserves valid candidate chunks)
        if subset:
            max_s = max(it.get("score", 0.0) for it in subset)
            for item in subset:
                raw_s = item.get("score", 0.0)
                norm_s = (raw_s / max_s) if max_s > 0 else 1.0
                item["rerank_score"] = norm_s
                item["score"] = norm_s
        return subset

reranker = Reranker()
