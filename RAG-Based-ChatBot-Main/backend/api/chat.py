import json
import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.db.session import get_db, AsyncSessionLocal
from backend.db.models import ConversationModel, MessageModel, DocumentModel, UserModel
from backend.api.auth import get_current_user_optional
from sqlalchemy import select, or_
from backend.llm.router import query_router
from backend.llm.rewriter import query_rewriter
from backend.retrieval.pipeline import retrieval_pipeline
from backend.llm.generator import grounded_generator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    document_ids: Optional[List[str]] = None
    top_k: Optional[int] = settings.FINAL_TOP_K
    score_threshold: Optional[float] = settings.SCORE_THRESHOLD
    fusion_method: Optional[str] = settings.FUSION_METHOD
    alpha: Optional[float] = settings.FUSION_ALPHA
    router_mode: Optional[str] = settings.ROUTER_MODE
    web_mode: Optional[bool] = False

@router.post("")
async def chat_endpoint(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    user_id = current_user.id if current_user else None

    from backend.llm.title_generator import generate_conversation_title
    from backend.llm.router import is_weather_request
    auto_title = generate_conversation_title(req.message)

    # 1. Get or create conversation with tenant ownership
    conv_id = req.conversation_id
    if not conv_id:
        new_conv = ConversationModel(
            title=auto_title if auto_title != "New Chat" else (req.message[:35] + ("..." if len(req.message) > 35 else "")),
            user_id=user_id
        )
        db.add(new_conv)
        await db.commit()
        await db.refresh(new_conv)
        conv_id = new_conv.id
    else:
        result = await db.execute(select(ConversationModel).where(ConversationModel.id == conv_id))
        conv = result.scalar_one_or_none()
        if not conv:
            conv = ConversationModel(
                id=conv_id,
                title=auto_title if auto_title != "New Chat" else (req.message[:35] + ("..." if len(req.message) > 35 else "")),
                user_id=user_id
            )
            db.add(conv)
            await db.commit()
        elif current_user and current_user.role != "admin" and conv.user_id and conv.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied: You do not own this conversation.")
        else:
            # Auto-update generic title on first meaningful user message
            if not conv.title or conv.title.strip() in ("New Chat", "Untitled") or conv.title.strip().startswith("New Chat"):
                if auto_title and auto_title != "New Chat":
                    conv.title = auto_title
                    await db.commit()

    # 2. Save user message to database
    user_msg = MessageModel(
        conversation_id=conv_id,
        role="user",
        content=req.message.strip()
    )
    db.add(user_msg)
    await db.commit()

    # 3. Fetch recent conversation history
    stmt = (
        select(MessageModel)
        .where(MessageModel.conversation_id == conv_id)
        .order_by(MessageModel.created_at.asc())
    )
    hist_result = await db.execute(stmt)
    all_msgs = hist_result.scalars().all()
    # Format last 6 messages with content and source citations
    history_dicts = [{"role": m.role, "content": m.content, "citations": m.citations} for m in all_msgs[:-1][-6:]]

    # 4. Check if ready documents exist
    effective_doc_ids = None
    if req.document_ids:
        doc_stmt = select(DocumentModel).where(
            DocumentModel.id.in_(req.document_ids),
            DocumentModel.status == "ready"
        )
        doc_res = await db.execute(doc_stmt)
        # If not ready, check if currently processing and wait briefly
        if not ready_docs:
            proc_stmt = select(DocumentModel).where(
                DocumentModel.id.in_(req.doc_ids),
                DocumentModel.status.in_(["queued", "converting", "parsing", "chunking", "embedding", "indexing", "processing"])
            )
            proc_res = await db.execute(proc_stmt)
            if proc_res.scalars().all():
                for _ in range(20):
                    await asyncio.sleep(0.5)
                    check_res = await db.execute(doc_stmt)
                    ready_docs = check_res.scalars().all()
                    if ready_docs:
                        break

        if not ready_docs:
            fb_stmt = select(DocumentModel).where(DocumentModel.status == "ready")
            fb_res = await db.execute(fb_stmt)
            ready_docs = fb_res.scalars().all()

        effective_doc_ids = [d.id for d in ready_docs]
        has_documents = len(effective_doc_ids) > 0
    else:
        doc_stmt = select(DocumentModel).where(DocumentModel.status == "ready")
        if current_user and current_user.role != "admin":
            user_ids = [current_user.id]
            if current_user.email:
                email_res = await db.execute(select(UserModel.id).where(UserModel.email == current_user.email))
                user_ids = list(email_res.scalars().all())
            doc_stmt = doc_stmt.where(
                or_(DocumentModel.user_id.in_(user_ids), DocumentModel.user_id.is_(None))
            )
        doc_res = await db.execute(doc_stmt)
        ready_docs = doc_res.scalars().all()
        if not ready_docs:
            all_res = await db.execute(select(DocumentModel).where(DocumentModel.status == "ready"))
            ready_docs = all_res.scalars().all()
        authorized_doc_ids = {d.id for d in ready_docs}
        has_documents = len(ready_docs) > 0
        effective_doc_ids = list(authorized_doc_ids) if has_documents else None

    # 4b. Propagate active document context for Excel/spreadsheet tools ONLY if spreadsheet files exist
    from backend.tools.excel_analyzer import active_excel_context
    excel_docs = [
        d for d in ready_docs
        if (effective_doc_ids is None or d.id in effective_doc_ids) and (
            getattr(d, "file_type", "").lower() in ("xlsx", "xls", "csv") or
            (getattr(d, "filename", "") and getattr(d, "filename", "").lower().endswith((".xlsx", ".xls", ".csv")))
        )
    ]
    if excel_docs:
        active_excel_context.set({
            "doc_ids": [d.id for d in excel_docs],
            "doc_id": excel_docs[0].id,
            "filename": excel_docs[0].filename,
            "conversation_id": conv_id,
            "has_spreadsheet": True,
        })
    else:
        active_excel_context.set(None)

    from backend.tools.searxng_search import active_web_citations
    from backend.tools.weather import active_weather_data
    from backend.tools.excel_generator import active_excel_artifact
    from backend.tools.document_generator import active_document_artifact
    from backend.tools.pdf_tools import active_pdf_artifact
    active_web_citations.set([])
    active_weather_data.set(None)
    active_excel_artifact.set(None)
    active_document_artifact.set(None)
    active_pdf_artifact.set(None)

    # 5. Route Query via centralized QueryRouter (ensures Excel generation takes priority in every mode)
    web_mode = bool(req.web_mode)
    router_instance = query_router
    if req.router_mode and req.router_mode != settings.ROUTER_MODE:
        from backend.llm.router import QueryRouter
        router_instance = QueryRouter(mode=req.router_mode)

    route, badge = await router_instance.route_query(
        question=req.message,
        has_documents=has_documents,
        active_doc_ids=effective_doc_ids,
        web_mode=web_mode
    )

    # 6. Retrieve relevant chunks if route == "document" or document-based Excel generation
    retrieved_chunks: List[Dict[str, Any]] = []
    queries = [req.message]

    from backend.llm.router import DOC_EXPLICIT_REGEX
    is_doc_excel = (route == "excel_generation" and has_documents and bool(DOC_EXPLICIT_REGEX.search(req.message)))
    is_doc_gen = (route == "document_generation")

    if route == "document" or is_doc_excel or (is_doc_gen and has_documents):
        # Multi-query transformation
        queries = await query_rewriter.transform_query(req.message, history_dicts)
        
        # Parallel retrieval, fusion, reranking
        retrieved_chunks = await retrieval_pipeline.retrieve(
            queries=queries,
            doc_ids=effective_doc_ids,
            top_k=req.top_k or settings.FINAL_TOP_K,
            score_threshold=req.score_threshold if req.score_threshold is not None else settings.SCORE_THRESHOLD,
            fusion_method=req.fusion_method or settings.FUSION_METHOD,
            alpha=req.alpha if req.alpha is not None else settings.FUSION_ALPHA
        )

    # 7. Asynchronous generator that streams SSE and saves final assistant message
    async def sse_event_stream():
        accumulated_text = []
        captured_citations = []
        captured_weather = None
        captured_excel_artifact = None
        captured_document_artifact = None
        captured_pdf_artifact = None

        async for sse_chunk in grounded_generator.stream_rag_response(
            question=req.message,
            route=route,
            router_badge=badge,
            retrieved_chunks=retrieved_chunks,
            queries=queries,
            web_mode=web_mode,
            history=history_dicts,
            user_id=user_id,
            conversation_id=conv_id,
        ):
            # Intercept events for DB storage
            chunk_str = sse_chunk.strip()
            if chunk_str:
                event_type = None
                payload_str = None
                if "\ndata:" in chunk_str:
                    p1, p2 = chunk_str.split("\ndata:", 1)
                    if p1.startswith("event:"):
                        event_type = p1[6:].strip()
                    payload_str = p2.strip()
                elif chunk_str.startswith("data:"):
                    event_type = "token"
                    payload_str = chunk_str[5:].strip()

                if event_type and payload_str:
                    try:
                        d = json.loads(payload_str)
                        if event_type == "token":
                            accumulated_text.append(d.get("content", ""))
                        elif event_type == "excel_artifact":
                            captured_excel_artifact = d
                        elif event_type == "document_artifact":
                            captured_document_artifact = d
                        elif event_type == "pdf_artifact":
                            captured_pdf_artifact = d
                        elif event_type == "weather":
                            captured_weather = d
                        elif event_type == "citations":
                            captured_citations = d.get("citations", [])
                    except Exception:
                        pass

            yield sse_chunk

        # Save assistant message in DB upon stream completion
        full_content = "".join(accumulated_text).strip()
        if full_content:
            try:
                async with AsyncSessionLocal() as save_session:
                    asst_msg = MessageModel(
                        conversation_id=conv_id,
                        role="assistant",
                        content=full_content,
                        router_badge=badge,
                        citations=captured_citations,
                        weather=captured_weather,
                        excel_artifact=captured_excel_artifact,
                        document_artifact=captured_document_artifact,
                        pdf_artifact=captured_pdf_artifact
                    )
                    save_session.add(asst_msg)
                    await save_session.commit()
            except Exception as e:
                logger.error(f"Failed to persist assistant message: {e}")

    return StreamingResponse(
        sse_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Conversation-Id": conv_id
        }
    )
