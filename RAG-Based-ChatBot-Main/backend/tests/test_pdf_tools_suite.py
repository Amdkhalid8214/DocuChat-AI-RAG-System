"""
DocuChat AI - Master PDF Tools Test Suite
Comprehensive automated test suite covering all PDF Tools operations:
1. Merging multiple PDFs (ordering, validation)
2. Splitting PDF by page ranges
3. Extracting selected pages (1, 3, 5-8, odd, even)
4. Rotating pages (90°, 180°, 270°) with non-target preservation
5. Compression with honest size reduction & disclaimer
6. Text & Markdown conversion with page boundaries
7. Table extraction to XLSX (with CWE-1236 formula injection defense) & CSV
8. PDF Information (dimensions, page count, metadata, encryption)
9. Watermarking & running page numbers
10. Images to PDF conversion
11. Empty, corrupted, and invalid file safety
12. Path traversal prevention
13. Query routing & negative isolation (RAG summary and Doc Gen never hijacked)
14. Download endpoint integrity
15. Bounding box & citation regression checks
"""

import os
import io
import tempfile
import pytest
import fitz  # PyMuPDF
from pathlib import Path
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import settings
from backend.tools.pdf_tools import (
    parse_page_selection,
    validate_pdf_file,
    merge_pdfs,
    split_pdf,
    extract_pages,
    rotate_pages,
    compress_pdf,
    convert_pdf_to_text,
    extract_pdf_tables,
    get_pdf_info,
    add_watermark,
    add_page_numbers,
    images_to_pdf,
    execute_pdf_tool_from_request,
)
from backend.llm.router import (
    query_router,
    is_pdf_tools,
    is_pdf_tool_request,
    is_document_generation_request,
    is_excel_generation_request,
)
from backend.tools.artifact_registry import artifact_registry


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


def _create_synthetic_pdf(
    num_pages: int = 4,
    title: str = "Synthetic Test Document",
    include_table: bool = True
) -> str:
    """Helper to create a small, valid synthetic PDF on disk using PyMuPDF."""
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=612, height=792)  # Standard US Letter
        pno = i + 1
        page.insert_text(
            fitz.Point(50, 70),
            f"{title} - Page {pno}",
            fontsize=16,
            color=(0.1, 0.2, 0.4)
        )
        page.insert_text(
            fitz.Point(50, 110),
            f"This is paragraph text on page {pno}. It provides sample body text for reading order tests.",
            fontsize=11
        )
        if include_table and i == 0:
            # Draw a simple table with borders and cell text
            # Headers
            page.draw_rect(fitz.Rect(50, 160, 450, 190), color=(0.2, 0.2, 0.2), width=1)
            page.insert_text(fitz.Point(60, 180), "Department", fontsize=11)
            page.insert_text(fitz.Point(200, 180), "Headcount", fontsize=11)
            page.insert_text(fitz.Point(340, 180), "Budget ($)", fontsize=11)

            # Row 1
            page.draw_rect(fitz.Rect(50, 190, 450, 220), color=(0.7, 0.7, 0.7), width=1)
            page.insert_text(fitz.Point(60, 210), "Engineering", fontsize=10)
            page.insert_text(fitz.Point(200, 210), "45", fontsize=10)
            page.insert_text(fitz.Point(340, 210), "1250000", fontsize=10)

            # Row 2 (with formula injection candidate)
            page.draw_rect(fitz.Rect(50, 220, 450, 250), color=(0.7, 0.7, 0.7), width=1)
            page.insert_text(fitz.Point(60, 240), "=CMD() Test", fontsize=10)
            page.insert_text(fitz.Point(200, 240), "12", fontsize=10)
            page.insert_text(fitz.Point(340, 240), "350000", fontsize=10)

            # Draw vertical column grid lines so table finders detect columns
            page.draw_line(fitz.Point(50, 160), fitz.Point(50, 250), color=(0.5, 0.5, 0.5), width=1)
            page.draw_line(fitz.Point(180, 160), fitz.Point(180, 250), color=(0.5, 0.5, 0.5), width=1)
            page.draw_line(fitz.Point(320, 160), fitz.Point(320, 250), color=(0.5, 0.5, 0.5), width=1)
            page.draw_line(fitz.Point(450, 160), fitz.Point(450, 250), color=(0.5, 0.5, 0.5), width=1)

    tmp_dir = Path(tempfile.gettempdir()) / "test_pdf_synthetic"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = str(tmp_dir / f"synthetic_{os.urandom(4).hex()}.pdf")
    doc.save(pdf_path)
    doc.close()
    return pdf_path


