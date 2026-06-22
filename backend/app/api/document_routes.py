"""Documents và supported-types endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.deps import get_indexing_service
from app.core.auth_deps import require_user, user_collection_name
from app.core.config import (
    MAX_FILE_SIZE_BYTES,
    MIN_FILE_SIZE_BYTES,
    SKIP_MIME_TYPES,
    SUPPORTED_MIME_TYPES,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/supported-types", summary="Danh sách MIME type được hỗ trợ index")
async def get_supported_types() -> dict[str, Any]:
    """MIME type được index, loại bị bỏ qua và giới hạn kích thước file."""
    from app.services.drive_service import SUPPORTED_TYPE_LABELS

    supported = [
        {
            "mime_type": mime,
            "extension": ext,
            "label": SUPPORTED_TYPE_LABELS.get(mime, mime),
            "is_google_workspace": mime.startswith("application/vnd.google-apps."),
        }
        for mime, ext in SUPPORTED_MIME_TYPES.items()
    ]

    return {
        "supported": supported,
        "skip_mime_types": sorted(SKIP_MIME_TYPES),
        "size_limits": {
            "min_bytes": MIN_FILE_SIZE_BYTES,
            "max_bytes": MAX_FILE_SIZE_BYTES,
            "max_mb": MAX_FILE_SIZE_BYTES // 1_000_000,
        },
        "note": "Hỗ trợ PDF, Word (.docx, .doc), Excel (.xlsx, .xls), Google Docs/Sheets.",
    }


@router.get("/documents", summary="Liệt kê tài liệu đã index")
async def list_documents(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Danh sách tài liệu đã index của user đang đăng nhập."""
    user = require_user(request)
    try:
        from app.db.neo4j_client import get_neo4j_client
        neo4j = get_neo4j_client()
        return neo4j.list_documents(limit=limit, owner_id=user["user_id"])
    except Exception as e:
        logger.error("GET /documents lỗi: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi lấy danh sách tài liệu: {e}")


@router.get("/documents/{file_id}", summary="Chi tiết một tài liệu")
async def get_document(request: Request, file_id: str) -> dict[str, Any]:
    """Metadata chi tiết của tài liệu thuộc user."""
    user = require_user(request)
    try:
        from app.db.neo4j_client import get_neo4j_client
        neo4j = get_neo4j_client()
        doc = neo4j.get_document_metadata(file_id, owner_id=user["user_id"])
        if not doc:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy tài liệu '{file_id}'")
        return doc
    except HTTPException:
        raise
    except Exception as e:
        logger.error("GET /documents/%s lỗi: %s", file_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{file_id}", summary="Xóa tài liệu khỏi knowledge base")
async def delete_document(request: Request, file_id: str) -> dict[str, str]:
    """Xóa tài liệu khỏi ChromaDB và Neo4j."""
    user = require_user(request)
    try:
        from app.db.neo4j_client import get_neo4j_client
        neo4j = get_neo4j_client()
        doc = neo4j.get_document_metadata(file_id, owner_id=user["user_id"])
        if not doc:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy tài liệu '{file_id}'")

        svc = get_indexing_service()
        col = user_collection_name(user["user_id"])
        svc.delete_index(file_id, collection_name=col, owner_id=user["user_id"])
        return {
            "status": "success",
            "message": f"Đã xóa tài liệu '{file_id}' khỏi knowledge base.",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("DELETE /documents/%s lỗi: %s", file_id, e)
        raise HTTPException(status_code=500, detail=f"Lỗi xóa tài liệu: {e}")
