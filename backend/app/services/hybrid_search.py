from __future__ import annotations

import re
import unicodedata
from typing import Any


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt để khớp từ khóa linh hoạt hơn."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def normalize_text(text: str) -> str:
    """Chuẩn hóa văn bản cho so khớp keyword."""
    lowered = strip_accents((text or "").lower())
    lowered = re.sub(r"[_\.\-]+", " ", lowered)
    return re.sub(r"[^\w\s]", " ", lowered)


def tokenize(text: str, min_len: int = 2) -> list[str]:
    """Tách token; bỏ token quá ngắn."""
    return [t for t in normalize_text(text).split() if len(t) >= min_len]


def keyword_score(query: str, document: str, file_name: str = "") -> float:
    """
    Điểm keyword [0, 1]: overlap token + bonus khớp cụm trong tên file/nội dung.

    Args:
        query: Câu hỏi người dùng.
        document: Nội dung chunk.
        file_name: Tên file nguồn (ưu tiên khớp tên tài liệu).

    Returns:
        Điểm trong khoảng [0.0, 1.0].
    """
    q_tokens = set(tokenize(query))
    if not q_tokens:
        return 0.0

    doc_tokens = set(tokenize(document))
    name_tokens = set(tokenize(file_name))

    doc_overlap = len(q_tokens & doc_tokens) / len(q_tokens)
    name_overlap = len(q_tokens & name_tokens) / len(q_tokens)

    q_norm = normalize_text(query)
    haystack = normalize_text(f"{document} {file_name}")
    phrase_bonus = 0.0
    if len(q_norm) >= 4 and q_norm in haystack:
        phrase_bonus = 1.0
    elif len(q_norm) >= 3:
        # Khớp từng token dài (mã API, tên riêng)
        long_tokens = [t for t in q_tokens if len(t) >= 4]
        if long_tokens and all(t in haystack for t in long_tokens):
            phrase_bonus = 0.6

    score = 0.65 * doc_overlap + 0.25 * name_overlap + 0.10 * phrase_bonus
    return min(1.0, max(0.0, score))


def merge_hybrid_scores(
    candidates: list[dict[str, Any]],
    query: str,
    vector_weight: float = 0.85,
    keyword_weight: float = 0.15,
) -> list[dict[str, Any]]:
    """
    Tính combined_score và sắp xếp giảm dần.

    Mỗi candidate phải có: text/document, file_name, score (vector similarity).
    Cập nhật thêm keyword_score, combined_score.
    """
    if not candidates:
        return []

    vw = max(0.0, min(1.0, vector_weight))
    kw = max(0.0, min(1.0, keyword_weight))
    total = vw + kw
    if total <= 0:
        vw, kw = 0.85, 0.15
        total = 1.0
    vw, kw = vw / total, kw / total

    merged: list[dict[str, Any]] = []
    for item in candidates:
        text = item.get("text") or item.get("document") or ""
        file_name = item.get("file_name") or item.get("metadata", {}).get("file_name", "")
        vec = float(item.get("score", 0.0))
        kw_score = keyword_score(query, text, file_name)
        combined = vw * vec + kw * kw_score
        out = {**item, "keyword_score": round(kw_score, 4), "combined_score": round(combined, 4)}
        out["score"] = out["combined_score"]
        merged.append(out)

    merged.sort(key=lambda x: x["combined_score"], reverse=True)
    return merged
