from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from backend.db.session import get_db
from backend.db.models import ConversationModel, MessageModel

router = APIRouter(prefix="/conversations", tags=["conversations"])

class CreateConversationRequest(BaseModel):
    title: Optional[str] = "New Chat"

class UpdateConversationRequest(BaseModel):
    title: str

@router.get("")
async def list_conversations(db: AsyncSession = Depends(get_db)):
    stmt = select(ConversationModel).order_by(desc(ConversationModel.updated_at))
    result = await db.execute(stmt)
    convs = result.scalars().all()
    return [c.to_dict() for c in convs]

@router.post("")
async def create_conversation(req: CreateConversationRequest, db: AsyncSession = Depends(get_db)):
    new_conv = ConversationModel(title=req.title or "New Chat")
    db.add(new_conv)
    await db.commit()
    await db.refresh(new_conv)
    return new_conv.to_dict()

@router.get("/{conv_id}")
async def get_conversation(conv_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(ConversationModel)
        .where(ConversationModel.id == conv_id)
        .options(selectinload(ConversationModel.messages))
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    data = conv.to_dict()
    data["messages"] = [m.to_dict() for m in conv.messages]
    return data

@router.patch("/{conv_id}")
async def update_conversation(conv_id: str, req: UpdateConversationRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ConversationModel).where(ConversationModel.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv.title = req.title.strip() or "Untitled"
    await db.commit()
    return conv.to_dict()

@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ConversationModel).where(ConversationModel.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.delete(conv)
    await db.commit()
    return {"message": "Conversation deleted", "id": conv_id}
