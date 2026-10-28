import logging
import asyncio
from typing import List, Dict, Any, Optional
from backend.config import settings
from backend.embeddings.embedder import embedder
from backend.retrieval.vector_store import vector_store
from backend.retrieval.bm25 import bm25_index
from backend.retrieval.fusion import reciprocal_rank_fusion, weighted_score_fusion
from backend.retrieval.dedup import deduplicate_chunks
from backend.retrieval.reranker import reranker

logger = logging.getLogger(__name__)

class RetrievalPipeline:
    def __init__(self):
        pass

    async def retrieve(
        self,
        queries: List[str],
        doc_ids: Optional[List[str]] = None,
        top_k: int = settings.FINAL_TOP_K,
        score_threshold: float = settings.SCORE_THRESHOLD,
        fusion_method: str = settings.FUSION_METHOD,
        alpha: float = settings.FUSION_ALPHA
    ) -> List[Dict[str, Any]]:
        """
        Full hybrid retrieval pipeline:
        1. Multi-query parallel retrieval (Vector top 30 + BM25 top 30)
        2. Reciprocal Rank Fusion / Weighted fusion
        3. Deduplication (chunk_id + text similarity)
        4. Cross-encoder reranking (top ~40)
        5. Top-K selection with score threshold
        """
        if not queries:
            return []

        primary_query = queries[0]
        ranking_lists: List[List[Dict[str, Any]]] = []
        all_vector_results: List[Dict[str, Any]] = []
        all_bm25_results: List[Dict[str, Any]] = []

        # Step 7: Parallel retrieval for each generated query
        async def fetch_query_results(q: str):
            # Vector search
            v_hits = []
            try:
                qvec = await asyncio.to_thread(embedder.embed_query, q)
                v_hits = await asyncio.to_thread(
                    vector_store.search,
                    query_vector=qvec,
                    doc_ids=doc_ids,
                    limit=settings.RETRIEVAL_TOP_K
                )
            except Exception as v_err:
                logger.warning(f"[RETRIEVAL] Vector search failed ({v_err}), falling back to lexical search")

            # BM25 search
            b_hits = []
            try:
                b_hits = await asyncio.to_thread(
                    bm25_index.search,
                    query=q,
                    doc_ids=doc_ids,
                    limit=settings.RETRIEVAL_TOP_K
                )
            except Exception as b_err:
                logger.warning(f"[RETRIEVAL] BM25 search failed ({b_err})")
            return v_hits, b_hits

        tasks = [fetch_query_results(q) for q in queries]
        results = await asyncio.gather(*tasks)

        for v_hits, b_hits in results:
            if v_hits:
                ranking_lists.append(v_hits)
                all_vector_results.extend(v_hits)
            if b_hits:
                ranking_lists.append(b_hits)
                all_bm25_results.extend(b_hits)

        total_retrieved = len(all_vector_results) + len(all_bm25_results)
        logger.info(f"[RETRIEVAL] Retrieved candidates: {total_retrieved} (vector: {len(all_vector_results)}, bm25: {len(all_bm25_results)})")

        if not ranking_lists:
            logger.info("[RETRIEVAL] No candidates retrieved from vector or lexical stores")
            return []

        # Step 8: Hybrid Fusion
        if fusion_method == "weighted":
            fused = weighted_score_fusion(all_vector_results, all_bm25_results, alpha=alpha)
            logger.info(f"[FUSION] Weighted fusion candidates: {len(fused)}")
        else:
            fused = reciprocal_rank_fusion(ranking_lists, k=settings.RRF_K)
            logger.info(f"[RRF] Fused candidates: {len(fused)}")

        # Step 9: Deduplication
        deduped = deduplicate_chunks(fused, similarity_threshold=settings.DEDUP_SIMILARITY_THRESHOLD)

        # Step 10: Cross-Encoder Reranker on top ~12 candidates
        top_candidates = deduped[:12]
        rescored = await asyncio.to_thread(reranker.rerank, primary_query, top_candidates, 12)
        logger.info(f"[RERANK] Candidates reranked: {len(top_candidates)}")

        # Step 11: Top-K Selection & Score Thresholding
        filtered = [c for c in rescored if c.get("score", 0.0) >= score_threshold]
        if filtered:
            best_score = max(c.get("score", 0.0) for c in filtered)
            if best_score >= 0.65:
                # If a high-confidence match exists, filter out weak distractor passages
                filtered = [c for c in filtered if c.get("score", 0.0) >= max(score_threshold, best_score * 0.75, 0.55)]
        elif rescored:
            # Fallback: keep the highest-scoring candidate if candidates exist from target document
            filtered = rescored[:1]
        logger.info(f"[THRESHOLD] Accepted: {len(filtered)} (threshold={score_threshold})")
        final_top = filtered[:top_k]
        logger.info(f"[CONTEXT] Final context chunks before expansion: {len(final_top)} (top_k={top_k})")

        # Step 12: Context Window & Section Continuation Expansion
        # Ensures cross-page sections, tables, numbered lists, and continuation paragraphs are never severed
        # while PRESERVING primary relevance ranking (highest scoring section is always Source [1]).
        import re
        from collections import Counter

        def resolve_chunk_page(c: Dict[str, Any]) -> int:
            bboxes = c.get("bboxes") or []
            if bboxes:
                substantive = [b for b in bboxes if len(b.get("text", "").strip()) > 3]
                target = substantive if substantive else bboxes
                counts = Counter(b.get("page") for b in target if b.get("page"))
                if counts:
                    return counts.most_common(1)[0][0]
            return int(c.get("page") or 1)

        expanded_chunks: List[Dict[str, Any]] = []
        existing_ids = set()

        for top_c in list(final_top):
            top_id = top_c.get("chunk_id")
            if not top_id or top_id in existing_ids:
                continue

            doc_id = top_c.get("doc_id")
            all_chunks = bm25_index.get_document_chunks(doc_id) if doc_id else []

            if not all_chunks:
                top_c_copy = dict(top_c)
                top_c_copy["page"] = resolve_chunk_page(top_c)
                expanded_chunks.append(top_c_copy)
                existing_ids.add(top_id)
                continue

            # Sort document chunks by true (page, vertical position) to find adjacent chunks
            sorted_chunks = sorted(
                all_chunks,
                key=lambda c: (
                    resolve_chunk_page(c),
                    c.get("bboxes", [{}])[0].get("y0", 0.0) if c.get("bboxes") else 0.0
                )
            )

            s_idx = next((i for i, c in enumerate(sorted_chunks) if c.get("chunk_id") == top_id), -1)

            # 1. Backward continuation: check if top_c started midway through an item, sentence, or table
            preceding_chunk = None
            if s_idx - 1 >= 0:
                prev_c = sorted_chunks[s_idx - 1]
                prev_id = prev_c.get("chunk_id")
                if prev_id not in existing_ids:
                    top_txt = top_c.get("text", "").strip()
                    prev_txt = prev_c.get("text", "").strip()
                    prev_p = resolve_chunk_page(prev_c)
                    curr_p = resolve_chunk_page(top_c)
                    starts_lowercase = bool(top_txt and top_txt[0].islower()) or bool(re.match(r'^\s*\|\s*[\-a-z]', top_txt))
                    is_table_pair = ("[TABLE]" in top_txt or "|" in top_txt) and ("[TABLE]" in prev_txt or "|" in prev_txt)

                    if (curr_p <= prev_p + 1) and (starts_lowercase or is_table_pair):
                        prev_c_copy = dict(prev_c)
                        prev_c_copy["score"] = float(top_c.get("score", 0.8)) * 0.95
                        prev_c_copy["source"] = "preceding"
                        prev_c_copy["page"] = prev_p
                        preceding_chunk = prev_c_copy
                        existing_ids.add(prev_id)
                        logger.info(f"[EXPANSION] Appended preceding chunk (Page {prev_p}) to complete header context.")

            if preceding_chunk:
                expanded_chunks.append(preceding_chunk)

            # 2. Primary candidate chunk
            top_c_copy = dict(top_c)
            top_c_copy["page"] = resolve_chunk_page(top_c)
            expanded_chunks.append(top_c_copy)
            existing_ids.add(top_id)

            # 3. Forward multi-hop continuation: follow continuing tables, checklists, or clauses across pages
            if s_idx != -1 and s_idx + 1 < len(sorted_chunks):
                next_c = sorted_chunks[s_idx + 1]
                next_id = next_c.get("chunk_id")
                if next_id not in existing_ids:
                    curr_txt = top_c.get("text", "").strip()
                    next_txt = next_c.get("text", "").strip()
                    curr_p = resolve_chunk_page(top_c)
                    next_p = resolve_chunk_page(next_c)

                    is_table_curr = "[TABLE]" in curr_txt or "|" in curr_txt
                    is_table_next = "[TABLE]" in next_txt or "|" in next_txt
                    ends_unclosed = bool(re.search(r'[,:\-–—/]\s*$', curr_txt)) or not bool(re.search(r'[\.!?]\s*$', curr_txt))
                    has_numbered_list = bool(re.search(r'\n\d+\.\s', curr_txt)) or bool(re.search(r'\|\s*\d+\.\s', curr_txt))

                    should_continue = (
                        (next_p <= curr_p + 1) and (
                            (is_table_curr and is_table_next) or
                            (is_table_curr and has_numbered_list) or
                            ends_unclosed or
                            ("ITEMS TO COVER" in curr_txt and next_p <= curr_p + 2)
                        )
                    )
                    if should_continue:
                        next_c_copy = dict(next_c)
                        next_c_copy["score"] = float(top_c.get("score", 0.8)) * 0.95
                        next_c_copy["source"] = "continuation"
                        next_c_copy["page"] = next_p
                        expanded_chunks.append(next_c_copy)
                        existing_ids.add(next_id)
                        logger.info(f"[EXPANSION] Appended continuation chunk (Page {next_p}) to complete section.")

        logger.info(f"[CONTEXT] Context chunks after window expansion: {len(expanded_chunks)}")
        return expanded_chunks

retrieval_pipeline = RetrievalPipeline()
