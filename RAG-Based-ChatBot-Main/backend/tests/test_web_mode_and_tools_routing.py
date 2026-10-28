"""
Test Suite: Web Mode and Multi-Tool Routing Integrity
Verifies:
1. When Web Mode is ON and a PDF document (e.g. Attention.pdf) is loaded, web questions (e.g. 'who is ms dhoni') route to ("web", "🌐 Live Web Search") rather than Spreadsheet Analysis.
2. When Web Mode is OFF and a PDF is loaded, document questions (e.g. 'what is Fine-tuning') route to ("document", "From document") and NEVER to Spreadsheet Analysis.
3. When an Excel document (.xlsx) is loaded, questions with spreadsheet metrics (e.g. rows, sales) route to ("document", "📊 Spreadsheet Analysis").
4. Weather questions route to ("general", "⛅ Live Weather").
5. Math calculation questions route to ("general", "🧮 Calculator").
6. End-to-end stream_rag_response with web_mode=True emits web meta badge and web citations without echoing internal guidelines.
"""

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to sys.path
root_dir = str(Path(__file__).resolve().parent.parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from langchain_core.messages.ai import AIMessageChunk
from backend.llm.router import QueryRouter
from backend.tools.excel_analyzer import active_excel_context
from backend.llm.generator import GroundedGenerator
from backend.llm.langchain_adapter import LangChainAdapter


@pytest.mark.asyncio
async def test_web_mode_with_pdf_routes_to_live_web_search():
    """
    User scenario: Attention.pdf is open, Web Mode toggle is ON.
    Query: 'who is ms dhoni'.
    Must route to 'web' with '🌐 Live Web Search' badge, NOT '📊 Spreadsheet Analysis'.
    """
    router = QueryRouter()
    # Emulate active PDF context (no spreadsheet)
    active_excel_context.set(None)

    route, badge = await router.route_query(
        question="who is ms dhoni",
        has_documents=True,
        active_doc_ids=["attention_pdf_doc_id"],
        web_mode=True
    )

    assert route == "web", f"Expected route 'web', got '{route}'"
    assert "Live Web Search" in badge, f"Expected Live Web Search badge, got '{badge}'"
    assert "Spreadsheet" not in badge, f"Spreadsheet badge must not be present for web query!"


@pytest.mark.asyncio
async def test_pdf_document_qa_never_routes_to_spreadsheet_analysis():
    """
    User scenario: Attention.pdf is open, Web Mode is OFF.
    Query: 'what is Fine-tuning'.
    Must route to 'document' with 'From document' badge, NEVER '📊 Spreadsheet Analysis'.
    """
    router = QueryRouter()
    active_excel_context.set(None)

    route, badge = await router.route_query(
        question="what is Fine-tuning",
        has_documents=True,
        active_doc_ids=["attention_pdf_doc_id"],
        web_mode=False
    )

    assert route == "document", f"Expected route 'document', got '{route}'"
    assert badge == "From document", f"Expected 'From document', got '{badge}'"
    assert "Spreadsheet" not in badge, f"Spreadsheet badge must not be present for PDF QA!"


@pytest.mark.asyncio
async def test_excel_document_with_spreadsheet_query_routes_to_spreadsheet_analysis():
    """
    User scenario: AMD Excel.xlsx is open.
    Query: 'how many rows in the sheet and what is total sales'.
    Must route to 'document' with '📊 Spreadsheet Analysis'.
    """
    router = QueryRouter()
    active_excel_context.set({
        "doc_ids": ["amd_excel_doc_id"],
        "doc_id": "amd_excel_doc_id",
        "filename": "AMD Excel.xlsx",
        "has_spreadsheet": True
    })

    route, badge = await router.route_query(
        question="how many rows in the sheet and what is total sales",
        has_documents=True,
        active_doc_ids=["amd_excel_doc_id"],
        web_mode=False
    )

    assert route == "document", f"Expected route 'document', got '{route}'"
    assert "Spreadsheet Analysis" in badge, f"Expected Spreadsheet Analysis badge, got '{badge}'"


@pytest.mark.asyncio
async def test_weather_query_routes_to_weather_badge():
    """
    Weather query with documents open must route to Live Weather.
    """
    router = QueryRouter()
    active_excel_context.set(None)

    route, badge = await router.route_query(
        question="Goa Weather Today",
        has_documents=True,
        active_doc_ids=["attention_pdf_doc_id"],
        web_mode=True
    )

    assert route == "general"
    assert "Live Weather" in badge


@pytest.mark.asyncio
async def test_calculator_query_routes_to_calculator_badge():
    """
    Math calculation with documents open must route to Calculator.
    """
    router = QueryRouter()
    active_excel_context.set(None)

    route, badge = await router.route_query(
        question="What is 43235 * 254?",
        has_documents=True,
        active_doc_ids=["attention_pdf_doc_id"],
        web_mode=True
    )

    assert route == "general"
    assert "Calculator" in badge


@pytest.mark.asyncio
async def test_web_mode_stream_rag_response_end_to_end():
    """
    Verifies that generator.stream_rag_response for a web query:
    1. Emits meta event with '🌐 Live Web Search' and route 'web'.
    2. Gathers web citations.
    3. Streams response tokens without echoing internal instruction headers.
    4. Does not output 'not mentioned in the provided document context'.
    """
    generator = GroundedGenerator()
    active_excel_context.set(None)

    mock_search_results = {
        "query": "who is ms dhoni",
        "results": [
            {
                "title": "MS Dhoni - Wikipedia",
                "url": "https://en.wikipedia.org/wiki/MS_Dhoni",
                "snippet": "MS Dhoni is an Indian former professional cricketer and captain of the national team.",
                "engine": "wikipedia",
                "full_page_read": False,
            }
        ],
        "count": 1,
        "formatted": "=== Grounded Web Research Evidence for: 'who is ms dhoni' ===\n[1] Source Title: MS Dhoni - Wikipedia\n    Source URL: https://en.wikipedia.org/wiki/MS_Dhoni\n    Snippet: MS Dhoni is an Indian former professional cricketer and captain of the national team."
    }

    async def mock_stream_tokens(*args, **kwargs):
        tokens = ["Mahendra ", "Singh ", "Dhoni ", "is ", "a ", "legendary ", "Indian ", "cricketer [1]."]
        for t in tokens:
            yield t

    with patch("backend.tools.searxng_search.search_searxng_async", new_callable=AsyncMock) as mock_search, \
         patch("backend.llm.langchain_adapter.langchain_adapter.stream_general_chat", side_effect=mock_stream_tokens):

        mock_search.return_value = mock_search_results

        events = []
        async for chunk in generator.stream_rag_response(
            question="who is ms dhoni",
            route="web",
            router_badge="🌐 Live Web Search",
            retrieved_chunks=[],
            queries=["who is ms dhoni"],
            web_mode=True
        ):
            events.append(chunk)

        combined = "".join(events)

        # 1. Meta event validation
        assert "event: meta" in combined
        assert "Live Web Search" in combined
        assert '"route": "web"' in combined

        # 2. Content validation
        assert "Mahendra" in combined
        assert "cricketer" in combined

        # 3. No document refusal leakage
        assert "not mentioned in the provided document context" not in combined.lower()

        # 4. Citations event validation
        assert "event: citations" in combined
        assert "https://en.wikipedia.org/wiki/MS_Dhoni" in combined
        assert "MS Dhoni - Wikipedia" in combined

        # 5. Done event
        assert "event: done" in combined


@pytest.mark.asyncio
async def test_cross_turn_excel_artifact_isolation():
    """
    Verifies that if a previous turn created an Excel artifact,
    a subsequent Document QA query in the same task/thread context cleanly resets
    active_excel_artifact and NEVER emits an 'excel_artifact' event or Excel badge.
    """
    from backend.tools.excel_generator import active_excel_artifact
    # Simulate stale artifact left over from previous Excel workbook generation turn
    active_excel_artifact.set({
        "status": "success",
        "filename": "cricket_players_909a155a.xlsx",
        "file_path": "data/generated_excel/cricket_players_909a155a.xlsx",
        "rows": 5,
        "columns": 5
    })

    generator = GroundedGenerator()
    chunks = [
        {
            "chunk_id": "c1",
            "doc_id": "doc1",
            "filename": "Production_Guide.pdf",
            "page": 1,
            "text": "Qdrant Vector DataBase is used for advanced RAG vector storage.",
            "bboxes": [{"page": 1, "x0": 10, "y0": 20, "x1": 100, "y1": 40, "text": "Qdrant Vector DataBase"}]
        }
    ]

    async def mock_stream_tokens(*args, **kwargs):
        yield "Qdrant Vector DataBase is used for vector storage."

    with patch("backend.llm.langchain_adapter.langchain_adapter.stream_grounded_chat") as mock_grounded:
        mock_grounded.return_value = (mock_stream_tokens(), [{"source_index": 1, "filename": "Production_Guide.pdf", "page": 1, "bboxes": []}])

        events = []
        async for chunk in generator.stream_rag_response(
            question="What is Qdrant Vector DataBase and why was it chosen over alternatives like chroma or Milvus",
            route="document",
            router_badge="From document",
            retrieved_chunks=chunks,
            queries=["What is Qdrant Vector DataBase"],
            web_mode=False
        ):
            events.append(chunk)

        combined = "".join(events)

        # 1. Excel artifact must NOT be emitted
        assert "event: excel_artifact" not in combined
        assert "cricket_players" not in combined

        # 2. Excel Generator badge must NOT be present
        assert "Excel Generator" not in combined
        assert "From document" in combined

        # 3. ContextVar must be reset to None
        assert active_excel_artifact.get() is None
