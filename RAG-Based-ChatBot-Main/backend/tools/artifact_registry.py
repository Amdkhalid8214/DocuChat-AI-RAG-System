"""
DocuChat AI - Secure Excel & Document Artifact Registry
Manages generation contexts, artifact metadata, session isolation, and access control.
Guarantees that each generation produces a fresh, distinct artifact record and prevents
stale artifact reuse or cross-tenant leakage.
"""

import os
import time
import uuid
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

from backend.config import settings

logger = logging.getLogger("artifact_registry")


class ArtifactRecord(BaseModel):
    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generation_request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    file_path: str
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    dataset_type: str = "general"
    data_row_count: int = 0
    data_column_count: int = 0
    worksheet_count: int = 1
    worksheet_names: List[str] = Field(default_factory=list)
    file_size: int = 0
    mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    validation_status: str = "Created and validated"
    is_qa_test_data: bool = False
    download_url: str = ""
    created_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ArtifactRegistry:
    """
    Thread-safe registry of generated output artifacts.
    Prevents stale artifact reuse and enforces strict user/session ownership checks.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._artifacts: Dict[str, ArtifactRecord] = {}  # artifact_id -> record
        self._filename_map: Dict[str, str] = {}  # safe_filename -> artifact_id

    def register_artifact(
        self,
        filename: str,
        file_path: str,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        dataset_type: str = "general",
        data_row_count: int = 0,
        data_column_count: int = 0,
        worksheet_count: int = 1,
        worksheet_names: Optional[List[str]] = None,
        file_size: int = 0,
        validation_status: str = "Created and validated",
        is_qa_test_data: bool = False,
        artifact_id: Optional[str] = None,
        generation_request_id: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        mime_type: Optional[str] = None,
    ) -> ArtifactRecord:
        with self._lock:
            art_id = artifact_id or str(uuid.uuid4())
            gen_id = generation_request_id or str(uuid.uuid4())
            safe_filename = Path(filename).name

            if not mime_type:
                ext = safe_filename.lower().rsplit(".", 1)[-1] if "." in safe_filename else ""
                mime_map = {
                    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "pdf": "application/pdf",
                    "txt": "text/plain; charset=utf-8",
                    "md": "text/markdown; charset=utf-8",
                    "csv": "text/csv; charset=utf-8",
                }
                mime_type = mime_map.get(ext, "application/octet-stream")

            record = ArtifactRecord(
                artifact_id=art_id,
                generation_request_id=gen_id,
                filename=safe_filename,
                file_path=str(file_path),
                user_id=user_id,
                conversation_id=conversation_id,
                dataset_type=dataset_type,
                data_row_count=data_row_count,
                data_column_count=data_column_count,
                worksheet_count=worksheet_count,
                worksheet_names=worksheet_names or ["Sheet1"],
                file_size=file_size,
                mime_type=mime_type,
                validation_status=validation_status,
                is_qa_test_data=is_qa_test_data,
                download_url=f"/api/tools/download/{art_id}",
                metadata=extra_metadata or {},
            )

            self._artifacts[art_id] = record
            self._filename_map[safe_filename] = art_id
            logger.info(
                f"[ARTIFACT_REGISTRY] Registered artifact '{art_id}' ({safe_filename}) "
                f"for user '{user_id}', conv '{conversation_id}' with {data_row_count} rows, {data_column_count} cols."
            )
            return record

    def get_artifact(self, identifier: str) -> Optional[ArtifactRecord]:
        """
        Resolves artifact by either artifact_id or filename.
        """
        with self._lock:
            if identifier in self._artifacts:
                return self._artifacts[identifier]
            clean_name = Path(identifier).name
            if clean_name in self._filename_map:
                art_id = self._filename_map[clean_name]
                return self._artifacts.get(art_id)
            return None

    def validate_access(
        self,
        artifact: ArtifactRecord,
        user_id: Optional[str] = None,
        user_role: Optional[str] = None,
        conversation_id: Optional[str] = None
    ) -> bool:
        """
        Validates tenant and session access:
        - Admins have global access.
        - If artifact has a user_id, user_id must match.
        - If artifact has no user_id, it is conversation-scoped or public to the current session.
        """
        if user_role == "admin":
            return True

        if artifact.user_id:
            if not user_id or artifact.user_id != user_id:
                logger.warning(
                    f"[ARTIFACT_REGISTRY] Access denied: Artifact '{artifact.artifact_id}' "
                    f"belongs to user '{artifact.user_id}', request user is '{user_id}'."
                )
                return False

        if artifact.conversation_id and conversation_id:
            if artifact.conversation_id != conversation_id and not artifact.user_id:
                return False

        return True

    def clear(self):
        """For testing purposes."""
        with self._lock:
            self._artifacts.clear()
            self._filename_map.clear()


artifact_registry = ArtifactRegistry()
