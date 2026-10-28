import re
import json
import asyncio
import logging
from typing import List, Dict
from backend.llm.client import ollama_client

logger = logging.getLogger(__name__)

PRONOUN_PATTERN = re.compile(
    r"\b(it|its|he|him|his|she|her|hers|they|them|their|theirs|this|that|these|those|former|latter|the same)\b",
    re.IGNORECASE
)

from backend.llm.memory import is_followup_question, build_memory_context_block

class QueryRewriter:
    def __init__(self):
        pass

    async def transform_query(
        self,
        question: str,
        chat_history: List[Dict[str, str]]
    ) -> List[str]:
        """
        Rewrites question using chat history to resolve pronouns and follow-up references
        and generates 2-3 alternative queries.
        Returns list of queries: [standalone_query, alt_1, alt_2].
        """
        clean_q = question.strip()

        # Handle compound questions joined by "and", "along with", "as well as", or comma
        if re.search(r"\b(and|as well as|along with)\b", clean_q, re.I):
            parts = re.split(r"\b(?:and|as well as|along with)\b", clean_q, flags=re.I)
            sub_queries = [p.strip() for p in parts if len(p.strip()) >= 10]
            if len(sub_queries) >= 2:
                # Clean leading phrases like 'explain', 'what are', 'tell me about'
                clean_subs = []
                for sq in sub_queries[:2]:
                    c_sub = re.sub(r'^(?:explain|describe|what are|what is|tell me about|list|detail)\s+(?:the\s+)?', '', sq, flags=re.I).strip()
                    clean_subs.append(c_sub if len(c_sub) >= 5 else sq)
                return [clean_q, clean_subs[0], clean_subs[1]]

        # Fast bypass: If no chat history or the question has no pronouns/anaphora/follow-up markers,
        # it is already standalone. Skip the extra synchronous LLM call to save latency.
        if not chat_history or not is_followup_question(clean_q):
            return [
                clean_q,
                f"{clean_q} details",
                f"{clean_q} overview"
            ]

        # Format compact history using memory context block (bounded turns to keep prompt focused)
        history_str = build_memory_context_block(chat_history, max_turns=3)

        short_prompt = f"""Task: Resolve pronouns, references, and follow-ups in Question using History into a standalone query, and generate 2 search variations.
History:
{history_str}
Question: {clean_q}
Format: JSON only: {{"standalone": "...", "alternatives": ["...", "..."]}}
JSON:"""

        try:
            raw_resp = await asyncio.wait_for(
                ollama_client.generate_complete(
                    prompt=short_prompt,
                    temperature=0.2,
                    max_tokens=60
                ),
                timeout=1.2
            )

            json_match = re.search(r"\{.*?\}", raw_resp, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                standalone = parsed.get("standalone", "").strip() or clean_q
                alts = parsed.get("alternatives", [])
                clean_alts = [str(a).strip() for a in alts if str(a).strip() and str(a).strip() != standalone]
                
                queries = [standalone] + clean_alts[:2]
                if len(queries) < 2:
                    queries.append(clean_q)
                return queries

        except Exception as e:
            logger.debug(f"Query rewriter fast-fallback: {e}")

        # Fallback if generation times out: enrich with prior user query terms instantly
        last_user_query = ""
        for msg in reversed(chat_history):
            if msg.get("role") == "user":
                last_user_query = str(msg.get("content", "")).strip()
                break
        if last_user_query:
            return [clean_q, f"{clean_q} {last_user_query}", f"{last_user_query} details"]
        return [clean_q, f"{clean_q} information"]

query_rewriter = QueryRewriter()
