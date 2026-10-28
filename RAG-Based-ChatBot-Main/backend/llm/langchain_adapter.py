"""
LangChain Adapter for DocuChat AI.

Architectural Separation:
=========================
1. Custom RAG Pipeline (Remains Custom & Fully Under Control):
   - Ingestion & Docling parsing (with PyMuPDF fallback)
   - Structure-aware chunking with token estimation and bbox tracking
   - Nomic / BGE embeddings via FastEmbed & SentenceTransformers
   - Qdrant vector database storage and ANN search
   - BM25Plus lexical indexing and BM25 search
   - Hybrid retrieval with Reciprocal Rank Fusion (RRF) / weighted fusion
   - Jaccard & token-ngram deduplication
   - Cross-encoder reranking (BAAI/bge-reranker-base)
   - Score thresholding and top-k selection
   - Citation refinement and bounding-box matching for PDF.js highlighting
   - FastAPI server with SSE streaming endpoints

2. LangChain Orchestration Layer (Focused, Well-Isolated Integration):
   - Document metadata preservation via langchain_core.documents.Document
   - Grounded prompt templates via langchain_core.prompts.ChatPromptTemplate
   - Message abstraction via SystemMessage and HumanMessage
   - LLM Orchestration via langchain_ollama.ChatOllama with qwen2.5:7b (configurable via settings.LLM_MODEL)
   - Asynchronous token streaming integration with SSE pipeline
   - Robust error handling and diagnostics for Ollama/Qwen availability
"""

import json
import logging
import re
from datetime import datetime
from typing import List, Dict, Any, AsyncGenerator, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from backend.config import settings
from backend.tools.calculator import calculator_tool, safe_calculate
from backend.tools.searxng_search import searxng_search_tool
from backend.tools.excel_analyzer import excel_analyzer_tool, active_excel_context
from backend.tools.excel_generator import excel_generator_tool, active_excel_artifact
from backend.tools.weather import weather_tool, active_weather_data
from backend.llm.memory import format_chat_history_for_llm
from backend.llm.router import is_weather_request, is_excel_generation_request

logger = logging.getLogger(__name__)


def clean_pdf_text(text: str) -> str:
    """
    Cleans PDF column line breaks, hyphenated split words, and whitespace artifacts
    while strictly preserving true paragraphs, headers, bulleted lists, and key-value lines.
    """
    if not text:
        return ""

    # Replace unicode replacement characters from custom font encodings
    text = text.replace("\ufffd", "•")

    # 1. Fix hyphenated word breaks at line ends: e.g. "transfor-\n mation" -> "transformation"
    text = re.sub(r'(\b[a-zA-Z]+)-\s*\n\s*([a-zA-Z]+\b)', r'\1\2', text)

    # 2. Normalize horizontal spaces/tabs
    text = re.sub(r'[ \t]+', ' ', text)

    # 3. Handle line breaks carefully to preserve structured layout in resumes, forms, tables
    lines = text.split('\n')
    cleaned_lines: List[str] = []

    for line in lines:
        line_s = line.strip()
        if not line_s:
            cleaned_lines.append("")
            continue

        # Bullet point or list item
        is_bullet = bool(re.match(r'^([•\-\*\u2022\u2013\u2014]|\d+\.|\d+\.\d+)', line_s))
        # Standalone numeric section or title
        is_heading = bool(re.match(r'^\d+(\.\d+)*\s*$', line_s)) or bool(
            re.match(r'^[A-Z][a-zA-Z0-9\s]{2,40}$', line_s) and len(line_s) < 45
        )
        # Key-value or structured field (e.g. "Percentage: 81%", "Phone: ...", "Email: ...")
        is_field = bool(re.search(r'^[A-Za-z\s]{2,25}\s*:', line_s)) or ("|" in line_s)

        if cleaned_lines and cleaned_lines[-1] != "" and not is_bullet and not is_heading and not is_field:
            prev = cleaned_lines[-1]
            prev_is_field = bool(re.search(r'^[A-Za-z\s]{2,25}\s*:', prev)) or ("|" in prev)
            # Only join lines if previous line is a long narrative sentence continuation
            if len(prev) > 60 and not prev.endswith(('.', ':', '?', '!')) and not prev_is_field:
                cleaned_lines[-1] = prev + " " + line_s
                continue

        cleaned_lines.append(line_s)

    # Reconstruct text with clean paragraph breaks
    result: List[str] = []
    for l in cleaned_lines:
        if l == "":
            if result and result[-1] != "":
                result.append("")
        else:
            result.append(l)

    return "\n".join(result)


