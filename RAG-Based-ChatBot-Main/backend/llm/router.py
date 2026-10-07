import re
import logging
from typing import Tuple, Optional, List
from backend.config import settings

logger = logging.getLogger(__name__)

GREETINGS_PATTERN = re.compile(
    r"^(hi|hello|hey|good\s+(morning|afternoon|evening)|howdy|sup|who\s+are\s+you|what\s+can\s+you\s+do|help|thanks|thank\s+you|bye|goodbye)[.?!]*$",
    re.IGNORECASE
)

class QueryRouter:
    def __init__(self, mode: str = settings.ROUTER_MODE):
        self.mode = mode

    async def route_query(
        self,
        question: str,
        has_documents: bool = True,
        active_doc_ids: Optional[List[str]] = None
    ) -> Tuple[str, str]:
        """
        Decides between 'document' question vs 'general' question.
        - When no documents are loaded/scoped: Always 'general' (ChatGPT real-world mode).
        - When documents ARE loaded/scoped:
            - Pure greetings -> 'general'
            - All other questions -> 'document' (prioritize document facts, citations, and highlight).
        """
        clean_q = question.strip()

        # Case 1: No documents uploaded or active -> pure ChatGPT mode
        if not has_documents or (active_doc_ids is not None and len(active_doc_ids) == 0):
            return "general", "General answer"

        # Case 2: Common conversational pleasantries/greetings
        if GREETINGS_PATTERN.match(clean_q):
            return "general", "General answer"

        # Case 3: Document is active -> Always route to document pipeline to answer from document!
        return "document", "From document"

query_router = QueryRouter()
