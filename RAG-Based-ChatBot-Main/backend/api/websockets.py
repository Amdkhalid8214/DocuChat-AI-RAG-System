"""
DocuChat AI - Production WebSocket Endpoints
Provides real-time, low-latency, bidirectional streaming for:
1. Interactive Chat (/ws/chat) with token streaming, citation highlights, and cancellation.
2. Document Ingestion (/ws/documents/{doc_id}/progress) with live step-by-step progress.
"""
import json
import uuid
import asyncio
import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy import select, or_

from backend.config import settings
from backend.db.session import AsyncSessionLocal
from backend.db.models import ConversationModel, MessageModel, DocumentModel, IngestJobModel, UserModel
from backend.api.auth import decode_jwt_token
from backend.llm.router import query_router
from backend.llm.rewriter import query_rewriter
from backend.retrieval.pipeline import retrieval_pipeline
from backend.llm.generator import grounded_generator
from backend.workers.ingest_worker import subscribe_progress, unsubscribe_progress

logger = logging.getLogger("ws_api")
router = APIRouter(tags=["websockets"])

@router.websocket("/ws/chat")
async def websocket_chat_endpoint(websocket: WebSocket, token: Optional[str] = Query(None)):
    """
    Production WebSocket chat streaming endpoint.
    Protocol Events:
      Server -> Client:
        - "start": { conversation_id, route, badge, request_id }
        - "token": { content, request_id }
        - "citations": { citations, request_id }
        - "complete": { conversation_id, total_tokens, request_id }
        - "error": { message, request_id }
    """
    await websocket.accept()
    logger.info("WebSocket chat connection established.")

    user_id = None
    if token:
        payload = decode_jwt_token(token)
        if payload:
            user_id = payload.get("sub")

    try:
        while True:
            # Receive client message
            raw_data = await websocket.receive_text()
            try:
                msg_payload = json.loads(raw_data)
            except Exception:
                try:
                    await websocket.send_json({"event": "error", "data": {"message": "Invalid JSON payload"}})
                except Exception:
                    break
                continue

            # Heartbeat ping handling
            if msg_payload.get("action") == "ping" or msg_payload.get("ping"):
                try:
                    await websocket.send_json({"event": "pong"})
                except Exception:
                    break
                continue

            message = msg_payload.get("message", "").strip()
            if not message:
                try:
                    await websocket.send_json({"event": "error", "data": {"message": "Message cannot be empty"}})
                except Exception:
                    break
                continue

            conversation_id = msg_payload.get("conversation_id")
            document_ids = msg_payload.get("document_ids")
            top_k = msg_payload.get("top_k", settings.FINAL_TOP_K)
            score_threshold = msg_payload.get("score_threshold", settings.SCORE_THRESHOLD)
            fusion_method = msg_payload.get("fusion_method", settings.FUSION_METHOD)
            alpha = msg_payload.get("alpha", settings.FUSION_ALPHA)
            request_id = msg_payload.get("request_id", str(uuid.uuid4()))

            from backend.llm.title_generator import generate_conversation_title
            from backend.llm.router import is_weather_request
            auto_title = generate_conversation_title(message)

            async with AsyncSessionLocal() as db:
                # 1. Get or create conversation with tenant ownership
                if not conversation_id:
                    new_conv = ConversationModel(
                        title=auto_title if auto_title != "New Chat" else (message[:35] + ("..." if len(message) > 35 else "")),
                        user_id=user_id
                    )
                    db.add(new_conv)
                    await db.commit()
                    await db.refresh(new_conv)
                    conversation_id = new_conv.id
                else:
                    conv_res = await db.execute(select(ConversationModel).where(ConversationModel.id == conversation_id))
                    conv = conv_res.scalar_one_or_none()
                    if not conv or (conv.user_id and user_id and conv.user_id != user_id):
                        new_conv = ConversationModel(
                            title=auto_title if auto_title != "New Chat" else (message[:35] + ("..." if len(message) > 35 else "")),
                            user_id=user_id
                        )
                        db.add(new_conv)
                        await db.commit()
                        await db.refresh(new_conv)
                        conversation_id = new_conv.id
                    else:
                        if not conv.user_id and user_id:
                            conv.user_id = user_id
                        # Auto-update generic title on first meaningful message
                        if not conv.title or conv.title.strip() in ("New Chat", "Untitled") or conv.title.strip().startswith("New Chat"):
                            if auto_title and auto_title != "New Chat":
                                conv.title = auto_title
                                await db.commit()
                                # Notify frontend immediately so sidebar updates without page refresh
                                await websocket.send_json({
                                    "event": "conversation_renamed",
                                    "data": {
                                        "conversation_id": conversation_id,
                                        "title": auto_title
                                    }
                                })

                # 2. Save user message
                user_msg = MessageModel(
                    conversation_id=conversation_id,
                    role="user",
                    content=message
                )
                db.add(user_msg)
                await db.commit()

                # 3. Retrieve recent history
                hist_res = await db.execute(
                    select(MessageModel)
                    .where(MessageModel.conversation_id == conversation_id)
                    .order_by(MessageModel.created_at.asc())
                )
                all_msgs = hist_res.scalars().all()
                history_dicts = [{"role": m.role, "content": m.content, "citations": m.citations} for m in all_msgs[:-1][-6:]]

                # 4. Check ready documents
                effective_doc_ids = None
                if document_ids:
                    # Explicit document scope requested from client (e.g. open activeDoc)
                    doc_stmt = select(DocumentModel).where(
                        DocumentModel.id.in_(document_ids),
                        DocumentModel.status == "ready"
                    )
                    doc_res = await db.execute(doc_stmt)
                    ready_docs = doc_res.scalars().all()

                    # If not ready, check if currently processing and wait briefly
                    if not ready_docs:
                        proc_stmt = select(DocumentModel).where(
                            DocumentModel.id.in_(document_ids),
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

                    # Fallback to any ready document if specified doc was not ready
                    if not ready_docs:
                        fb_stmt = select(DocumentModel).where(DocumentModel.status == "ready")
                        fb_res = await db.execute(fb_stmt)
                        ready_docs = fb_res.scalars().all()

                    effective_doc_ids = [d.id for d in ready_docs]
                    has_documents = len(effective_doc_ids) > 0
                else:
                    # Discover ready documents for current user or unassigned/shared
                    doc_stmt = select(DocumentModel).where(DocumentModel.status == "ready")
                    if user_id:
                        u_res = await db.execute(select(UserModel).where(UserModel.id == user_id))
                        user_obj = u_res.scalar_one_or_none()
                        user_ids = [user_id]
                        if user_obj and user_obj.email:
                            same_e_res = await db.execute(select(UserModel.id).where(UserModel.email == user_obj.email))
                            user_ids = list(same_e_res.scalars().all())
                        doc_stmt = doc_stmt.where(
                            or_(DocumentModel.user_id.in_(user_ids), DocumentModel.user_id.is_(None))
                        )
                    doc_res = await db.execute(doc_stmt)
                    ready_docs = doc_res.scalars().all()

                    # Fallback to any ready document in system if user list is empty
                    if not ready_docs:
                        all_ready_res = await db.execute(select(DocumentModel).where(DocumentModel.status == "ready"))
                        ready_docs = all_ready_res.scalars().all()

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
                    "conversation_id": conversation_id,
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

            # 5. Route query (prioritizes Live Weather, supports explicit Real-Web Mode)
            web_mode = bool(msg_payload.get("web_mode", False))
            route, badge = await query_router.route_query(
                question=message,
                has_documents=has_documents,
                active_doc_ids=effective_doc_ids,
                web_mode=web_mode
            )

            # Send 'start' event
            await websocket.send_json({
                "event": "start",
                "request_id": request_id,
                "data": {
                    "conversation_id": conversation_id,
                    "route": route,
                    "router_badge": badge
                }
            })

            # 6. Multi-query rewriting & Hybrid retrieval
            retrieved_chunks = []
            queries = [message]
            from backend.llm.router import DOC_EXPLICIT_REGEX
            is_doc_excel = (route == "excel_generation" and has_documents and bool(DOC_EXPLICIT_REGEX.search(message)))
            is_doc_gen = (route == "document_generation")
            if route == "document" or is_doc_excel or (is_doc_gen and has_documents):
                queries = await query_rewriter.transform_query(message, history_dicts)
                retrieved_chunks = await retrieval_pipeline.retrieve(
                    queries=queries,
                    doc_ids=effective_doc_ids,
                    top_k=top_k,
                    score_threshold=score_threshold,
                    fusion_method=fusion_method,
                    alpha=alpha
                )

            # Map document filename to chunks for clean, user-friendly citation bars
            if retrieved_chunks and ready_docs:
                doc_filename_map = {d.id: d.filename for d in ready_docs}
                for c in retrieved_chunks:
                    if not c.get("filename"):
                        c["filename"] = doc_filename_map.get(c.get("doc_id"), "")

            # 7. Incremental token streaming
            accumulated_tokens = []
            captured_citations = []
            captured_weather = None
            captured_excel_artifact = None
            captured_document_artifact = None
            captured_pdf_artifact = None
            client_disconnected = False

            try:
                async for sse_chunk in grounded_generator.stream_rag_response(
                    question=message,
                    route=route,
                    router_badge=badge,
                    retrieved_chunks=retrieved_chunks,
                    queries=queries,
                    web_mode=web_mode,
                    history=history_dicts,
                    user_id=user_id,
                    conversation_id=conversation_id,
                ):
                    # Parse internal SSE chunks into structured WebSocket messages
                    chunk_str = sse_chunk.strip()
                    if not chunk_str:
                        continue
                    evt_type = None
                    payload_str = None
                    if "\ndata:" in chunk_str:
                        p1, p2 = chunk_str.split("\ndata:", 1)
                        if p1.startswith("event:"):
                            evt_type = p1[6:].strip()
                        payload_str = p2.strip()
                    elif chunk_str.startswith("data:"):
                        evt_type = "token"
                        payload_str = chunk_str[5:].strip()

                    if evt_type and payload_str:
                        try:
                            d = json.loads(payload_str)
                            if evt_type == "token":
                                token_content = d.get("content", "")
                                accumulated_tokens.append(token_content)
                                await websocket.send_json({
                                    "event": "token",
                                    "request_id": request_id,
                                    "data": {"content": token_content}
                                })
                            elif evt_type == "excel_artifact":
                                captured_excel_artifact = d
                                await websocket.send_json({
                                    "event": "excel_artifact",
                                    "request_id": request_id,
                                    "data": captured_excel_artifact
                                })
                            elif evt_type == "document_artifact":
                                captured_document_artifact = d
                                await websocket.send_json({
                                    "event": "document_artifact",
                                    "request_id": request_id,
                                    "data": captured_document_artifact
                                })
                            elif evt_type == "pdf_artifact":
                                captured_pdf_artifact = d
                                await websocket.send_json({
                                    "event": "pdf_artifact",
                                    "request_id": request_id,
                                    "data": captured_pdf_artifact
                                })
                            elif evt_type == "weather":
                                captured_weather = d
                                await websocket.send_json({
                                    "event": "weather",
                                    "request_id": request_id,
                                    "data": captured_weather
                                })
                            elif evt_type == "citations":
                                captured_citations = d.get("citations", [])
                                await websocket.send_json({
                                    "event": "citations",
                                    "request_id": request_id,
                                    "data": {"citations": captured_citations}
                                })
                        except (RuntimeError, WebSocketDisconnect):
                            logger.info("[WS Chat] Client disconnected during token stream.")
                            client_disconnected = True
                            break
                        except Exception as ex:
                            logger.error(f"[WS Chat] Error parsing SSE payload for '{evt_type}': {ex}")

                # 8. Persist completed assistant message
                full_reply = "".join(accumulated_tokens).strip()
                if full_reply:
                    async with AsyncSessionLocal() as save_db:
                        asst_msg = MessageModel(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=full_reply,
                            router_badge=badge,
                            citations=captured_citations,
                            weather=captured_weather,
                            excel_artifact=captured_excel_artifact,
                            document_artifact=captured_document_artifact,
                            pdf_artifact=captured_pdf_artifact
                        )
                        save_db.add(asst_msg)
                        await save_db.commit()

                if client_disconnected:
                    logger.info("[WS Chat] Cleanly exiting connection loop after client disconnect.")
                    break

                # Send 'complete' event
                try:
                    await websocket.send_json({
                        "event": "complete",
                        "request_id": request_id,
                        "data": {
                            "conversation_id": conversation_id,
                            "token_count": len(accumulated_tokens)
                        }
                    })
                except (RuntimeError, WebSocketDisconnect):
                    logger.info("[WS Chat] Client disconnected before complete event could be delivered.")
                    break

            except (WebSocketDisconnect, asyncio.CancelledError):
                logger.info("WebSocket chat connection disconnected or cancelled.")
                break
            except Exception as stream_err:
                logger.error(f"Error during response generation: {stream_err}", exc_info=True)
                if not client_disconnected:
                    try:
                        await websocket.send_json({
                            "event": "error",
                            "request_id": request_id,
                            "data": {"message": f"Generation error: {str(stream_err)}"}
                        })
                    except Exception:
                        break
                else:
                    break

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected normally.")
    except Exception as e:
        logger.error(f"WebSocket unhandled exception: {e}", exc_info=True)


@router.websocket("/ws/documents/{doc_id}/progress")
async def websocket_document_progress_endpoint(websocket: WebSocket, doc_id: str):
    """
    Subscribes to live ingestion job progress for a specific document.
    Streams real-time updates as the document transitions from parsing to ready/failed.
    """
    await websocket.accept()
    logger.info(f"WebSocket progress connection opened for document {doc_id}")

    # Send current document/job status immediately upon connect
    async with AsyncSessionLocal() as db:
        doc_res = await db.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        doc = doc_res.scalar_one_or_none()
        if doc:
            job_res = await db.execute(
                select(IngestJobModel)
                .where(IngestJobModel.document_id == doc_id)
                .order_by(IngestJobModel.created_at.desc())
            )
            job = job_res.scalars().first()
            await websocket.send_json({
                "document_id": doc.id,
                "status": doc.status,
                "progress": job.progress if job else (100 if doc.status == "ready" else 0),
                "message": job.message if job else doc.status_message or doc.status
            })

    # Queue for updates received from worker broadcast (in-memory + Redis pub/sub)
    queue = asyncio.Queue()

    def on_progress_event(event_dict):
        queue.put_nowait(event_dict)

    subscribe_progress(doc_id, on_progress_event)

    # Redis pub/sub listener task
    redis_task = None
    try:
        import redis.asyncio as aioredis
        async def _redis_subscriber():
            try:
                r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                pubsub = r.pubsub()
                await pubsub.subscribe(f"ingest_progress:{doc_id}")
                async for msg in pubsub.listen():
                    if msg.get("type") == "message":
                        try:
                            payload = json.loads(msg.get("data", "{}"))
                            queue.put_nowait(payload)
                        except Exception:
                            pass
            except asyncio.CancelledError:
                pass
            except Exception as re:
                logger.debug(f"Redis progress sub exception: {re}")
        redis_task = asyncio.create_task(_redis_subscriber())
    except Exception:
        pass

    try:
        while True:
            # Wait for event from queue or timeout heartbeat
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25.0)
                await websocket.send_json(event)
                # If finished, exit gracefully
                if event.get("status") in ("ready", "failed"):
                    break
            except asyncio.TimeoutError:
                # Send ping/heartbeat
                await websocket.send_json({"ping": True})
    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected from doc progress {doc_id}")
    finally:
        unsubscribe_progress(doc_id, on_progress_event)
        if redis_task:
            redis_task.cancel()
