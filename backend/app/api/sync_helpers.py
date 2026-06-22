"""Logic đồng bộ Drive dùng chung (sync-all, async job)."""

import logging
from typing import Any

from app.api.deps import get_indexing_service
from app.api.schemas import SyncDriveResponse, summarize_sync_results

logger = logging.getLogger(__name__)


def perform_drive_sync_all(
    user_id: str,
    collection_name: str,
    force_reindex: bool = False,
    folder_id: str | None = None,
    on_progress: Any = None,
) -> SyncDriveResponse:
    """Quét Drive và index toàn bộ tài liệu được hỗ trợ (PDF, Word, Excel...) cho user."""
    from app.services.drive_service import DriveService

    svc_index = get_indexing_service()
    drive = DriveService(user_id=user_id)
    auth = drive.load_credentials()

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
        collection_name=collection_name,
        force_reindex=force_reindex,
        on_progress=_progress,
        drive=drive,
        owner_id=user_id,
    )

    return summarize_sync_results(
        results,
        files_found=len(files),
        account_email=auth.get("email"),
    )


def run_drive_sync_all_job(
    job_id: str,
    user_id: str,
    collection_name: str,
    force_reindex: bool,
    folder_id: str | None,
) -> None:
    """Chạy đồng bộ Drive trong background thread."""
    from app.services.sync_job_store import get_sync_job_store

    store = get_sync_job_store()
    try:
        store.update(job_id, status="running", message="Đang quét Google Drive...")

        def on_progress(done: int, total: int) -> None:
            store.update(
                job_id,
                processed=done,
                total=total,
                message=f"Đang index file {done}/{total}...",
            )

        result = perform_drive_sync_all(
            user_id=user_id,
            collection_name=collection_name,
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

        from app.services.community_service import run_community_detection_best_effort
        store.update(job_id, message="Đang phát hiện community...")
        run_community_detection_best_effort(user_id)
    except Exception as e:
        logger.error("sync job %s lỗi: %s", job_id, e, exc_info=True)
        store.update(
            job_id,
            status="failed",
            message="Đồng bộ thất bại.",
            error=str(e),
        )
