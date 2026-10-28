import logging
import math
import threading
from typing import List, Dict, Any
from backend.config import settings

logger = logging.getLogger(__name__)

class Reranker:
    def __init__(self):
        self.model_name = settings.RERANKER_MODEL
        self.enabled = settings.USE_RERANKER
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        if self._model is None and self.enabled:
            with self._lock:
                if self._model is None and self.enabled:
                    try:
                        from sentence_transformers import CrossEncoder
                        import torch
                        device = "cuda" if torch.cuda.is_available() else "cpu"
                        logger.info(f"Loading CrossEncoder reranker model: {self.model_name} on device: {device}")
                        self._model = CrossEncoder(
                            self.model_name,
                            max_length=512,
                            device=device,
                            model_kwargs={"low_cpu_mem_usage": False}
                        )
                    except Exception as e:
                        logger.warning(f"Could not load CrossEncoder model {self.model_name} ({e}). Falling back to fusion scores.")
                        self.enabled = False
        return self._model

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_n: int = 15
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

        # Fallback: Normalize fusion scores with query keyword overlap validation
        if subset:
            import re
            stop_words = {
                'the', 'is', 'in', 'of', 'and', 'a', 'an', 'to', 'for', 'with', 'on', 'at',
                'by', 'from', 'this', 'that', 'are', 'was', 'were', 'document', 'resume',
                'what', 'write', 'how', 'when', 'where', 'who', 'why', 'can', 'you'
            }
            q_words = [w for w in re.findall(r"\b\w+\b", query.lower()) if len(w) > 2 and w not in stop_words]
            max_s = max(it.get("score", 0.0) for it in subset)
            for item in subset:
                raw_s = item.get("score", 0.0)
                base_norm = (raw_s / max_s) if max_s > 0 else 0.0

                text_lower = item.get("text", "").lower()
                overlap = sum(1 for w in q_words if w in text_lower)
                overlap_ratio = overlap / max(len(q_words), 1) if q_words else 1.0

                # If query has specific content words and NONE are in the candidate chunk, penalize heavily
                # so it falls below SCORE_THRESHOLD (0.25)
                if q_words and overlap == 0:
                    final_s = min(base_norm * 0.1, 0.15)
                else:
                    final_s = base_norm * (0.5 + 0.5 * overlap_ratio)

                item["rerank_score"] = final_s
                item["score"] = final_s

            subset.sort(key=lambda x: x["score"], reverse=True)
        return subset

reranker = Reranker()
