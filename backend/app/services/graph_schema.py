"""
graph_schema.py — Ontology quan hệ tổng quát cho Knowledge Graph (domain-neutral).

Dùng chung cho mọi user/Drive: chỉ định nghĩa *loại* quan hệ, không hardcode entity cụ thể.
"""

from __future__ import annotations

import re

# Loại entity (khớp prompt extraction)
ENTITY_TYPES: tuple[str, ...] = (
    "PERSON",
    "ORGANIZATION",
    "CONCEPT",
    "LOCATION",
    "DATE",
    "OTHER",
)

# Quan hệ semantic — lưu trực tiếp làm relationship type trên Neo4j
SEMANTIC_RELATION_TYPES: tuple[str, ...] = (
    "WORKS_AT",
    "INTERNS_AT",
    "STUDIES_AT",
    "DIRECTOR_OF",
    "MANAGES",
    "REPORTS_TO",
    "MEMBER_OF",
    "LOCATED_IN",
    "PART_OF",
    "SIGNED_BY",
    "CREATED_BY",
    "COLLABORATES_WITH",
    "RELATED_TO",
)

# Quan hệ do hệ thống sinh (không yêu cầu LLM trích)
SYSTEM_RELATION_TYPES: tuple[str, ...] = (
    "MENTIONS",
    "COOCCURS_WITH",
    "CONTAINS",
    "HAS_CHUNK",
    "NEXT_CHUNK",
    "IN_COMMUNITY",
)

ALL_ENTITY_REL_TYPES: tuple[str, ...] = SEMANTIC_RELATION_TYPES + (
    "COOCCURS_WITH",
)

# Pattern cho Cypher: (e)-[r:WORKS_AT|INTERNS_AT|...]-(e2)
ENTITY_REL_CYPHER_PATTERN: str = "|".join(ALL_ENTITY_REL_TYPES)

RELATION_TYPE_ALIASES: dict[str, str] = {
    "WORK_AT": "WORKS_AT",
    "WORKING_AT": "WORKS_AT",
    "EMPLOYED_AT": "WORKS_AT",
    "LAM_VIEC_TAI": "WORKS_AT",
    "INTERN_AT": "INTERNS_AT",
    "INTERNSHIP_AT": "INTERNS_AT",
    "THUC_TAP_TAI": "INTERNS_AT",
    "HOC_TAI": "STUDIES_AT",
    "STUDY_AT": "STUDIES_AT",
    "STUDIES_AT": "STUDIES_AT",
    "GIAM_DOC": "DIRECTOR_OF",
    "DIRECTOR": "DIRECTOR_OF",
    "CEO_OF": "DIRECTOR_OF",
    "QUAN_LY": "MANAGES",
    "MANAGER_OF": "MANAGES",
    "BAO_CAO_CHO": "REPORTS_TO",
    "REPORT_TO": "REPORTS_TO",
    "THANH_VIEN": "MEMBER_OF",
    "BELONGS_TO": "MEMBER_OF",
    "MEMBER_OF": "MEMBER_OF",
    "O_TAI": "LOCATED_IN",
    "LOCATION": "LOCATED_IN",
    "THUOC": "PART_OF",
    "PART_OF": "PART_OF",
    "KY_BOI": "SIGNED_BY",
    "CREATED_BY": "CREATED_BY",
    "HOP_TAC": "COLLABORATES_WITH",
    "LIEN_QUAN": "RELATED_TO",
    "RELATED": "RELATED_TO",
    "RELATED_TO": "RELATED_TO",
}

PATH_REL_CYPHER_PATTERN: str = "|".join(SEMANTIC_RELATION_TYPES)

_RELATION_TYPES_DOC = "\n".join(
    f"  - {r}"
    for r in SEMANTIC_RELATION_TYPES
    if r != "RELATED_TO"
)

ENTITY_EXTRACTION_PROMPT = (
    "Phân tích đoạn văn bản và trích xuất thực thể + quan hệ có trong văn bản.\n\n"
    "Quy tắc:\n"
    "- Chỉ lấy thông tin CÓ TRONG văn bản, không suy diễn thêm.\n"
    f"- Entity type: {' | '.join(ENTITY_TYPES)}.\n"
    "- Relation type PHẢI là một trong:\n"
    f"{_RELATION_TYPES_DOC}\n"
    "  - RELATED_TO: chỉ khi không khớp loại trên (kèm description rõ).\n"
    '- Hướng quan hệ: "from" → "to" (vd: PERSON —INTERNS_AT→ ORGANIZATION).\n'
    "- Nếu A thực tập/làm việc tại org X và B là giám đốc org X → tạo 2 quan hệ riêng tới X.\n\n"
    "Văn bản:\n"
    "{text}\n\n"
    "Trả về JSON:\n"
    '{{\n'
    '  "entities": [\n'
    '    {{"name": "tên đầy đủ", "type": "PERSON", "description": "mô tả ngắn"}}\n'
    "  ],\n"
    '  "relations": [\n'
    '    {{"from": "entity A", "to": "entity B", "relation": "INTERNS_AT", "description": "mô tả"}}\n'
    "  ]\n"
    "}}\n\n"
    "Chỉ trả về JSON thuần, không markdown."
)

BATCH_ENTITY_EXTRACTION_PROMPT = (
    "Phân tích từng đoạn văn bản và trích entity + relation.\n"
    "Mỗi đoạn có nhãn [CHUNK_N] với N là chunk_index.\n\n"
    f"Quy tắc relation type: {' | '.join(SEMANTIC_RELATION_TYPES)}.\n\n"
    "{texts}\n\n"
    "Trả về JSON:\n"
    '{{\n'
    '  "chunks": [\n'
    "    {{\n"
    '      "chunk_index": 0,\n'
    '      "entities": [{{"name": "...", "type": "PERSON", "description": "..."}}],\n'
    '      "relations": [{{"from": "...", "to": "...", "relation": "WORKS_AT", "description": "..."}}]\n'
    "    }}\n"
    "  ]\n"
    "}}\n\n"
    'Chỉ JSON thuần. Mỗi phần tử "chunks" khớp đúng chunk_index.'
)


def normalize_relation_type(raw: str) -> str:
    """Chuẩn hóa relation từ LLM về ontology; fallback RELATED_TO."""
    if not raw or not str(raw).strip():
        return "RELATED_TO"

    key = re.sub(r"[^A-Za-z0-9_]", "_", str(raw).strip().upper())
    key = re.sub(r"_+", "_", key).strip("_")

    if key in SEMANTIC_RELATION_TYPES:
        return key
    if key in RELATION_TYPE_ALIASES:
        return RELATION_TYPE_ALIASES[key]

    # Thử bỏ hậu tố _OF / _AT
    for suffix in ("_OF", "_AT", "_TO", "_WITH", "_IN"):
        if key.endswith(suffix):
            candidate = key
            if candidate in RELATION_TYPE_ALIASES:
                return RELATION_TYPE_ALIASES[candidate]
            if candidate in SEMANTIC_RELATION_TYPES:
                return candidate

    return "RELATED_TO"


def is_semantic_relation(rel_type: str) -> bool:
    return normalize_relation_type(rel_type) in SEMANTIC_RELATION_TYPES


def community_edge_weight(rel_type: str, related_w: float, cooccur_w: float) -> float:
    """Trọng số cạnh cho Louvain — ưu tiên quan hệ semantic hơn COOCCURS_WITH."""
    raw = str(rel_type or "").strip().upper()
    if raw == "COOCCURS_WITH":
        return cooccur_w
    rt = normalize_relation_type(rel_type)
    if rt == "RELATED_TO":
        return related_w
    return related_w * 1.25
