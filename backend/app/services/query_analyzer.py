"""
query_analyzer.py — Phân loại câu hỏi (factual / descriptive / combined) bằng keyword.
Không gọi LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.services.entity_normalizer import EntityNormalizer

QueryType = Literal["factual", "descriptive", "combined"]

FACTUAL_PATTERNS: tuple[str, ...] = (
    r"\bai\b", r"\blà ai\b", r"\bwho\b",
    r"\bkhi nào\b", r"\bngày\b", r"\bwhen\b",
    r"\bở đâu\b", r"\bo dau\b", r"\bwhere\b",
    r"\bbao nhiêu\b", r"\bmấy\b", r"\bhow many\b", r"\bwhich\b",
    r"\blà gì\b", r"\bla gi\b", r"\bwhat is\b", r"\bwhat are\b", r"\bdefine\b",
    r"\bliên quan\b", r"\blen quan\b", r"\bquan hệ\b", r"\bquan he\b",
    r"\brelated\b", r"\bbelongs\b", r"\bthuộc\b", r"\bthuoc\b",
    r"\blà ai là\b", r"\bcông ty nào\b", r"\bcong ty nao\b",
    r"\bwhich company\b", r"\bwhich organization\b",
)

RELATIONSHIP_PATTERNS: tuple[str, ...] = (
    r"\bla gi cua nhau\b", r"\blà gì của nhau\b",
    r"\bquan he giua\b", r"\bquan hệ giữa\b",
    r"\bmoi quan he\b", r"\bmối quan hệ\b",
    r"\blien quan gi\b", r"\bliên quan gì\b",
    r"\brelationship between\b", r"\bhow are .+ related\b",
    r"\brelated to each other\b", r"\bconnection between\b",
    r"\bco lien quan gi\b", r"\bcó liên quan gì\b",
)

DESCRIPTIVE_PATTERNS: tuple[str, ...] = (
    r"\btóm tắt\b", r"\btom tat\b", r"\bsummarize\b", r"\bsummary\b",
    r"\btổng quan\b", r"\btong quan\b", r"\boverview\b",
    r"\bmô tả\b", r"\bmo ta\b", r"\bdescribe\b", r"\bdescription\b",
    r"\bgiải thích\b", r"\bgiai thich\b", r"\bexplain\b",
    r"\bphân tích\b", r"\bphan tich\b", r"\banalyze\b",
    r"\bchủ đề\b", r"\bchu de\b", r"\btopic\b", r"\btheme\b",
    r"\blĩnh vực\b", r"\blinh vuc\b", r"\bsubject\b",
    r"\bxu hướng\b", r"\bxu huong\b", r"\btrend\b",
    r"\bbức tranh\b", r"\bbig picture\b",
    r"\bso sánh\b", r"\bso sanh\b", r"\bcompare\b", r"\bdifference\b",
    r"\btại sao\b", r"\btai sao\b", r"\bvì sao\b", r"\bwhy\b",
    r"\bnói về gì\b", r"\bnoi ve gi\b", r"\babout what\b",
)

STOPWORDS: frozenset[str] = frozenset({
    "la", "là", "cua", "của", "toi", "tôi", "ban", "bạn", "trong", "the", "a", "an",
    "is", "are", "va", "và", "and", "or", "cho", "for", "ve", "về", "gi", "gì",
    "what", "how", "do", "does", "did", "my", "me", "your", "documents", "tai",
    "lieu", "tài", "liệu", "file", "files",
})


@dataclass
class QueryAnalysis:
    query_type: QueryType
    factual_score: int
    descriptive_score: int
    confidence: float
    entity_hint_count: int = 0


class QueryAnalyzer:
    """Keyword-based query classifier (Vietnamese + English)."""

    def __init__(self) -> None:
        self._normalizer = EntityNormalizer()

    @staticmethod
    def _normalize_query(query: str) -> str:
        return EntityNormalizer.normalize_name(query)

    def _score_patterns(self, text: str, patterns: tuple[str, ...]) -> int:
        score = 0
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                score += 1
        return score

    def _count_entity_hints(self, query: str) -> int:
        """Đếm token dài có vẻ là proper noun / entity."""
        norm = self._normalize_query(query)
        tokens = [t for t in norm.split() if t not in STOPWORDS and len(t) >= 3]
        hints = 0
        for tok in tokens:
            if tok.isupper() or len(tok) >= 5:
                hints += 1
            resolved = self._normalizer.resolve_canonical(tok, "OTHER")
            if resolved and resolved[0].lower() != tok:
                hints += 1
        return hints

    def classify(self, query: str) -> QueryAnalysis:
        raw = query.strip()
        norm = self._normalize_query(raw)

        factual = self._score_patterns(norm, FACTUAL_PATTERNS)
        descriptive = self._score_patterns(norm, DESCRIPTIVE_PATTERNS)
        entity_hints = self._count_entity_hints(raw)

        if entity_hints >= 1:
            factual += 1

        if factual >= 2 and descriptive >= 2:
            qtype: QueryType = "combined"
        elif abs(factual - descriptive) <= 1 and factual >= 1 and descriptive >= 1:
            qtype = "combined"
        elif descriptive >= 2 and factual <= 1:
            qtype = "descriptive"
        elif factual > descriptive:
            qtype = "factual"
        elif descriptive > factual:
            qtype = "descriptive"
        else:
            qtype = "combined"

        total = max(factual + descriptive, 1)
        confidence = min(1.0, abs(factual - descriptive) / total + 0.3)

        return QueryAnalysis(
            query_type=qtype,
            factual_score=factual,
            descriptive_score=descriptive,
            confidence=round(confidence, 3),
            entity_hint_count=entity_hints,
        )

    @staticmethod
    def alpha_for_type(query_type: QueryType) -> float:
        """Trọng số vector trong hybrid chunk merge."""
        return {
            "factual": 0.3,
            "descriptive": 0.85,
            "combined": 0.6,
        }.get(query_type, 0.6)

    @staticmethod
    def vector_top_k(query_type: QueryType, default: int) -> int:
        return {
            "factual": min(default, 3),
            "descriptive": max(default, 7),
            "combined": default,
        }.get(query_type, default)


def is_relationship_query(query: str) -> bool:
    """Câu hỏi hỏi quan hệ giữa hai entity trở lên."""
    norm = EntityNormalizer.normalize_name(query)
    for pat in RELATIONSHIP_PATTERNS:
        if re.search(pat, norm, re.IGNORECASE):
            return True
    return False


_default_analyzer: QueryAnalyzer | None = None


def get_query_analyzer() -> QueryAnalyzer:
    global _default_analyzer
    if _default_analyzer is None:
        _default_analyzer = QueryAnalyzer()
    return _default_analyzer
