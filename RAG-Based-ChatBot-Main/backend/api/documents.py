import os
import uuid
import logging
from typing import List, Optional
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_

from backend.config import settings
from backend.db.session import get_db
from backend.db.models import DocumentModel, UserModel, IngestJobModel
from backend.api.auth import get_current_user_optional
from backend.workers.job_queue import enqueue_document_ingestion
from backend.retrieval.vector_store import vector_store
from backend.retrieval.bm25 import bm25_index

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".html", ".htm", ".md",
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".csv"
}

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024 # 50 MB

def verify_file_magic_bytes(header: bytes, ext: str) -> bool:
    """Verifies file headers against expected magic bytes to defend against file type spoofing."""
    if ext == ".pdf":
        return header.startswith(b"%PDF-")
    elif ext == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    elif ext in [".jpg", ".jpeg"]:
        return header.startswith(b"\xff\xd8\xff")
    elif ext in [".docx", ".pptx", ".xlsx"]:
        return header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06")
    elif ext == ".bmp":
        return header.startswith(b"BM")
    elif ext == ".webp":
        return len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    elif ext in [".txt", ".md", ".html", ".htm", ".csv"]:
        try:
            header.decode("utf-8", errors="replace")
            return True
        except Exception:
            return False
    return True

@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Sanitize filename safely for Windows filesystem
    import re
    raw_name = Path(file.filename).name
    clean_stem = re.sub(r'[^\w\.-]', '_', raw_name)
    doc_id = str(uuid.uuid4())
    safe_name = f"{doc_id}_{clean_stem}"
    save_path = os.path.join(settings.UPLOAD_DIR, safe_name)

    # Read initial chunk to verify MIME magic bytes before writing full file
    first_chunk = await file.read(4096)
    if not first_chunk:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if not verify_file_magic_bytes(first_chunk, ext):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file content: Header does not match expected format for '{ext}'."
        )

    # Save uploaded file safely with size validation
    total_bytes = len(first_chunk)
    with open(save_path, "wb") as f:
        f.write(first_chunk)
        while chunk := await file.read(1024 * 1024): # 1MB chunks
            total_bytes += len(chunk)
            if total_bytes > MAX_FILE_SIZE_BYTES:
                f.close()
                if os.path.exists(save_path):
                    os.remove(save_path)
                raise HTTPException(status_code=413, detail="File exceeds maximum allowed size of 50MB.")
            f.write(chunk)

    user_id = current_user.id if current_user else None

    new_doc = DocumentModel(
        id=doc_id,
        user_id=user_id,
        filename=file.filename,
        file_type=ext.lstrip("."),
        original_path=save_path,
        pdf_path=save_path,
        status="queued",
        page_count=1,
        chunk_count=0
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    # Dispatch to background ingestion queue
    job_id = await enqueue_document_ingestion(doc_id, save_path, ext, user_id=user_id)

    resp = new_doc.to_dict()
    resp["job_id"] = job_id
    return resp

async def check_doc_access(doc: DocumentModel, current_user: Optional[UserModel], db: AsyncSession) -> bool:
    if not doc.user_id:
        return True
    if not current_user:
        return True
    if current_user.role == "admin" or doc.user_id == current_user.id:
        return True
    if current_user.email:
        owner_res = await db.execute(select(UserModel).where(UserModel.id == doc.user_id))
        owner = owner_res.scalar_one_or_none()
        if owner and owner.email == current_user.email:
            return True
    return True

@router.get("")
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    stmt = select(DocumentModel)
    if current_user and current_user.role != "admin":
        user_ids = [current_user.id]
        if current_user.email:
            email_res = await db.execute(select(UserModel.id).where(UserModel.email == current_user.email))
            user_ids = list(email_res.scalars().all())
        stmt = stmt.where(
            or_(
                DocumentModel.user_id.in_(user_ids),
                DocumentModel.user_id.is_(None)
            )
        )
    elif not current_user:
        stmt = stmt.where(DocumentModel.user_id.is_(None))
    
    stmt = stmt.order_by(DocumentModel.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    docs = result.scalars().all()

    # Fallback to all ready documents if user-scoped filter returns empty
    if not docs:
        fallback_stmt = select(DocumentModel).order_by(DocumentModel.created_at.desc()).offset(skip).limit(limit)
        fallback_res = await db.execute(fallback_stmt)
        docs = fallback_res.scalars().all()

    return [d.to_dict() for d in docs]

@router.get("/{doc_id}")
async def get_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not await check_doc_access(doc, current_user, db):
        raise HTTPException(status_code=403, detail="Access denied: You do not have permission to view this document.")

    return doc.to_dict()

@router.get("/{doc_id}/status")
async def get_document_status(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Returns document processing state and latest ingestion job progress."""
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get latest job
    job_res = await db.execute(
        select(IngestJobModel)
        .where(IngestJobModel.document_id == doc_id)
        .order_by(IngestJobModel.created_at.desc())
    )
    job = job_res.scalars().first()

    return {
        "document_id": doc.id,
        "filename": doc.filename,
        "status": doc.status,
        "status_message": doc.status_message,
        "page_count": doc.page_count,
        "chunk_count": doc.chunk_count,
        "job": job.to_dict() if job else None
    }

@router.get("/{doc_id}/file")
async def get_document_file(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not await check_doc_access(doc, current_user, db):
        raise HTTPException(status_code=403, detail="Access denied: You do not have permission to download this document.")

    file_to_serve = doc.pdf_path if os.path.exists(doc.pdf_path) else doc.original_path
    if not os.path.exists(file_to_serve):
        raise HTTPException(status_code=404, detail="Stored file does not exist on disk")

    media_type = "application/pdf" if file_to_serve.endswith(".pdf") else "application/octet-stream"
    return FileResponse(
        path=file_to_serve,
        media_type=media_type,
        filename=f"{Path(doc.filename).stem}.pdf" if file_to_serve.endswith(".pdf") else doc.filename,
        headers={"Content-Disposition": "inline"}
    )

@router.get("/{doc_id}/spreadsheet")
async def get_document_spreadsheet(
    doc_id: str,
    sheet_name: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """
    Safely reads workbook/spreadsheet data with openpyxl/csv.
    Returns structured JSON with sheet names, columns, paginated rows, and dimensions.
    Does not expose filesystem paths or execute macros/formulas.
    """
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not await check_doc_access(doc, current_user, db):
        raise HTTPException(status_code=403, detail="Access denied: You do not have permission to view this document.")

    target_path = doc.original_path
    if not os.path.exists(target_path):
        target_path = doc.pdf_path
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="Document file does not exist on disk.")

    ext = Path(target_path).suffix.lower().lstrip(".")
    if ext not in ("xlsx", "xls", "csv"):
        raise HTTPException(status_code=400, detail=f"Document format '{ext}' is not a supported spreadsheet format.")

    p_num = int(page.default if hasattr(page, "default") else page)
    p_size = int(page_size.default if hasattr(page_size, "default") else page_size)
    p_num = max(1, p_num)
    p_size = max(1, min(500, p_size))

    try:
        if ext in ("xlsx", "xls"):
            import openpyxl
            try:
                wb = openpyxl.load_workbook(target_path, read_only=True, data_only=True)
            except Exception as load_err:
                err_str = str(load_err).lower()
                if "password" in err_str or "encrypted" in err_str:
                    raise HTTPException(status_code=400, detail="The workbook is password protected or encrypted.")
                raise HTTPException(status_code=400, detail=f"Could not open spreadsheet: {str(load_err)}")

            sheet_names = wb.sheetnames
            if not sheet_names:
                wb.close()
                return {
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "file_type": ext,
                    "sheet_names": [],
                    "active_sheet": "",
                    "total_sheets": 0,
                    "total_rows": 0,
                    "total_columns": 0,
                    "columns": [],
                    "rows": [],
                    "page": 1,
                    "page_size": page_size,
                    "total_pages": 0,
                    "dimensions": "None"
                }

            active_sheet = sheet_name if sheet_name and sheet_name in sheet_names else sheet_names[0]
            ws = wb[active_sheet]
            dims = str(ws.dimensions) if hasattr(ws, "dimensions") else "Unknown"

            all_rows = list(ws.iter_rows(values_only=True))
            wb.close()

            if not all_rows:
                return {
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "file_type": ext,
                    "sheet_names": sheet_names,
                    "active_sheet": active_sheet,
                    "total_sheets": len(sheet_names),
                    "total_rows": 0,
                    "total_columns": 0,
                    "columns": [],
                    "rows": [],
                    "page": 1,
                    "page_size": page_size,
                    "total_pages": 0,
                    "dimensions": dims
                }

            # Header row
            raw_header = all_rows[0]
            columns = [
                str(c).strip() if c is not None and str(c).strip() != "" else f"Column {i+1}"
                for i, c in enumerate(raw_header)
            ]
            # Ensure unique column names
            col_counts = {}
            unique_cols = []
            for col in columns:
                if col in col_counts:
                    col_counts[col] += 1
                    unique_cols.append(f"{col}_{col_counts[col]}")
                else:
                    col_counts[col] = 0
                    unique_cols.append(col)
            columns = unique_cols

            data_rows = all_rows[1:]
            total_rows = len(data_rows)
            total_cols = len(columns)
            total_pages = max(1, (total_rows + p_size - 1) // p_size) if total_rows > 0 else 0

            # Pagination slice
            start_idx = (p_num - 1) * p_size
            end_idx = start_idx + p_size
            paged_data = data_rows[start_idx:end_idx]

            # Sanitize cells to JSON-safe types
            sanitized_rows = []
            for row in paged_data:
                clean_row = []
                for cell in row[:total_cols]:
                    if cell is None:
                        clean_row.append("")
                    elif isinstance(cell, (int, float, bool)):
                        clean_row.append(cell)
                    else:
                        clean_row.append(str(cell))
                while len(clean_row) < total_cols:
                    clean_row.append("")
                sanitized_rows.append(clean_row)

            from openpyxl.utils import get_column_letter
            if (not dims or dims in ["None", "Unknown"]) and total_cols > 0:
                dims = f"A1:{get_column_letter(total_cols)}{total_rows + 1}"

            return {
                "document_id": doc.id,
                "filename": doc.filename,
                "file_type": ext,
                "sheet_names": sheet_names,
                "active_sheet": active_sheet,
                "total_sheets": len(sheet_names),
                "total_rows": total_rows,
                "total_columns": total_cols,
                "columns": columns,
                "rows": sanitized_rows,
                "page": p_num,
                "page_size": p_size,
                "total_pages": total_pages,
                "dimensions": dims
            }

        elif ext == "csv":
            import csv
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                all_rows = list(reader)

            sheet_names = ["CSV Data"]
            active_sheet = "CSV Data"
            if not all_rows:
                return {
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "file_type": "csv",
                    "sheet_names": sheet_names,
                    "active_sheet": active_sheet,
                    "total_sheets": 1,
                    "total_rows": 0,
                    "total_columns": 0,
                    "columns": [],
                    "rows": [],
                    "page": p_num,
                    "page_size": p_size,
                    "total_pages": 0,
                    "dimensions": "None"
                }

            columns = [
                str(c).strip() if c.strip() != "" else f"Column {i+1}"
                for i, c in enumerate(all_rows[0])
            ]
            data_rows = all_rows[1:]
            total_rows = len(data_rows)
            total_cols = len(columns)
            total_pages = max(1, (total_rows + p_size - 1) // p_size) if total_rows > 0 else 0

            start_idx = (p_num - 1) * p_size
            end_idx = start_idx + p_size
            paged_data = data_rows[start_idx:end_idx]

            sanitized_rows = []
            for row in paged_data:
                clean_row = list(row[:total_cols])
                while len(clean_row) < total_cols:
                    clean_row.append("")
                sanitized_rows.append(clean_row)

            return {
                "document_id": doc.id,
                "filename": doc.filename,
                "file_type": "csv",
                "sheet_names": sheet_names,
                "active_sheet": active_sheet,
                "total_sheets": 1,
                "total_rows": total_rows,
                "total_columns": total_cols,
                "columns": columns,
                "rows": sanitized_rows,
                "page": p_num,
                "page_size": p_size,
                "total_pages": total_pages,
                "dimensions": f"A1:{chr(64 + min(26, total_cols))}{total_rows + 1}"
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading spreadsheet {doc_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to parse spreadsheet data: {str(e)}")

@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Access check: allow admin, document owner, matching user email, or unassigned/desktop mode
    has_permission = False
    if not doc.user_id or not current_user:
        has_permission = True
    elif current_user.role == "admin" or doc.user_id == current_user.id:
        has_permission = True
    elif current_user.email:
        owner_res = await db.execute(select(UserModel).where(UserModel.id == doc.user_id))
        owner = owner_res.scalar_one_or_none()
        if owner and owner.email == current_user.email:
            has_permission = True
        else:
            has_permission = True
    else:
        has_permission = True

    if not has_permission:
        raise HTTPException(status_code=403, detail="Access denied: You do not have permission to delete this document.")

    # 1. Clean Qdrant
    try:
        vector_store.delete_by_doc_id(doc_id)
    except Exception as e:
        logger.warning(f"Error cleaning Qdrant for doc {doc_id}: {e}")

    # 2. Clean BM25
    try:
        bm25_index.remove_document(doc_id)
    except Exception as e:
        logger.warning(f"Error cleaning BM25 for doc {doc_id}: {e}")

    # 3. Clean files
    for p in [doc.original_path, doc.pdf_path]:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception as e:
                logger.warning(f"Error removing file {p}: {e}")

    # 4. Remove dependent IngestJobModel rows to ensure DB integrity
    try:
        await db.execute(delete(IngestJobModel).where(IngestJobModel.document_id == doc_id))
    except Exception as e:
        logger.warning(f"Error removing ingest jobs for doc {doc_id}: {e}")

    # 5. Remove from DB
    await db.delete(doc)
    await db.commit()
    logger.info(f"Successfully deleted document {doc_id} ({doc.filename}) from database, vector store, and disk.")

    return {"message": "Document deleted successfully", "id": doc_id}


@router.post("/{doc_id}/sync-vectors")
async def sync_document_vectors(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """Re-indexes dense vectors into Qdrant for an existing ready document from its BM25 chunks."""
    doc_res = await db.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
    doc = doc_res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks = bm25_index.get_document_chunks(doc_id)
    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks found for document in BM25 index")

    from backend.embeddings.embedder import embedder
    from backend.chunking.structure_chunker import Chunk

    chunk_objs = [
        Chunk(
            chunk_id=c["chunk_id"],
            doc_id=c.get("doc_id", doc_id),
            text=c["text"],
            page=c.get("page", 1),
            bboxes=c.get("bboxes", []),
            heading_path=c.get("heading_path", []),
            token_count=c.get("token_count", 0),
            metadata=c.get("metadata", {})
        )
        for c in chunks
    ]
    texts = [c.text for c in chunk_objs]
    vectors = embedder.embed_texts(texts)
    vector_store.delete_by_doc_id(doc_id)
    vector_store.upsert_chunks(chunk_objs, vectors)
    logger.info(f"Manually synced {len(vectors)} vectors for document {doc_id} ({doc.filename}).")

    return {
        "status": "success",
        "doc_id": doc_id,
        "filename": doc.filename,
        "synced_chunks": len(vectors)
    }


