import re
import json
import logging
import asyncio
from typing import List, Dict, Any, AsyncGenerator, Optional, Tuple
from backend.config import settings
from backend.llm.client import ollama_client
from backend.llm.langchain_adapter import langchain_adapter
from backend.retrieval.web_search import live_web_search
from backend.llm.router import is_verbatim_extraction_request, GREETINGS_PATTERN
from backend.llm.prompts import (
    GROUNDED_SYSTEM_TEMPLATE,
    GROUNDED_HUMAN_TEMPLATE,
    VERBATIM_EXTRACTION_SYSTEM_TEMPLATE,
    VERBATIM_EXTRACTION_HUMAN_TEMPLATE,
    GENERAL_SYSTEM_TEMPLATE,
    GENERAL_HUMAN_TEMPLATE_PLAIN,
    GENERAL_HUMAN_TEMPLATE_WITH_WEB,
    NOT_FOUND_RESPONSE,
    GroundingValidationResult,
)

logger = logging.getLogger(__name__)

class GroundedGenerator:
    def __init__(self):
        pass

    def build_grounded_prompt(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        max_char_budget: Optional[int] = None
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        """
        Builds grounded numbered context and maps citations for frontend highlighting.
        Adheres strictly to GROUNDED_SYSTEM_TEMPLATE and GROUNDED_HUMAN_TEMPLATE.
        Uses a context budget rather than arbitrary hard truncation.
        Returns: (system_prompt, user_prompt, citations_payload)
        """
        from collections import Counter

        if max_char_budget is None:
            configured_budget = getattr(settings, "CONTEXT_BUDGET_TOKENS", 750)
            ctx_tokens = getattr(settings, "LLM_NUM_CTX", 2048)
            max_out_tokens = getattr(settings, "LLM_MAX_TOKENS", 512)
            available_tokens = min(configured_budget, max(500, ctx_tokens - max_out_tokens - 400))
            max_char_budget = available_tokens * 4

        context_blocks = []
        citations_payload = []
        current_chars = 0

        for idx, chunk in enumerate(chunks):
            source_num = idx + 1
            bboxes = chunk.get("bboxes") or []

            # Resolve true page and candidate page span
            raw_page = chunk.get("page", 1)
            candidate_pages = []
            if bboxes:
                candidate_pages = sorted(list(set(int(b.get("page")) for b in bboxes if b.get("page"))))
            if not candidate_pages:
                candidate_pages = [int(raw_page)]

            if bboxes:
                substantive = [b for b in bboxes if len(b.get("text", "").strip()) > 3]
                target = substantive if substantive else bboxes
                counts = Counter(int(b.get("page")) for b in target if b.get("page"))
                true_page = counts.most_common(1)[0][0] if counts else int(raw_page)
            else:
                true_page = int(raw_page)

            if len(candidate_pages) > 1:
                page_str = f"{candidate_pages[0]}-{candidate_pages[-1]}"
            else:
                page_str = str(true_page)

            text = chunk.get("text", "").strip()
            header = f"=== CONTEXT SOURCE [{source_num}] (Page {page_str}) ==="
            header_len = len(header) + 2

            # Budget check: avoid slicing chunks arbitrarily unless necessary
            remaining_budget = max_char_budget - current_chars - header_len
            if remaining_budget <= 150 and context_blocks:
                logger.info(f"[CONTEXT] Budget reached at chunk {idx+1}/{len(chunks)} ({current_chars}/{max_char_budget} chars)")
                break

            if len(text) > remaining_budget and context_blocks:
                snippet = text[:remaining_budget]
            else:
                snippet = text

            context_blocks.append(f"{header}\n{snippet}")
            current_chars += header_len + len(snippet)

            citations_payload.append({
                "source_index": source_num,
                "chunk_id": chunk.get("chunk_id", ""),
                "doc_id": chunk.get("doc_id", ""),
                "filename": chunk.get("filename") or chunk.get("doc_name", ""),
                "page": true_page,
                "candidate_pages": candidate_pages,
                "bboxes": bboxes,
                "heading_path": chunk.get("heading_path", []),
                "snippet": text[:250],
                "full_text": text,
                "text": text,
            })

        formatted_context = "\n\n".join(context_blocks)
        system_prompt = GROUNDED_SYSTEM_TEMPLATE
        user_prompt = GROUNDED_HUMAN_TEMPLATE.format(
            context=formatted_context,
            question=question
        )
        return system_prompt, user_prompt, citations_payload

    def build_verbatim_prompt(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        max_char_budget: Optional[int] = None
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        """
        Builds prompt for exact-text or verbatim extraction requests
        (VERBATIM_EXTRACTION_SYSTEM_TEMPLATE + VERBATIM_EXTRACTION_HUMAN_TEMPLATE).
        """
        system_prompt, _, citations_payload = self.build_grounded_prompt(
            question=question,
            chunks=chunks,
            max_char_budget=max_char_budget
        )
        # Reformat user prompt with verbatim extraction human template
        context_blocks = []
        for idx, cite in enumerate(citations_payload):
            page_str = str(cite.get("page", 1))
            cand = cite.get("candidate_pages", [])
            if len(cand) > 1:
                page_str = f"{cand[0]}-{cand[-1]}"
            header = f"=== CONTEXT SOURCE [{cite.get('source_index', idx+1)}] (Page {page_str}) ==="
            context_blocks.append(f"{header}\n{cite.get('full_text', cite.get('text', ''))}")

        formatted_context = "\n\n".join(context_blocks)
        user_prompt = VERBATIM_EXTRACTION_HUMAN_TEMPLATE.format(
            context=formatted_context,
            question=question
        )
        return VERBATIM_EXTRACTION_SYSTEM_TEMPLATE, user_prompt, citations_payload

    def build_general_prompt(self, question: str, live_context: str = "") -> Tuple[str, str]:
        """
        Builds prompt for general chat queries unrelated to document-grounded retrieval.
        """
        system_prompt = GENERAL_SYSTEM_TEMPLATE
        if live_context:
            user_prompt = GENERAL_HUMAN_TEMPLATE_WITH_WEB.format(
                live_context=live_context,
                question=question
            )
        else:
            user_prompt = GENERAL_HUMAN_TEMPLATE_PLAIN.format(
                question=question
            )
        return system_prompt, user_prompt

    async def stream_rag_response(
        self,
        question: str,
        route: str,
        router_badge: str,
        retrieved_chunks: List[Dict[str, Any]],
        queries: List[str],
        web_mode: bool = False,
        history: Optional[List[Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Yields Server-Sent Events (SSE) lines:
        - meta event (route badge, transformed queries)
        - token events (streaming LLM tokens orchestrated via LangChain)
        - citations event (list of cited sources with bboxes for PDF.js highlighting or web links)
        - done event
        When web_mode is False, web search is strictly prohibited.
        When web_mode is True, web search is permitted via SearXNG.
        Injects bounded persistent conversational memory across all modes.
        """
        from backend.tools.searxng_search import active_web_citations
        from backend.tools.weather import active_weather_data
        from backend.tools.excel_generator import active_excel_artifact, generate_workbook_from_request
        from backend.tools.document_generator import active_document_artifact, generate_document_from_request
        from backend.tools.pdf_tools import active_pdf_artifact, execute_pdf_tool_from_request
        from backend.llm.router import is_excel_generation_request, is_document_generation_request, is_pdf_tools

        active_web_citations.set([])
        active_weather_data.set(None)
        active_excel_artifact.set(None)
        active_document_artifact.set(None)
        active_pdf_artifact.set(None)

        # Determine exact request type
        is_verbatim = is_verbatim_extraction_request(question)
        prompt_type = "verbatim_extraction" if is_verbatim else "grounded_qa"

        is_excel_gen = (route == "excel_generation" or is_excel_generation_request(question))
        if is_excel_gen:
            route = "excel_generation"
            router_badge = "📊 Excel Generator"
            prompt_type = "excel_generation"

        is_doc_gen = (route == "document_generation" or is_document_generation_request(question))
        if is_doc_gen:
            route = "document_generation"
            router_badge = "📝 Document Generator"
            prompt_type = "document_generation"

        is_pdf = (route == "pdf_tools" or is_pdf_tools(question))
        if is_pdf:
            route = "pdf_tools"
            router_badge = "🛠️ PDF Tools"
            prompt_type = "pdf_tools"

        if is_verbatim and route == "document":
            router_badge = "Exact Extraction"

        # 1. Send meta event first
        meta_data = {
            "badge": router_badge,
            "route": route,
            "queries": queries,
            "prompt_type": prompt_type,
            "web_mode": web_mode,
        }
        yield f"event: meta\ndata: {json.dumps(meta_data, ensure_ascii=False)}\n\n"

        # Case 0: Excel Generation Route
        if is_excel_gen:
            active_excel_artifact.set(None)
            try:
                # 1. Provide retrieved document context if available (for document-based excel generation)
                doc_ctx = ""
                if retrieved_chunks:
                    doc_ctx = "\n\n".join([c.get("text", "") for c in retrieved_chunks[:3]])

                # 2. Provide live web research context if external information is explicitly requested
                web_ctx = ""
                has_synthetic_keyword = bool(re.search(r"\b(?:synthetic|random|mock|dummy|fake|sample)\b", question, re.I))
                external_research_needed = bool(
                    re.search(r"\b(research|web\s+search|internet|online|current\s+(?:prices?|info|information|data|statistics|stats)|latest\s+(?:news|info|information|prices?|stats))\b", question, re.I)
                    or (web_mode and not doc_ctx and not has_synthetic_keyword and not re.search(r"\b(?:students?|customers?|employees?|test\s+cases?)\b", question, re.I))
                ) and not has_synthetic_keyword

                if external_research_needed:
                    from backend.tools.searxng_search import search_searxng_async, active_web_citations
                    from backend.llm.memory import package_web_citations
                    try:
                        search_res = await search_searxng_async(question, inspect_pages=True, fallback=True)
                        if search_res.get("results"):
                            web_ctx = search_res.get("formatted", "")
                            cites = package_web_citations(question, search_res["results"])
                            active_web_citations.set(cites)
                    except Exception as err:
                        logger.warning(f"[EXCEL_GEN] Web research failed: {err}")

                combined_ctx = f"{doc_ctx}\n\n{web_ctx}".strip()

                artifact = await generate_workbook_from_request(
                    prompt=question,
                    history=history,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    context=combined_ctx
                )
                active_excel_artifact.set(artifact)

                # Emit structured excel_artifact event for chat UI card and coverage dashboard
                yield f"event: excel_artifact\ndata: {json.dumps(artifact, ensure_ascii=False)}\n\n"

                # Stream confirmation message tokens
                reply_text = artifact.get(
                    "reply_message",
                    f"Done, AMD! I generated the Excel workbook {artifact.get('filename')}."
                )
                words = reply_text.split(" ")
                for idx, w in enumerate(words):
                    tok = w if idx == len(words) - 1 else w + " "
                    yield f"event: token\ndata: {json.dumps({'content': tok}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

            except Exception as ex:
                logger.error(f"[EXCEL_GEN] Failed to generate Excel workbook: {ex}", exc_info=True)
                err_text = f"Failed to generate Excel workbook: {str(ex)}"
                for w in err_text.split(" "):
                    yield f"event: token\ndata: {json.dumps({'content': w + ' '}, ensure_ascii=False)}\n\n"

            web_cites = active_web_citations.get([])
            yield f"event: citations\ndata: {json.dumps({'citations': web_cites})}\n\n"
            yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"
            return

        # Case 0.5: Document Generation Route (DOCX, PDF, TXT, MD)
        if is_doc_gen:
            active_document_artifact.set(None)
            try:
                # 1. Provide retrieved document context if available (for document-based report generation)
                doc_ctx = ""
                if retrieved_chunks:
                    doc_ctx = "\n\n".join([c.get("text", "") for c in retrieved_chunks[:5]])

                artifact = await generate_document_from_request(
                    prompt=question,
                    context=doc_ctx,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    history=history
                )
                active_document_artifact.set(artifact)

                # Emit structured document_artifact event for chat UI card
                yield f"event: document_artifact\ndata: {json.dumps(artifact, ensure_ascii=False)}\n\n"

                # Stream confirmation message tokens
                reply_text = artifact.get(
                    "reply_message",
                    f"Done! I generated the {artifact.get('file_type')} {artifact.get('filename')}."
                )
                words = reply_text.split(" ")
                for idx, w in enumerate(words):
                    tok = w if idx == len(words) - 1 else w + " "
                    yield f"event: token\ndata: {json.dumps({'content': tok}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

            except Exception as ex:
                logger.error(f"[DOC_GEN] Failed to generate document: {ex}", exc_info=True)
                err_text = f"Failed to generate document: {str(ex)}"
                for w in err_text.split(" "):
                    yield f"event: token\ndata: {json.dumps({'content': w + ' '}, ensure_ascii=False)}\n\n"

            yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"
            return

        # Case 0.7: PDF Tools Route (Merge, Split, Extract, Rotate, Compress, Text, Tables, Info, etc.)
        if is_pdf:
            active_pdf_artifact.set(None)
            try:
                # Resolve candidate documents if provided or open
                candidate_doc_ids = []
                if retrieved_chunks:
                    candidate_doc_ids = list({c.get("doc_id") for c in retrieved_chunks if c.get("doc_id")})

                artifact = await execute_pdf_tool_from_request(
                    prompt=question,
                    doc_ids=candidate_doc_ids,
                    history=history,
                    user_id=user_id,
                    conversation_id=conversation_id
                )
                active_pdf_artifact.set(artifact)

                # Emit structured pdf_artifact event for chat UI card
                yield f"event: pdf_artifact\ndata: {json.dumps(artifact, ensure_ascii=False)}\n\n"

                # Stream confirmation message tokens
                reply_text = artifact.get(
                    "reply_message",
                    f"Done! I processed the PDF and created {artifact.get('filename')}."
                )
                words = reply_text.split(" ")
                for idx, w in enumerate(words):
                    tok = w if idx == len(words) - 1 else w + " "
                    yield f"event: token\ndata: {json.dumps({'content': tok}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.01)

            except Exception as ex:
                logger.error(f"[PDF_TOOLS] Failed to execute PDF tool: {ex}", exc_info=True)
                err_text = f"Failed to execute PDF tool: {str(ex)}"
                for w in err_text.split(" "):
                    yield f"event: token\ndata: {json.dumps({'content': w + ' '}, ensure_ascii=False)}\n\n"

            yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"
            return

        # Case A: General chat route or explicit web mode route
        if route != "document":
            from backend.tools.weather import active_weather_data, get_weather_forecast_async, extract_location_from_query
            from backend.llm.router import is_weather_request, is_explicit_web_search_request, GREETINGS_PATTERN
            from backend.tools.searxng_search import active_web_citations, search_searxng_async
            from backend.llm.memory import package_web_citations
            active_weather_data.set(None)
            active_web_citations.set([])

            live_context = ""
            is_weather = is_weather_request(question)
            if is_weather:
                router_badge = "⛅ Live Weather"
                # Proactively resolve real Open-Meteo weather data to ground the response
                target_loc = extract_location_from_query(question) or "Goa"
                try:
                    w_res = await get_weather_forecast_async(target_loc)
                    if w_res.get("status") == "success" and w_res.get("weather"):
                        active_weather_data.set(w_res["weather"])
                        live_context = (
                            f"Verified real-time weather from Open-Meteo:\n{w_res['summary']}\n"
                            f"Provide a friendly, crisp 2-3 bullet point summary for {w_res['weather']['location']}: "
                            "current temperature & condition, rain probability, and clothing advice. "
                            "Keep it concise and under 60 words."
                        )
                        # Immediately yield weather event for frontend WeatherCard
                        yield f"event: weather\ndata: {json.dumps(w_res['weather'])}\n\n"
                except Exception as ex:
                    logger.warning(f"Error fetching live weather in generator: {ex}")

            elif router_badge == "📊 Formula Explainer":
                live_context = (
                    "You are a senior Excel specialist and financial modeling architect. "
                    "The user is asking to explain an Excel formula, function, or expression. "
                    "Provide a clear, authoritative explanation with:\n"
                    "1. Executive Summary: What the formula computes.\n"
                    "2. Syntax & Parameters: What each argument represents.\n"
                    "3. Working Example: Concrete cell values and output.\n"
                    "4. Error Handling: Common pitfalls (#DIV/0!, #N/A, #VALUE!) and safeguards (IFERROR, ISBLANK)."
                )

            elif (route == "web" or (web_mode and not is_weather) or is_explicit_web_search_request(question)) and not bool(GREETINGS_PATTERN.match(question.strip())):
                router_badge = "🌐 Live Web Search"
                try:
                    search_res = await search_searxng_async(question, inspect_pages=True, fallback=True)
                    if search_res.get("results"):
                        live_context = search_res.get("formatted", "")
                        cites = package_web_citations(question, search_res["results"])
                        active_web_citations.set(cites)
                except Exception as ex:
                    logger.warning(f"Error during proactive web research in generator: {ex}")

            async for token in langchain_adapter.stream_general_chat(
                question=question,
                live_context=live_context,
                temperature=0.7,
                max_tokens=settings.LLM_MAX_TOKENS,
                web_mode=web_mode,
                history=history,
            ):
                yield f"event: token\ndata: {json.dumps({'content': token})}\n\n"

            # Check if weather tool was executed during LangChain tool calls
            weather_payload = active_weather_data.get()
            if weather_payload and not is_weather:
                yield f"event: weather\ndata: {json.dumps(weather_payload)}\n\n"

            # Check if excel generator tool was executed during LangChain tool calls
            excel_art = active_excel_artifact.get()
            if excel_art:
                yield f"event: excel_artifact\ndata: {json.dumps(excel_art, ensure_ascii=False)}\n\n"

            # Check if document generator tool was executed
            doc_art = active_document_artifact.get()
            if doc_art:
                yield f"event: document_artifact\ndata: {json.dumps(doc_art, ensure_ascii=False)}\n\n"

            # Check if pdf tools was executed
            pdf_art = active_pdf_artifact.get()
            if pdf_art:
                yield f"event: pdf_artifact\ndata: {json.dumps(pdf_art, ensure_ascii=False)}\n\n"

            web_cites = active_web_citations.get([])
            yield f"event: citations\ndata: {json.dumps({'citations': web_cites})}\n\n"
            yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"
            return

        # Check if Spreadsheet Analysis is active
        from backend.tools.excel_analyzer import active_excel_context, execute_excel_analysis
        excel_ctx = active_excel_context.get()
        is_spreadsheet_mode = bool(
            router_badge == "📊 Spreadsheet Analysis" or
            (excel_ctx and excel_ctx.get("has_spreadsheet"))
        )

        if is_spreadsheet_mode:
            try:
                analysis_res = execute_excel_analysis(
                    operation="query",
                    query=question,
                    doc_id=excel_ctx.get("doc_id") if excel_ctx else None
                )
                if analysis_res.get("status") == "success" and analysis_res.get("answer"):
                    answer_text = analysis_res["answer"]
                    words = answer_text.split(" ")
                    for idx, w in enumerate(words):
                        tok = w if idx == len(words) - 1 else w + " "
                        yield f"event: token\ndata: {json.dumps({'content': tok}, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0.01)

                    sheet_cite = [{
                        "source_index": 1,
                        "filename": analysis_res.get("filename", "Spreadsheet.xlsx"),
                        "doc_id": excel_ctx.get("doc_id", "") if excel_ctx else "excel_file",
                        "page": 1,
                        "text": f"Calculation verified across all data rows in {analysis_res.get('filename')}.",
                        "bboxes": []
                    }]
                    yield f"event: citations\ndata: {json.dumps({'citations': sheet_cite})}\n\n"
                    yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"
                    return
            except Exception as err:
                logger.warning(f"[SPREADSHEET_QA] Direct analysis execution error: {err}")

        # Case B: Document route but nothing retrieved or passed threshold
        # (e.g. low relevance, off-topic question asked while document is loaded)
        if not retrieved_chunks:
            spreadsheet_chunk = None
            if excel_ctx:
                try:
                    meta = execute_excel_analysis("metadata")
                    if meta.get("status") == "success":
                        sheet_text = (
                            f"Worksheet: {meta.get('active_sheet', 'Sheet1')}\n"
                            f"Total Rows: {meta.get('data_rows', 0)} (data rows)\n"
                            f"Total Columns: {meta.get('total_columns', 0)}\n"
                            f"Columns: {', '.join(meta.get('columns', []))}\n"
                            f"Dimensions: {meta.get('dimensions', 'Unknown')}\n"
                            f"Filename: {meta.get('filename')}\n"
                        )
                        spreadsheet_chunk = {
                            "chunk_id": f"excel_meta_{meta.get('filename')}",
                            "doc_id": excel_ctx.get("doc_id", ""),
                            "filename": meta.get("filename"),
                            "text": sheet_text,
                            "page": 1,
                            "bboxes": []
                        }
                except Exception as ex:
                    logger.debug(f"Excel metadata synthesis error: {ex}")

            if spreadsheet_chunk:
                retrieved_chunks = [spreadsheet_chunk]
            else:
                notice = NOT_FOUND_RESPONSE + "\n"
                for word in notice.split(" "):
                    yield f"event: token\ndata: {json.dumps({'content': word + ' '})}\n\n"

                yield f"event: citations\ndata: {json.dumps({'citations': []})}\n\n"
                yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"
                return

        # Case C: Document route with retrieved context chunks
        # Orchestrate generation via LangChain (ChatPromptTemplate + SystemMessage/HumanMessage + ChatOllama)
        token_stream, citations = await langchain_adapter.stream_grounded_chat(
            question=question,
            chunks=retrieved_chunks,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            prompt_type=prompt_type,
            web_mode=web_mode,
            history=history,
        )

        accumulated_tokens = []
        async for token in token_stream:
            accumulated_tokens.append(token)
            yield f"event: token\ndata: {json.dumps({'content': token})}\n\n"

        full_text = "".join(accumulated_tokens).strip()
        full_text_lower = full_text.lower()

        # Check if the document did not contain the answer
        not_found_markers = [
            "this is not mentioned in the provided document context",
            "not mentioned in the provided document context",
            "not mentioned in the document",
            "not contain this information",
            "not found in the document",
            "not mentioned in the provided",
            "does not contain sufficient information",
            "not available in the document",
            "insufficient information",
            "couldn't find enough relevant information",
            "not mentioned in the context",
            "not mentioned in",
            "not found in",
            "not present in",
        ]
        is_not_found = any(m in full_text_lower for m in not_found_markers)

        if is_not_found:
            # The model identified that this info is missing in the document.
            # Cleanly return empty citations to prevent drawing any highlights on the PDF.
            citations = []
        else:
            # Fact found! Score all bounding boxes across all citations against the generated answer!
            logger.info("[CITATION] Evidence refinement started")
            citations = self.refine_citations_for_answer(
                citations=citations,
                answer_text=full_text,
                question_text=question
            )
            logger.info(f"[CITATION] Evidence refinement completed: {len(citations)} citations")

        # Append web citations if web tool executed
        web_cites = active_web_citations.get([])
        if web_cites:
            citations = citations + web_cites

        # Check if excel generator tool was executed during LangChain grounded tool calls
        excel_art = active_excel_artifact.get()
        if excel_art:
            yield f"event: excel_artifact\ndata: {json.dumps(excel_art, ensure_ascii=False)}\n\n"

        # Check if document generator tool was executed
        doc_art = active_document_artifact.get()
        if doc_art:
            yield f"event: document_artifact\ndata: {json.dumps(doc_art, ensure_ascii=False)}\n\n"

        # Check if pdf tools was executed
        pdf_art = active_pdf_artifact.get()
        if pdf_art:
            yield f"event: pdf_artifact\ndata: {json.dumps(pdf_art, ensure_ascii=False)}\n\n"

        # Send citations event (only containing the exact answer highlight boxes and web citations)
        yield f"event: citations\ndata: {json.dumps({'citations': citations})}\n\n"
        yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"

    async def validate_grounding(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        answer_text: str
    ) -> GroundingValidationResult:
        """
        Validates factual claims in answer_text against retrieved chunks using
        GROUNDING_VALIDATION_SYSTEM_TEMPLATE. Returns a structured GroundingValidationResult.
        """
        documents = langchain_adapter.chunks_to_documents(chunks)
        formatted_context, _ = langchain_adapter.format_context_from_documents(documents)
        return await langchain_adapter.validate_draft_answer(
            question=question,
            context=formatted_context,
            draft_answer=answer_text
        )

    async def generate_grounded_answer(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        validate: bool = False,
        max_retries: int = 1
    ) -> Tuple[str, List[Dict[str, Any]], Optional[GroundingValidationResult]]:
        """
        Non-streaming answer generation with optional grounding verification and bounded revision.
        """
        if not chunks:
            return NOT_FOUND_RESPONSE, [], None

        is_verbatim = is_verbatim_extraction_request(question)
        documents = langchain_adapter.chunks_to_documents(chunks)

        if is_verbatim:
            messages, citations = langchain_adapter.build_verbatim_messages(question, documents)
        else:
            messages, citations = langchain_adapter.build_grounded_messages(question, documents)

        draft_answer = await langchain_adapter.ainvoke_messages(
            messages,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS
        )

        validation_result: Optional[GroundingValidationResult] = None
        current_answer = draft_answer

        # Optional answer verification step
        if validate and not is_verbatim:
            formatted_context, _ = langchain_adapter.format_context_from_documents(documents)
            retries = 0
            while retries < max_retries:
                validation_result = await langchain_adapter.validate_draft_answer(
                    question=question,
                    context=formatted_context,
                    draft_answer=current_answer
                )
                if validation_result.recommendation == "revise":
                    logger.info(f"[VALIDATION] Draft needs revision. Retrying (attempt {retries+1}/{max_retries})...")
                    revision_messages = langchain_adapter.build_revision_messages(
                        question=question,
                        context=formatted_context,
                        draft_answer=current_answer,
                        unsupported_claims=validation_result.unsupported_claims,
                        contradicted_claims=validation_result.contradicted_claims,
                        missing_information=validation_result.missing_information
                    )
                    current_answer = await langchain_adapter.ainvoke_messages(
                        revision_messages,
                        temperature=settings.LLM_TEMPERATURE,
                        max_tokens=settings.LLM_MAX_TOKENS
                    )
                    retries += 1
                else:
                    break

        # Check for not found markers in final text
        ans_lower = current_answer.lower()
        not_found_markers = [
            "this is not mentioned in the provided document context",
            "not mentioned in the provided",
            "not mentioned in the document",
            "not contain this information",
            "not found in the document",
            "insufficient information",
        ]
        if any(m in ans_lower for m in not_found_markers):
            return current_answer, [], validation_result

        refined_citations = self.refine_citations_for_answer(
            citations=citations,
            answer_text=current_answer,
            question_text=question
        )
        return current_answer, refined_citations, validation_result


    def refine_citations_for_answer(
        self,
        citations: List[Dict[str, Any]],
        answer_text: str,
        question_text: str
    ) -> List[Dict[str, Any]]:
        """
        Refines citations and pinpoints line-level bounding boxes for EVERY relevant page in the answer.
        Supports multi-page answers without truncating to a single page.
        Resolves true pages when chunks span multiple pages (e.g. Page 24 vs 25).
        Filters out non-relevant retrieved chunks so citation cards only present genuine grounded evidence.
        """
        if not citations or not answer_text:
            return []

        import re
        ans_lower = answer_text.lower()
        not_found_markers = [
            "not mentioned in the document",
            "not contain this information",
            "not found in the document",
            "not mentioned in the provided",
            "does not contain sufficient information",
            "not available in the document",
            "insufficient information",
            "couldn't find enough relevant information",
            "not mentioned in the context",
            "not mentioned in",
            "not found in",
            "not present in",
            "there is no",
        ]
        if any(m in ans_lower for m in not_found_markers):
            return []

        cited_indices = [int(m) for m in re.findall(r"\[(\d+)\]", answer_text)]

        stop_words = {
            'the', 'is', 'in', 'of', 'and', 'a', 'an', 'to', 'for', 'with', 'on', 'at',
            'by', 'from', 'this', 'that', 'are', 'was', 'were', 'document', 'resume',
            'candidate', 'answer', 'according', 'mentioned', 'based', 'context', 'listed', 'include', 'as', 'it'
        }

        def clean_tokens(text: str) -> List[str]:
            return [w for w in re.findall(r'[a-zA-Z0-9%]+', text.lower()) if len(w) >= 3 and w not in stop_words]

        def get_ngrams(tokens: List[str], n: int) -> set:
            return set(" ".join(tokens[i:i+n]) for i in range(len(tokens) - n + 1))

        ans_tokens = clean_tokens(answer_text)
        ans_unique_kws = set(ans_tokens)
        ans_bigrams = get_ngrams(ans_tokens, 2)
        ans_trigrams = get_ngrams(ans_tokens, 3)

        if not ans_unique_kws and not cited_indices:
            return []

        # 1. Identify which citations actually contributed to the answer
        scored_citations = []
        for c_idx, cite in enumerate(citations):
            src_idx = cite.get("source_index", c_idx + 1)
            is_explicitly_cited = (src_idx in cited_indices)

            # Check full text first, then snippet and bboxes for thorough grounding verification
            cite_text = cite.get("full_text") or cite.get("text") or cite.get("snippet") or ""
            for b in cite.get("bboxes", []):
                cite_text += " " + (b.get("text") or "")

            c_tokens = clean_tokens(cite_text)
            c_unique = set(c_tokens)
            matched_kws = ans_unique_kws.intersection(c_unique)
            c_bigrams = get_ngrams(c_tokens, 2)
            matched_bigrams = ans_bigrams.intersection(c_bigrams)
            matched_trigrams = ans_trigrams.intersection(get_ngrams(c_tokens, 3))

            relevance_score = len(matched_kws) * 4.0 + len(matched_bigrams) * 8.0 + len(matched_trigrams) * 16.0
            # Only boost explicitly cited sources if they actually share content words with the answer
            if is_explicitly_cited and len(matched_kws) > 0:
                relevance_score += 100.0

            if (is_explicitly_cited and len(matched_kws) > 0) or relevance_score >= 8.0 or len(matched_kws) >= 2:
                scored_citations.append({
                    "cite": cite,
                    "score": relevance_score,
                    "src_idx": src_idx
                })

        if not scored_citations:
            if citations:
                scored_citations = [{"cite": citations[0], "score": 10.0, "src_idx": 1}]
            else:
                return []


        scored_citations.sort(key=lambda x: -x["score"])

        refined = []
        seen_keys = set()

        for item in scored_citations:
            cite = dict(item["cite"])
            doc_id = cite.get("doc_id", "")
            is_explicit = (item["src_idx"] in cited_indices)

            # Check candidate pages associated with this citation
            cand_pages = cite.get("candidate_pages") or []
            if not cand_pages:
                bbox_pages = [int(b["page"]) for b in cite.get("bboxes", []) if b.get("page")]
                cand_pages = list(dict.fromkeys([int(cite.get("page") or 1)] + bbox_pages))

            # Search each candidate page for pinpoint line boxes
            found_on_pages = []
            for p in cand_pages:
                line_boxes = self._locate_pinpoint_answer_boxes(
                    doc_id=doc_id,
                    page_num=p,
                    answer_text=answer_text
                )
                if line_boxes:
                    k = (doc_id, p)
                    if k not in seen_keys:
                        seen_keys.add(k)
                        new_cite = dict(cite)
                        new_cite["page"] = p
                        new_cite["page_number"] = p
                        new_cite["bboxes"] = line_boxes
                        refined.append(new_cite)
                        logger.info(f"[CITATION] Pinpoint exact {len(line_boxes)} line boxes resolved on page {p}")

        if refined:
            # Filter out stray low-density pages when a dominant page has high density
            if len(refined) > 1:
                max_matched = max(max(b.get("matched_chars", 0) for b in c.get("bboxes", [])) for c in refined)
                max_lines = max(max(b.get("line_count", 1) for b in c.get("bboxes", [])) for c in refined)
                if max_matched >= 50:
                    filtered_cites = []
                    for c in refined:
                        c_chars = max(b.get("matched_chars", 0) for b in c.get("bboxes", []))
                        c_lines = max(b.get("line_count", 1) for b in c.get("bboxes", []))
                        # Discard single-line stray hits when a dominant page has a complete block (>= 4 lines)
                        if max_lines >= 4 and c_lines <= 1:
                            continue
                        # Discard weak pages with < 30% density of the dominant page
                        if c_chars < max(40, int(max_matched * 0.30)):
                            continue
                        filtered_cites.append(c)

                    if filtered_cites:
                        refined = filtered_cites

            # Sort logically by source_index to preserve primary relevance order
            refined.sort(key=lambda c: c.get("source_index", 1))
            if cited_indices:
                sorted_cites = sorted(cited_indices)
                for i, c in enumerate(refined):
                    if i < len(sorted_cites):
                        c["source_index"] = sorted_cites[i]
            else:
                for i, c in enumerate(refined):
                    c["source_index"] = i + 1
        else:
            # Fallback when PyMuPDF exact text search could not locate lines on candidate pages
            target_items = [it for it in scored_citations if it["src_idx"] in cited_indices] if cited_indices else scored_citations
            for item in target_items:
                cite = dict(item["cite"])
                raw_b = cite.get("bboxes", [])
                if raw_b and any("text" in b for b in raw_b):
                    matched_b = [
                        b for b in raw_b
                        if any(w in (b.get("text") or "").lower() for w in ans_tokens if len(w) >= 3)
                    ]
                    if matched_b:
                        cite["bboxes"] = matched_b
                        if matched_b[0].get("page"):
                            cite["page"] = int(matched_b[0]["page"])
                            cite["page_number"] = int(matched_b[0]["page"])
                    else:
                        cite["bboxes"] = raw_b
                elif raw_b:
                    cite["bboxes"] = raw_b
                refined.append(cite)
            if not refined and scored_citations:
                first_cite = dict(scored_citations[0]["cite"])
                refined = [first_cite]


        # Sort refined citations logically by source_index
        refined.sort(key=lambda c: c.get("source_index", 1))
        return refined

    def _locate_pinpoint_answer_boxes(
        self,
        doc_id: str,
        page_num: int,
        answer_text: str
    ) -> List[Dict[str, Any]]:
        """
        Locates precise, line-level bounding boxes for text from the answer that appears on page_num.
        Merges adjacent words on the same line and returns individual line boxes (never a single giant union block).
        Guarantees that unrelated bullet points, headers, and adjacent paragraphs remain unhighlighted.
        """
        import os
        import glob
        import re
        try:
            import pymupdf
        except ImportError:
            try:
                import fitz as pymupdf
            except ImportError:
                return []

        if not doc_id or not answer_text or page_num < 1:
            return []

        upload_dir = getattr(settings, "UPLOAD_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "uploads"))
        pattern = os.path.join(upload_dir, f"{doc_id}*")
        matches = glob.glob(pattern)
        if not matches:
            return []

        pdf_path = next((m for m in matches if m.lower().endswith(".pdf")), matches[0])
        if not os.path.exists(pdf_path) or not pdf_path.lower().endswith(".pdf"):
            return []

        try:
            doc = pymupdf.open(pdf_path)
            if page_num > len(doc):
                return []
            page = doc[page_num - 1]
            page_w = round(float(page.rect.width), 2)
            page_h = round(float(page.rect.height), 2)

            def normalize_str(s: str) -> str:
                s = s.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
                s = s.replace('–', '-').replace('—', '-').replace('\u2022', '').replace('\uf0b7', '')
                return s

            clean = re.sub(r'\[\d+\]', '', answer_text)
            clean = re.sub(r'[*#_`]', '', clean).strip()

            raw_units = [u.strip() for u in re.split(r'[\n\r]+|[.!?]\s+', clean) if len(u.strip()) >= 8]
            matched_rects = []
            total_matched_chars = 0

            for unit in raw_units:
                norm_unit = normalize_str(unit)
                # 1. Exact phrase/sentence search
                r = page.search_for(unit) or page.search_for(norm_unit)
                if r:
                    matched_rects.extend(r)
                    total_matched_chars += len(norm_unit)
                    continue

                # 2. Overlapping 4-word & 3-word phrase search
                # Ensure candidate phrases have at least 2 content words to prevent matching random generic phrases
                stop_words = {
                    'the', 'is', 'in', 'of', 'and', 'a', 'an', 'to', 'for', 'with', 'on', 'at',
                    'by', 'from', 'this', 'that', 'are', 'was', 'were', 'document', 'resume',
                    'candidate', 'answer', 'according', 'mentioned', 'based', 'context', 'listed', 'include', 'as', 'it'
                }
                words = re.findall(r'\b[A-Za-z0-9\-\']+\b', norm_unit)
                if len(words) < 3:
                    if len(words) == 2:
                        p = " ".join(words)
                        if len(p) >= 10:
                            hits = page.search_for(p)
                            if hits:
                                matched_rects.extend(hits)
                                total_matched_chars += len(p)
                    continue

                unit_rects = []
                for i in range(len(words) - 3):
                    p = " ".join(words[i:i+4])
                    c_cnt = sum(1 for w in words[i:i+4] if len(w) >= 3 and w.lower() not in stop_words)
                    if len(p) >= 12 and c_cnt >= 2:
                        hits = page.search_for(p)
                        if hits:
                            unit_rects.extend(hits)
                            total_matched_chars += len(p)

                if not unit_rects:
                    for i in range(len(words) - 2):
                        p = " ".join(words[i:i+3])
                        c_cnt = sum(1 for w in words[i:i+3] if len(w) >= 3 and w.lower() not in stop_words)
                        if len(p) >= 10 and c_cnt >= 2:
                            hits = page.search_for(p)
                            if hits:
                                unit_rects.extend(hits)
                                total_matched_chars += len(p)

                if unit_rects:
                    matched_rects.extend(unit_rects)

            if not matched_rects:
                return []

            # 3. Line clustering: Group rects that belong to the same text line
            sorted_rects = sorted(matched_rects, key=lambda r: (round(r.y0 / 5.0), r.x0))
            lines = []
            for r in sorted_rects:
                placed = False
                r_mid = (r.y0 + r.y1) / 2.0
                for line in lines:
                    line_mid = sum((lr.y0 + lr.y1) / 2.0 for lr in line) / len(line)
                    if abs(r_mid - line_mid) <= 5.0:
                        line.append(r)
                        placed = True
                        break
                if not placed:
                    lines.append([r])

            line_boxes = []
            for line in lines:
                min_x0 = min(r.x0 for r in line)
                min_y0 = min(r.y0 for r in line)
                max_x1 = max(r.x1 for r in line)
                max_y1 = max(r.y1 for r in line)

                box_height = max_y1 - min_y0
                if box_height > 35:
                    continue

                line_boxes.append({
                    "x0": round(float(min_x0), 2),
                    "y0": round(float(min_y0), 2),
                    "x1": round(float(max_x1), 2),
                    "y1": round(float(max_y1), 2),
                    "width": round(float(max_x1 - min_x0), 2),
                    "page": page_num,
                    "page_width": page_w,
                    "page_height": page_h,
                    "coord_origin": "TOPLEFT",
                })

            # Filter out stray isolated single-character or noise hits while preserving bullet lists
            if len(line_boxes) >= 4:
                dense_lines = []
                for i, b in enumerate(line_boxes):
                    has_neighbor = False
                    for j, ob in enumerate(line_boxes):
                        if i != j and abs(b["y0"] - ob["y0"]) <= 85.0:
                            has_neighbor = True
                            break
                    if has_neighbor:
                        dense_lines.append(b)
                if dense_lines:
                    line_boxes = dense_lines

            line_boxes.sort(key=lambda b: b["y0"])

            # Group lines into contiguous answer blocks (vertical gap <= 25pt)
            blocks = []
            current_block = []
            for b in line_boxes:
                if not current_block:
                    current_block.append(b)
                else:
                    prev_b = current_block[-1]
                    gap = b["y0"] - prev_b["y1"]
                    if gap <= 25.0:
                        current_block.append(b)
                    else:
                        blocks.append(current_block)
                        current_block = [b]
            if current_block:
                blocks.append(current_block)

            # Merge blocks separated by a displayed equation or single formula line (gap <= 48pt)
            # when both blocks have substantial content
            merged_blocks = []
            for blk in blocks:
                if not merged_blocks:
                    merged_blocks.append(blk)
                else:
                    prev_blk = merged_blocks[-1]
                    gap = blk[0]["y0"] - prev_blk[-1]["y1"]
                    prev_w = sum(b.get("width", b["x1"] - b["x0"]) for b in prev_blk)
                    curr_w = sum(b.get("width", b["x1"] - b["x0"]) for b in blk)
                    if gap <= 48.0 and prev_w >= 150.0 and curr_w >= 150.0:
                        prev_blk.extend(blk)
                    else:
                        merged_blocks.append(blk)
            blocks = merged_blocks

            # Block Dominance & Distinctive Content-Word Filtering:
            # Prevents stray false-positive blocks from adjacent sections that only matched generic vocabulary
            if len(blocks) > 1:
                common_doc_words = {
                    'the', 'is', 'in', 'of', 'and', 'a', 'an', 'to', 'for', 'with', 'on', 'at',
                    'by', 'from', 'this', 'that', 'are', 'was', 'were', 'document', 'resume',
                    'candidate', 'answer', 'according', 'mentioned', 'based', 'context', 'listed',
                    'include', 'as', 'it', 'each', 'all', 'some', 'any', 'many', 'more', 'most',
                    'other', 'such', 'than', 'then', 'their', 'there', 'them', 'they', 'our',
                    'your', 'we', 'you', 'which', 'what', 'where', 'when', 'who', 'how', 'can',
                    'could', 'will', 'would', 'should', 'may', 'might', 'must', 'have', 'has',
                    'had', 'do', 'does', 'did', 'be', 'been', 'being', 'also', 'into', 'only',
                    'same', 'different', 'used', 'using', 'between', 'through', 'over', 'both',
                    'layer', 'layers', 'model', 'models', 'input', 'inputs', 'output', 'outputs',
                    'sequence', 'sequences', 'position', 'positions', 'section', 'table', 'figure',
                    'page', 'type', 'types', 'process', 'order'
                }
                def get_content_words(t):
                    return set(w for w in re.findall(r'[a-zA-Z0-9]{3,}', t.lower()) if w not in common_doc_words)

                ans_cw = get_content_words(answer_text)
                for blk in blocks:
                    min_y = min(b["y0"] for b in blk)
                    max_y = max(b["y1"] for b in blk)
                    min_x = min(b["x0"] for b in blk)
                    max_x = max(b["x1"] for b in blk)
                    blk_text = page.get_text("text", clip=pymupdf.Rect(min_x, min_y, max_x, max_y))
                    blk_cw = get_content_words(blk_text)
                    blk[0]["distinctive_hits"] = len(ans_cw.intersection(blk_cw))

                max_hits = max(blk[0].get("distinctive_hits", 0) for blk in blocks)
                if max_hits >= 4:
                    blocks = [blk for blk in blocks if blk[0].get("distinctive_hits", 0) >= max(3, int(max_hits * 0.35))]

            if len(blocks) > 1:
                block_weights = [sum(b.get("width", b["x1"] - b["x0"]) for b in blk) for blk in blocks]
                max_w = max(block_weights) if block_weights else 0
                blocks = [blk for blk in blocks if sum(b.get("width", b["x1"] - b["x0"]) for b in blk) >= min(80.0, max_w * 0.20)]

            unified_boxes = []
            padding_x = 4.0
            padding_y = 4.0
            for block in blocks:
                min_x0 = max(0.0, min(b["x0"] for b in block) - padding_x)
                min_y0 = max(0.0, min(b["y0"] for b in block) - padding_y)
                max_x1 = min(page_w, max(b["x1"] for b in block) + padding_x)
                max_y1 = min(page_h, max(b["y1"] for b in block) + padding_y)

                unified_boxes.append({
                    "x0": round(float(min_x0), 2),
                    "y0": round(float(min_y0), 2),
                    "x1": round(float(max_x1), 2),
                    "y1": round(float(max_y1), 2),
                    "page": page_num,
                    "page_width": page_w,
                    "page_height": page_h,
                    "coord_origin": "TOPLEFT",
                    "line_count": len(block),
                    "matched_chars": total_matched_chars,
                })

            return unified_boxes
        except Exception as e:
            logger.debug(f"[CITATION] PyMuPDF line locator error: {e}")
            return []

grounded_generator = GroundedGenerator()
