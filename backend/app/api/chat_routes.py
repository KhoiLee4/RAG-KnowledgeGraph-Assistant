"""POST /chat — hỏi đáp RAG với streaming SSE."""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_chat_service
from app.api.schemas import ChatRequest
from app.core.auth_deps import require_user, user_collection_name
from app.core.gemini_retry import format_gemini_error, is_quota_error

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", summary="Hỏi đáp dựa trên knowledge base")
async def chat(req: ChatRequest, request: Request):
    """
    Nhận câu hỏi, retrieval + Gemini generation, trả answer + citations.
    - stream=false: JSON đầy đủ.
    - stream=true: Server-Sent Events (SSE).
    """
    user = require_user(request)
    svc = get_chat_service()
    col = req.collection_name or user_collection_name(user["user_id"])

    if req.stream:
        async def sse_generator():
            async for chunk in svc.chat_stream(
                question=req.question,
                collection_name=col,
                history=req.history or None,
                owner_id=user["user_id"],
                retrieval_mode=req.retrieval_mode,
            ):
                yield chunk

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        result = svc.chat(
            question=req.question,
            collection_name=col,
            history=req.history or None,
            owner_id=user["user_id"],
            retrieval_mode=req.retrieval_mode,
        )
        return {
            "answer": result["answer"],
            "citations": result["citations"],
            "sources_count": result["sources_count"],
        }
    except Exception as e:
        logger.error("POST /chat lỗi: %s", e)
        if is_quota_error(e):
            raise HTTPException(status_code=429, detail=format_gemini_error(e))
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý câu hỏi: {format_gemini_error(e)}")
