import os
import uuid
import logging
from typing import List
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from backend.config import settings
from backend.db.session import get_db, AsyncSessionLocal
from backend.db.models import DocumentModel
from backend.parsers.converter import convert_to_pdf
from backend.parsers.docling_parser import docling_parser
from backend.chunking.structure_chunker import structure_chunker
from backend.embeddings.embedder import embedder
from backend.retrieval.vector_store import vector_store
from backend.retrieval.bm25 import bm25_index

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".html", ".htm", ".md",
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".csv"
}

async def process_document_background(doc_id: str, file_path: str, ext: str):
    """
    Background worker: converts non-PDFs, runs Docling extraction,
    structure chunking, embeddings, Qdrant indexing, and BM25 building.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            return

        try:
            logger.info(f"Starting background processing for document: {doc.filename} (ID: {doc_id})")

            # 1. Convert to PDF if necessary
            pdf_path = convert_to_pdf(file_path, settings.CONVERTED_DIR)
            doc.pdf_path = pdf_path

            # Count pages if PDF
            page_count = 1
            if pdf_path.endswith(".pdf") and os.path.exists(pdf_path):
                try:
                    import fitz
                    pdf_doc = fitz.open(pdf_path)
                    page_count = len(pdf_doc)
                    pdf_doc.close()
                except Exception:
                    pass
            doc.page_count = page_count

            # 2. Parse elements with Docling / PyMuPDF fallback
            elements = docling_parser.parse_file(file_path, pdf_path=pdf_path)
            if not elements:
                raise ValueError("No text or structural elements could be extracted from document.")

            # 3. Structure-aware chunking
            chunks = structure_chunker.chunk_elements(elements, doc_id=doc_id)
            if not chunks:
                raise ValueError("Chunking produced 0 chunks.")

            # 4. Generate Embeddings
            chunk_texts = [c.text for c in chunks]
            vectors = embedder.embed_texts(chunk_texts)

            # 5. Upsert into Qdrant
            vector_store.upsert_chunks(chunks, vectors)

            # 6. Build and persist BM25 index
            bm25_index.add_document(doc_id, chunks)

            # Update document record
            doc.status = "ready"
            doc.chunk_count = len(chunks)
            doc.status_message = None
            await session.commit()
            logger.info(f"Document {doc.filename} processed successfully. ({len(chunks)} chunks, {page_count} pages)")

        except Exception as e:
            logger.error(f"Failed to process document {doc_id}: {e}", exc_info=True)
            doc.status = "failed"
            doc.status_message = str(e)
            await session.commit()

@router.post("")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    doc_id = str(uuid.uuid4())
    safe_name = f"{doc_id}_{Path(file.filename).name}"
    save_path = os.path.join(settings.UPLOAD_DIR, safe_name)

    # Save uploaded file
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    new_doc = DocumentModel(
        id=doc_id,
        filename=file.filename,
        file_type=ext.lstrip("."),
        original_path=save_path,
        pdf_path=save_path,
        status="processing",
        page_count=1,
        chunk_count=0
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    # Enqueue background task
    background_tasks.add_task(process_document_background, doc_id, save_path, ext)

    return new_doc.to_dict()

@router.get("")
async def list_documents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DocumentModel).order_by(DocumentModel.created_at.desc()))
    docs = result.scalars().all()
    return [d.to_dict() for d in docs]

@router.get("/{doc_id}")
async def get_document(doc_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc.to_dict()

@router.get("/{doc_id}/file")
async def get_document_file(doc_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

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

@router.delete("/{doc_id}")
async def delete_document(doc_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 1. Clean Qdrant
    vector_store.delete_by_doc_id(doc_id)

    # 2. Clean BM25
    bm25_index.remove_document(doc_id)

    # 3. Clean files
    for p in [doc.original_path, doc.pdf_path]:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    # 4. Remove from DB
    await db.delete(doc)
    await db.commit()

    return {"message": "Document deleted successfully", "id": doc_id}
