"""
DocuChat AI - Production PDF Tools Engine
Provides enterprise-grade, high-performance, validated PDF operations:
1. Merge multiple PDFs (with user-controlled order)
2. Split PDF by page ranges or into individual pages
3. Extract specific pages (e.g. 1, 3, 5-8) into a new PDF
4. Rotate specific or all pages (90°, 180°, 270°)
5. Compress PDF with intelligent stream deflating and object deduplication
6. Convert PDF to structured Text (.txt) or Markdown (.md)
7. Extract PDF tables into Excel (.xlsx) or CSV (.csv)
8. PDF Information & Metadata Inspection
9. Add Text Watermark (configurable text, opacity, angle)
10. Add Page Numbers ("Page X of Y") in header/footer
11. Convert Images to PDF (PNG, JPG, WEBP)
"""

import os
import re
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Union
from contextvars import ContextVar
from pydantic import BaseModel, Field

import pymupdf
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from backend.config import settings
from backend.tools.artifact_registry import artifact_registry

logger = logging.getLogger("pdf_tools")

# ContextVar for streaming/WebSocket integration
active_pdf_artifact: ContextVar[Optional[Dict[str, Any]]] = ContextVar("active_pdf_artifact", default=None)

# Maximum file processing limits
MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # 50MB
MAX_MERGE_FILES = 20
MAX_PAGES_TO_PROCESS = 1000


class PdfToolsInput(BaseModel):
    operation: str = Field(..., description="PDF operation: merge, split, extract, rotate, compress, to_text, extract_tables, info, watermark, page_numbers, images_to_pdf")
    document_ids: Optional[List[str]] = Field(None, description="Document IDs or filenames to process")
    page_spec: Optional[str] = Field("all", description="Page specification: e.g. '1, 3, 5-8', '2-4', 'even', 'odd', 'all'")
    angle: Optional[int] = Field(90, description="Rotation angle: 90, 180, or 270 degrees")
    compression_level: Optional[str] = Field("medium", description="Compression level: low, medium, high")
    text_format: Optional[str] = Field("markdown", description="Text output format: txt or markdown")
    table_format: Optional[str] = Field("xlsx", description="Table export format: xlsx or csv")
    watermark_text: Optional[str] = Field("CONFIDENTIAL", description="Watermark text to imprint")
    page_number_position: Optional[str] = Field("bottom-center", description="Position: bottom-center, bottom-right, top-right")


def parse_page_selection(page_spec: str, total_pages: int) -> List[int]:
    """
    Parses natural human-readable 1-indexed page specifications into 0-indexed integer list.
    Supports:
      - 'all', '', None -> all pages [0, 1, ..., total_pages-1]
      - '1, 3, 5' -> [0, 2, 4]
      - '2-5' -> [1, 2, 3, 4]
      - '1, 3-5, 8' -> [0, 2, 3, 4, 7]
      - 'even' -> [1, 3, 5, ...]
      - 'odd' -> [0, 2, 4, ...]
      - 'last' -> [total_pages - 1]
    Validates range boundaries and prevents out-of-bounds indices.
    """
    if total_pages <= 0:
        return []

    if not page_spec or page_spec.strip().lower() in ("all", "*"):
        return list(range(total_pages))

    spec = page_spec.strip().lower()

    if spec == "even":
        return [i for i in range(total_pages) if (i + 1) % 2 == 0]
    if spec == "odd":
        return [i for i in range(total_pages) if (i + 1) % 2 != 0]
    if spec == "last":
        return [total_pages - 1]

    selected_pages: List[int] = []
    seen = set()

    # Split by comma or semicolon
    parts = re.split(r"[,;]+", spec)
    for raw_part in parts:
        part = raw_part.strip()
        if not part:
            continue

        if "-" in part:
            sub = part.split("-", 1)
            try:
                start_str, end_str = sub[0].strip(), sub[1].strip()
                start = 1 if not start_str else int(start_str)
                end = total_pages if not end_str else int(end_str)
            except ValueError:
                raise ValueError(f"Invalid page range specification: '{part}'. Expected format 'start-end' (e.g. '2-5').")

            if start < 1 or end > total_pages:
                raise ValueError(f"Page range '{start}-{end}' exceeds document boundary (1 to {total_pages}).")
            if start > end:
                raise ValueError(f"Start page {start} cannot be greater than end page {end} in range '{part}'.")

            for p_num in range(start, end + 1):
                idx = p_num - 1
                if idx not in seen:
                    seen.add(idx)
                    selected_pages.append(idx)
        else:
            try:
                p_num = int(part)
            except ValueError:
                raise ValueError(f"Invalid page number '{part}'. Must be an integer or range like '1-3'.")

            if p_num < 1 or p_num > total_pages:
                raise ValueError(f"Page number {p_num} is out of bounds for document with {total_pages} pages.")

            idx = p_num - 1
            if idx not in seen:
                seen.add(idx)
                selected_pages.append(idx)

    if not selected_pages:
        raise ValueError(f"No valid pages selected by specification '{page_spec}'.")

    return selected_pages


