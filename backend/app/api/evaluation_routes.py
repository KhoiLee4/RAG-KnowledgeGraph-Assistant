"""GET /evaluation/* — thống kê và hỗ trợ benchmark."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.core.auth_deps import require_user, user_collection_name

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/evaluation/indexing-stats", summary="Thống kê pipeline indexing (Lớp 1)")
async def get_indexing_stats(request: Request) -> dict[str, Any]:
    """Tổng hợp file, chunk, vector, graph nodes/relations."""
    user = require_user(request)
    try:
        from app.evaluation.indexing_stats import collect_indexing_stats

        return collect_indexing_stats(
            owner_id=user["user_id"],
            collection_name=user_collection_name(user["user_id"]),
        )
    except Exception as e:
        logger.error("GET /evaluation/indexing-stats lỗi: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
