"""
DocuChat AI - PDF Tools REST API Router
Provides dedicated endpoints for PDF operations:
- Merge, Split, Extract Pages, Rotate, Compress, Convert to Text,
- Extract Tables, Metadata/Info, Watermark, Page Numbers, Images to PDF.
Supports both direct file uploads and referencing existing DocuChat document IDs.
"""

import os
import uuid
import tempfile
import logging
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.config import settings
from backend.db.session import get_db
from backend.db.models import DocumentModel, UserModel
from backend.api.auth import get_current_user_optional
from backend.tools.pdf_tools import (
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
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pdf-tools", tags=["pdf-tools"])

MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


async def _save_upload_to_temp(upload_file: UploadFile, allowed_exts: Optional[set] = None) -> str:
    """Safely saves an uploaded file to a temporary location and returns the path."""
    ext = Path(upload_file.filename).suffix.lower()
    if allowed_exts and ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{ext}'. Allowed: {', '.join(sorted(allowed_exts))}"
        )

    tmp_dir = Path(tempfile.gettempdir()) / "docuchat_pdf_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = tmp_dir / f"upload_{uuid.uuid4().hex[:10]}_{Path(upload_file.filename).name}"

    total_bytes = 0
    with open(temp_path, "wb") as f:
        while chunk := await upload_file.read(1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > MAX_PDF_SIZE_BYTES:
                f.close()
                if temp_path.exists():
                    os.remove(temp_path)
                raise HTTPException(status_code=413, detail="File exceeds maximum allowed size of 50MB.")
            f.write(chunk)

    return str(temp_path)


async def _resolve_pdf_path(
    file: Optional[UploadFile],
    doc_id: Optional[str],
    db: AsyncSession,
    current_user: Optional[UserModel]
) -> str:
    """Resolves local file path from either an uploaded file or an existing document ID."""
    if file and file.filename:
        temp_path = await _save_upload_to_temp(file, allowed_exts={".pdf"})
        valid, err = validate_pdf_file(temp_path)
        if not valid:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise HTTPException(status_code=400, detail=f"Invalid PDF: {err}")
        return temp_path

    if doc_id:
        res = await db.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        doc = res.scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document with ID '{doc_id}' not found.")
        
        path = doc.pdf_path or doc.original_path
        if not path or not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Underlying document file not found on disk.")
        
        valid, err = validate_pdf_file(path)
        if not valid:
            raise HTTPException(status_code=400, detail=f"Document '{doc.filename}' is not a valid PDF: {err}")
        return path

    raise HTTPException(status_code=400, detail="Must provide either an uploaded PDF file or a valid document_id.")


@router.post("/info")
async def pdf_info_endpoint(
    file: Optional[UploadFile] = File(None),
    doc_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Inspects PDF metadata, dimensions, security status, and page structure."""
    pdf_path = await _resolve_pdf_path(file, doc_id, db, current_user)
    info = get_pdf_info(pdf_path)
    if not info.get("valid", False):
        raise HTTPException(status_code=400, detail=info.get("error", "Unable to inspect PDF."))
    return info


@router.post("/merge")
async def merge_pdfs_endpoint(
    files: Optional[List[UploadFile]] = File(None),
    doc_ids: Optional[str] = Form(None),  # Comma-separated document IDs
    output_filename: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Combines multiple PDFs in the specified order into a single PDF."""
    pdf_paths = []
    
    # 1. From uploaded files
    if files:
        for f in files:
            if f.filename:
                tmp_path = await _save_upload_to_temp(f, allowed_exts={".pdf"})
                pdf_paths.append(tmp_path)

    # 2. From document IDs
    if doc_ids:
        for did in [d.strip() for d in doc_ids.split(",") if d.strip()]:
            res = await db.execute(select(DocumentModel).where(DocumentModel.id == did))
            doc = res.scalar_one_or_none()
            if doc:
                p = doc.pdf_path or doc.original_path
                if p and os.path.exists(p):
                    pdf_paths.append(p)

    if len(pdf_paths) < 2:
        raise HTTPException(status_code=400, detail="At least 2 PDF files are required to perform a merge.")

    user_id = current_user.id if current_user else None
    artifact = merge_pdfs(pdf_paths, output_filename=output_filename, user_id=user_id)
    return artifact


@router.post("/split")
async def split_pdf_endpoint(
    file: Optional[UploadFile] = File(None),
    doc_id: Optional[str] = Form(None),
    ranges: str = Form(...),  # e.g. "1-3, 4-6" or "1, 2-5"
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Splits a PDF into separate parts based on comma-separated page ranges."""
    pdf_path = await _resolve_pdf_path(file, doc_id, db, current_user)
    range_list = [r.strip() for r in ranges.split(",") if r.strip()]
    if not range_list:
        raise HTTPException(status_code=400, detail="Please provide valid page ranges (e.g. '1-3, 4-6').")

    user_id = current_user.id if current_user else None
    try:
        artifacts = split_pdf(pdf_path, ranges=range_list, user_id=user_id)
        return {"status": "success", "count": len(artifacts), "artifacts": artifacts}
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/extract-pages")
async def extract_pages_endpoint(
    file: Optional[UploadFile] = File(None),
    doc_id: Optional[str] = Form(None),
    page_spec: str = Form(...),  # e.g. "1, 3, 5-8"
    output_filename: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Extracts specified pages into a single new PDF."""
    pdf_path = await _resolve_pdf_path(file, doc_id, db, current_user)
    user_id = current_user.id if current_user else None
    try:
        artifact = extract_pages(pdf_path, page_spec=page_spec, output_filename=output_filename, user_id=user_id)
        return artifact
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/rotate")
async def rotate_pages_endpoint(
    file: Optional[UploadFile] = File(None),
    doc_id: Optional[str] = Form(None),
    angle: int = Form(...),  # 90, 180, 270
    page_spec: str = Form("all"),  # e.g. "1, 3" or "all"
    output_filename: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Rotates selected or all pages in a PDF by 90, 180, or 270 degrees clockwise."""
    if angle not in (90, 180, 270):
        raise HTTPException(status_code=400, detail="Angle must be 90, 180, or 270 degrees.")

    pdf_path = await _resolve_pdf_path(file, doc_id, db, current_user)
    user_id = current_user.id if current_user else None
    try:
        artifact = rotate_pages(pdf_path, angle=angle, page_spec=page_spec, output_filename=output_filename, user_id=user_id)
        return artifact
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/compress")
async def compress_pdf_endpoint(
    file: Optional[UploadFile] = File(None),
    doc_id: Optional[str] = Form(None),
    level: str = Form("medium"),  # light, medium, strong
    output_filename: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Optimizes PDF streams and compresses content with honest reduction reporting."""
    pdf_path = await _resolve_pdf_path(file, doc_id, db, current_user)
    user_id = current_user.id if current_user else None
    try:
        artifact = compress_pdf(pdf_path, level=level, output_filename=output_filename, user_id=user_id)
        return artifact
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/to-text")
async def convert_to_text_endpoint(
    file: Optional[UploadFile] = File(None),
    doc_id: Optional[str] = Form(None),
    format: str = Form("markdown"),  # "markdown" or "text"
    output_filename: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Extracts text while preserving reading order and page boundaries."""
    pdf_path = await _resolve_pdf_path(file, doc_id, db, current_user)
    user_id = current_user.id if current_user else None
    try:
        artifact = convert_pdf_to_text(pdf_path, format=format, output_filename=output_filename, user_id=user_id)
        return artifact
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/extract-tables")
async def extract_tables_endpoint(
    file: Optional[UploadFile] = File(None),
    doc_id: Optional[str] = Form(None),
    format: str = Form("xlsx"),  # "xlsx" or "csv"
    output_filename: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Extracts tables from the PDF into styled XLSX or CSV."""
    pdf_path = await _resolve_pdf_path(file, doc_id, db, current_user)
    user_id = current_user.id if current_user else None
    try:
        artifact = extract_pdf_tables(pdf_path, format=format, output_filename=output_filename, user_id=user_id)
        return artifact
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/watermark")
async def watermark_pdf_endpoint(
    file: Optional[UploadFile] = File(None),
    doc_id: Optional[str] = Form(None),
    text: str = Form("CONFIDENTIAL"),
    page_spec: str = Form("all"),
    opacity: float = Form(0.25),
    fontsize: int = Form(48),
    output_filename: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Imprints semi-transparent text watermark across specified pages."""
    pdf_path = await _resolve_pdf_path(file, doc_id, db, current_user)
    user_id = current_user.id if current_user else None
    try:
        artifact = add_watermark(
            pdf_path,
            text=text,
            page_spec=page_spec,
            opacity=opacity,
            fontsize=fontsize,
            output_filename=output_filename,
            user_id=user_id
        )
        return artifact
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/page-numbers")
async def page_numbers_endpoint(
    file: Optional[UploadFile] = File(None),
    doc_id: Optional[str] = Form(None),
    position: str = Form("bottom-center"),  # bottom-center, bottom-right, top-right
    format_str: str = Form("Page {page} of {total}"),
    output_filename: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Inserts running page numbers on every page."""
    pdf_path = await _resolve_pdf_path(file, doc_id, db, current_user)
    user_id = current_user.id if current_user else None
    try:
        artifact = add_page_numbers(
            pdf_path,
            position=position,
            format_str=format_str,
            output_filename=output_filename,
            user_id=user_id
        )
        return artifact
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/images-to-pdf")
async def images_to_pdf_endpoint(
    files: List[UploadFile] = File(...),
    output_filename: Optional[str] = Form(None),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Converts a collection of images (PNG, JPG, WEBP, BMP) into a single PDF."""
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one image file.")

    img_paths = []
    for f in files:
        if f.filename:
            tmp_path = await _save_upload_to_temp(f, allowed_exts=ALLOWED_IMAGE_EXTS)
            img_paths.append(tmp_path)

    if not img_paths:
        raise HTTPException(status_code=400, detail="No valid images uploaded.")

    user_id = current_user.id if current_user else None
    try:
        artifact = images_to_pdf(img_paths, output_filename=output_filename, user_id=user_id)
        return artifact
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))
