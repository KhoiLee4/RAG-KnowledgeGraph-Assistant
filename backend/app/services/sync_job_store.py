"""
sync_job_store.py — Lưu trạng thái job đồng bộ Drive (in-memory, dùng khi dev).

Job chạy nền qua FastAPI BackgroundTasks; client poll GET /drive/sync-all/jobs/{id}.
"""

from __future__ import annotations

import threading
import time
from typing import Any


class SyncJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str, user_id: str | None = None) -> None:
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "user_id": user_id,
                "status": "pending",
                "message": "Đang chờ bắt đầu...",
                "total": 0,
                "processed": 0,
                "created_at": time.time(),
                "updated_at": time.time(),
                "result": None,
                "error": None,
            }

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(fields)
            job["updated_at"] = time.time()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def has_running_for_user(self, user_id: str) -> bool:
        """True nếu user đã có job sync đang chạy."""
        with self._lock:
            for job in self._jobs.values():
                if job.get("user_id") == user_id and job.get("status") in (
                    "pending",
                    "running",
                ):
                    return True
            return False


_store: SyncJobStore | None = None


def get_sync_job_store() -> SyncJobStore:
    global _store
    if _store is None:
        _store = SyncJobStore()
    return _store
