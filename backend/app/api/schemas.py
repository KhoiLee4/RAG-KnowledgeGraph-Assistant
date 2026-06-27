"""Pydantic schemas dùng chung cho các API endpoint."""

import dataclasses
from typing import Any

from typing import Literal

from pydantic import BaseModel, Field


RetrievalMode = Literal["rag", "graph_rag"]


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
    retrieval_mode: RetrievalMode = Field(
        default="rag",
        description="rag = chỉ tài liệu, graph_rag = GraphRAG đầy đủ",
    )


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

    total_found: int = 0
    indexed: int = 0
    skipped: int = 0
    errors: int = 0
    account_email: str | None = None
    details: list[dict[str, Any]] = []


def summarize_sync_results(
    results: list,
    files_found: int = 0,
    account_email: str | None = None,
) -> SyncDriveResponse:
    """Tổng hợp danh sách IndexResult thành SyncDriveResponse."""

    def _get_status(r: Any) -> str:
        if dataclasses.is_dataclass(r):
            return r.status  # type: ignore[attr-defined]
        return r.get("status", "")

    def _to_dict(r: Any) -> dict[str, Any]:
        if dataclasses.is_dataclass(r):
            return dataclasses.asdict(r)
        return r

    details = [_to_dict(r) for r in results]

    return SyncDriveResponse(
        total_found=files_found if files_found > 0 else len(results),
        indexed=sum(1 for r in results if _get_status(r) == "success"),
        skipped=sum(1 for r in results if _get_status(r) == "skipped"),
        errors=sum(1 for r in results if _get_status(r) in ("error", "failed")),
        account_email=account_email,
        details=details,
    )
