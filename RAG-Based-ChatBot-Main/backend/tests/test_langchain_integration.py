import sys
import json
import asyncio
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch, MagicMock

# Add project root to sys.path
root_dir = str(Path(__file__).resolve().parent.parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from langchain_core.documents import Document
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.messages.ai import AIMessageChunk

from backend.llm.langchain_adapter import LangChainAdapter, langchain_adapter
from backend.llm.generator import GroundedGenerator, grounded_generator


def test_chunk_to_langchain_document_mapping():
    """Verify that custom RAG chunk dictionaries are cleanly mapped to LangChain Document objects with all metadata preserved."""
    adapter = LangChainAdapter()
    test_chunks = [
        {
            "chunk_id": "chunk_001",
            "doc_id": "doc_abc",
            "doc_name": "Annual_Report.pdf",
            "text": "Total revenue for fiscal year 2024 increased by 14% to $120 million.",
            "page": 5,
            "bboxes": [{"x0": 50, "y0": 100, "x1": 250, "y1": 120, "text": "increased by 14% to $120 million"}],
            "heading_path": ["Financial Highlights", "Revenue Summary"],
            "score": 0.89,
            "reranker_score": 0.92,
        },
        {
            "chunk_id": "chunk_002",
            "doc_id": "doc_abc",
            "doc_name": "Annual_Report.pdf",
            "text": "Operating margin improved to 22% compared to 19% in the prior year.",
            "page": 6,
            "bboxes": [{"x0": 60, "y0": 200, "x1": 280, "y1": 220, "text": "Operating margin improved to 22%"}],
            "heading_path": ["Financial Highlights", "Operating Margins"],
            "score": 0.78,
            "reranker_score": 0.81,
        }
    ]

    docs = adapter.chunks_to_documents(test_chunks)
    assert len(docs) == 2
    assert isinstance(docs[0], Document)
    assert isinstance(docs[1], Document)

    # Check content
    assert "Total revenue for fiscal year 2024" in docs[0].page_content

    # Check preserved metadata
    meta = docs[0].metadata
    assert meta["document_id"] == "doc_abc"
    assert meta["document_name"] == "Annual_Report.pdf"
    assert meta["chunk_id"] == "chunk_001"
    assert meta["page_number"] == 5
    assert meta["section"] == "Financial Highlights > Revenue Summary"
    assert meta["heading_path"] == ["Financial Highlights", "Revenue Summary"]
    assert meta["source"] == "[1]"
    assert meta["source_index"] == 1
    assert meta["retrieval_score"] == 0.89
    assert meta["reranker_score"] == 0.92
    assert len(meta["bbox"]) == 1
    assert meta["bbox"][0]["text"] == "increased by 14% to $120 million"
    print("test_chunk_to_langchain_document_mapping passed!")


def test_grounded_prompt_template_and_messages():
    """Verify that ChatPromptTemplate constructs SystemMessage and HumanMessage with strict grounding instructions."""
    adapter = LangChainAdapter()
    sample_doc = Document(
        page_content="Antigravity system throughput is 10,000 queries per second.",
        metadata={
            "document_id": "doc_01",
            "chunk_id": "c_01",
            "page_number": 3,
            "section": "Architecture > Performance",
            "source_index": 1,
            "bbox": [{"x0": 10, "y0": 20, "x1": 100, "y1": 40, "text": "throughput is 10,000"}],
            "heading_path": ["Architecture", "Performance"]
        }
    )

    messages, citations = adapter.build_grounded_messages(
        question="What is the system throughput?",
        documents=[sample_doc]
    )

    assert len(messages) == 2
    system_msg, human_msg = messages[0], messages[1]

    # Verify message types
    assert isinstance(system_msg, SystemMessage)
    assert isinstance(human_msg, HumanMessage)

    # Verify system message grounding instructions
    sys_text = system_msg.content
    assert "DocuChat AI" in sys_text
    assert "document-grounded" in sys_text
    assert "PRIMARY RULE" in sys_text
    assert "This is not mentioned in the provided document context." in sys_text

    # Verify human message structure
    human_text = human_msg.content
    assert "Context Sources:" in human_text
    assert "CONTEXT SOURCE [1]" in human_text
    assert "Antigravity system throughput is 10,000 queries per second." in human_text
    assert "User Question:" in human_text
    assert "What is the system throughput?" in human_text

    # Verify citations payload
    assert len(citations) == 1
    assert citations[0]["source_index"] == 1
    assert citations[0]["chunk_id"] == "c_01"
    assert citations[0]["page"] == 3
    assert len(citations[0]["bboxes"]) == 1
    print("test_grounded_prompt_template_and_messages passed!")


def test_general_prompt_messages():
    """Verify general conversation prompt construction."""
    adapter = LangChainAdapter()
    messages = adapter.build_general_messages(
        question="What is the weather like?",
        live_context="Sunny, 25C in Madrid."
    )
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert "Sunny, 25C in Madrid" in messages[1].content
    assert "What is the weather like?" in messages[1].content
    print("test_general_prompt_messages passed!")


def test_citation_refinement_with_langchain_output():
    """Verify that the existing citation refinement correctly maps the generated answer to bounding boxes."""
    citations = [
        {
            "source_index": 1,
            "chunk_id": "c1",
            "doc_id": "doc1",
            "page": 1,
            "bboxes": [
                {"x0": 0, "y0": 0, "x1": 50, "y1": 10, "text": "Python, TypeScript, Docker"},
                {"x0": 0, "y0": 20, "x1": 50, "y1": 30, "text": "Education: BS in Computer Science"}
            ],
            "heading_path": ["Skills"],
            "snippet": "Technical skills include Python, TypeScript, Docker."
        },
        {
            "source_index": 2,
            "chunk_id": "c2",
            "doc_id": "doc1",
            "page": 2,
            "bboxes": [
                {"x0": 0, "y0": 0, "x1": 50, "y1": 10, "text": "Previous experience at TechCorp"}
            ],
            "heading_path": ["Experience"],
            "snippet": "Previous experience at TechCorp."
        }
    ]

    answer = "The technical skills listed are Python, TypeScript, and Docker [1]."
    question = "What are the candidate's skills?"

    generator = GroundedGenerator()
    refined = generator.refine_citations_for_answer(citations, answer, question)

    assert len(refined) >= 1
    # First citation should have the winning bbox
    winning_cite = refined[0]
    assert len(winning_cite["bboxes"]) == 1
    assert "python" in winning_cite["bboxes"][0]["text"].lower()
    print("test_citation_refinement_with_langchain_output passed!")



def test_langchain_streaming_with_mock_llm():
    """Verify async streaming yields tokens correctly using LangChain ChatOllama abstraction."""
    adapter = LangChainAdapter()

    async def mock_astream(messages):
        tokens = ["The ", "total ", "revenue ", "was ", "$120M", "."]
        for t in tokens:
            yield AIMessageChunk(content=t)

    mock_llm = MagicMock()
    mock_llm.astream = mock_astream

    async def run_stream():
        with patch.object(adapter, "get_llm", return_value=mock_llm):
            stream = adapter.stream_messages([HumanMessage(content="Hello")])
            collected = []
            async for token in stream:
                collected.append(token)
            return "".join(collected)

    result = asyncio.run(run_stream())
    assert result == "The total revenue was $120M."
    print("test_langchain_streaming_with_mock_llm passed!")


def test_langchain_error_resilience():
    """Verify that when Ollama is unavailable or model is missing, the adapter yields a diagnostic error without crashing."""
    adapter = LangChainAdapter()

    async def mock_failing_astream(messages):
        raise ConnectionError("Failed to establish a new connection: [WinError 10061] No connection could be made")
        yield  # Make it an async generator

    mock_llm = MagicMock()
    mock_llm.astream = mock_failing_astream

    async def run_error_stream():
        with patch.object(adapter, "get_llm", return_value=mock_llm):
            stream = adapter.stream_messages([HumanMessage(content="Hello")])
            collected = []
            async for token in stream:
                collected.append(token)
            return "".join(collected)

    result = asyncio.run(run_error_stream())
    assert "Ollama connection error" in result or "Generation error" in result
    print("test_langchain_error_resilience passed!")


def test_end_to_end_generator_sse_events():
    """Verify end-to-end SSE generation yields meta, token, citations, and done events."""
    chunks = [
        {
            "chunk_id": "c1",
            "doc_id": "d1",
            "text": "The project uses Python and FastAPI.",
            "page": 1,
            "bboxes": [{"x0": 0, "y0": 0, "x1": 50, "y1": 10, "text": "Python and FastAPI"}],
            "heading_path": ["Tech Stack"],
            "score": 0.95
        }
    ]

    async def mock_astream(messages):
        for token in ["The ", "tech ", "stack ", "is ", "Python ", "and ", "FastAPI", " [1]."]:
            yield AIMessageChunk(content=token)

    mock_llm = MagicMock()
    mock_llm.astream = mock_astream

    async def run_sse():
        with patch.object(langchain_adapter, "get_llm", return_value=mock_llm):
            sse_events = []
            async for sse_chunk in grounded_generator.stream_rag_response(
                question="What is the tech stack?",
                route="document",
                router_badge="From document",
                retrieved_chunks=chunks,
                queries=["tech stack"]
            ):
                sse_events.append(sse_chunk)
            return sse_events

    events = asyncio.run(run_sse())
    full_stream = "".join(events)

    assert "event: meta" in full_stream
    assert "event: token" in full_stream
    assert "event: citations" in full_stream
    assert "event: done" in full_stream

    # Parse citations event to ensure winning box is preserved
    for chunk in events:
        if "event: citations" in chunk:
            lines = chunk.strip().split("\n")
            for line in lines:
                if line.startswith("data:"):
                    data = json.loads(line.replace("data:", "").strip())
                    cites = data.get("citations", [])
                    assert len(cites) == 1
                    assert len(cites[0]["bboxes"]) == 1
                    assert cites[0]["bboxes"][0]["text"] == "Python and FastAPI"
    print("test_end_to_end_generator_sse_events passed!")


if __name__ == "__main__":
    test_chunk_to_langchain_document_mapping()
    test_grounded_prompt_template_and_messages()
    test_general_prompt_messages()
    test_citation_refinement_with_langchain_output()
    test_langchain_streaming_with_mock_llm()
    test_langchain_error_resilience()
    test_end_to_end_generator_sse_events()
    print("\nAll LangChain integration tests passed successfully!")
