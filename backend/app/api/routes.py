"""
routes.py — FastAPI Router định nghĩa tất cả API endpoints.

Endpoints:
  POST /chat              — Hỏi đáp RAG
  GET  /drive/status      — Trạng thái đăng nhập Google Drive
  POST /drive/login       — Đăng nhập Google (mở browser)
  POST /drive/sync-all    — Đồng bộ TOÀN BỘ file được hỗ trợ trên Drive
  GET  /drive/files       — Xem trước danh sách file trên Drive
  POST /sync-drive        — Đồng bộ theo file ID / folder (trả về summary chi tiết)
  GET  /supported-types   — Danh sách MIME type được hỗ trợ index
  GET  /documents         — Tài liệu đã index
  GET  /health            — Health check
"""

import dataclasses
import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import (
    MAX_FILE_SIZE_BYTES,
    MIN_FILE_SIZE_BYTES,
    SKIP_MIME_TYPES,
    SUPPORTED_MIME_TYPES,
    settings,
)
from app.core.gemini_retry import format_gemini_error, is_quota_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["RAG Knowledge Base"])

# ── Lazy init service singletons ─────────────────────────────
# (khởi tạo khi gọi lần đầu, không block import)

_chat_svc = None
_indexing_svc = None


def _get_chat():
    global _chat_svc
    if _chat_svc is None:
        from app.services.chat_service import ChatService
        _chat_svc = ChatService()
    return _chat_svc


def _get_indexing():
    global _indexing_svc
    if _indexing_svc is None:
        from app.services.indexing_service import IndexingService
        _indexing_svc = IndexingService()
    return _indexing_svc


# ══════════════════════════════════════════════════════════════
# Request / Response Schemas
# ══════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    """Request body cho POST /chat."""
    question: str = Field(..., min_length=1, max_length=2000, description="Câu hỏi")
    collection_name: str = Field(
        default="", description="ChromaDB collection (để trống = dùng mặc định)"
    )
    history: list[dict[str, str]] = Field(
        default=[],
        description="Lịch sử hội thoại: [{role: 'user'/'model', content: '...'}]",
    )
    stream: bool = Field(default=False, description="True = streaming SSE response")


class ChatResponse(BaseModel):
    """Response body cho POST /chat (non-streaming)."""
    answer: str
    citations: list[dict[str, str]]
    sources_count: int


class SyncDriveRequest(BaseModel):
    """Request body cho POST /sync-drive."""
    file_ids: list[str] = Field(
        default=[],
        description="Danh sách Drive file ID cần index. Rỗng = liệt kê từ Drive.",
    )
    folder_id: str | None = Field(
        default=None,
        description="ID folder Google Drive cần quét (áp dụng khi file_ids rỗng).",
    )
    collection_name: str = Field(
        default="",
        description="ChromaDB collection (để trống = dùng mặc định)",
    )
    force_reindex: bool = Field(
        default=False,
        description="True = index lại dù đã tồn tại",
    )


class SyncDriveResponse(BaseModel):
    """Response body sau POST /sync-drive và POST /drive/sync-all."""
    total_found: int = 0            # Tổng số file tìm được trên Drive (sau filter)
    indexed: int = 0                # Số file index thành công
    skipped: int = 0                # Số file bị bỏ qua (đã index / mime không hỗ trợ)
    errors: int = 0                 # Số file gặp lỗi khi xử lý
    account_email: str | None = None
    details: list[dict[str, Any]] = []  # Chi tiết từng file (IndexResult dạng dict)


def _summarize_sync_results(
    results: list,
    files_found: int = 0,
    account_email: str | None = None,
) -> SyncDriveResponse:
    """
    Tổng hợp danh sách IndexResult thành SyncDriveResponse.

    Chấp nhận cả list[IndexResult] (dataclass) lẫn list[dict] để tương thích
    với các code path khác nhau.
    """
    def _get_status(r: Any) -> str:
        """Lấy trường status từ IndexResult hoặc dict."""
        if dataclasses.is_dataclass(r):
            return r.status  # type: ignore[attr-defined]
        return r.get("status", "")

    def _to_dict(r: Any) -> dict[str, Any]:
        """Chuyển IndexResult → dict để serialize JSON."""
        if dataclasses.is_dataclass(r):
            return dataclasses.asdict(r)
        return r

    details = [_to_dict(r) for r in results]

    return SyncDriveResponse(
        total_found=files_found if files_found > 0 else len(results),
        indexed=sum(1 for r in results if _get_status(r) == "success"),
        skipped=sum(1 for r in results if _get_status(r) == "skipped"),
        errors=sum(
            1 for r in results if _get_status(r) in ("error", "failed")
        ),
        account_email=account_email,
        details=details,
    )


