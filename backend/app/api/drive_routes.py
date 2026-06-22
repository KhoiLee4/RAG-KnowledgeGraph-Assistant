"""Google Drive: status, preview, sync-all (sync + async job)."""

import logging
import threading
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.deps import get_indexing_service
from app.api.schemas import SyncDriveRequest, SyncDriveResponse, summarize_sync_results
from app.api.sync_helpers import perform_drive_sync_all, run_drive_sync_all_job
from app.core.auth_deps import require_user, user_collection_name

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/drive/status", summary="Trạng thái đăng nhập Google Drive")
async def drive_status(request: Request) -> dict[str, Any]:
    """Kiểm tra user đã đăng nhập và token Drive còn hợp lệ không."""
    try:
        from app.core.auth_deps import get_session_user
        from app.services.drive_service import DriveService

        user = get_session_user(request)
        user_id = user["user_id"] if user else None
        status = DriveService.get_auth_status(user_id)
        status["logged_in"] = user is not None
        if user:
            status["session_email"] = user.get("email")
        return status
    except Exception as e:
        logger.error("GET /drive/status lỗi: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drive/login", summary="[Deprecated] Dùng GET /auth/google")
async def drive_login() -> dict[str, Any]:
    """Endpoint cũ (Desktop OAuth). Đã thay bằng Web OAuth."""
    raise HTTPException(
        status_code=410,
        detail=(
            "Desktop OAuth đã ngừng hỗ trợ. "
            "Dùng GET /api/v1/auth/google để đăng nhập trên trình duyệt."
        ),
    )


@router.get("/drive/files", summary="Xem trước file được hỗ trợ trên Drive")
async def drive_list_files(
    request: Request,
    folder_id: str | None = Query(default=None, description="Lọc theo folder ID"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """Liệt kê tài liệu được hỗ trợ trên Drive. Cần đăng nhập Google trước."""
    try:
        from app.services.drive_service import DriveService, SUPPORTED_TYPE_LABELS

        user = require_user(request)
        svc = DriveService(user_id=user["user_id"])
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
        status = DriveService.get_auth_status(user["user_id"])
        return {
            "total": len(files),
            "showing": len(preview),
            "account_email": status.get("email"),
            "files": preview,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("GET /drive/files lỗi: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drive/sync-all", summary="Index TOÀN BỘ file Drive được hỗ trợ")
async def drive_sync_all(
    request: Request,
    force_reindex: bool = Query(default=False, description="Index lại dù đã có"),
    folder_id: str | None = Query(default=None, description="Chỉ quét folder này"),
) -> SyncDriveResponse:
    """Quét Drive của user và index mọi tài liệu được hỗ trợ (PDF, Word, Excel...)."""
    user = require_user(request)
    col = user_collection_name(user["user_id"])
    try:
        return perform_drive_sync_all(
            user_id=user["user_id"],
            collection_name=col,
            force_reindex=force_reindex,
            folder_id=folder_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("POST /drive/sync-all lỗi: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi đồng bộ Drive: {e}")


@router.post("/drive/sync-all/async", summary="Đồng bộ Drive nền (không timeout HTTP)")
async def drive_sync_all_async(
    request: Request,
    force_reindex: bool = Query(default=False),
    folder_id: str | None = Query(default=None),
) -> dict[str, str]:
    """Trả về job_id; client poll GET /drive/sync-all/jobs/{job_id}."""
    from app.services.sync_job_store import get_sync_job_store

    user = require_user(request)
    col = user_collection_name(user["user_id"])
    store = get_sync_job_store()

    if store.has_running_for_user(user["user_id"]):
        raise HTTPException(
            status_code=409,
            detail="Đã có job đồng bộ đang chạy. Vui lòng đợi job hiện tại xong.",
        )

    job_id = str(uuid.uuid4())
    store.create(job_id, user_id=user["user_id"])
    threading.Thread(
        target=run_drive_sync_all_job,
        args=(job_id, user["user_id"], col, force_reindex, folder_id),
        daemon=True,
    ).start()
    return {"job_id": job_id, "status": "pending"}


@router.get("/drive/sync-all/jobs/{job_id}", summary="Trạng thái job đồng bộ Drive")
async def drive_sync_all_job_status(request: Request, job_id: str) -> dict[str, Any]:
    from app.services.sync_job_store import get_sync_job_store

    user = require_user(request)
    job = get_sync_job_store().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại hoặc đã hết hạn.")
    if job.get("user_id") and job["user_id"] != user["user_id"]:
        raise HTTPException(status_code=403, detail="Không có quyền xem job này.")
    return job


@router.post("/sync-drive", summary="Đồng bộ và index file từ Google Drive")
async def sync_drive(req: SyncDriveRequest, request: Request) -> SyncDriveResponse:
    """Index file theo file ID hoặc quét folder trên Drive."""
    user = require_user(request)
    svc = get_indexing_service()
    col = req.collection_name or user_collection_name(user["user_id"])

    try:
        from app.services.drive_service import DriveService

        drive = DriveService(user_id=user["user_id"])

        if req.file_ids:
            results = svc.index_drive(
                file_ids=req.file_ids,
                collection_name=col,
                force_reindex=req.force_reindex,
                drive=drive,
                owner_id=user["user_id"],
            )
            return summarize_sync_results(results)

        auth = drive.load_credentials()
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
            drive=drive,
            owner_id=user["user_id"],
        )
        return summarize_sync_results(
            results,
            files_found=len(files),
            account_email=auth.get("email"),
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("POST /sync-drive lỗi: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi đồng bộ Drive: {e}")
