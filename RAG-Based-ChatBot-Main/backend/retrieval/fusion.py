from typing import List, Dict, Any

def reciprocal_rank_fusion(
    ranking_lists: List[List[Dict[str, Any]]],
    k: int = 60
) -> List[Dict[str, Any]]:
    """
    Reciprocal Rank Fusion (RRF):
    Score(d) = sum_{list in ranking_lists} (1 / (k + rank(d)))
    k = 60 by default as per RRF benchmark literature.
    """
    chunk_map: Dict[str, Dict[str, Any]] = {}
    score_map: Dict[str, float] = {}

    for ranking in ranking_lists:
        for rank_0, item in enumerate(ranking):
            cid = item["chunk_id"]
            rank = rank_0 + 1  # 1-based rank
            if cid not in chunk_map:
                chunk_map[cid] = dict(item)
                score_map[cid] = 0.0

            score_map[cid] += 1.0 / (k + rank)

    # Attach final fusion score
    fused_results = []
    for cid, item in chunk_map.items():
        fused_item = dict(item)
        fused_item["rrf_score"] = score_map[cid]
        fused_item["score"] = score_map[cid]
        fused_results.append(fused_item)

    fused_results.sort(key=lambda x: x["score"], reverse=True)
    return fused_results

def weighted_score_fusion(
    vector_results: List[Dict[str, Any]],
    bm25_results: List[Dict[str, Any]],
    alpha: float = 0.5
) -> List[Dict[str, Any]]:
    """
    Linear weighted score fusion with Min-Max normalization:
    Score(d) = alpha * norm(vector_score) + (1 - alpha) * norm(bm25_score)
    """
    def min_max_normalize(items: List[Dict[str, Any]], score_key: str) -> Dict[str, float]:
        if not items:
            return {}
        scores = [it.get(score_key, 0.0) for it in items]
        min_s, max_s = min(scores), max(scores)
        if max_s == min_s:
            return {it["chunk_id"]: 1.0 for it in items}
        return {
            it["chunk_id"]: (it.get(score_key, 0.0) - min_s) / (max_s - min_s)
            for it in items
        }

    norm_vector = min_max_normalize(vector_results, "vector_score")
    norm_bm25 = min_max_normalize(bm25_results, "bm25_score")

    chunk_map: Dict[str, Dict[str, Any]] = {}
    for item in vector_results + bm25_results:
        cid = item["chunk_id"]
        if cid not in chunk_map:
            chunk_map[cid] = dict(item)

    fused_results = []
    for cid, item in chunk_map.items():
        v_s = norm_vector.get(cid, 0.0)
        b_s = norm_bm25.get(cid, 0.0)
        comb_score = (alpha * v_s) + ((1.0 - alpha) * b_s)
        fused_item = dict(item)
        fused_item["weighted_score"] = comb_score
        fused_item["score"] = comb_score
        fused_results.append(fused_item)

    fused_results.sort(key=lambda x: x["score"], reverse=True)
    return fused_results