def _perform_drive_sync_all(
    force_reindex: bool = False,
    folder_id: str | None = None,
    on_progress: Any = None,
) -> SyncDriveResponse:
    """Quét Drive và index toàn bộ file được hỗ trợ."""
    from app.services.drive_service import DriveService

    svc_index = _get_indexing()
    col = settings.CHROMA_DEFAULT_COLLECTION

    drive = DriveService()
    auth = drive.authenticate()

    files = drive.list_all_supported_files(folder_id=folder_id)
    if not files:
        return SyncDriveResponse(
            total_found=0,
            indexed=0,
            skipped=0,
            errors=0,
            account_email=auth.get("email"),
            details=[],
        )

    file_ids = [f["id"] for f in files]
    logger.info(
        "sync-all: %d file từ Drive (%s)",
        len(file_ids),
        auth.get("email", "?"),
    )

    def _progress(done: int, total: int) -> None:
        if on_progress:
            on_progress(done, total)

    results = svc_index.index_drive(
        file_ids=file_ids,
        collection_name=col,
        force_reindex=force_reindex,
        on_progress=_progress,
    )

    return _summarize_sync_results(
        results,
        files_found=len(files),
        account_email=auth.get("email"),
    )


def _run_drive_sync_all_job(
    job_id: str,
    force_reindex: bool,
    folder_id: str | None,
) -> None:
    """Chạy đồng bộ Drive trong background thread."""
    from app.services.sync_job_store import get_sync_job_store

    store = get_sync_job_store()
    try:
        store.update(
            job_id,
            status="running",
            message="Đang quét Google Drive...",
        )

        def on_progress(done: int, total: int) -> None:
            store.update(
                job_id,
                processed=done,
                total=total,
                message=f"Đang index file {done}/{total}...",
            )

        result = _perform_drive_sync_all(
            force_reindex=force_reindex,
            folder_id=folder_id,
            on_progress=on_progress,
        )
        store.update(
            job_id,
            status="completed",
            message="Hoàn tất đồng bộ.",
            result=result.model_dump(),
        )
    except Exception as e:
        logger.error("sync job %s lỗi: %s", job_id, e, exc_info=True)
        store.update(
            job_id,
            status="failed",
            message="Đồng bộ thất bại.",
            error=str(e),
        )


# ══════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════

# ── Health check ──────────────────────────────────────────────

@router.get("/health", summary="Kiểm tra trạng thái hệ thống")
async def health_check() -> dict[str, Any]:
    """
    Ping ChromaDB và Neo4j để kiểm tra hệ thống hoạt động.
    Dùng cho load balancer / monitoring / Docker healthcheck.
    """
    status: dict[str, Any] = {"status": "ok", "services": {}}

    # Kiểm tra ChromaDB
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

    # Kiểm tra Neo4j
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


# ── Chat endpoint ─────────────────────────────────────────────

