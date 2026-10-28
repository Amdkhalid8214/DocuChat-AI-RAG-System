"""
DocuChat AI - Tool Endpoints & Secure Output File Download
"""
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional
from backend.config import settings
from backend.tools.registry import TOOL_DEFINITIONS, execute_tool
from backend.tools.artifact_registry import artifact_registry
from backend.api.auth import get_current_user_optional
from backend.db.models import UserModel

router = APIRouter(prefix="/tools", tags=["tools"])

class ToolExecuteRequest(BaseModel):
    tool: str
    arguments: Dict[str, Any]

@router.get("")
async def list_available_tools():
    """Returns list of registered, safe tools with JSON schemas."""
    return {"tools": TOOL_DEFINITIONS}

@router.post("/execute")
async def execute_tool_endpoint(req: ToolExecuteRequest):
    """Executes a vetted tool safely."""
    result = await execute_tool(req.tool, req.arguments)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.get("/download/{filename}")
@router.get("/artifacts/{filename}/download")
@router.get("/artifacts/{filename}")
async def download_output_file(
    filename: str,
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
):
    """
    Secure file download endpoint:
    1. Looks up artifact in ArtifactRegistry by artifact_id or filename.
    2. Validates user/session ownership to prevent unauthorized cross-session access.
    3. Prevents path traversal and never exposes internal server paths.
    4. Serves correct MIME type and Content-Disposition headers.
    """
    # 1. Check ArtifactRegistry
    record = artifact_registry.get_artifact(filename)
    if record:
        user_id = current_user.id if isinstance(current_user, UserModel) else None
        user_role = current_user.role if isinstance(current_user, UserModel) else None

        if not artifact_registry.validate_access(record, user_id=user_id, user_role=user_role):
            raise HTTPException(status_code=403, detail="Forbidden: You do not have permission to access this generated artifact.")

        target_path = Path(record.file_path)
        safe_filename = record.filename
    else:
        # Fallback to direct filename in settings.OUTPUT_DIR (for backward compatibility)
        safe_filename = Path(filename).name
        target_path = Path(settings.OUTPUT_DIR) / safe_filename

    # Ensure path stays strictly within settings.OUTPUT_DIR
    resolved_target = target_path.resolve()
    resolved_output_dir = Path(settings.OUTPUT_DIR).resolve()

    if not str(resolved_target).startswith(str(resolved_output_dir)):
        raise HTTPException(status_code=403, detail="Forbidden: Path traversal detected.")

    if not resolved_target.exists():
        raise HTTPException(status_code=404, detail="Requested generated file not found.")

    ext = safe_filename.lower().rsplit(".", 1)[-1] if "." in safe_filename else ""
    mime_map = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "txt": "text/plain; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "csv": "text/csv; charset=utf-8",
    }
    media_type = mime_map.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(resolved_target),
        filename=safe_filename,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={safe_filename}"}
    )
