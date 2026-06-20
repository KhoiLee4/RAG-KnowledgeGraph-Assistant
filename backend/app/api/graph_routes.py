"""Knowledge Graph: stats, entities, rebuild."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.auth_deps import require_user, user_collection_name

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/graph/stats", summary="Thống kê Knowledge Graph của user")
async def get_graph_stats(request: Request) -> dict[str, Any]:
    """Tổng entity, phân loại entity, top entity."""
    user = require_user(request)
    try:
        from app.services.graph_service import GraphService
        return GraphService().get_graph_stats(owner_id=user["user_id"])
    except Exception as e:
        logger.error("GET /graph/stats lỗi: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi lấy graph stats: {e}")


@router.get("/graph/entities/{file_id}", summary="Entity của một tài liệu")
async def get_document_entities(
    request: Request,
    file_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Danh sách entity trích xuất từ tài liệu cụ thể."""
    user = require_user(request)
    try:
        from app.services.graph_service import GraphService
        return GraphService().get_entities_for_document(
            file_id=file_id,
            owner_id=user["user_id"],
            limit=limit,
        )
    except Exception as e:
        logger.error("GET /graph/entities/%s lỗi: %s", file_id, e)
        raise HTTPException(status_code=500, detail=f"Lỗi lấy entity: {e}")


@router.post("/graph/rebuild/{file_id}", summary="Rebuild entity graph cho một tài liệu")
async def rebuild_graph_for_document(request: Request, file_id: str) -> dict[str, Any]:
    """Xóa và build lại KG cho tài liệu đã index (khi bật GraphRAG sau khi index)."""
    user = require_user(request)
    try:
        from app.db.chroma_client import get_chroma_client
        from app.db.neo4j_client import get_neo4j_client
        from app.services.graph_service import GraphService

        neo4j = get_neo4j_client()
        doc = neo4j.get_document_metadata(file_id, owner_id=user["user_id"])
        if not doc:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy tài liệu '{file_id}'")

        chroma = get_chroma_client()
        col = user_collection_name(user["user_id"])
        chunk_count = doc.get("chunk_count", 0)
        chunk_ids = [f"{file_id}__chunk_{i}" for i in range(chunk_count)]

        if not chunk_ids:
            return {"status": "skipped", "message": "Tài liệu không có chunk nào."}

        chroma_results = chroma.get_by_ids(chunk_ids, collection_name=col)
        chunks = [
            {
                "id": r["id"],
                "text": r.get("document", ""),
                "chunk_index": r.get("metadata", {}).get("chunk_index", 0),
            }
            for r in chroma_results
            if r.get("document")
        ]

        if not chunks:
            return {"status": "skipped", "message": "Không tìm thấy dữ liệu chunk trong ChromaDB."}

        stats = GraphService().build_graph_from_chunks(
            chunks=chunks,
            file_id=file_id,
            owner_id=user["user_id"],
        )
        return {
            "status": "success",
            "file_id": file_id,
            "file_name": doc.get("file_name", ""),
            **stats,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("POST /graph/rebuild/%s lỗi: %s", file_id, e)
        raise HTTPException(status_code=500, detail=f"Lỗi rebuild graph: {e}")


@router.get("/graph/communities", summary="Danh sách Community của user")
async def list_communities(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Community nodes kèm summary (Louvain + Gemini)."""
    user = require_user(request)
    try:
        from app.services.community_service import get_community_service
        return get_community_service().list_communities(
            owner_id=user["user_id"],
            limit=limit,
        )
    except Exception as e:
        logger.error("GET /graph/communities lỗi: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi lấy communities: {e}")


@router.post("/graph/communities/rebuild", summary="Rebuild communities cho user")
async def rebuild_communities(request: Request) -> dict[str, Any]:
    """Chạy lại Louvain + summary trên toàn bộ entity graph của user."""
    user = require_user(request)
    try:
        from app.services.community_service import get_community_service
        stats = get_community_service().detect_and_summarize(owner_id=user["user_id"])
        return {"status": stats.get("status", "unknown"), **stats}
    except Exception as e:
        logger.error("POST /graph/communities/rebuild lỗi: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi rebuild communities: {e}")