@router.post("/chat", summary="Hỏi đáp dựa trên knowledge base")
async def chat(req: ChatRequest):
    """
    Nhận câu hỏi, thực hiện retrieval + Gemini generation, trả về answer + citations.

    - **stream=false** (mặc định): Trả về JSON đầy đủ.
    - **stream=true**: Trả về Server-Sent Events (SSE) stream.
    """
    svc = _get_chat()
    col = req.collection_name or settings.CHROMA_DEFAULT_COLLECTION

    # ── Streaming mode ────────────────────────────────────────
    if req.stream:
        async def sse_generator():
            async for chunk in svc.chat_stream(
                question=req.question,
                collection_name=col,
                history=req.history or None,
            ):
                yield chunk

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Synchronous mode ──────────────────────────────────────
    try:
        result = svc.chat(
            question=req.question,
            collection_name=col,
            history=req.history or None,
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


# ── Google Drive: đăng nhập + đồng bộ toàn bộ ─────────────────

@router.get("/drive/status", summary="Trạng thái đăng nhập Google Drive")
async def drive_status() -> dict[str, Any]:
    """
    Kiểm tra đã có credentials.json / token.pickle và token còn hợp lệ không.
    Không mở trình duyệt.
    """
    try:
        from app.services.drive_service import DriveService
        return DriveService.get_auth_status()
    except Exception as e:
        logger.error("GET /drive/status lỗi: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drive/login", summary="Đăng nhập Google Drive (OAuth2)")
async def drive_login() -> dict[str, Any]:
    """
    Đăng nhập Google Drive qua OAuth2.

    Lần đầu hoặc token hết hạn: **mở trình duyệt trên máy chạy backend**
    để chọn tài khoản Google và cấp quyền đọc Drive (readonly).

    Sau khi thành công, lưu token.pickle — các lần sau không cần đăng nhập lại.
    """
    try:
        from app.services.drive_service import DriveService
        svc = DriveService(auto_authenticate=False)
        return svc.authenticate()
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("POST /drive/login lỗi: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi đăng nhập Drive: {e}")


@router.get("/drive/files", summary="Xem trước file được hỗ trợ trên Drive")
async def drive_list_files(
    folder_id: str | None = Query(default=None, description="Lọc theo folder ID"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """
    Liệt kê file trên Drive (chỉ các loại được hỗ trợ index).
    Cần đã đăng nhập (POST /drive/login) trước.
    """
    try:
        from app.services.drive_service import DriveService, SUPPORTED_TYPE_LABELS

        svc = DriveService()
        files = svc.list_all_supported_files(folder_id=folder_id)
        preview = [
            {
                "id": f["id"],
                "name": f["name"],
                "mimeType": f.get("mimeType"),
                "type_label": SUPPORTED_TYPE_LABELS.get(f.get("mimeType", ""), "File"),
                "modifiedTime": f.get("modifiedTime"),
                "webViewLink": f.get("webViewLink"),
            }
            for f in files[:limit]
        ]
        status = DriveService.get_auth_status()
        return {
            "total": len(files),
            "showing": len(preview),
            "account_email": status.get("email"),
            "files": preview,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("GET /drive/files lỗi: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drive/sync-all", summary="Đăng nhập (nếu cần) + index TOÀN BỘ file Drive được hỗ trợ")
async def drive_sync_all(
    force_reindex: bool = Query(default=False, description="Index lại dù đã có"),
    folder_id: str | None = Query(default=None, description="Chỉ quét folder này"),
) -> SyncDriveResponse:
    """
  Luồng chính: **Đăng nhập Google → quét Drive → tải & index mọi file được hỗ trợ**.

  Hỗ trợ: PDF, DOCX, XLSX, TXT, CSV, ảnh (OCR), Google Docs/Sheets/Slides.

  Có thể mất vài phút tùy số lượng file (embedding qua Gemini API).
    """
    try:
        return _perform_drive_sync_all(
            force_reindex=force_reindex,
            folder_id=folder_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("POST /drive/sync-all lỗi: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi đồng bộ Drive: {e}")


@router.post(
    "/drive/sync-all/async",
    summary="Bắt đầu đồng bộ Drive nền (không timeout HTTP)",
)
async def drive_sync_all_async(
    background_tasks: BackgroundTasks,
    force_reindex: bool = Query(default=False, description="Index lại dù đã có"),
    folder_id: str | None = Query(default=None, description="Chỉ quét folder này"),
) -> dict[str, str]:
    """
    Trả về ngay job_id; client poll GET /drive/sync-all/jobs/{job_id}.
    Dùng cho đồng bộ nhiều file (có thể > 10 phút).
    """
    from app.services.sync_job_store import get_sync_job_store

    job_id = str(uuid.uuid4())
    get_sync_job_store().create(job_id)
    background_tasks.add_task(
        _run_drive_sync_all_job,
        job_id,
        force_reindex,
        folder_id,
    )
    return {"job_id": job_id, "status": "pending"}


@router.get(
    "/drive/sync-all/jobs/{job_id}",
    summary="Trạng thái job đồng bộ Drive",
)
async def drive_sync_all_job_status(job_id: str) -> dict[str, Any]:
    from app.services.sync_job_store import get_sync_job_store

    job = get_sync_job_store().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại hoặc đã hết hạn.")
    return job


# ── Sync Drive endpoint (tùy chọn file ID / folder) ─────────────

@router.post("/sync-drive", summary="Đồng bộ và index file từ Google Drive")
async def sync_drive(req: SyncDriveRequest) -> SyncDriveResponse:
    """
    Index file từ Google Drive vào knowledge base.

    Nếu **file_ids** được cung cấp: chỉ index các file đó.
    Nếu không: liệt kê tất cả file được hỗ trợ trong Drive (hoặc folder).

    Quá trình: download → parse → chunk → embed → ChromaDB + Neo4j.
    """
    svc = _get_indexing()
    col = req.collection_name or settings.CHROMA_DEFAULT_COLLECTION

    try:
        if req.file_ids:
            # Index theo danh sách ID cụ thể
            results = svc.index_drive(
                file_ids=req.file_ids,
                collection_name=col,
                force_reindex=req.force_reindex,
            )
        else:
            from app.services.drive_service import DriveService

            drive = DriveService()
            auth = drive.authenticate()
            files = drive.list_all_supported_files(folder_id=req.folder_id)

            if not files:
                return SyncDriveResponse(
                    total_found=0,
                    indexed=0,
                    skipped=0,
                    errors=0,
                    account_email=auth.get("email"),
                    details=[],
                )

            file_ids = [f["id"] for f in files]
            results = svc.index_drive(
                file_ids=file_ids,
                collection_name=col,
                force_reindex=req.force_reindex,
            )
            return _summarize_sync_results(
                results,
                files_found=len(files),
                account_email=auth.get("email"),
            )

        return _summarize_sync_results(results)

    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("POST /sync-drive lỗi: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi đồng bộ Drive: {e}")


# ── Supported types endpoint ──────────────────────────────────

@router.get("/supported-types", summary="Danh sách MIME type được hỗ trợ index")
async def get_supported_types() -> dict[str, Any]:
    """
    Trả về danh sách đầy đủ các MIME type mà hệ thống hỗ trợ index,
    kèm danh sách MIME type bị bỏ qua và giới hạn kích thước file.

    Dùng để hiển thị trong UI hoặc kiểm tra trước khi upload.
    """
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
        "note": (
            "Google Workspace files (Docs/Sheets/Slides) được export tự động "
            "sang DOCX/XLSX/PPTX qua Drive Export API."
        ),
    }


# ── Documents endpoints ────────────────────────────────────────

@router.get("/documents", summary="Liệt kê tài liệu đã index")
async def list_documents(
    limit: int = Query(default=50, ge=1, le=500, description="Số lượng tối đa"),
) -> list[dict[str, Any]]:
    """
    Trả về danh sách tài liệu đã được index, lấy từ Neo4j.
    Mỗi document gồm: id, file_name, mime_type, chunk_count, drive_link.
    """
    try:
        from app.db.neo4j_client import get_neo4j_client
        neo4j = get_neo4j_client()
        return neo4j.list_documents(limit=limit)
    except Exception as e:
        logger.error("GET /documents lỗi: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi lấy danh sách tài liệu: {e}")


@router.get("/documents/{file_id}", summary="Chi tiết một tài liệu")
async def get_document(file_id: str) -> dict[str, Any]:
    """
    Trả về metadata chi tiết của tài liệu và số chunk đã index.

    Args:
        file_id: Google Drive file ID của tài liệu.
    """
    try:
        from app.db.neo4j_client import get_neo4j_client
        neo4j = get_neo4j_client()
        doc = neo4j.get_document_metadata(file_id)
        if not doc:
            raise HTTPException(
                status_code=404,
                detail=f"Không tìm thấy tài liệu với id='{file_id}'",
            )
        return doc
    except HTTPException:
        raise
    except Exception as e:
        logger.error("GET /documents/%s lỗi: %s", file_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{file_id}", summary="Xóa tài liệu khỏi knowledge base")
async def delete_document(file_id: str) -> dict[str, str]:
    """
    Xóa tài liệu (và toàn bộ chunk, embedding) khỏi ChromaDB và Neo4j.

    Args:
        file_id: ID tài liệu cần xóa.
    """
    try:
        svc = _get_indexing()
        svc.delete_index(file_id)
        return {
            "status": "success",
            "message": f"Đã xóa tài liệu '{file_id}' khỏi knowledge base.",
        }
    except Exception as e:
        logger.error("DELETE /documents/%s lỗi: %s", file_id, e)
        raise HTTPException(status_code=500, detail=f"Lỗi xóa tài liệu: {e}")