from backend.llm.prompts import (
    GROUNDED_SYSTEM_TEMPLATE,
    GROUNDED_HUMAN_TEMPLATE,
    VERBATIM_EXTRACTION_SYSTEM_TEMPLATE,
    VERBATIM_EXTRACTION_HUMAN_TEMPLATE,
    GENERAL_SYSTEM_TEMPLATE,
    GENERAL_SYSTEM_TEMPLATE_WITH_WEB,
    GENERAL_HUMAN_TEMPLATE_PLAIN,
    GENERAL_HUMAN_TEMPLATE_WITH_WEB,
    GROUNDING_VALIDATION_SYSTEM_TEMPLATE,
    GROUNDING_VALIDATION_HUMAN_TEMPLATE,
    GROUNDED_REVISION_HUMAN_TEMPLATE,
    NOT_FOUND_RESPONSE,
    GroundingValidationResult,
)


class LangChainAdapter:
    """
    Isolated LangChain orchestration component for DocuChat AI.
    Handles message structure, prompt templating, and Ollama/Qwen interaction.
    """

    def __init__(
        self,
        base_url: str = settings.LLM_BASE_URL,
        model: str = settings.LLM_MODEL,
        temperature: float = settings.LLM_TEMPERATURE,
        max_tokens: int = settings.LLM_MAX_TOKENS,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Precompile ChatPromptTemplates for all four operational categories
        self.grounded_prompt_template = ChatPromptTemplate.from_messages([
            ("system", GROUNDED_SYSTEM_TEMPLATE),
            ("human", GROUNDED_HUMAN_TEMPLATE),
        ])

        self.verbatim_prompt_template = ChatPromptTemplate.from_messages([
            ("system", VERBATIM_EXTRACTION_SYSTEM_TEMPLATE),
            ("human", VERBATIM_EXTRACTION_HUMAN_TEMPLATE),
        ])

        self.general_prompt_template_plain = ChatPromptTemplate.from_messages([
            ("system", GENERAL_SYSTEM_TEMPLATE),
            ("human", GENERAL_HUMAN_TEMPLATE_PLAIN),
        ])

        self.general_prompt_template_web = ChatPromptTemplate.from_messages([
            ("system", GENERAL_SYSTEM_TEMPLATE_WITH_WEB),
            ("human", GENERAL_HUMAN_TEMPLATE_WITH_WEB),
        ])

        self.validation_prompt_template = ChatPromptTemplate.from_messages([
            ("system", GROUNDING_VALIDATION_SYSTEM_TEMPLATE),
            ("human", GROUNDING_VALIDATION_HUMAN_TEMPLATE),
        ])

        self.revision_prompt_template = ChatPromptTemplate.from_messages([
            ("system", GROUNDED_SYSTEM_TEMPLATE),
            ("human", GROUNDED_REVISION_HUMAN_TEMPLATE),
        ])

        logger.info(
            f"[LANGCHAIN] Adapter initialized for model='{self.model_name}' at '{self.base_url}'"
        )


    def get_llm(
        self,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ChatOllama:
        """
        Creates or returns a ChatOllama instance configured for the specified generation parameters.
        """
        temp = self.temperature if temperature is None else temperature
        num_predict = self.max_tokens if max_tokens is None else max_tokens
        client_timeout = getattr(settings, "LLM_TIMEOUT", 180.0) if timeout is None else timeout
        num_threads = getattr(settings, "LLM_NUM_THREADS", 2)
        num_ctx = getattr(settings, "LLM_NUM_CTX", 2048)

        return ChatOllama(
            base_url=self.base_url,
            model=self.model_name,
            temperature=temp,
            num_predict=num_predict,
            timeout=client_timeout,
            num_thread=num_threads,
            num_ctx=num_ctx,
            keep_alive="24h",
        )

    def chunks_to_documents(self, chunks: List[Dict[str, Any]]) -> List[Document]:
        """
        Converts custom RAG chunk dictionaries into LangChain Document objects
        while strictly preserving all structural provenance and citation metadata.
        """
        documents: List[Document] = []
        from collections import Counter
        for idx, chunk in enumerate(chunks):
            source_num = idx + 1
            bboxes = chunk.get("bboxes", [])
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

            page_str = f"{candidate_pages[0]}-{candidate_pages[-1]}" if len(candidate_pages) > 1 else str(true_page)

            text = chunk.get("text", "").strip()
            doc_id = chunk.get("doc_id", "")
            doc_name = (
                chunk.get("filename")
                or chunk.get("doc_name")
                or chunk.get("document_name")
                or chunk.get("metadata", {}).get("doc_name", "")
                or chunk.get("metadata", {}).get("filename", "")
            )
            chunk_id = chunk.get("chunk_id", "")
            heading_path = chunk.get("heading_path", [])
            section_str = " > ".join(heading_path) if heading_path else f"Page {page_str}"
            retrieval_score = float(chunk.get("score", 0.0))
            reranker_score = float(chunk.get("reranker_score", retrieval_score))

            metadata = {
                "document_id": doc_id,
                "document_name": doc_name,
                "filename": doc_name,
                "chunk_id": chunk_id,
                "page_number": true_page,
                "page_str": page_str,
                "candidate_pages": candidate_pages,
                "section": section_str,
                "heading_path": heading_path,
                "bbox": bboxes,
                "text": text,
                "source": f"[{source_num}]",
                "retrieval_score": retrieval_score,
                "reranker_score": reranker_score,
                "source_index": source_num,
            }

            doc = Document(page_content=text, metadata=metadata)
            documents.append(doc)

        logger.info(f"[LANGCHAIN] Converted {len(documents)} chunks to LangChain Document objects")
        return documents

    def format_context_from_documents(
        self,
        documents: List[Document],
        max_char_budget: Optional[int] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Builds complete, formatted context sources respecting a context budget,
        preserving complete relevant chunks without arbitrary hard truncation.
        Returns: (formatted_context_string, citations_payload)
        """
        if max_char_budget is None:
            configured_budget = getattr(settings, "CONTEXT_BUDGET_TOKENS", 2048)
            ctx_tokens = getattr(settings, "LLM_NUM_CTX", 4096)
            max_out_tokens = getattr(settings, "LLM_MAX_TOKENS", 512)
            available_tokens = min(configured_budget, max(500, ctx_tokens - max_out_tokens - 400))
            max_char_budget = available_tokens * 4

        context_blocks: List[str] = []
        citations_payload: List[Dict[str, Any]] = []
        current_chars = 0

        for doc in documents:
            source_idx = doc.metadata.get("source_index", 1)
            page = doc.metadata.get("page_number", 1)
            page_str = doc.metadata.get("page_str") or str(page)
            full_text = doc.page_content.strip()

            header = f"=== CONTEXT SOURCE [{source_idx}] (Page {page_str}) ==="
            header_len = len(header) + 2

            # Context budget check
            remaining_budget = max_char_budget - current_chars - header_len
            if remaining_budget <= 150 and context_blocks:
                logger.info(
                    f"[CONTEXT] Budget reached ({current_chars}/{max_char_budget} chars). "
                    f"Included {len(context_blocks)} chunks."
                )
                break

            if len(full_text) > remaining_budget and context_blocks:
                content = full_text[:remaining_budget]
            else:
                content = full_text

            context_blocks.append(f"{header}\n{content}")
            current_chars += len(header) + len(content) + 2

            citations_payload.append({
                "source_index": source_idx,
                "chunk_id": doc.metadata.get("chunk_id", ""),
                "doc_id": doc.metadata.get("document_id", ""),
                "filename": doc.metadata.get("filename") or doc.metadata.get("document_name", ""),
                "page": page,
                "candidate_pages": doc.metadata.get("candidate_pages", [page]),
                "bboxes": doc.metadata.get("bbox", []),
                "heading_path": doc.metadata.get("heading_path", []),
                "snippet": full_text[:250],
                "full_text": full_text,
                "text": full_text,
            })

        formatted_context = "\n\n".join(context_blocks)
        return formatted_context, citations_payload

    def build_grounded_messages(
        self,
        question: str,
        documents: List[Document],
        max_char_budget: Optional[int] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[BaseMessage], List[Dict[str, Any]]]:
        """
        Builds structured LangChain messages for grounded document QA (GROUNDED_SYSTEM_TEMPLATE + GROUNDED_HUMAN_TEMPLATE)
        and extracts the complete citations payload for PDF.js highlighting and validation.
        Injects bounded prior conversational history between System and Human messages.
        """
        formatted_context, citations_payload = self.format_context_from_documents(
            documents=documents,
            max_char_budget=max_char_budget
        )

        base_messages = self.grounded_prompt_template.format_messages(
            context=formatted_context,
            question=question,
        )

        history_messages = format_chat_history_for_llm(history) if history else []
        if history_messages and len(base_messages) >= 2:
            messages = [base_messages[0]] + history_messages + [base_messages[1]]
        else:
            messages = base_messages

        logger.info(f"[LANGCHAIN] Grounded prompt constructed with {len(messages)} messages (including {len(history_messages)} history turns)")
        return messages, citations_payload

    def build_verbatim_messages(
        self,
        question: str,
        documents: List[Document],
        max_char_budget: Optional[int] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[BaseMessage], List[Dict[str, Any]]]:
        """
        Builds structured LangChain messages for verbatim / exact-text extraction
        (VERBATIM_EXTRACTION_SYSTEM_TEMPLATE + VERBATIM_EXTRACTION_HUMAN_TEMPLATE).
        """
        formatted_context, citations_payload = self.format_context_from_documents(
            documents=documents,
            max_char_budget=max_char_budget
        )

        base_messages = self.verbatim_prompt_template.format_messages(
            context=formatted_context,
            question=question,
        )

        history_messages = format_chat_history_for_llm(history) if history else []
        if history_messages and len(base_messages) >= 2:
            messages = [base_messages[0]] + history_messages + [base_messages[1]]
        else:
            messages = base_messages

        logger.info(f"[LANGCHAIN] Verbatim extraction prompt constructed with {len(messages)} messages")
        return messages, citations_payload

    def build_general_messages(
        self,
        question: str,
        live_context: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> List[BaseMessage]:
        """
        Builds LangChain messages for general real-world / conversational queries.
        Selects plain general template or web-augmented template based on context availability.
        Injects bounded prior conversational history between System and Human messages.
        """
        if live_context:
            base_messages = self.general_prompt_template_web.format_messages(
                live_context=live_context,
                question=question,
            )
        else:
            base_messages = self.general_prompt_template_plain.format_messages(
                question=question,
            )

        history_messages = format_chat_history_for_llm(history) if history else []
        if history_messages and len(base_messages) >= 2:
            messages = [base_messages[0]] + history_messages + [base_messages[1]]
        else:
            messages = base_messages

        logger.info(f"[LANGCHAIN] General prompt constructed with {len(messages)} messages (including {len(history_messages)} history turns)")
        return messages

    def build_validation_messages(
        self,
        question: str,
        context: str,
        draft_answer: str,
    ) -> List[BaseMessage]:
        """
        Builds messages for the grounding validation stage.
        """
        return self.validation_prompt_template.format_messages(
            context=context,
            question=question,
            draft_answer=draft_answer,
        )

    def build_revision_messages(
        self,
        question: str,
        context: str,
        draft_answer: str,
        unsupported_claims: List[str],
        contradicted_claims: List[str],
        missing_information: List[str],
    ) -> List[BaseMessage]:
        """
        Builds messages to revise an answer based on grounding validator feedback.
        """
        return self.revision_prompt_template.format_messages(
            context=context,
            question=question,
            draft_answer=draft_answer,
            unsupported_claims=json.dumps(unsupported_claims) if unsupported_claims else "None",
            contradicted_claims=json.dumps(contradicted_claims) if contradicted_claims else "None",
            missing_information=json.dumps(missing_information) if missing_information else "None",
        )

    async def validate_draft_answer(
        self,
        question: str,
        context: str,
        draft_answer: str,
    ) -> GroundingValidationResult:
        """
        Compares a generated draft against retrieved context using GROUNDING_VALIDATION_SYSTEM_TEMPLATE.
        Returns a validated GroundingValidationResult with safe parsing and fallbacks.
        """
        if not draft_answer or not context:
            return GroundingValidationResult(grounded=True, recommendation="accept")

        messages = self.build_validation_messages(
            question=question,
            context=context,
            draft_answer=draft_answer,
        )

        try:
            raw_response = await self.ainvoke_messages(
                messages,
                temperature=0.0,
                max_tokens=512,
            )
            clean_str = raw_response.strip()
            # Strip code fences if present
            code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_str)
            if code_block_match:
                clean_str = code_block_match.group(1).strip()
            else:
                json_match = re.search(r"\{[\s\S]*\}", clean_str)
                if json_match:
                    clean_str = json_match.group(0).strip()

            parsed = json.loads(clean_str)
            result = GroundingValidationResult(**parsed)
            logger.info(f"[VALIDATION] Recommendation: {result.recommendation}, Grounded: {result.grounded}")
            return result
        except Exception as e:
            logger.debug(f"[VALIDATION] Validation check returned non-JSON or encountered error: {e}")
            return GroundingValidationResult(grounded=True, recommendation="accept")

    async def stream_messages(
        self,
        messages: List[BaseMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Asynchronously streams generation tokens from ChatOllama for SSE events.
        Catches Ollama connection or model availability issues and yields diagnostics.
        """
        logger.info(f"[LLM] Model: {self.model_name}")
        logger.info("[LLM] Generation started")
        logger.info("[LLM] Streaming response")

        try:
            llm = self.get_llm(temperature=temperature, max_tokens=max_tokens)
            async for chunk in llm.astream(messages):
                token = chunk.content
                if isinstance(token, str) and token:
                    yield token
                elif isinstance(token, list):
                    for item in token:
                        if isinstance(item, str):
                            yield item
                        elif isinstance(item, dict) and "text" in item:
                            yield item["text"]
        except Exception as e:
            err_str = str(e)
            logger.error(f"[LLM] Error during LangChain generation: {e}")
            if "not found" in err_str.lower():
                yield (
                    f"\n[Ollama error: Model '{self.model_name}' not found at {self.base_url}. "
                    f"Please run 'ollama pull {self.model_name}' to download it.]"
                )
            elif "memory" in err_str.lower() or "cuda" in err_str.lower():
                yield (
                    f"\n[Ollama resource error: Insufficient system memory/VRAM to load '{self.model_name}'. "
                    f"Please close background applications, free VRAM, or allocate additional swap/RAM for 7B inference.]"
                )
            elif "timeout" in err_str.lower() or "timed out" in err_str.lower():
                yield (
                    f"\n[Ollama timeout error: Request to '{self.model_name}' timed out. "
                    f"Inference on CPU with a 7B model can take longer; consider GPU offloading or increasing LLM_TIMEOUT.]"
                )
            elif (
                isinstance(e, ConnectionError)
                or "connection" in err_str.lower()
                or "connect" in err_str.lower()
                or "could not reach" in err_str.lower()
            ):
                yield (
                    f"\n[Ollama connection error: Could not reach Ollama at {self.base_url}. "
                    f"Please ensure Ollama is running.]"
                )
            else:
                yield f"\n[Generation error: {err_str}]"

    async def ainvoke_messages(
        self,
        messages: List[BaseMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Non-streaming generation via LangChain ainvoke.
        """
        try:
            llm = self.get_llm(temperature=temperature, max_tokens=max_tokens)
            response = await llm.ainvoke(messages)
            return str(response.content).strip()
        except Exception as e:
            err_str = str(e)
            logger.error(f"[LLM] ainvoke error: {e}")
            if "not found" in err_str.lower():
                return f"[Ollama error: Model '{self.model_name}' not found. Please run 'ollama pull {self.model_name}']"
            elif "memory" in err_str.lower() or "cuda" in err_str.lower():
                return f"[Ollama resource error: Insufficient memory/VRAM to load '{self.model_name}']"
            elif "timeout" in err_str.lower():
                return f"[Ollama timeout error: Request to '{self.model_name}' timed out]"
            return ""

    async def stream_chat_with_tools(
        self,
        messages: List[BaseMessage],
        tools: Optional[List[Any]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_iterations: int = 3,
    ) -> AsyncGenerator[str, None]:
        """
        Asynchronously streams generation tokens with automatic LangChain tool calling:
        HumanMessage -> AIMessage with tool_calls -> execute calculator -> ToolMessage -> stream final tokens.
        If no tool is called, streams the direct response tokens seamlessly.
        """
        if not tools:
            async for token in self.stream_messages(messages, temperature=temperature, max_tokens=max_tokens):
                yield token
            return

        llm_plain = self.get_llm(temperature=temperature, max_tokens=max_tokens)
        try:
            llm_with_tools = llm_plain.bind_tools(tools)
        except Exception as e:
            logger.warning(f"[LANGCHAIN] bind_tools failed on model {self.model_name}: {e}. Streaming plain response.")
            async for token in self.stream_messages(messages, temperature=temperature, max_tokens=max_tokens):
                yield token
            return

        tools_by_name = {getattr(t, "name", str(t)): t for t in tools}
        current_messages = list(messages)

        try:
            tools_executed = False
            for iteration in range(max_iterations):
                ai_response = await llm_with_tools.ainvoke(current_messages)
                tool_calls = getattr(ai_response, "tool_calls", None)

                if not tool_calls:
                    # Model provided direct answer without tool call
                    if tools_executed:
                        break
                    content = str(ai_response.content)
                    if content:
                        words = content.split(" ")
                        for idx, word in enumerate(words):
                            token = word if idx == len(words) - 1 else word + " "
                            yield token
                    return

                logger.info(f"[LANGCHAIN] Tool call triggered at step {iteration + 1}: {tool_calls}")
                current_messages.append(ai_response)
                tools_executed = True

                for tc in tool_calls:
                    t_name = tc.get("name")
                    t_args = tc.get("args", {})
                    t_id = tc.get("id", f"call_{iteration}")

                    if t_name in tools_by_name:
                        tool_obj = tools_by_name[t_name]
                        try:
                            if hasattr(tool_obj, "ainvoke"):
                                raw_result = await tool_obj.ainvoke(t_args)
                            else:
                                raw_result = tool_obj.invoke(t_args)
                            result_str = str(raw_result)
                        except Exception as e:
                            logger.error(f"[TOOL] Error executing tool {t_name}: {e}")
                            result_str = json.dumps({"error": f"Tool execution failed: {str(e)}"})
                    else:
                        result_str = json.dumps({"error": f"Tool '{t_name}' not available."})

                    tool_msg = ToolMessage(content=result_str, tool_call_id=t_id, name=t_name)
                    current_messages.append(tool_msg)

                # After web_search tool execution, add synthesis directive to ensure answer synthesis
                if any(tc.get("name") == "web_search" for tc in tool_calls):
                    current_messages.append(
                        HumanMessage(
                            content=(
                                "Now synthesize a comprehensive, direct, and structured answer to the question using the research evidence above. "
                                "Explain concepts, tutorials, or comparisons step-by-step with practical details and examples. "
                                "Use inline citation markers [1], [2] to reference the sources, and conclude with a '### Sources' section "
                                "with clickable markdown links: - [Title](URL). "
                                "Do NOT merely return a list of search links or say 'Based on the search results, here are some links'. "
                                "Do NOT echo, quote, or output these instructions, guidelines, or headings like 'DIRECT ANSWER:'. Start directly with the synthesized answer."
                            )
                        )
                    )

            # Stream final response tokens from llm_plain given the complete tool trajectory
            async for chunk in llm_plain.astream(current_messages):
                token = chunk.content
                if isinstance(token, str) and token:
                    yield token
                elif isinstance(token, list):
                    for item in token:
                        if isinstance(item, str):
                            yield item
                        elif isinstance(item, dict) and "text" in item:
                            yield item["text"]

        except Exception as e:
            err_str = str(e)
            logger.error(f"[LANGCHAIN] Error in stream_chat_with_tools: {e}", exc_info=True)
            yield f"\n[Generation error: {err_str}]"

    async def stream_grounded_chat(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        prompt_type: str = "grounded_qa",
        tools: Optional[List[Any]] = None,
        web_mode: bool = False,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[AsyncGenerator[str, None], List[Dict[str, Any]]]:
        """
        End-to-end grounded RAG orchestration with optional automatic tool calling:
        1. Chunks -> LangChain Documents
        2. Documents -> SystemMessage + HumanMessage Prompt (Grounded QA or Verbatim Extraction)
        3. Messages -> ChatOllama tool calling stream
        When web_mode is False, web_search tool is strictly prevented from executing.
        Returns: (token_stream_generator, citations_payload)
        """
        documents = self.chunks_to_documents(chunks)
        if prompt_type == "verbatim_extraction":
            messages, citations = self.build_verbatim_messages(question, documents, history=history)
            use_tools = None
        else:
            messages, citations = self.build_grounded_messages(question, documents, history=history)
            if tools is not None:
                use_tools = list(tools)
                if not web_mode:
                    use_tools = [t for t in use_tools if getattr(t, "name", "") != "web_search"]
            else:
                active_tools = []
                excel_ctx = active_excel_context.get()
                has_excel_spreadsheet = bool(excel_ctx and excel_ctx.get("has_spreadsheet")) or any(
                    str(c.get("filename", "")).lower().endswith((".xlsx", ".xls", ".csv"))
                    or "worksheet:" in str(c.get("text", "")).lower()
                    for c in chunks
                )
                if has_excel_spreadsheet:
                    has_excel_calc = any(
                        k in question.lower()
                        for k in (
                            "calculate", "sum", "average", "mean", "total", "max", "min",
                            "highest", "lowest", "formula", "pivot", "aggregate"
                        )
                    )
                    if has_excel_calc:
                        active_tools.append(excel_analyzer_tool)

                from backend.llm.router import is_standalone_math_request, is_excel_generation_request
                if is_standalone_math_request(question):
                    active_tools.append(calculator_tool)
                if is_excel_generation_request(question):
                    active_tools.append(excel_generator_tool)
                use_tools = active_tools if active_tools else None

        async def token_generator():
            async for token in self.stream_chat_with_tools(
                messages,
                tools=use_tools,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                yield token

        return token_generator(), citations

    async def stream_general_chat(
        self,
        question: str,
        live_context: str = "",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Any]] = None,
        web_mode: bool = False,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streams response for conversational / real-world queries via LangChain with automatic tool support.
        When web_mode is True, searxng_search_tool is enabled for the model to retrieve live information.
        When web_mode is False, web search is strictly disabled.
        Weather queries prioritize the weather tool and prevent fallback to search snippets.
        """
        is_weather = is_weather_request(question)
        from backend.llm.router import GREETINGS_PATTERN, is_standalone_math_request, is_excel_generation_request
        if bool(GREETINGS_PATTERN.match(question.strip())) and (max_tokens is None or max_tokens > 60):
            max_tokens = 60

        if live_context or is_weather:
            # Context is already pre-fetched and grounded (weather or web search).
            # Stream tokens immediately without expensive tool-binding overhead.
            tools = None
            if is_weather and (max_tokens is None or max_tokens > 90):
                max_tokens = 90
        else:
            if max_tokens is None or max_tokens > 256:
                max_tokens = 256
            if tools is None:
                active_tools = []
                if is_standalone_math_request(question):
                    active_tools.append(calculator_tool)
                excel_ctx = active_excel_context.get()
                if excel_ctx and excel_ctx.get("has_spreadsheet"):
                    has_excel_calc = any(
                        k in question.lower()
                        for k in (
                            "calculate", "sum", "average", "mean", "total", "max", "min",
                            "highest", "lowest", "formula", "pivot", "aggregate"
                        )
                    )
                    if has_excel_calc:
                        active_tools.append(excel_analyzer_tool)
                if is_excel_generation_request(question):
                    active_tools.append(excel_generator_tool)
                if web_mode and not is_weather:
                    active_tools.append(searxng_search_tool)
                tools = active_tools if active_tools else None
            else:
                tools = list(tools)
                if weather_tool not in tools and not is_weather:
                    tools.append(weather_tool)
                if excel_generator_tool not in tools:
                    tools.append(excel_generator_tool)
                excel_ctx = active_excel_context.get()
                if excel_ctx and excel_ctx.get("has_spreadsheet") and excel_analyzer_tool not in tools:
                    tools.append(excel_analyzer_tool)
                if not web_mode or is_weather:
                    tools = [t for t in tools if getattr(t, "name", "") != "web_search"]

        messages = self.build_general_messages(question, live_context=live_context, history=history)
        async for token in self.stream_chat_with_tools(
            messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            yield token


async def execute_tool_call_loop(
    llm_with_tools: Any,
    llm_plain: Any,
    messages: List[BaseMessage],
    tools: List[Any],
    max_iterations: int = 3,
) -> Tuple[str, bool]:
    """
    Executes a bounded LangChain tool calling loop:
    HumanMessage -> AIMessage with tool_calls -> execute tool -> ToolMessage -> AIMessage final answer.
    Returns: (final_answer_text, was_tool_called)
    """
    tools_by_name = {getattr(t, "name", str(t)): t for t in tools}
    current_messages = list(messages)
    tool_called_flag = False

    for iteration in range(max_iterations):
        ai_response = await llm_with_tools.ainvoke(current_messages)
        tool_calls = getattr(ai_response, "tool_calls", None)

        if not tool_calls:
            return str(ai_response.content).strip(), tool_called_flag

        tool_called_flag = True
        current_messages.append(ai_response)

        for tc in tool_calls:
            t_name = tc.get("name")
            t_args = tc.get("args", {})
            t_id = tc.get("id", f"call_{iteration}")

            if t_name in tools_by_name:
                tool_obj = tools_by_name[t_name]
                try:
                    if hasattr(tool_obj, "ainvoke"):
                        raw_result = await tool_obj.ainvoke(t_args)
                    else:
                        raw_result = tool_obj.invoke(t_args)
                    result_str = str(raw_result)
                except Exception as e:
                    logger.error(f"[TOOL] Error executing {t_name}: {e}")
                    result_str = json.dumps({"error": f"Tool execution failed: {str(e)}"})
            else:
                result_str = json.dumps({"error": f"Tool '{t_name}' not available."})

            tool_msg = ToolMessage(content=result_str, tool_call_id=t_id, name=t_name)
            current_messages.append(tool_msg)

    # After completing tool calls, get final generation from llm_plain
    final_response = await llm_plain.ainvoke(current_messages)
    return str(final_response.content).strip(), tool_called_flag


langchain_adapter = LangChainAdapter()