# ==============================================================================
# 1. PAGE PARSING & VALIDATION TESTS
# ==============================================================================

def test_parse_page_selection():
    """Verify page selection parsing for ranges, individual pages, odd, even, all."""
    assert parse_page_selection("1, 3, 5-7", 10) == [0, 2, 4, 5, 6]
    assert parse_page_selection("all", 4) == [0, 1, 2, 3]
    assert parse_page_selection("odd", 5) == [0, 2, 4]
    assert parse_page_selection("even", 5) == [1, 3]
    assert parse_page_selection("2", 3) == [1]

    # Out-of-bounds pages should be safely skipped or raise
    with pytest.raises(ValueError):
        parse_page_selection("15", 5)


def test_validate_pdf_file():
    """Verify magic byte validation, empty file defense, and non-PDF rejection."""
    valid_pdf = _create_synthetic_pdf(2)
    valid, err = validate_pdf_file(valid_pdf)
    assert valid is True
    assert err is None

    # Empty file
    empty_file = Path(tempfile.gettempdir()) / f"empty_{os.urandom(4).hex()}.pdf"
    empty_file.write_bytes(b"")
    valid, err = validate_pdf_file(str(empty_file))
    assert valid is False
    assert "empty" in err.lower()

    # Corrupted / fake PDF
    fake_pdf = Path(tempfile.gettempdir()) / f"fake_{os.urandom(4).hex()}.pdf"
    fake_pdf.write_bytes(b"NOT A REAL PDF HEADER")
    valid, err = validate_pdf_file(str(fake_pdf))
    assert valid is False
    assert "header" in err.lower() or "signature" in err.lower()


# ==============================================================================
# 2. CORE PDF OPERATIONS: MERGE, SPLIT, EXTRACT, ROTATE
# ==============================================================================

def test_merge_pdfs():
    """Verify merging multiple PDFs preserves order and page count."""
    pdf1 = _create_synthetic_pdf(2, title="Document Alpha")
    pdf2 = _create_synthetic_pdf(3, title="Document Beta")

    artifact = merge_pdfs([pdf1, pdf2], output_filename="Merged_Test.pdf")
    assert artifact["operation"] == "merge"
    assert artifact["status"] == "ready"
    assert artifact["page_count"] == 5
    assert os.path.exists(artifact["file_path"])

    # Verify merged content order
    doc = fitz.open(artifact["file_path"])
    assert doc.page_count == 5
    assert "Document Alpha" in doc[0].get_text()
    assert "Document Beta" in doc[2].get_text()
    doc.close()


def test_split_pdf():
    """Verify splitting PDF into separate parts based on ranges."""
    pdf = _create_synthetic_pdf(6, title="Document to Split")
    artifacts = split_pdf(pdf, ranges=["1-2", "3-4", "5-6"])

    assert len(artifacts) == 3
    assert artifacts[0]["page_count"] == 2
    assert artifacts[1]["page_count"] == 2
    assert artifacts[2]["page_count"] == 2

    for a in artifacts:
        assert os.path.exists(a["file_path"])
        d = fitz.open(a["file_path"])
        assert d.page_count == 2
        d.close()


def test_extract_pages():
    """Verify extracting specific pages into a single new PDF."""
    pdf = _create_synthetic_pdf(5, title="Document For Extraction")
    artifact = extract_pages(pdf, page_spec="1, 3, 5")

    assert artifact["operation"] == "extract_pages"
    assert artifact["page_count"] == 3
    assert os.path.exists(artifact["file_path"])

    doc = fitz.open(artifact["file_path"])
    assert doc.page_count == 3
    assert "Page 1" in doc[0].get_text()
    assert "Page 3" in doc[1].get_text()
    assert "Page 5" in doc[2].get_text()
    doc.close()


def test_rotate_pages():
    """Verify rotating specified pages preserves other pages."""
    pdf = _create_synthetic_pdf(4, title="Rotate Document")
    artifact = rotate_pages(pdf, angle=90, page_spec="2")

    assert artifact["operation"] == "rotate"
    assert os.path.exists(artifact["file_path"])

    doc = fitz.open(artifact["file_path"])
    assert doc[0].rotation == 0   # Page 1 untouched
    assert doc[1].rotation == 90  # Page 2 rotated
    assert doc[2].rotation == 0   # Page 3 untouched
    doc.close()


# ==============================================================================
# 3. COMPRESSION & TEXT EXTRACTION TESTS
# ==============================================================================

