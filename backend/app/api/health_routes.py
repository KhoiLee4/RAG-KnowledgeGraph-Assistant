"""GET /health — kiểm tra ChromaDB và Neo4j."""

import logging
from typing import Any

from fastapi import APIRouter

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", summary="Kiểm tra trạng thái hệ thống")
async def health_check() -> dict[str, Any]:
    """Ping ChromaDB và Neo4j. Dùng cho monitoring / Docker healthcheck."""
    status: dict[str, Any] = {"status": "ok", "services": {}}

    try:
        from app.db.chroma_client import get_chroma_client
        chroma = get_chroma_client()
        info = chroma.get_collection_info(settings.CHROMA_DEFAULT_COLLECTION)
        status["services"]["chromadb"] = {
            "status": "ok",
            "collection": settings.CHROMA_DEFAULT_COLLECTION,
            "documents": info.get("count", 0),
        }
    except Exception as e:
        status["services"]["chromadb"] = {"status": "error", "detail": str(e)}
        status["status"] = "degraded"

    try:
        from app.db.neo4j_client import get_neo4j_client
        neo4j = get_neo4j_client()
        records = neo4j.run_cypher("MATCH (n:Document) RETURN count(n) AS count")
        status["services"]["neo4j"] = {
            "status": "ok",
            "documents_indexed": records[0]["count"] if records else 0,
        }
    except Exception as e:
        status["services"]["neo4j"] = {"status": "error", "detail": str(e)}
        status["status"] = "degraded"

    return status
