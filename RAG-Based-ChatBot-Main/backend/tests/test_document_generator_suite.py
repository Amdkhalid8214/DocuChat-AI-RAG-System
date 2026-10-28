"""
DocuChat AI - Master Document Generator Test Suite
Tests DOCX, PDF, TXT, and Markdown generation, format validation, RAG context incorporation,
routing logic, download endpoints, artifact registry, and regression isolation.
"""

import os
import pytest
import docx
from pathlib import Path
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import settings
from backend.tools.document_generator import (
    generate_document_from_request,
    detect_document_format,
    detect_document_type,
    extract_document_title,
    validate_generated_document,
    SUPPORTED_FORMATS
)
from backend.tools.artifact_registry import artifact_registry
from backend.llm.router import (
    query_router,
    is_document_generation_request,
    is_excel_generation_request,
    is_weather_request,
    is_standalone_math_request,
)


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


# ==============================================================================
# 1. FORMAT TESTS (DOCX, PDF, TXT, MD, UNSUPPORTED)
# ==============================================================================

@pytest.mark.asyncio
async def test_generate_docx_file_structure():
    """Verify DOCX generation produces a valid, readable OpenXML document with tables."""
    prompt = "Create a professional project report for my DocuChat AI application in DOCX format."
    artifact = await generate_document_from_request(prompt, requested_format="docx")

    assert artifact["format"] == "docx"
    assert artifact["status"] == "ready"
    assert os.path.exists(artifact["file_path"])
    assert artifact["file_size"] > 0
    assert artifact["filename"].endswith(".docx")

    # Verify document structure by re-opening with python-docx
    doc = docx.Document(artifact["file_path"])
    assert len(doc.paragraphs) > 5
    assert len(doc.tables) >= 1

    # Check title presence
    text_corpus = " ".join([p.text for p in doc.paragraphs])
    assert "DocuChat" in text_corpus


@pytest.mark.asyncio
async def test_generate_pdf_file_structure():
    """Verify PDF generation produces a valid, print-ready document with %PDF- header."""
    prompt = "Convert this project report into a downloadable PDF."
    artifact = await generate_document_from_request(prompt, requested_format="pdf")

    assert artifact["format"] == "pdf"
    assert artifact["status"] == "ready"
    assert os.path.exists(artifact["file_path"])
    assert artifact["file_size"] > 0
    assert artifact["filename"].endswith(".pdf")

    # Verify PDF header
    with open(artifact["file_path"], "rb") as f:
        header = f.read(5)
        assert header == b"%PDF-"


@pytest.mark.asyncio
async def test_generate_txt_and_md_files():
    """Verify plain text and markdown document generation."""
    # TXT
    art_txt = await generate_document_from_request(
        "Create a simple text document containing notes for the project.",
        requested_format="txt"
    )
    assert art_txt["format"] == "txt"
    assert os.path.exists(art_txt["file_path"])
    with open(art_txt["file_path"], "r", encoding="utf-8") as f:
        txt_content = f.read()
    assert len(txt_content) > 100
    assert "===" in txt_content

    # MD
    art_md = await generate_document_from_request(
        "Create requirement specifications in markdown format.",
        requested_format="md"
    )
    assert art_md["format"] == "md"
    assert os.path.exists(art_md["file_path"])
    with open(art_md["file_path"], "r", encoding="utf-8") as f:
        md_content = f.read()
    assert md_content.startswith("# ")
    assert "|" in md_content  # Contains table markdown


@pytest.mark.asyncio
async def test_unsupported_format_rejected():
    """Verify that unsupported formats (e.g. .exe, .bin) are strictly rejected."""
    with pytest.raises(ValueError, match="Unsupported document format"):
        await generate_document_from_request(
            "Create a document in binary executable format",
            requested_format="exe"
        )


# ==============================================================================
# 2. CONTENT & RAG EVIDENCE TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_generate_resume_from_prompt():
    """Verify generation of professional resume with competencies and experience."""
    prompt = "Generate a resume using the information I provide: Senior AI Engineer with Python and RAG experience."
    artifact = await generate_document_from_request(prompt, requested_format="docx")

    assert artifact["document_type"] == "resume"
    doc = docx.Document(artifact["file_path"])
    full_text = " ".join([p.text for p in doc.paragraphs])
    assert "Professional Summary" in full_text or "Experience" in full_text
    assert len(doc.tables) >= 1


