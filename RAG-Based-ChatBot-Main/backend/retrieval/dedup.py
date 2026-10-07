import re
from typing import List, Dict, Any, Set
from backend.config import settings

def get_char_ngrams(text: str, n: int = 3) -> Set[str]:
    """Extract set of character n-grams from normalized text."""
    clean = re.sub(r"\s+", " ", text.lower().strip())
    if len(clean) < n:
        return {clean}
    return {clean[i:i+n] for i in range(len(clean) - n + 1)}

def jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    return intersection / union if union > 0 else 0.0

def deduplicate_chunks(
    chunks: List[Dict[str, Any]],
    similarity_threshold: float = settings.DEDUP_SIMILARITY_THRESHOLD
) -> List[Dict[str, Any]]:
    """
    Deduplicates candidates:
    1. By exact chunk_id (preserves higher-ranked occurrence)
    2. By near-duplicate text similarity using character 3-gram Jaccard similarity.
    """
    seen_ids: Set[str] = set()
    unique_chunks: List[Dict[str, Any]] = []
    unique_ngram_sets: List[Set[str]] = []

    for item in chunks:
        cid = item.get("chunk_id")
        if not cid or cid in seen_ids:
            continue

        text = item.get("text", "")
        item_ngrams = get_char_ngrams(text, n=3)

        # Check against existing unique chunks
        is_near_duplicate = False
        for existing_ngrams in unique_ngram_sets:
            sim = jaccard_similarity(item_ngrams, existing_ngrams)
            if sim >= similarity_threshold:
                is_near_duplicate = True
                break

        if not is_near_duplicate:
            seen_ids.add(cid)
            unique_chunks.append(item)
            unique_ngram_sets.append(item_ngrams)

    return unique_chunks
