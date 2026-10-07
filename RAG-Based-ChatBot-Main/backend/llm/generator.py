import json
import logging
import asyncio
from typing import List, Dict, Any, AsyncGenerator, Optional, Tuple
from backend.config import settings
from backend.llm.client import ollama_client
from backend.retrieval.web_search import live_web_search

logger = logging.getLogger(__name__)

class GroundedGenerator:
    def __init__(self):
        pass

    def build_grounded_prompt(
        self,
        question: str,
        chunks: List[Dict[str, Any]]
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        """
        Builds compact numbered context and maps citations for frontend highlighting.
        Returns: (system_prompt, user_prompt, citations_payload)
        """
        system_prompt = (
            "You are an expert document assistant. You answer questions based on the provided document sources.\n\n"
            "Rules:\n"
            "1. Read the Context Sources carefully.\n"
            "2. If the user asks for a list or items (e.g. technical skills, education, projects), provide a comprehensive and complete list directly from the document without omitting any categories.\n"
            "3. If the answer is present in the sources, provide the exact facts directly from the document and cite [1].\n"
            "4. If the answer is completely absent from the document sources:\n"
            "   - State: 'This is not mentioned in the document.'\n"
            "5. Never invent facts about the document."
        )

        context_blocks = []
        citations_payload = []

        for idx, chunk in enumerate(chunks):
            source_num = idx + 1
            page = chunk.get("page", 1)
            text = chunk.get("text", "").strip()
            # Preserve full structured text up to 3500 chars so entire sections are visible
            snippet = text[:3500]

            context_blocks.append(f"[{source_num}] (Page {page}):\n{snippet}")
            citations_payload.append({
                "source_index": source_num,
                "chunk_id": chunk.get("chunk_id", ""),
                "doc_id": chunk.get("doc_id", ""),
                "page": page,
                "bboxes": chunk.get("bboxes", []),
                "heading_path": chunk.get("heading_path", []),
                "snippet": text[:250],
            })

        formatted_context = "\n\n".join(context_blocks)
        user_prompt = f"Context Sources:\n{formatted_context}\n\nQuestion: {question}\n\nAnswer:"
        return system_prompt, user_prompt, citations_payload

    def build_general_prompt(self, question: str, live_context: str = "") -> Tuple[str, str]:
        """
        Builds a comprehensive ChatGPT-style prompt with real-time live data for movies,
        stocks, sports, politics, and general queries.
        """
        system_prompt = (
            "You are an intelligent, versatile, and up-to-date AI assistant like ChatGPT.\n"
            "You provide accurate, well-structured, and helpful answers on all topics including:\n"
            "- Movies, entertainment, and pop culture\n"
            "- Stock market prices, financial analysis, and companies\n"
            "- Sports scores, teams, tournaments, and athletes\n"
            "- Politics, government, and world events\n"
            "- Technology, coding, science, and history\n"
            "When live web or market data is provided, use it to give exact, real-time answers."
        )
        if live_context:
            user_prompt = f"Live Real-Time Web Context:\n{live_context}\n\nUser Question: {question}\n\nHelpful & Detailed Answer:"
        else:
            user_prompt = f"User Question: {question}\n\nHelpful & Detailed Answer:"
        return system_prompt, user_prompt

    async def stream_rag_response(
        self,
        question: str,
        route: str,
        router_badge: str,
        retrieved_chunks: List[Dict[str, Any]],
        queries: List[str]
    ) -> AsyncGenerator[str, None]:
        """
        Yields Server-Sent Events (SSE) lines:
        - meta event (route badge, transformed queries)
        - token events (streaming LLM tokens)
        - citations event (list of cited sources with bboxes)
        - done event
        """
        # 1. Send meta event first
        meta_data = {
            "badge": router_badge,
            "route": route,
            "queries": queries,
        }
        yield f"event: meta\ndata: {json.dumps(meta_data)}\n\n"

        # Case A: General chat route (no documents active or ChatGPT mode)
        if route != "document":
            live_context = await asyncio.to_thread(live_web_search.get_live_context, question)
            system_prompt, prompt = self.build_general_prompt(question, live_context=live_context)
            async for token in ollama_client.stream_generate(
                prompt=prompt,
                system=system_prompt,
                temperature=0.7,
                max_tokens=settings.LLM_MAX_TOKENS
            ):
                yield f"event: token\ndata: {json.dumps({'content': token})}\n\n"

            yield f"event: citations\ndata: {json.dumps({'citations': []})}\n\n"
            yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"
            return

        # Case B: Document route but nothing retrieved or passed threshold
        # (e.g. off-topic question asked while document is loaded, like stocks, movies, sports)
        if not retrieved_chunks:
            notice = "This is not mentioned in the document.\n\n**Suggestions / Real-World Answer:**\n\n"
            for word in notice.split(" "):
                yield f"event: token\ndata: {json.dumps({'content': word + ' '})}\n\n"

            live_context = await asyncio.to_thread(live_web_search.get_live_context, question)
            gen_sys, gen_prompt = self.build_general_prompt(question, live_context=live_context)
            async for token in ollama_client.stream_generate(
                prompt=gen_prompt,
                system=gen_sys,
                temperature=0.7,
                max_tokens=settings.LLM_MAX_TOKENS
            ):
                yield f"event: token\ndata: {json.dumps({'content': token})}\n\n"

            yield f"event: citations\ndata: {json.dumps({'citations': []})}\n\n"
            yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"
            return

        # Case C: Document route with retrieved context chunks
        system_prompt, prompt, citations = self.build_grounded_prompt(question, retrieved_chunks)

        accumulated_tokens = []
        async for token in ollama_client.stream_generate(
            prompt=prompt,
            system=system_prompt,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS
        ):
            accumulated_tokens.append(token)
            yield f"event: token\ndata: {json.dumps({'content': token})}\n\n"

        full_text = "".join(accumulated_tokens).strip()
        full_text_lower = full_text.lower()

        # Check if the document did not contain the answer
        not_found_markers = [
            "not mentioned in the document",
            "not contain this information",
            "not found in the document",
            "not mentioned in the provided",
            "does not contain sufficient information"
        ]
        is_not_found = any(m in full_text_lower for m in not_found_markers)

        if is_not_found:
            # The model identified that this info is missing in the document.
            # Append live suggestions!
            header = "\n\n**Suggestions / Real-World Answer:**\n\n"
            yield f"event: token\ndata: {json.dumps({'content': header})}\n\n"

            live_context = await asyncio.to_thread(live_web_search.get_live_context, question)
            gen_sys, gen_prompt = self.build_general_prompt(question, live_context=live_context)
            async for token in ollama_client.stream_generate(
                prompt=gen_prompt,
                system=gen_sys,
                temperature=0.7,
                max_tokens=settings.LLM_MAX_TOKENS
            ):
                yield f"event: token\ndata: {json.dumps({'content': token})}\n\n"

            # No citations to highlight on document if not found in document
            citations = []
        else:
            # Fact found! Score all bounding boxes across all citations against the generated answer!
            citations = self.refine_citations_for_answer(
                citations=citations,
                answer_text=full_text,
                question_text=question
            )

        # Send citations event (only containing the exact answer highlight boxes)
        yield f"event: citations\ndata: {json.dumps({'citations': citations})}\n\n"
        yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"

    def refine_citations_for_answer(
        self,
        citations: List[Dict[str, Any]],
        answer_text: str,
        question_text: str
    ) -> List[Dict[str, Any]]:
        """
        Scores all candidate bounding boxes across all citations against the generated answer.
        Assigns the single highest-matching bounding box to the winning citation and clears others.
        Guarantees that the exact section answering the question is highlighted in the PDF.
        """
        if not citations or not answer_text:
            return citations

        import re
        stop_words = {
            'the', 'is', 'in', 'of', 'and', 'a', 'an', 'to', 'for', 'with', 'on', 'at',
            'by', 'from', 'this', 'that', 'are', 'was', 'were', 'document', 'resume',
            'candidate', 'answer', 'according', 'mentioned', 'based', 'context', 'listed', 'include'
        }

        ans_tokens = re.findall(r'[a-zA-Z0-9%]+', answer_text.lower())
        ans_keywords = [t for t in ans_tokens if len(t) > 1 and t not in stop_words]

        q_tokens = re.findall(r'[a-zA-Z0-9%]+', question_text.lower())
        q_keywords = [t for t in q_tokens if len(t) > 1 and t not in stop_words]

        best_score = -1
        best_box = None
        best_cite_idx = -1

        for c_idx, cite in enumerate(citations):
            for b in cite.get("bboxes", []):
                btext = (b.get("text") or "").lower()
                if not btext:
                    continue
                score = 0
                for kw in ans_keywords:
                    if kw in btext:
                        score += 3
                        if any(c.isdigit() or c == '%' for c in kw):
                            score += 6
                for kw in q_keywords:
                    if kw in btext:
                        score += 1

                if score > best_score:
                    best_score = score
                    best_box = b
                    best_cite_idx = c_idx

        # If a winning box was found, attach it ONLY to the winning citation
        refined = []
        for c_idx, cite in enumerate(citations):
            cite_copy = dict(cite)
            if c_idx == best_cite_idx and best_box is not None:
                cite_copy["bboxes"] = [best_box]
            else:
                cite_copy["bboxes"] = []
            refined.append(cite_copy)

        # Place the winning citation first so the frontend automatically opens and focuses it
        if best_cite_idx > 0:
            winner = refined.pop(best_cite_idx)
            refined.insert(0, winner)

        return refined

grounded_generator = GroundedGenerator()