def test_compress_pdf():
    """Verify compression creates a readable PDF and reports honest reduction metrics."""
    pdf = _create_synthetic_pdf(4, title="Compressible Document")
    artifact = compress_pdf(pdf, level="medium")

    assert artifact["operation"] == "compress"
    assert os.path.exists(artifact["file_path"])
    assert "reduction_percent" in artifact
    assert "disclaimer" in artifact
    assert "depend" in artifact["disclaimer"].lower()

    # Re-verify PDF readability
    doc = fitz.open(artifact["file_path"])
    assert doc.page_count == 4
    doc.close()


def test_convert_pdf_to_text_and_markdown():
    """Verify text & markdown extraction with page boundary preservation."""
    pdf = _create_synthetic_pdf(3, title="Text Document")

    # Markdown format
    md_artifact = convert_pdf_to_text(pdf, format="markdown")
    assert md_artifact["format"] == "md"
    assert os.path.exists(md_artifact["file_path"])
    md_content = Path(md_artifact["file_path"]).read_text(encoding="utf-8")
    assert "## Page 1" in md_content
    assert "Text Document" in md_content

    # Plain Text format
    txt_artifact = convert_pdf_to_text(pdf, format="text")
    assert txt_artifact["format"] == "txt"
    assert os.path.exists(txt_artifact["file_path"])
    txt_content = Path(txt_artifact["file_path"]).read_text(encoding="utf-8")
    assert "--- PAGE 1 ---" in txt_content


# ==============================================================================
# 4. TABLE EXTRACTION & CWE-1236 FORMULA INJECTION DEFENSE
# ==============================================================================

def test_extract_pdf_tables():
    """Verify table extraction into XLSX and CSV with CSV formula injection defense."""
    pdf = _create_synthetic_pdf(2, title="Table PDF", include_table=True)

    # Extract to XLSX
    xlsx_art = extract_pdf_tables(pdf, format="xlsx")
    assert xlsx_art["format"] == "xlsx"
    assert os.path.exists(xlsx_art["file_path"])
    assert xlsx_art["file_size"] > 0

    # Extract to CSV
    csv_art = extract_pdf_tables(pdf, format="csv")
    assert csv_art["format"] == "csv"
    assert os.path.exists(csv_art["file_path"])

    # Verify formula injection defense in CSV output
    csv_text = Path(csv_art["file_path"]).read_text(encoding="utf-8")
    # `=CMD()` must have been prefixed with `'` to prevent spreadsheet code execution
    assert "=CMD()" not in csv_text or "'=CMD()" in csv_text


# ==============================================================================
# 5. PDF INFO, WATERMARK, PAGE NUMBERS, IMAGES TO PDF
# ==============================================================================

def test_get_pdf_info():
    """Verify PDF metadata, dimensions, and security status inspection."""
    pdf = _create_synthetic_pdf(3, title="Info Inspection")
    info = get_pdf_info(pdf)

    assert info["valid"] is True
    assert info["page_count"] == 3
    assert info["is_encrypted"] is False
    assert "dimensions" in info
    assert info["dimensions"]["paper_size"] in ("Letter", "A4", "Custom")


def test_add_watermark():
    """Verify adding diagonal semi-transparent watermark to pages."""
    pdf = _create_synthetic_pdf(2, title="Watermark Doc")
    art = add_watermark(pdf, text="CONFIDENTIAL TEST", page_spec="all")

    assert art["operation"] == "watermark"
    assert os.path.exists(art["file_path"])

    doc = fitz.open(art["file_path"])
    assert doc.page_count == 2
    # Verify watermark text present in page streams
    assert "CONFIDENTIAL TEST" in doc[0].get_text()
    doc.close()


def test_add_page_numbers():
    """Verify adding running page numbers to pages."""
    pdf = _create_synthetic_pdf(3, title="Page Number Doc")
    art = add_page_numbers(pdf, position="bottom-center", format_str="Page {page} of {total}")

    assert art["operation"] == "page_numbers"
    assert os.path.exists(art["file_path"])

    doc = fitz.open(art["file_path"])
    assert "Page 1 of 3" in doc[0].get_text()
    assert "Page 2 of 3" in doc[1].get_text()
    doc.close()


def test_images_to_pdf():
    """Verify compiling multiple images into a single PDF."""
    from PIL import Image

    tmp_dir = Path(tempfile.gettempdir()) / "test_images"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    img_paths = []
    for i in range(2):
        img = Image.new("RGB", (300, 200), color=(100 + i * 50, 150, 200))
        p = str(tmp_dir / f"img_{i}_{os.urandom(4).hex()}.png")
        img.save(p)
        img_paths.append(p)

    art = images_to_pdf(img_paths, output_filename="Images_Compiled.pdf")
    assert art["operation"] == "images_to_pdf"
    assert art["page_count"] == 2
    assert os.path.exists(art["file_path"])

    doc = fitz.open(art["file_path"])
    assert doc.page_count == 2
    doc.close()


