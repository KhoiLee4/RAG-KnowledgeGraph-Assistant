"""Retrieval và answer metrics cho benchmark RAG / GraphRAG."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

REFUSAL_PATTERNS: tuple[str, ...] = (
    r"không tìm thấy",
    r"khong tim thay",
    r"không có thông tin",
    r"khong co thong tin",
    r"không có trong tài liệu",
    r"khong co trong tai lieu",
    r"không nằm trong",
    r"i (?:could not|cannot|can't) find",
    r"not found in (?:your )?documents",
    r"no (?:relevant )?information",
)


def chunk_key(file_id: str | None, chunk_index: int | str | None) -> str:
    """Chuẩn hóa định danh chunk: {file_id}__chunk_{index}."""
    fid = str(file_id or "").strip()
    try:
        idx = int(chunk_index)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        idx = 0
    return f"{fid}__chunk_{idx}"


def normalize_chunk_ref(ref: dict[str, Any] | str) -> str:
    """Chấp nhận chunk_id hoặc {file_id, chunk_index}."""
    if isinstance(ref, str):
        return ref.strip()
    if ref.get("chunk_id"):
        return str(ref["chunk_id"]).strip()
    return chunk_key(ref.get("file_id"), ref.get("chunk_index"))


def retrieved_chunk_keys(chunks: list[dict[str, Any]]) -> list[str]:
    """Trích danh sách chunk key theo thứ tự retrieval."""
    keys: list[str] = []
    for chunk in chunks:
        cid = chunk.get("chunk_id") or chunk.get("id")
        if cid:
            keys.append(str(cid))
            continue
        keys.append(chunk_key(chunk.get("file_id"), chunk.get("chunk_index")))
    return keys


def compute_retrieval_metrics(
    retrieved_keys: list[str],
    expected_refs: list[dict[str, Any] | str],
    k: int = 5,
) -> dict[str, Any]:
    """
    Tính Hit@k, Recall@k, Precision@k, MRR từ danh sách chunk truy xuất.

    expected_refs: chunk_id hoặc {file_id, chunk_index}.
    """
    expected = {normalize_chunk_ref(r) for r in expected_refs if normalize_chunk_ref(r)}
    top_k = retrieved_keys[:k]

    if not expected:
        return {
            "hit_at_k": None,
            "recall_at_k": None,
            "precision_at_k": None,
            "mrr": None,
            "relevant_in_top_k": 0,
            "expected_count": 0,
            "skipped": True,
        }

    relevant_hits = [key for key in top_k if key in expected]
    hit = int(len(relevant_hits) > 0)

    recall = len(set(top_k) & expected) / len(expected)
    precision = len(relevant_hits) / k if k > 0 else 0.0

    mrr = 0.0
    for rank, key in enumerate(retrieved_keys, start=1):
        if key in expected:
            mrr = 1.0 / rank
            break

    return {
        "hit_at_k": hit,
        "recall_at_k": round(recall, 4),
        "precision_at_k": round(precision, 4),
        "mrr": round(mrr, 4),
        "relevant_in_top_k": len(relevant_hits),
        "expected_count": len(expected),
        "skipped": False,
    }


def detect_refusal(answer: str) -> bool:
    """Heuristic: câu trả lời có từ chối / không tìm thấy thông tin."""
    text = _normalize_text(answer)
    return any(re.search(pat, text) for pat in REFUSAL_PATTERNS)


def keyword_overlap_score(answer: str, keywords: list[str]) -> float | None:
    """
    Tỷ lệ keyword ground-truth xuất hiện trong câu trả lời [0, 1].
    Proxy yếu cho answer correctness khi chưa chấm tay.
    """
    cleaned = [k.strip() for k in keywords if k and k.strip()]
    if not cleaned:
        return None

    norm_answer = _normalize_text(answer)
    hits = sum(1 for kw in cleaned if _normalize_text(kw) in norm_answer)
    return round(hits / len(cleaned), 4)


def _normalize_text(text: str) -> str:
    lowered = unicodedata.normalize("NFKD", (text or "").lower())
    lowered = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", lowered).strip()
