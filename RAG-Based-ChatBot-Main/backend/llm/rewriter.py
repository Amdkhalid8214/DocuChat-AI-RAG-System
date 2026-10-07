import re
import json
import logging
from typing import List, Dict
from backend.llm.client import ollama_client

logger = logging.getLogger(__name__)

class QueryRewriter:
    def __init__(self):
        pass

    async def transform_query(
        self,
        question: str,
        chat_history: List[Dict[str, str]]
    ) -> List[str]:
        """
        Rewrites question using chat history to resolve pronouns and generates 2-3 alternative queries.
        Returns list of queries: [standalone_query, alt_1, alt_2].
        """
        clean_q = question.strip()
        if not chat_history:
            # If no history, generate quick variations or return standalone
            return [
                clean_q,
                f"{clean_q} details",
                f"{clean_q} overview"
            ]

        # Format compact history (last 3 turns max to keep context window small for Qwen 1.5B)
        recent_turns = chat_history[-3:]
        history_lines = []
        for msg in recent_turns:
            role = msg.get("role", "user")
            content = msg.get("content", "").replace("\n", " ")[:150]
            history_lines.append(f"{role}: {content}")
        history_str = "\n".join(history_lines)

        short_prompt = f"""Task: Resolve pronouns in Question using History into a standalone query, and generate 2 search variations.
History:
{history_str}
Question: {clean_q}
Format: JSON only: {{"standalone": "...", "alternatives": ["...", "..."]}}
JSON:"""

        try:
            raw_resp = await ollama_client.generate_complete(
                prompt=short_prompt,
                temperature=0.2,
                max_tokens=100
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
            logger.warning(f"Query rewriter error: {e}")

        # Fallback if JSON generation fails or times out
        return [clean_q, f"{clean_q} information"]

query_rewriter = QueryRewriter()