def open_and_validate_pdf(file_path: str) -> pymupdf.Document:
    """
    Rigorously validates a PDF file and returns the opened Document:
    1. Checks file existence and non-zero byte size.
    2. Verifies %PDF- magic header bytes.
    3. Opens document via PyMuPDF.
    4. Detects if document is encrypted/password-protected.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file does not exist at '{file_path}'.")

    size = path.stat().st_size
    if size == 0:
        raise ValueError(f"PDF file at '{file_path}' is empty (0 bytes).")

    if size > MAX_PDF_SIZE_BYTES:
        raise ValueError(f"PDF file size ({size / (1024*1024):.1f}MB) exceeds safe maximum limit of {MAX_PDF_SIZE_BYTES / (1024*1024):.0f}MB.")

    with open(file_path, "rb") as f:
        header = f.read(5)
        if not header.startswith(b"%PDF-"):
            raise ValueError(f"File at '{file_path}' does not have a valid PDF header ('%PDF-').")

    try:
        doc = pymupdf.open(file_path)
    except Exception as e:
        raise ValueError(f"Corrupted or unreadable PDF file: {str(e)}")

    if doc.is_encrypted:
        # Check if it can be read without password
        if not doc.authenticate(""):
            raise ValueError("The PDF document is password-protected or encrypted. Please provide an unencrypted PDF.")

    if doc.page_count == 0:
        raise ValueError("PDF document contains 0 pages.")

    return doc


def validate_pdf_file(file_path: str) -> Tuple[bool, Optional[str]]:
    """
    Validates a PDF file, returning (True, None) if valid or (False, error_msg) if invalid.
    """
    try:
        doc = open_and_validate_pdf(file_path)
        doc.close()
        return True, None
    except Exception as ex:
        return False, str(ex)


def generate_safe_pdf_output_path(prefix: str = "pdf_tool", ext: str = "pdf") -> Tuple[str, str, str]:
    """Generates a safe, unique filename, absolute path, and artifact ID in settings.OUTPUT_DIR."""
    output_dir = Path(getattr(settings, "OUTPUT_DIR", "backend/data/output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    art_id = str(uuid.uuid4())
    short_hash = art_id[:8]
    clean_prefix = re.sub(r"[^\w-]", "_", prefix)[:30].strip("_")
    filename = f"{clean_prefix}_{short_hash}.{ext.lstrip('.')}"
    file_path = str((output_dir / filename).resolve())

    return filename, file_path, art_id


# ==============================================================================
# CORE OPERATION A: MERGE PDFS
# ==============================================================================

def merge_pdfs(
    pdf_paths: List[str],
    output_filename: Optional[str] = None,
    output_filename_prefix: str = "merged_document",
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Combines multiple PDF files into one validated output PDF preserving source order.
    """
    if not pdf_paths or len(pdf_paths) < 2:
        raise ValueError("Merging requires at least 2 PDF documents.")

    if len(pdf_paths) > MAX_MERGE_FILES:
        raise ValueError(f"Cannot merge more than {MAX_MERGE_FILES} files simultaneously.")

    merged_doc = pymupdf.open()
    total_source_pages = 0
    source_summaries = []

    try:
        for idx, src_path in enumerate(pdf_paths):
            src_doc = open_and_validate_pdf(src_path)
            p_count = src_doc.page_count
            total_source_pages += p_count
            source_summaries.append({
                "filename": Path(src_path).name,
                "pages": p_count,
                "order": idx + 1
            })

            merged_doc.insert_pdf(src_doc)
            src_doc.close()

        if total_source_pages > MAX_PAGES_TO_PROCESS:
            raise ValueError(f"Combined document exceeds maximum page limit of {MAX_PAGES_TO_PROCESS} pages (total: {total_source_pages}).")

        prefix = Path(output_filename).stem if output_filename else output_filename_prefix
        filename, file_path, art_id = generate_safe_pdf_output_path(prefix, "pdf")
        merged_doc.save(file_path, garbage=3, deflate=True)
    finally:
        merged_doc.close()

    # Validate output
    val_doc = open_and_validate_pdf(file_path)
    final_page_count = val_doc.page_count
    val_doc.close()
    file_size = os.path.getsize(file_path)

    artifact_registry.register_artifact(
        filename=filename,
        file_path=file_path,
        user_id=user_id,
        conversation_id=conversation_id,
        dataset_type="merged_pdf",
        data_row_count=final_page_count,
        file_size=file_size,
        mime_type="application/pdf",
        artifact_id=art_id,
        extra_metadata={
            "operation": "merge",
            "source_files_count": len(pdf_paths),
            "total_pages": final_page_count
        }
    )

    artifact = {
        "artifact_id": art_id,
        "filename": filename,
        "file_path": file_path,
        "file_size": file_size,
        "page_count": final_page_count,
        "operation": "merge",
        "format": "pdf",
        "status": "ready",
        "title": f"Merged PDF ({len(pdf_paths)} Files)",
        "download_url": f"/api/tools/download/{art_id}",
        "summary": f"Successfully merged {len(pdf_paths)} PDF documents into {filename} ({final_page_count} total pages, {file_size/1024:.1f} KB).",
        "source_files": source_summaries
    }
    active_pdf_artifact.set(artifact)
    return artifact


# ==============================================================================
# CORE OPERATION B & C: SPLIT & EXTRACT PAGES
# ==============================================================================

