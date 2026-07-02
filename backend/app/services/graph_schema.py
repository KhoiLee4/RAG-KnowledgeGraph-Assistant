"""
graph_schema.py — Ontology cho Knowledge Graph theo mô hình "lõi cố định + mở rộng linh hoạt".

Nguyên tắc (phù hợp KG đa lĩnh vực):
  - Entity 2 tầng: LABEL lõi cố định (~10 loại, dùng làm node type ổn định cho Louvain)
    + SUBTYPE tự do (property, không ảnh hưởng cấu trúc graph — chỉ để hiển thị/filter).
  - Relation: một tập CANONICAL nhỏ (~20 loại) chia theo nhóm ngữ nghĩa. Loại lạ do LLM
    sinh ra được map về canonical gần nhất (embedding, xem relation_normalizer.py),
    fallback RELATED_TO nếu không khớp — tránh phình schema mất kiểm soát.
"""

from __future__ import annotations

import re
import unicodedata


def _strip_diacritics(s: str) -> str:
    """Bỏ dấu tiếng Việt (kể cả đ/Đ, không bị NFD tách rời) trước khi làm sạch key."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")

# ── Entity labels (tầng 1) — cố định, KHÔNG cho LLM tự tạo ─────────────────
ENTITY_TYPES: tuple[str, ...] = (
    "PERSON",
    "ORGANIZATION",
    "LOCATION",
    "EVENT",
    "CONCEPT",
    "PRODUCT",
    "DOCUMENT",
    "DATE",
    "WORK_OF_ART",
    "OTHER",
)

_ENTITY_TYPES_SET = frozenset(ENTITY_TYPES)

# Gộp các biến thể label phổ biến về label lõi.
ENTITY_LABEL_ALIASES: dict[str, str] = {
    "ORG": "ORGANIZATION",
    "COMPANY": "ORGANIZATION",
    "CORPORATION": "ORGANIZATION",
    "CORP": "ORGANIZATION",
    "BUSINESS": "ORGANIZATION",
    "ORGANISATION": "ORGANIZATION",
    "INSTITUTION": "ORGANIZATION",
    "AGENCY": "ORGANIZATION",
    "GROUP": "ORGANIZATION",
    "PEOPLE": "PERSON",
    "HUMAN": "PERSON",
    "INDIVIDUAL": "PERSON",
    "PLACE": "LOCATION",
    "GPE": "LOCATION",
    "COUNTRY": "LOCATION",
    "CITY": "LOCATION",
    "REGION": "LOCATION",
    "TIME": "DATE",
    "DATETIME": "DATE",
    "YEAR": "DATE",
    "TECHNOLOGY": "PRODUCT",
    "TECH": "PRODUCT",
    "TOOL": "PRODUCT",
    "SOFTWARE": "PRODUCT",
    "APP": "PRODUCT",
    "SERVICE": "PRODUCT",
    "ARTWORK": "WORK_OF_ART",
    "WORKOFART": "WORK_OF_ART",
    "ARTICLE": "DOCUMENT",
    "BOOK": "DOCUMENT",
    "REPORT": "DOCUMENT",
    "PAPER": "DOCUMENT",
    "THEORY": "CONCEPT",
    "METHOD": "CONCEPT",
    "IDEA": "CONCEPT",
    "MISC": "OTHER",
    "UNKNOWN": "OTHER",
}


def canonical_entity_label(raw: str) -> str:
    """Chuẩn hóa entity label về tập lõi; không khớp → OTHER."""
    key = re.sub(r"[^A-Za-z0-9_]", "_", str(raw or "").strip().upper())
    key = re.sub(r"_+", "_", key).strip("_")
    if not key:
        return "OTHER"
    if key in _ENTITY_TYPES_SET:
        return key
    if key in ENTITY_LABEL_ALIASES:
        return ENTITY_LABEL_ALIASES[key]
    return "OTHER"


# ── Relation canonical set (tầng lõi) — chia theo nhóm ngữ nghĩa ───────────
CANONICAL_RELATION_TYPES: tuple[str, ...] = (
    # Cấu trúc / thành phần
    "PART_OF",
    "LOCATED_IN",
    "MEMBER_OF",
    # Nhân quả
    "CAUSES",
    "LEADS_TO",
    "ENABLES",
    # Thời gian
    "PRECEDES",
    "HAPPENED_ON",
    "DURING",
    # Sở hữu / tạo ra
    "CREATED_BY",
    "OWNS",
    "AUTHORED_BY",
    "SIGNED_BY",
    # Công việc / tổ chức / xã hội
    "WORKS_FOR",
    "MANAGES",
    "REPORTS_TO",
    "COLLABORATES_WITH",
    "STUDIES_AT",
    "DIRECTOR_OF",
    # Liên kết chung
    "REFERENCES",
    "RELATED_TO",
)

_CANONICAL_SET = frozenset(CANONICAL_RELATION_TYPES)

# Giữ tên cũ cho tương thích ngược + dùng làm gợi ý trong prompt.
KNOWN_RELATION_TYPES = CANONICAL_RELATION_TYPES
SEMANTIC_RELATION_TYPES = CANONICAL_RELATION_TYPES

# Quan hệ do hệ thống sinh (không do LLM trích).
SYSTEM_RELATION_TYPES: tuple[str, ...] = (
    "MENTIONS",
    "COOCCURS_WITH",
    "CONTAINS",
    "HAS_CHUNK",
    "NEXT_CHUNK",
    "NEXT",
    "BELONGS_TO",
    "IN_COMMUNITY",
)

# Các loại KHÔNG mang ngữ nghĩa entity↔entity (dùng để loại trừ khi cần chỉ semantic).
NON_SEMANTIC_RELATION_TYPES: frozenset[str] = frozenset(SYSTEM_RELATION_TYPES)

# Độ dài tối đa cho tên quan hệ (chặn rác quá dài từ LLM).
_MAX_RELATION_LEN: int = 60

# Map biến thể quan hệ đã biết → canonical (fast path, không cần embedding).
RELATION_TYPE_ALIASES: dict[str, str] = {
    # WORKS_FOR
    "WORKS_AT": "WORKS_FOR",
    "WORK_AT": "WORKS_FOR",
    "WORKING_AT": "WORKS_FOR",
    "WORK_FOR": "WORKS_FOR",
    "WORKING_FOR": "WORKS_FOR",
    "EMPLOYED_AT": "WORKS_FOR",
    "EMPLOYED_BY": "WORKS_FOR",
    "IS_EMPLOYEE_OF": "WORKS_FOR",
    "EMPLOYEE_OF": "WORKS_FOR",
    "LAM_VIEC_TAI": "WORKS_FOR",
    "INTERNS_AT": "WORKS_FOR",
    "INTERN_AT": "WORKS_FOR",
    "INTERNSHIP_AT": "WORKS_FOR",
    "THUC_TAP_TAI": "WORKS_FOR",
    # STUDIES_AT
    "STUDY_AT": "STUDIES_AT",
    "STUDIES_AT": "STUDIES_AT",
    "HOC_TAI": "STUDIES_AT",
    # DIRECTOR_OF
    "GIAM_DOC": "DIRECTOR_OF",
    "DIRECTOR": "DIRECTOR_OF",
    "CEO_OF": "DIRECTOR_OF",
    "HEAD_OF": "DIRECTOR_OF",
    # MANAGES
    "QUAN_LY": "MANAGES",
    "MANAGER_OF": "MANAGES",
    "MANAGE": "MANAGES",
    # REPORTS_TO
    "BAO_CAO_CHO": "REPORTS_TO",
    "REPORT_TO": "REPORTS_TO",
    # MEMBER_OF
    "THANH_VIEN": "MEMBER_OF",
    "BELONGS_TO_ORG": "MEMBER_OF",
    "MEMBER": "MEMBER_OF",
    # LOCATED_IN
    "O_TAI": "LOCATED_IN",
    "LOCATION_OF": "LOCATED_IN",
    "LOCATED_AT": "LOCATED_IN",
    "IN_LOCATION": "LOCATED_IN",
    # PART_OF
    "THUOC": "PART_OF",
    "SUBSIDIARY_OF": "PART_OF",
    "DIVISION_OF": "PART_OF",
    # SIGNED_BY
    "KY_BOI": "SIGNED_BY",
    # CREATED_BY / AUTHORED_BY
    "CREATED": "CREATED_BY",
    "MADE_BY": "CREATED_BY",
    "DEVELOPED_BY": "CREATED_BY",
    "WRITTEN_BY": "AUTHORED_BY",
    "AUTHOR_OF": "AUTHORED_BY",
    # OWNS
    "OWNED_BY": "OWNS",
    "OWNER_OF": "OWNS",
    "ACQUIRED": "OWNS",
    "ACQUIRES": "OWNS",
    # COLLABORATES_WITH
    "HOP_TAC": "COLLABORATES_WITH",
    "COLLABORATE_WITH": "COLLABORATES_WITH",
    "PARTNER_WITH": "COLLABORATES_WITH",
    # CAUSES / LEADS_TO
    "CAUSE": "CAUSES",
    "CAUSED_BY": "CAUSES",
    "RESULTS_IN": "LEADS_TO",
    "LEAD_TO": "LEADS_TO",
    # REFERENCES
    "REFERENCE": "REFERENCES",
    "REFERS_TO": "REFERENCES",
    "CITES": "REFERENCES",
    # RELATED_TO
    "LIEN_QUAN": "RELATED_TO",
    "RELATED": "RELATED_TO",
    "RELATED_TO": "RELATED_TO",
}

_RELATION_TYPES_DOC = "\n".join(
    f"  - {r}"
    for r in CANONICAL_RELATION_TYPES
    if r != "RELATED_TO"
)

ENTITY_EXTRACTION_PROMPT = (
    "Bạn là hệ thống trích xuất thực thể + quan hệ cho Knowledge Graph.\n\n"
    "## Entity label — CHỈ chọn 1 trong (KHÔNG tự tạo label mới):\n"
    f"  {' | '.join(ENTITY_TYPES)}\n"
    "  Kèm 'subtype' là mô tả chi tiết TỰ DO (vd: 'startup AI', 'sông', 'giao thức mạng').\n\n"
    "## Relation type — ưu tiên chọn trong danh sách canonical dưới đây;\n"
    "   chỉ TỰ ĐẶT loại mới (UPPER_SNAKE_CASE, dạng động từ) nếu THỰC SỰ không loại nào phù hợp:\n"
    f"{_RELATION_TYPES_DOC}\n"
    "  - RELATED_TO: chỉ khi quan hệ chung chung, không xác định rõ.\n\n"
    "Quy tắc:\n"
    "- Chỉ lấy thông tin CÓ TRONG văn bản, không suy diễn.\n"
    '- Hướng quan hệ: "from" → "to".\n\n'
    "Văn bản:\n"
    "{text}\n\n"
    "Trả về JSON thuần (không markdown):\n"
    '{{\n'
    '  "entities": [\n'
    '    {{"name": "tên đầy đủ", "type": "PERSON", "subtype": "mô tả tự do", "description": "mô tả ngắn"}}\n'
    "  ],\n"
    '  "relations": [\n'
    '    {{"from": "entity A", "to": "entity B", "relation": "WORKS_FOR", "description": "mô tả"}}\n'
    "  ]\n"
    "}}"
)

BATCH_ENTITY_EXTRACTION_PROMPT = (
    "Bạn là hệ thống trích xuất thực thể + quan hệ cho Knowledge Graph.\n"
    "Phân tích từng đoạn có nhãn [CHUNK_N] (N là chunk_index).\n\n"
    "## Entity label — CHỈ chọn 1 trong (KHÔNG tự tạo label mới):\n"
    f"  {' | '.join(ENTITY_TYPES)}\n"
    "  Kèm 'subtype' là mô tả chi tiết tự do.\n\n"
    "## Relation type — ưu tiên canonical, chỉ tự đặt loại mới nếu thật sự không phù hợp:\n"
    f"  {' | '.join(CANONICAL_RELATION_TYPES)}\n"
    "  Chỉ dùng RELATED_TO khi thật sự chung chung.\n\n"
    "{texts}\n\n"
    "Trả về JSON thuần:\n"
    '{{\n'
    '  "chunks": [\n'
    "    {{\n"
    '      "chunk_index": 0,\n'
    '      "entities": [{{"name": "...", "type": "PERSON", "subtype": "...", "description": "..."}}],\n'
    '      "relations": [{{"from": "...", "to": "...", "relation": "WORKS_FOR", "description": "..."}}]\n'
    "    }}\n"
    "  ]\n"
    "}}\n\n"
    'Chỉ JSON thuần. Mỗi phần tử "chunks" khớp đúng chunk_index.'
)


def clean_relation_key(raw: str) -> str:
    """Làm sạch tên quan hệ về UPPER_SNAKE_CASE hợp lệ cho Neo4j (chưa map canonical)."""
    text = _strip_diacritics(str(raw or ""))
    key = re.sub(r"[^A-Za-z0-9_]", "_", text.strip().upper())
    key = re.sub(r"_+", "_", key).strip("_")
    if not key:
        return "RELATED_TO"
    if key[0].isdigit():
        key = f"REL_{key}"
    if len(key) > _MAX_RELATION_LEN:
        key = key[:_MAX_RELATION_LEN].strip("_")
    return key or "RELATED_TO"


def normalize_relation_type(raw: str) -> str:
    """
    Chuẩn hóa cú pháp (rẻ, không gọi API):
      - Làm sạch về UPPER_SNAKE_CASE hợp lệ.
      - Gộp biến thể đã biết về canonical qua ``RELATION_TYPE_ALIASES``.
      - Nếu chưa khớp canonical, GIỮ NGUYÊN tên đã làm sạch (để bước embedding
        trong relation_normalizer map tiếp về canonical / RELATED_TO).
    """
    if not raw or not str(raw).strip():
        return "RELATED_TO"

    key = clean_relation_key(raw)
    if key in RELATION_TYPE_ALIASES:
        return RELATION_TYPE_ALIASES[key]
    return key


def is_canonical_relation(rel_type: str) -> bool:
    """True nếu (sau chuẩn hóa cú pháp) thuộc canonical set."""
    return normalize_relation_type(rel_type) in _CANONICAL_SET


def is_semantic_relation(rel_type: str) -> bool:
    """True nếu là quan hệ ngữ nghĩa entity↔entity (không phải system/cooccurs)."""
    rt = normalize_relation_type(rel_type)
    return rt not in NON_SEMANTIC_RELATION_TYPES


def community_edge_weight(rel_type: str, related_w: float, cooccur_w: float) -> float:
    """Trọng số cạnh cho Louvain — ưu tiên quan hệ semantic hơn COOCCURS_WITH / system relation."""
    raw = str(rel_type or "").strip().upper()
    if raw == "COOCCURS_WITH":
        return cooccur_w
    if raw in NON_SEMANTIC_RELATION_TYPES:
        return related_w
    rt = normalize_relation_type(rel_type)
    if rt == "RELATED_TO":
        return related_w
    return related_w * 1.25