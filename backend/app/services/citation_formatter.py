"""Chuẩn hóa trích dẫn thân thiện với người dùng (trang, file, link vị trí)."""

from __future__ import annotations

import re
from typing import Any

SOURCE_LABELS = {
    "vector": "Tài liệu",
    "graph": "Đồ thị tri thức",
    "hybrid": "Tài liệu + Đồ thị",
    "community": "Tổng quan chủ đề",
}


def _parse_page(value: Any) -> int | None:
    if value is None:
        return None
    try:
        page = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def build_location_link(
    drive_link: str,
    file_id: str = "",
    page: int | None = None,
    mime_type: str = "",
    file_name: str = "",
) -> str:
    """Tạo link mở file tại trang cụ thể (PDF trên Google Drive)."""
    base = (drive_link or "").strip()
    if not base and file_id:
        base = f"https://drive.google.com/file/d/{file_id}/view"

    if not base or not page or page <= 0:
        return base

    name_hint = (file_name or base).lower()
    is_pdf = (
        "pdf" in mime_type.lower()
        or name_hint.endswith(".pdf")
        or "/pdf" in base.lower()
    )
    if mime_type and not is_pdf:
        return base

    if "/view" in base:
        base = base.replace("/view", "/preview")
    elif "/preview" not in base and file_id:
        base = f"https://drive.google.com/file/d/{file_id}/preview"

    anchor = f"#page={page}"
    if anchor not in base:
        base = f"{base}{anchor}"
    return base


def _truncate(text: str, max_len: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def format_citation(raw: dict[str, Any], index: int) -> dict[str, str]:
    """Chuyển metadata nội bộ thành citation hiển thị cho người dùng."""
    source = str(raw.get("source", raw.get("source_type", "vector")))
    source_label = SOURCE_LABELS.get(source, "Nguồn")

    file_name = str(raw.get("file_name", "")).strip()
    file_id = str(raw.get("file_id", "")).strip()
    drive_link = str(raw.get("drive_link", "")).strip()
    page = _parse_page(raw.get("page_estimate"))
    mime_type = str(raw.get("mime_type", ""))

    snippet = _truncate(
        raw.get("snippet")
        or raw.get("summary_preview")
        or raw.get("text", "")
    )

    relation = str(raw.get("relation", "")).strip()
    member_count = str(raw.get("member_count", "")).strip()

    if source == "community":
        label = "Tổng quan chủ đề"
        if member_count:
            label = f"Tổng quan ({member_count} thực thể)"
        location = ""
    elif source == "graph":
        label = file_name or "Quan hệ trong đồ thị tri thức"
        source_file = str(raw.get("source_file", "")).strip()
        if source_file:
            location = f"Tài liệu: {source_file}"
        elif relation:
            location = relation.replace("_", " ").title()
        else:
            location = "Đồ thị tri thức"
    else:
        label = file_name or "Tài liệu"
        location = f"Trang {page}" if page else ""

    location_link = build_location_link(
        drive_link, file_id, page, mime_type, file_name=file_name
    )

    return {
        "index": str(index),
        "label": label,
        "location": location,
        "snippet": snippet,
        "source": source,
        "source_label": source_label,
        "drive_link": drive_link,
        "location_link": location_link or drive_link,
        "file_id": file_id,
        "page": str(page) if page else "",
        # Giữ field cũ để tương thích ngược
        "file_name": label,
        "page_estimate": str(page) if page else "",
        "chunk_index": "",
    }


def format_citations(raw_list: list[dict[str, Any]], max_items: int = 10) -> list[dict[str, str]]:
    """Lọc trùng và giới hạn số citation trả về."""
    seen: set[str] = set()
    result: list[dict[str, str]] = []

    for raw in raw_list:
        source = str(raw.get("source", raw.get("source_type", "vector")))
        file_name = str(raw.get("file_name", "")).strip()
        page = str(_parse_page(raw.get("page_estimate")) or "")
        relation = str(raw.get("relation", "")).strip()
        snippet_key = _truncate(raw.get("snippet") or raw.get("summary_preview") or "", 40)

        dedupe_key = f"{source}|{file_name}|{page}|{relation}|{snippet_key}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        result.append(format_citation(raw, len(result) + 1))
        if len(result) >= max_items:
            break

    return result