def extract_pages(
    pdf_path: str,
    page_spec: str,
    output_filename: Optional[str] = None,
    output_filename_prefix: str = "extracted_pages",
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extracts selected pages (e.g. '1, 3, 5-8') into a new validated PDF.
    """
    src_doc = open_and_validate_pdf(pdf_path)
    total_pages = src_doc.page_count

    selected_indices = parse_page_selection(page_spec, total_pages)
    if not selected_indices:
        src_doc.close()
        raise ValueError(f"No valid pages found in page specification '{page_spec}'.")

    new_doc = pymupdf.open()
    try:
        new_doc.insert_pdf(src_doc, from_page=0, to_page=total_pages - 1)
        # Select keeps only specified indices in order
        new_doc.select(selected_indices)

        prefix = Path(output_filename).stem if output_filename else output_filename_prefix
        filename, file_path, art_id = generate_safe_pdf_output_path(prefix, "pdf")
        new_doc.save(file_path, garbage=3, deflate=True)
    finally:
        new_doc.close()
        src_doc.close()

    # Validate generated output
    val_doc = open_and_validate_pdf(file_path)
    extracted_page_count = val_doc.page_count
    val_doc.close()
    file_size = os.path.getsize(file_path)

    human_pages = ", ".join(str(idx + 1) for idx in selected_indices[:10])
    if len(selected_indices) > 10:
        human_pages += f"... (+{len(selected_indices) - 10} more)"

    artifact_registry.register_artifact(
        filename=filename,
        file_path=file_path,
        user_id=user_id,
        conversation_id=conversation_id,
        dataset_type="extracted_pdf",
        data_row_count=extracted_page_count,
        file_size=file_size,
        mime_type="application/pdf",
        artifact_id=art_id,
        extra_metadata={
            "operation": "extract_pages",
            "page_spec": page_spec,
            "extracted_count": extracted_page_count
        }
    )

    artifact = {
        "artifact_id": art_id,
        "filename": filename,
        "file_path": file_path,
        "file_size": file_size,
        "page_count": extracted_page_count,
        "operation": "extract_pages",
        "format": "pdf",
        "status": "ready",
        "title": f"Extracted PDF ({extracted_page_count} Pages)",
        "download_url": f"/api/tools/download/{art_id}",
        "summary": f"Extracted {extracted_page_count} pages ({human_pages}) from {Path(pdf_path).name} into {filename} ({file_size/1024:.1f} KB)."
    }
    active_pdf_artifact.set(artifact)
    return artifact


def split_pdf(
    pdf_path: str,
    ranges: Optional[Union[List[str], str]] = None,
    page_ranges: Optional[Union[List[str], str]] = None,
    output_filename: Optional[str] = None,
    output_filename_prefix: str = "split_part",
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Splits a PDF into sub-documents according to comma-separated page ranges (e.g. '1-3, 4-6, 7-10').
    If only one range is passed, acts identically to extract_pages.
    """
    target = ranges if ranges is not None else page_ranges
    if not target:
        raise ValueError("Please provide at least one valid range to split (e.g. '1-3, 4-6').")

    if isinstance(target, list):
        raw_ranges = [r.strip() for r in target if r.strip()]
    else:
        raw_ranges = [r.strip() for r in re.split(r"[,;]+", str(target)) if r.strip()]

    if not raw_ranges:
        raise ValueError("Please provide at least one valid range to split (e.g. '1-3, 4-6').")

    src_doc = open_and_validate_pdf(pdf_path)
    total_pages = src_doc.page_count
    src_doc.close()

    if len(raw_ranges) == 1 and not isinstance(ranges, list):
        return extract_pages(
            pdf_path=pdf_path,
            page_spec=raw_ranges[0],
            output_filename=output_filename,
            output_filename_prefix=f"split_range_{raw_ranges[0]}",
            user_id=user_id,
            conversation_id=conversation_id
        )

    # Multi-range split: generates files and packages into result list
    split_parts = []
    for r_idx, r_spec in enumerate(raw_ranges, start=1):
        part_prefix = f"split_part_{r_idx}_{r_spec.replace(' ', '_')}"
        part_artifact = extract_pages(
            pdf_path=pdf_path,
            page_spec=r_spec,
            output_filename_prefix=part_prefix,
            user_id=user_id,
            conversation_id=conversation_id
        )
        split_parts.append(part_artifact)

    if isinstance(ranges, list):
        return split_parts

    primary = split_parts[0]
    combined_artifact = {
        "artifact_id": primary["artifact_id"],
        "filename": primary["filename"],
        "file_path": primary["file_path"],
        "file_size": primary["file_size"],
        "page_count": primary["page_count"],
        "operation": "split",
        "format": "pdf",
        "status": "ready",
        "title": f"Split PDF ({len(split_parts)} Parts)",
        "download_url": primary["download_url"],
        "split_parts": split_parts,
        "summary": f"Split {Path(pdf_path).name} into {len(split_parts)} separate PDF files according to ranges '{raw_ranges}'."
    }
    active_pdf_artifact.set(combined_artifact)
    return combined_artifact


# ==============================================================================
# CORE OPERATION D: ROTATE PAGES
# ==============================================================================

def rotate_pages(
    pdf_path: str,
    angle: int = 90,
    page_spec: str = "all",
    output_filename: Optional[str] = None,
    output_filename_prefix: str = "rotated_document",
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Rotates selected pages by 90, 180, or 270 degrees while preserving the remaining pages.
    """
    if angle not in (90, 180, 270, -90, -180, -270):
        raise ValueError(f"Invalid rotation angle: {angle}°. Must be 90, 180, or 270 degrees.")

    normalized_angle = angle % 360

    src_doc = open_and_validate_pdf(pdf_path)
    total_pages = src_doc.page_count
    selected_indices = set(parse_page_selection(page_spec, total_pages))

    new_doc = pymupdf.open()
    try:
        new_doc.insert_pdf(src_doc)
        for idx in range(new_doc.page_count):
            if idx in selected_indices:
                p = new_doc[idx]
                p.set_rotation((p.rotation + normalized_angle) % 360)

        prefix = Path(output_filename).stem if output_filename else output_filename_prefix
        filename, file_path, art_id = generate_safe_pdf_output_path(prefix, "pdf")
        new_doc.save(file_path, garbage=3, deflate=True)
    finally:
        new_doc.close()
        src_doc.close()

    val_doc = open_and_validate_pdf(file_path)
    val_doc.close()
    file_size = os.path.getsize(file_path)

    artifact_registry.register_artifact(
        filename=filename,
        file_path=file_path,
        user_id=user_id,
        conversation_id=conversation_id,
        dataset_type="rotated_pdf",
        data_row_count=total_pages,
        file_size=file_size,
        mime_type="application/pdf",
        artifact_id=art_id,
        extra_metadata={
            "operation": "rotate",
            "angle": normalized_angle,
            "rotated_pages_count": len(selected_indices)
        }
    )

    artifact = {
        "artifact_id": art_id,
        "filename": filename,
        "file_path": file_path,
        "file_size": file_size,
        "page_count": total_pages,
        "operation": "rotate",
        "format": "pdf",
        "status": "ready",
        "title": f"Rotated PDF ({normalized_angle}°)",
        "download_url": f"/api/tools/download/{art_id}",
        "summary": f"Successfully rotated {len(selected_indices)} page(s) by {normalized_angle}° in {filename} ({file_size/1024:.1f} KB)."
    }
    active_pdf_artifact.set(artifact)
    return artifact


# ==============================================================================
# CORE OPERATION E: COMPRESS PDF
# ==============================================================================

def compress_pdf(
    pdf_path: str,
    level: str = "medium",
    output_filename: Optional[str] = None,
    output_filename_prefix: str = "compressed_document",
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compresses PDF using stream deflating, object deduplication, and cleanup.
    Includes explicit disclaimer that reduction depends on original PDF contents.
    """
    lvl = level.lower().strip()
    if lvl not in ("low", "medium", "high"):
        lvl = "medium"

    src_doc = open_and_validate_pdf(pdf_path)
    total_pages = src_doc.page_count
    original_size = os.path.getsize(pdf_path)

    prefix = Path(output_filename).stem if output_filename else output_filename_prefix
    filename, file_path, art_id = generate_safe_pdf_output_path(prefix, "pdf")

    try:
        # Save options based on compression level
        if lvl == "low":
            src_doc.save(file_path, garbage=2, deflate=True, clean=True)
        elif lvl == "medium":
            src_doc.save(file_path, garbage=3, deflate=True, deflate_images=True, deflate_fonts=True, clean=True)
        else:  # high
            src_doc.save(file_path, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True, linear=True)
    finally:
        src_doc.close()

    new_size = os.path.getsize(file_path)
    bytes_saved = max(0, original_size - new_size)
    reduction_pct = (bytes_saved / original_size * 100) if original_size > 0 else 0.0

    artifact_registry.register_artifact(
        filename=filename,
        file_path=file_path,
        user_id=user_id,
        conversation_id=conversation_id,
        dataset_type="compressed_pdf",
        data_row_count=total_pages,
        file_size=new_size,
        mime_type="application/pdf",
        artifact_id=art_id,
        extra_metadata={
            "operation": "compress",
            "original_size": original_size,
            "compressed_size": new_size,
            "reduction_pct": round(reduction_pct, 1),
            "level": lvl
        }
    )

    disclaimer = (
        "Note: PDF compression efficiency depends on document composition. "
        "Files with uncompressed streams or redundant objects achieve substantial size reductions, "
        "while documents that already contain highly compressed images (e.g. JPEG) maintain their original size to preserve visual quality."
    )

    summary_msg = (
        f"Compressed {Path(pdf_path).name} from {original_size/1024:.1f} KB down to {new_size/1024:.1f} KB "
        f"({reduction_pct:.1f}% reduction). {disclaimer}"
    )

    artifact = {
        "artifact_id": art_id,
        "filename": filename,
        "file_path": file_path,
        "file_size": new_size,
        "original_size": original_size,
        "reduction_pct": round(reduction_pct, 1),
        "reduction_percent": round(reduction_pct, 1),
        "page_count": total_pages,
        "operation": "compress",
        "format": "pdf",
        "status": "ready",
        "title": f"Compressed PDF ({reduction_pct:.1f}% Saved)",
        "download_url": f"/api/tools/download/{art_id}",
        "summary": summary_msg,
        "disclaimer": disclaimer,
        "honest_note": disclaimer
    }
    active_pdf_artifact.set(artifact)
    return artifact


# ==============================================================================
# CORE OPERATION F: CONVERT PDF TO TEXT / MARKDOWN
# ==============================================================================

def convert_pdf_to_text(
    pdf_path: str,
    format: Optional[str] = None,
    output_format: str = "markdown",
    output_filename: Optional[str] = None,
    output_filename_prefix: str = "extracted_text",
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extracts text preserving reading order and page boundaries into TXT or Markdown.
    Reports clearly when pages are scanned images without extractable text streams.
    """
    raw_fmt = (format if format is not None else output_format) or "markdown"
    fmt = str(raw_fmt).lower().lstrip(".")
    if fmt in ("txt", "text", "plain"):
        ext = "txt"
    else:
        ext = "md"

    src_doc = open_and_validate_pdf(pdf_path)
    total_pages = src_doc.page_count
    lines: List[str] = []
    scanned_pages: List[int] = []

    try:
        base_name = Path(pdf_path).stem
        if ext == "md":
            lines.append(f"# Extracted Content: {base_name}\n")
            lines.append(f"> **Source File:** `{Path(pdf_path).name}` | **Total Pages:** {total_pages}\n\n---\n")
        else:
            lines.append(f"EXTRACTED TEXT FROM: {Path(pdf_path).name}")
            lines.append(f"TOTAL PAGES: {total_pages}")
            lines.append("=" * 60 + "\n")

        total_extracted_words = 0

        for p_idx in range(total_pages):
            page = src_doc[p_idx]
            p_num = p_idx + 1

            text = page.get_text("text").strip()
            word_count = len(text.split())
            total_extracted_words += word_count

            if word_count == 0:
                scanned_pages.append(p_num)

            if ext == "md":
                lines.append(f"\n## Page {p_num}\n")
                if text:
                    lines.append(text)
                else:
                    lines.append("_*(No selectable text found on this page. May contain scanned images or diagrams)*_")
                lines.append("\n---\n")
            else:
                lines.append(f"--- PAGE {p_num} ---")
                if text:
                    lines.append(text)
                else:
                    lines.append("[No selectable text found on this page]")
                lines.append("\n")

        prefix = Path(output_filename).stem if output_filename else output_filename_prefix
        filename, file_path, art_id = generate_safe_pdf_output_path(prefix, ext)
        full_content = "\n".join(lines)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(full_content)

    finally:
        src_doc.close()

    file_size = os.path.getsize(file_path)
    mime = "text/markdown; charset=utf-8" if ext == "md" else "text/plain; charset=utf-8"

    artifact_registry.register_artifact(
        filename=filename,
        file_path=file_path,
        user_id=user_id,
        conversation_id=conversation_id,
        dataset_type=f"extracted_{ext}",
        data_row_count=total_pages,
        file_size=file_size,
        mime_type=mime,
        artifact_id=art_id,
        extra_metadata={
            "operation": "to_text",
            "format": ext,
            "word_count": total_extracted_words,
            "scanned_pages_count": len(scanned_pages)
        }
    )

    scanned_report = ""
    if scanned_pages:
        scanned_report = f" Note: {len(scanned_pages)} page(s) (pages {scanned_pages[:5]}) contain scanned images without extractable digital text."

    artifact = {
        "artifact_id": art_id,
        "filename": filename,
        "file_path": file_path,
        "file_size": file_size,
        "page_count": total_pages,
        "word_count": total_extracted_words,
        "operation": "to_text",
        "format": ext,
        "status": "ready",
        "title": f"Extracted Text ({ext.upper()})",
        "download_url": f"/api/tools/download/{art_id}",
        "preview_text": full_content[:800] + ("..." if len(full_content) > 800 else ""),
        "summary": f"Extracted {total_extracted_words} words across {total_pages} pages into {filename} ({file_size/1024:.1f} KB).{scanned_report}"
    }
    active_pdf_artifact.set(artifact)
    return artifact


# ==============================================================================
# CORE OPERATION G: EXTRACT PDF TABLES
# ==============================================================================

def extract_pdf_tables(
    pdf_path: str,
    format: Optional[str] = None,
    output_format: Optional[str] = None,
    table_format: str = "xlsx",
    output_filename: Optional[str] = None,
    output_filename_prefix: str = "extracted_tables",
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extracts detectable tables across PDF pages into an Excel (.xlsx) workbook or CSV file.
    """
    raw_fmt = format if format is not None else (output_format if output_format is not None else table_format)
    fmt = raw_fmt.lower().lstrip(".")
    if fmt not in ("xlsx", "csv"):
        fmt = "xlsx"

    src_doc = open_and_validate_pdf(pdf_path)
    total_pages = src_doc.page_count
    all_tables_data: List[Dict[str, Any]] = []

    try:
        for p_idx in range(total_pages):
            page = src_doc[p_idx]
            p_num = p_idx + 1

            # 1. Native PyMuPDF table finder with multiple strategies
            tabs = page.find_tables()
            if not (tabs and tabs.tables):
                tabs = page.find_tables(strategy="lines")
            if not (tabs and tabs.tables):
                tabs = page.find_tables(strategy="text")

            if tabs and tabs.tables:
                for t_idx, tab in enumerate(tabs.tables, start=1):
                    extracted = tab.extract()
                    if extracted and len(extracted) > 0:
                        all_tables_data.append({
                            "page": p_num,
                            "table_index": t_idx,
                            "title": f"Page {p_num} Table {t_idx}",
                            "rows": extracted
                        })
            else:
                # 2. Secondary heuristic fallback: look for tab/pipe separated lines
                text = page.get_text("text")
                pipe_lines = [l.strip() for l in text.splitlines() if "|" in l]
                if len(pipe_lines) >= 2:
                    rows = []
                    for pl in pipe_lines:
                        cells = [c.strip() for c in pl.split("|") if c.strip() != ""]
                        if cells and not all(re.match(r"^[-:]+$", c) for c in cells):
                            rows.append(cells)
                    if len(rows) >= 2:
                        all_tables_data.append({
                            "page": p_num,
                            "table_index": 1,
                            "title": f"Page {p_num} Delimited Table",
                            "rows": rows
                        })
    finally:
        src_doc.close()

    if not all_tables_data:
        raise ValueError(
            f"No structured tables were detected in '{Path(pdf_path).name}'. "
            "Note: Scanned images of tables or complex multi-layered layouts without vector borders cannot be extracted reliably without OCR table models."
        )

    prefix = Path(output_filename).stem if output_filename else output_filename_prefix
    filename, file_path, art_id = generate_safe_pdf_output_path(prefix, fmt)

    if fmt == "xlsx":
        wb = openpyxl.Workbook()
        # Remove default sheet
        wb.remove(wb.active)

        navy_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        regular_font = Font(name="Calibri", size=10, color="1E293B")
        center_align = Alignment(vertical="center")
        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1")
        )

        for tab_item in all_tables_data:
            sheet_title = tab_item["title"][:31]  # Excel 31-char limit
            ws = wb.create_sheet(title=sheet_title)
            ws.views.sheetView[0].showGridLines = True

            rows = tab_item["rows"]
            for r_idx, row in enumerate(rows, start=1):
                for c_idx, cell in enumerate(row, start=1):
                    val = cell if cell is not None else ""
                    # CWE-1236 Defense: escape leading formula injection chars
                    s_val = str(val).strip()
                    if s_val and s_val[0] in ("=", "+", "-", "@", "\t", "\r"):
                        s_val = "'" + s_val

                    c = ws.cell(row=r_idx, column=c_idx, value=s_val)
                    c.border = thin_border
                    c.alignment = center_align

                    if r_idx == 1:
                        c.fill = navy_fill
                        c.font = header_font
                    else:
                        c.font = regular_font

            # Auto column widths
            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(12, min(40, max_len + 4))

        wb.save(file_path)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        # CSV format: exports all tables sequentially with section headers
        import csv
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for tab_item in all_tables_data:
                writer.writerow([f"=== {tab_item['title']} ==="])
                for r in tab_item["rows"]:
                    # Sanitize formula injection
                    clean_r = ["'" + str(c) if str(c).startswith(("=", "+", "-", "@")) else str(c) for c in r]
                    writer.writerow(clean_r)
                writer.writerow([])
        mime = "text/csv; charset=utf-8"

    file_size = os.path.getsize(file_path)

    artifact_registry.register_artifact(
        filename=filename,
        file_path=file_path,
        user_id=user_id,
        conversation_id=conversation_id,
        dataset_type=f"extracted_tables_{fmt}",
        data_row_count=len(all_tables_data),
        file_size=file_size,
        mime_type=mime,
        artifact_id=art_id,
        extra_metadata={
            "operation": "extract_tables",
            "format": fmt,
            "tables_count": len(all_tables_data)
        }
    )

    artifact = {
        "artifact_id": art_id,
        "filename": filename,
        "file_path": file_path,
        "file_size": file_size,
        "tables_count": len(all_tables_data),
        "operation": "extract_tables",
        "format": fmt,
        "status": "ready",
        "title": f"Extracted Tables ({len(all_tables_data)} Found)",
        "download_url": f"/api/tools/download/{art_id}",
        "summary": f"Detected and extracted {len(all_tables_data)} structured table(s) from {Path(pdf_path).name} into {filename} ({file_size/1024:.1f} KB)."
    }
    active_pdf_artifact.set(artifact)
    return artifact


# ==============================================================================
# CORE OPERATION H: PDF INFORMATION & METADATA INSPECTION
# ==============================================================================

def get_pdf_info(pdf_path: str) -> Dict[str, Any]:
    """
    Returns comprehensive metadata, dimensions, security status, and statistics of a PDF.
    """
    src_doc = open_and_validate_pdf(pdf_path)
    try:
        p_count = src_doc.page_count
        meta = src_doc.metadata or {}
        file_size = os.path.getsize(pdf_path)

        # Inspect first page dimensions
        first_page = src_doc[0]
        rect = first_page.rect
        width_pts = round(rect.width, 1)
        height_pts = round(rect.height, 1)
        width_in = round(width_pts / 72.0, 2)
        height_in = round(height_pts / 72.0, 2)

        # Standard paper size estimation
        paper_type = "Custom"
        if abs(width_in - 8.5) < 0.2 and abs(height_in - 11.0) < 0.2:
            paper_type = "Letter"
        elif abs(width_in - 8.27) < 0.2 and abs(height_in - 11.69) < 0.2:
            paper_type = "A4"
        elif abs(width_in - 8.5) < 0.2 and abs(height_in - 14.0) < 0.2:
            paper_type = "Legal"

        # Count tables, images, and fonts across pages
        total_tables = 0
        total_images = 0
        for p in src_doc:
            total_images += len(p.get_images())
            tabs = p.find_tables()
            if tabs and tabs.tables:
                total_tables += len(tabs.tables)

        return {
            "valid": True,
            "status": "success",
            "filename": Path(pdf_path).name,
            "file_size": file_size,
            "file_size_formatted": f"{file_size / 1024:.1f} KB" if file_size < 1024*1024 else f"{file_size / (1024*1024):.2f} MB",
            "page_count": p_count,
            "is_encrypted": src_doc.is_encrypted,
            "dimensions": {
                "points": f"{width_pts} x {height_pts} pt",
                "inches": f"{width_in} x {height_in} in",
                "standard_size": paper_type,
                "paper_size": paper_type,
                "orientation": "Landscape" if width_pts > height_pts else "Portrait"
            },
            "metadata": {
                "title": meta.get("title") or "Not Specified",
                "author": meta.get("author") or "Not Specified",
                "subject": meta.get("subject") or "Not Specified",
                "creator": meta.get("creator") or "Not Specified",
                "producer": meta.get("producer") or "Not Specified",
                "creation_date": meta.get("creationDate") or "Not Specified",
                "modification_date": meta.get("modDate") or "Not Specified"
            },
            "security": {
                "encrypted": src_doc.is_encrypted,
                "needs_pass": src_doc.needs_pass,
                "permissions": src_doc.permissions
            },
            "statistics": {
                "total_embedded_images": total_images,
                "detected_tables": total_tables
            }
        }
    finally:
        src_doc.close()


# ==============================================================================
# ADVANCED OPERATIONS: WATERMARK, PAGE NUMBERS, IMAGES TO PDF
# ==============================================================================

def add_watermark(
    pdf_path: str,
    text: Optional[str] = None,
    watermark_text: str = "CONFIDENTIAL",
    page_spec: str = "all",
    opacity: float = 0.25,
    fontsize: int = 48,
    output_filename: Optional[str] = None,
    output_filename_prefix: str = "watermarked_document",
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Imprints a semi-transparent text watermark across the center of every page.
    """
    src_doc = open_and_validate_pdf(pdf_path)
    total_pages = src_doc.page_count
    wm_text = (text if text is not None else watermark_text).strip()
    selected_indices = set(parse_page_selection(page_spec, total_pages)) if (page_spec and page_spec != "all") else set(range(total_pages))

    new_doc = pymupdf.open()
    try:
        new_doc.insert_pdf(src_doc)
        for idx in range(total_pages):
            if idx not in selected_indices:
                continue
            page = new_doc[idx]
            rect = page.rect
            center_x = rect.width / 2
            center_y = rect.height / 2

            font_size = fontsize if fontsize > 0 else (min(rect.width, rect.height) / 8)
            pt = pymupdf.Point(center_x - (len(wm_text) * font_size * 0.22), center_y)
            morph = (pt, pymupdf.Matrix(45))
            page.insert_text(
                point=pt,
                text=wm_text,
                fontsize=font_size,
                fontname="helv",
                color=(0.8, 0.2, 0.2),  # Soft red
                fill_opacity=opacity,
                morph=morph
            )

        prefix = Path(output_filename).stem if output_filename else output_filename_prefix
        filename, file_path, art_id = generate_safe_pdf_output_path(prefix, "pdf")
        new_doc.save(file_path, garbage=3, deflate=True)
    finally:
        new_doc.close()
        src_doc.close()

    val_doc = open_and_validate_pdf(file_path)
    val_doc.close()
    file_size = os.path.getsize(file_path)

    artifact_registry.register_artifact(
        filename=filename,
        file_path=file_path,
        user_id=user_id,
        conversation_id=conversation_id,
        dataset_type="watermarked_pdf",
        data_row_count=total_pages,
        file_size=file_size,
        mime_type="application/pdf",
        artifact_id=art_id,
        extra_metadata={
            "operation": "watermark",
            "watermark_text": wm_text,
            "pages_count": len(selected_indices)
        }
    )

    artifact = {
        "artifact_id": art_id,
        "filename": filename,
        "file_path": file_path,
        "file_size": file_size,
        "page_count": total_pages,
        "operation": "watermark",
        "format": "pdf",
        "status": "ready",
        "title": f"Watermarked PDF ('{wm_text}')",
        "download_url": f"/api/tools/download/{art_id}",
        "summary": f"Applied '{wm_text}' watermark across {len(selected_indices)} page(s) in {filename} ({file_size/1024:.1f} KB)."
    }
    active_pdf_artifact.set(artifact)
    return artifact


def add_page_numbers(
    pdf_path: str,
    position: str = "bottom-center",
    format_str: str = "Page {page} of {total}",
    output_filename: Optional[str] = None,
    output_filename_prefix: str = "numbered_document",
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Inserts running page numbers ('Page X of Y') into header or footer.
    """
    src_doc = open_and_validate_pdf(pdf_path)
    total_pages = src_doc.page_count

    new_doc = pymupdf.open()
    try:
        new_doc.insert_pdf(src_doc)
        for idx in range(total_pages):
            page = new_doc[idx]
            p_num = idx + 1
            num_text = format_str.format(page=p_num, total=total_pages)

            rect = page.rect
            # Position coordinates
            if position == "bottom-right":
                pt = pymupdf.Point(rect.width - 120, rect.height - 25)
            elif position == "top-right":
                pt = pymupdf.Point(rect.width - 120, 30)
            else:  # bottom-center
                pt = pymupdf.Point(rect.width / 2 - 40, rect.height - 25)

            page.insert_text(
                point=pt,
                text=num_text,
                fontsize=9,
                fontname="helv",
                color=(0.3, 0.35, 0.4)  # Slate gray
            )

        prefix = Path(output_filename).stem if output_filename else output_filename_prefix
        filename, file_path, art_id = generate_safe_pdf_output_path(prefix, "pdf")
        new_doc.save(file_path, garbage=3, deflate=True)
    finally:
        new_doc.close()
        src_doc.close()

    val_doc = open_and_validate_pdf(file_path)
    val_doc.close()
    file_size = os.path.getsize(file_path)

    artifact_registry.register_artifact(
        filename=filename,
        file_path=file_path,
        user_id=user_id,
        conversation_id=conversation_id,
        dataset_type="numbered_pdf",
        data_row_count=total_pages,
        file_size=file_size,
        mime_type="application/pdf",
        artifact_id=art_id,
        extra_metadata={
            "operation": "page_numbers",
            "position": position
        }
    )

    artifact = {
        "artifact_id": art_id,
        "filename": filename,
        "file_path": file_path,
        "file_size": file_size,
        "page_count": total_pages,
        "operation": "page_numbers",
        "format": "pdf",
        "status": "ready",
        "title": "Numbered PDF",
        "download_url": f"/api/tools/download/{art_id}",
        "summary": f"Added dynamic page numbers to all {total_pages} pages in {filename} ({file_size/1024:.1f} KB)."
    }
    active_pdf_artifact.set(artifact)
    return artifact


def images_to_pdf(
    image_paths: List[str],
    output_filename: Optional[str] = None,
    output_filename_prefix: str = "compiled_images",
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Converts one or more image files (PNG, JPG, JPEG, WEBP) into a single PDF document.
    """
    if not image_paths:
        raise ValueError("Please provide at least one valid image file.")

    combined_pdf = pymupdf.open()
    valid_exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

    try:
        for img_path in image_paths:
            path = Path(img_path)
            if not path.exists():
                raise FileNotFoundError(f"Image not found at '{img_path}'.")
            if path.suffix.lower() not in valid_exts:
                raise ValueError(f"Unsupported image format '{path.suffix}'. Allowed: PNG, JPG, JPEG, BMP, WEBP.")

            img_doc = pymupdf.open(img_path)
            pdf_bytes = img_doc.convert_to_pdf()
            img_doc.close()

            img_pdf = pymupdf.open("pdf", pdf_bytes)
            combined_pdf.insert_pdf(img_pdf)
            img_pdf.close()

        prefix = Path(output_filename).stem if output_filename else output_filename_prefix
        filename, file_path, art_id = generate_safe_pdf_output_path(prefix, "pdf")
        combined_pdf.save(file_path, garbage=3, deflate=True)
    finally:
        combined_pdf.close()

    val_doc = open_and_validate_pdf(file_path)
    final_page_count = val_doc.page_count
    val_doc.close()
    file_size = os.path.getsize(file_path)

    artifact_registry.register_artifact(
        filename=filename,
        file_path=file_path,
        user_id=user_id,
        conversation_id=conversation_id,
        dataset_type="images_to_pdf",
        data_row_count=final_page_count,
        file_size=file_size,
        mime_type="application/pdf",
        artifact_id=art_id,
        extra_metadata={
            "operation": "images_to_pdf",
            "image_count": len(image_paths)
        }
    )

    artifact = {
        "artifact_id": art_id,
        "filename": filename,
        "file_path": file_path,
        "file_size": file_size,
        "page_count": final_page_count,
        "operation": "images_to_pdf",
        "format": "pdf",
        "status": "ready",
        "title": f"Converted Image(s) to PDF ({len(image_paths)} Images)",
        "download_url": f"/api/tools/download/{art_id}",
        "summary": f"Successfully compiled {len(image_paths)} image(s) into PDF {filename} ({file_size/1024:.1f} KB)."
    }
    active_pdf_artifact.set(artifact)
    return artifact


# ==============================================================================
# NATURAL LANGUAGE DISPATCHER FOR AI AGENT
# ==============================================================================

async def execute_pdf_tool_from_request(
    prompt: str,
    active_doc_path: Optional[str] = None,
    candidate_doc_paths: Optional[List[str]] = None,
    doc_ids: Optional[List[str]] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Parses intent and parameters from natural language prompts, resolving the target PDF
    from the current conversation or workspace, and executes the appropriate PDF operation.
    """
    p_lower = prompt.lower()

    if doc_ids and not candidate_doc_paths:
        candidate_doc_paths = []
        for did in doc_ids:
            if os.path.exists(did):
                candidate_doc_paths.append(did)
            else:
                upload_dir = Path(getattr(settings, "UPLOAD_DIR", "backend/data/uploads"))
                found = list(upload_dir.glob(f"*{did}*.pdf"))
                if found:
                    candidate_doc_paths.append(str(found[0].resolve()))

    # 1. Merge intent
    if re.search(r"\b(merge|combine|join|concatenate)\b.*\b(?:pdfs?|documents?|files?)\b", p_lower):
        paths_to_merge = candidate_doc_paths or []
        if len(paths_to_merge) < 2 and active_doc_path:
            paths_to_merge = [active_doc_path] + [p for p in (candidate_doc_paths or []) if p != active_doc_path]

        if len(paths_to_merge) < 2:
            # Check uploaded documents in data/uploads
            upload_dir = Path(getattr(settings, "UPLOAD_DIR", "backend/data/uploads"))
            if upload_dir.exists():
                existing = [str(f.resolve()) for f in upload_dir.glob("*.pdf") if f.is_file()]
                if len(existing) >= 2:
                    paths_to_merge = existing[:3]

        if len(paths_to_merge) < 2:
            raise ValueError("Merging requires at least 2 PDF documents. Please upload or select multiple PDFs.")

        return merge_pdfs(
            pdf_paths=paths_to_merge,
            user_id=user_id,
            conversation_id=conversation_id
        )

    # Resolve single target PDF for all other operations
    target_path = active_doc_path
    if not target_path and candidate_doc_paths:
        target_path = candidate_doc_paths[0]

    if not target_path:
        # Search upload dir for most recently uploaded PDF
        upload_dir = Path(getattr(settings, "UPLOAD_DIR", "backend/data/uploads"))
        if upload_dir.exists():
            pdfs = sorted(upload_dir.glob("*.pdf"), key=os.path.getmtime, reverse=True)
            if pdfs:
                target_path = str(pdfs[0].resolve())

    if not target_path:
        raise ValueError("Please select or upload a PDF document to perform this operation.")

    # 2. Extract pages intent
    match_extract = re.search(r"\bextract\s+(?:pages?|page\s+numbers?)\s+([0-9\s,\-]+)", p_lower)
    if match_extract or re.search(r"\b(extract|pull\s+out|isolate)\b.*\bpages?\b", p_lower):
        page_spec = match_extract.group(1).strip() if match_extract else "1"
        return extract_pages(
            pdf_path=target_path,
            page_spec=page_spec,
            user_id=user_id,
            conversation_id=conversation_id
        )

    # 3. Split intent
    match_split = re.search(r"\bsplit\b.*\b(?:by|at|ranges?)\s+([0-9\s,\-]+)", p_lower)
    if match_split or re.search(r"\b(split|divide|break\s+up)\b.*\b(?:pdf|document)\b", p_lower):
        ranges = match_split.group(1).strip() if match_split else "1-2, 3-4"
        return split_pdf(
            pdf_path=target_path,
            page_ranges=ranges,
            user_id=user_id,
            conversation_id=conversation_id
        )

    # 4. Rotate intent
    if re.search(r"\b(rotate|turn|orient)\b", p_lower):
        angle = 90
        if "180" in p_lower:
            angle = 180
        elif "270" in p_lower:
            angle = 270

        # Detect page spec if specified
        page_spec = "all"
        p_match = re.search(r"\bpage\s+(\d+)\b", p_lower)
        if p_match:
            page_spec = p_match.group(1)

        return rotate_pages(
            pdf_path=target_path,
            page_spec=page_spec,
            angle=angle,
            user_id=user_id,
            conversation_id=conversation_id
        )

    # 5. Compress intent
    if re.search(r"\b(compress|reduce|shrink|optimize|minimize)\b.*\b(?:pdf|size|file)\b", p_lower):
        return compress_pdf(
            pdf_path=target_path,
            level="medium",
            user_id=user_id,
            conversation_id=conversation_id
        )

    # 6. Extract Tables intent
    if re.search(r"\b(extract|export)\b.*\b(?:tables?|tabular\s+data)\b", p_lower) or re.search(r"\bconvert\b.*\b(?:into|to)\b.*\b(?:excel|spreadsheet|\.?xlsx?|\.?csv)\b", p_lower):
        output_fmt = "xlsx" if "excel" in p_lower or "xlsx" in p_lower or "spreadsheet" in p_lower else "csv"
        return extract_pdf_tables(
            pdf_path=target_path,
            output_format=output_fmt,
            user_id=user_id,
            conversation_id=conversation_id
        )

    # 7. Convert to Text/Markdown intent
    if re.search(r"\b(convert|extract|export|turn)\b.*\b(?:into|to)\b.*\b(?:text|txt|markdown|\.?md)\b", p_lower) or re.search(r"\bextract\s+(?:all\s+)?text\b", p_lower):
        out_fmt = "md" if "markdown" in p_lower or ".md" in p_lower else "txt"
        return convert_pdf_to_text(
            pdf_path=target_path,
            output_format=out_fmt,
            user_id=user_id,
            conversation_id=conversation_id
        )

    # 8. Watermark intent
    if re.search(r"\b(watermark|stamp)\b", p_lower):
        wm_text = "CONFIDENTIAL"
        wm_match = re.search(r"['\"]([^'\"]+)['\"]", prompt)
        if wm_match:
            wm_text = wm_match.group(1)
        return add_watermark(
            pdf_path=target_path,
            watermark_text=wm_text,
            user_id=user_id,
            conversation_id=conversation_id
        )

    # 9. Page Numbers intent
    if re.search(r"\b(?:add|insert)\s+(?:page\s+numbers?|pagination|page\s+counts?)\b", p_lower):
        return add_page_numbers(
            pdf_path=target_path,
            user_id=user_id,
            conversation_id=conversation_id
        )

    # 10. PDF Info intent
    if re.search(r"\b(?:info|information|metadata|details|page\s+count|properties)\b.*\b(?:pdf|document)\b", p_lower):
        info_data = get_pdf_info(target_path)
        return {
            "operation": "info",
            "format": "json",
            "title": f"PDF Info: {info_data['filename']}",
            "info": info_data,
            "summary": (
                f"**PDF Information for {info_data['filename']}**:\n"
                f"- **Pages**: {info_data['page_count']}\n"
                f"- **Size**: {info_data['file_size_formatted']}\n"
                f"- **Dimensions**: {info_data['dimensions']['points']} ({info_data['dimensions']['standard_size']}, {info_data['dimensions']['orientation']})\n"
                f"- **Author**: {info_data['metadata']['author']}\n"
                f"- **Title**: {info_data['metadata']['title']}\n"
                f"- **Security**: {'Encrypted' if info_data['security']['encrypted'] else 'Unencrypted'}\n"
                f"- **Tables**: {info_data['statistics']['detected_tables']} detected | **Images**: {info_data['statistics']['total_embedded_images']}"
            )
        }

    # Default fallback
    raise ValueError(f"Unrecognized PDF operation in query: '{prompt}'. Supported operations: merge, split, extract, rotate, compress, to_text, extract_tables, info, watermark, page_numbers.")
