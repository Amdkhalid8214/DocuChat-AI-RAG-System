from backend.api.documents import router as documents_router
from backend.api.conversations import router as conversations_router
from backend.api.chat import router as chat_router
from backend.api.auth import router as auth_router, seed_default_users
from backend.api.websockets import router as websockets_router
from backend.api.tools import router as tools_router
from backend.api.pdf_tools import router as pdf_tools_router

__all__ = [
    "documents_router",
    "conversations_router",
    "chat_router",
    "auth_router",
    "websockets_router",
    "tools_router",
    "pdf_tools_router",
    "seed_default_users"
]

