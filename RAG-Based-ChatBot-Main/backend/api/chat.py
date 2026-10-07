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
from backend.db.models import ConversationModel, MessageModel, DocumentModel
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

@router.post("")
async def chat_endpoint(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # 1. Get or create conversation
    conv_id = req.conversation_id
    if not conv_id:
        new_conv = ConversationModel(title=req.message[:35] + ("..." if len(req.message) > 35 else ""))
        db.add(new_conv)
        await db.commit()
        await db.refresh(new_conv)
        conv_id = new_conv.id
    else:
        result = await db.execute(select(ConversationModel).where(ConversationModel.id == conv_id))
        conv = result.scalar_one_or_none()
        if not conv:
            conv = ConversationModel(id=conv_id, title=req.message[:35] + ("..." if len(req.message) > 35 else ""))
            db.add(conv)
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
    # Format last 6 messages
    history_dicts = [{"role": m.role, "content": m.content} for m in all_msgs[:-1][-6:]]

    # 4. Check if ready documents exist
    doc_res = await db.execute(select(DocumentModel).where(DocumentModel.status == "ready"))
    ready_docs = doc_res.scalars().all()
    has_documents = len(ready_docs) > 0

    # 5. Route Query
    router_instance = query_router
    if req.router_mode and req.router_mode != settings.ROUTER_MODE:
        from backend.llm.router import QueryRouter
        router_instance = QueryRouter(mode=req.router_mode)

    route, badge = await router_instance.route_query(
        question=req.message,
        has_documents=has_documents,
        active_doc_ids=req.document_ids
    )

    # 6. Retrieve relevant chunks if route == "document"
    retrieved_chunks: List[Dict[str, Any]] = []
    queries = [req.message]

    if route == "document":
        # Multi-query transformation
        queries = await query_rewriter.transform_query(req.message, history_dicts)
        
        # Parallel retrieval, fusion, reranking
        retrieved_chunks = await retrieval_pipeline.retrieve(
            queries=queries,
            doc_ids=req.document_ids,
            top_k=req.top_k or settings.FINAL_TOP_K,
            score_threshold=req.score_threshold if req.score_threshold is not None else settings.SCORE_THRESHOLD,
            fusion_method=req.fusion_method or settings.FUSION_METHOD,
            alpha=req.alpha if req.alpha is not None else settings.FUSION_ALPHA
        )

    # 7. Asynchronous generator that streams SSE and saves final assistant message
    async def sse_event_stream():
        accumulated_text = []
        captured_citations = []

        async for sse_chunk in grounded_generator.stream_rag_response(
            question=req.message,
            route=route,
            router_badge=badge,
            retrieved_chunks=retrieved_chunks,
            queries=queries
        ):
            # Intercept events for DB storage
            lines = sse_chunk.strip().split("\n")
            event_type = ""
            for line in lines:
                if line.startswith("event:"):
                    event_type = line.replace("event:", "").strip()
                elif line.startswith("data:") and event_type == "token":
                    try:
                        d = json.loads(line.replace("data:", "").strip())
                        accumulated_text.append(d.get("content", ""))
                    except Exception:
                        pass
                elif line.startswith("data:") and event_type == "citations":
                    try:
                        d = json.loads(line.replace("data:", "").strip())
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
                        citations=captured_citations
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