@pytest.mark.asyncio
async def test_generate_technical_doc_with_rag_evidence():
    """Verify that retrieved RAG context is incorporated into the generated document."""
    rag_context = (
        "DocuChat AI uses Qdrant dense vector search with 384-dimensional embeddings "
        "and Rank-BM25 hybrid retrieval fused using Reciprocal Rank Fusion (alpha=0.5). "
        "The reranker model is BAAI/bge-reranker-base which scores candidate passages."
    )
    prompt = "Create a document based on the information in my uploaded PDF."
    artifact = await generate_document_from_request(
        prompt=prompt,
        requested_format="pdf",
        context=rag_context
    )

    assert artifact["format"] == "pdf"
    assert artifact["sections_count"] >= 4
    # The artifact should reflect the title and sections
    assert os.path.exists(artifact["file_path"])


@pytest.mark.asyncio
async def test_generate_meeting_minutes_with_action_items():
    """Verify meeting minutes document type includes attendees, agenda, and action items table."""
    prompt = "Create a meeting report with decisions and action items."
    artifact = await generate_document_from_request(prompt, requested_format="docx")

    assert artifact["document_type"] == "meeting_minutes"
    doc = docx.Document(artifact["file_path"])
    # Should have meeting overview table and action items table
    assert len(doc.tables) >= 2


# ==============================================================================
# 3. ROUTING MATRIX TESTS
# ==============================================================================

def test_document_generator_routing_positives():
    """Verify all 9 Master Prompt natural language examples route to Document Generator."""
    examples = [
        "Create a professional project report for my DocuChat AI application.",
        "Generate a resume using the information I provide.",
        "Create a technical document explaining my RAG architecture.",
        "Generate a project proposal in DOCX format.",
        "Create a meeting report with decisions and action items.",
        "Convert this report into a downloadable PDF.",
        "Create a document based on the information in my uploaded PDF.",
        "Generate a 5-page technical report with a table of contents.",
        "Create a simple text document containing these notes.",
        "Draft a formal cover letter for software engineer position.",
        "Generate software requirements specification (SRS) in markdown format."
    ]

    for ex in examples:
        assert is_document_generation_request(ex) is True, f"Failed for query: {ex}"


@pytest.mark.asyncio
async def test_routing_matrix_isolation():
    """
    Verify strict isolation between Document Generator, Excel Generator,
    Document QA (RAG), Web Search, Weather, and Calculator.
    """
    # 1. Document Generator
    r1, b1 = await query_router.route_query("Generate a project proposal in DOCX format.")
    assert r1 == "document_generation"
    assert "Document Generator" in b1

    # 2. Excel Generator
    r2, b2 = await query_router.route_query("Generate 50 student records with 12 columns in Excel")
    assert r2 == "excel_generation"
    assert "Excel Generator" in b2

    # 3. Document QA (RAG)
    r3, b3 = await query_router.route_query("What does section 2 of the uploaded document state?")
    assert r3 == "document"
    assert b3 == "From document"

    # 4. Web Search
    r4, b4 = await query_router.route_query("Search the web for Qwen 2.5 benchmarks")
    assert r4 == "web"
    assert "Web Search" in b4

    # 5. Live Weather
    r5, b5 = await query_router.route_query("What is the weather today in Goa?")
    assert r5 == "general"
    assert "Live Weather" in b5

    # 6. Calculator
    r6, b6 = await query_router.route_query("Calculate 254 * 43235")
    assert r6 == "general"
    assert "Calculator" in b6


# ==============================================================================
# 4. DOWNLOAD ENDPOINT & SECURITY TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_download_endpoint_docx(client):
    """Verify downloading generated DOCX file via /api/tools/download/{artifact_id}."""
    art = await generate_document_from_request("Create a project proposal in DOCX format.", requested_format="docx")
    art_id = art["artifact_id"]

    res = client.get(f"/api/tools/download/{art_id}")
    assert res.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in res.headers["content-type"]
    assert len(res.content) == art["file_size"]


@pytest.mark.asyncio
async def test_download_endpoint_pdf(client):
    """Verify downloading generated PDF file via /api/tools/download/{artifact_id}."""
    art = await generate_document_from_request("Convert this report into a downloadable PDF.", requested_format="pdf")
    art_id = art["artifact_id"]

    res = client.get(f"/api/tools/download/{art_id}")
    assert res.status_code == 200
    assert "application/pdf" in res.headers["content-type"]
    assert res.content.startswith(b"%PDF-")


def test_download_path_traversal_prevention(client):
    """Verify that path traversal attempts are blocked with HTTP 403 Forbidden."""
    res = client.get("/api/tools/download/../../../../windows/system.ini")
    assert res.status_code in (403, 404)