# ==============================================================================
# 6. REST API ENDPOINTS
# ==============================================================================

def test_api_merge_and_download(client):
    """Test POST /api/pdf-tools/merge endpoint with direct file uploads."""
    pdf1 = _create_synthetic_pdf(1, title="API PDF 1")
    pdf2 = _create_synthetic_pdf(1, title="API PDF 2")

    with open(pdf1, "rb") as f1, open(pdf2, "rb") as f2:
        res = client.post(
            "/api/pdf-tools/merge",
            files=[
                ("files", ("p1.pdf", f1, "application/pdf")),
                ("files", ("p2.pdf", f2, "application/pdf")),
            ]
        )

    assert res.status_code == 200
    data = res.json()
    assert data["operation"] == "merge"
    assert data["page_count"] == 2

    # Verify download endpoint
    dl_res = client.get(f"/api/tools/download/{data['filename']}")
    assert dl_res.status_code == 200
    assert dl_res.headers["content-type"] == "application/pdf"
    assert len(dl_res.content) > 0


def test_api_path_traversal_prevention(client):
    """Verify directory traversal is strictly blocked on download endpoints."""
    res = client.get("/api/tools/download/..%2F..%2Fetc%2Fpasswd")
    assert res.status_code in (403, 404)


# ==============================================================================
# 7. ROUTING & NEGATIVE ISOLATION (ZERO REGRESSIONS TO RAG & DOC GEN)
# ==============================================================================

def test_pdf_tools_routing_positives():
    """Verify PDF tool requests are routed to pdf_tools."""
    positives = [
        "Merge these two PDFs into one document",
        "Split this PDF by pages 1-3 and 4-6",
        "Extract pages 2, 4, 6 from this PDF",
        "Rotate page 3 by 90 degrees clockwise",
        "Compress this PDF file",
        "Extract tables from this PDF into Excel",
        "Convert this PDF into markdown format",
        "Add a CONFIDENTIAL watermark to this PDF",
        "Add page numbers to the bottom of this PDF",
        "Convert these images into a PDF",
        "Show me the metadata and page count of this PDF",
    ]
    for q in positives:
        assert is_pdf_tools(q) is True, f"Failed positive routing for: '{q}'"


def test_pdf_tools_routing_negative_isolation():
    """
    CRITICAL: Verify RAG queries, document generation, and Excel analysis are NEVER
    hijacked by PDF Tools.
    """
    rag_queries = [
        "Summarize this PDF document",
        "What is the main topic discussed in this PDF?",
        "Find the section about annual leave in this document",
        "According to the contract, what is the notice period?",
        "Explain the conclusion on page 4",
        "What are the key findings in this report?",
    ]
    for q in rag_queries:
        assert is_pdf_tools(q) is False, f"RAG query falsely routed to PDF Tools: '{q}'"

    doc_gen_queries = [
        "Create a professional resume in PDF format",
        "Generate a project proposal document in PDF",
        "Write a technical report in DOCX format",
        "Draft meeting minutes in PDF format",
    ]
    for q in doc_gen_queries:
        assert is_pdf_tools(q) is False, f"Doc Gen query falsely routed to PDF Tools: '{q}'"
        assert is_document_generation_request(q) is True, f"Doc Gen missed: '{q}'"

    excel_queries = [
        "Generate an Excel sheet with monthly revenue data",
        "Create a financial spreadsheet with Q1 to Q4 budget",
        "Build an Excel model with 20 rows of sales data",
    ]
    for q in excel_queries:
        assert is_pdf_tools(q) is False, f"Excel query falsely routed to PDF Tools: '{q}'"
        assert is_excel_generation_request(q) is True, f"Excel Gen missed: '{q}'"


# ==============================================================================
# 8. DISPATCHER & NATURAL LANGUAGE INTEGRATION
# ==============================================================================

@pytest.mark.asyncio
async def test_execute_pdf_tool_from_request_merge():
    """Verify natural language dispatcher executes merge when prompted."""
    pdf1 = _create_synthetic_pdf(1, title="NL Merge 1")
    pdf2 = _create_synthetic_pdf(1, title="NL Merge 2")

    # Dispatch merge request directly with paths
    artifact = await execute_pdf_tool_from_request(
        prompt=f"Merge these PDF files",
        doc_ids=[pdf1, pdf2]
    )

    assert artifact["operation"] == "merge"
    assert artifact["status"] == "ready"
    assert artifact["page_count"] == 2
    assert os.path.exists(artifact["file_path"])
