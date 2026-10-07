"""
DocuChat Production RAG - Entry Point
This file maintains backward compatibility with the legacy app.py while executing
the modular production FastAPI application.
"""
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from backend.main import app
from backend.config import settings

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
