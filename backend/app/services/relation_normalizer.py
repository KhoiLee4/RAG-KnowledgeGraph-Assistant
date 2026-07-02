"""
relation_normalizer.py — Map relation type tự do (LLM) về CANONICAL set bằng embedding.

Pipeline khi persist quan hệ:
  1. Chuẩn hóa cú pháp (rẻ): clean + alias tĩnh → nếu đã là canonical thì dùng luôn.
  2. Nếu vẫn là loại lạ: embed tên quan hệ, so cosine với các canonical (đã cache),
     lấy loại gần nhất nếu >= ngưỡng, ngược lại fallback RELATED_TO.

Lưu ý chi phí:
  - Embedding của N canonical được tính 1 lần rồi cache (không gọi lại mỗi lần).
  - Kết quả map của mỗi tên lạ cũng được cache trong phiên → chỉ 1 lần embed / tên mới.
  - Có thể tắt hoàn toàn embedding qua settings.RELATION_NORMALIZE_USE_EMBEDDING.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from app.core.config import settings
from app.services.graph_schema import (
    CANONICAL_RELATION_TYPES,
    normalize_relation_type,
)

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class RelationNormalizer:
    """Chuẩn hóa relation type về canonical set (alias tĩnh + embedding fallback)."""

    def __init__(
        self,
        embedder: Any | None = None,
        threshold: float | None = None,
        use_embedding: bool | None = None,
    ) -> None:
        self._embedder = embedder
        self.threshold = (
            threshold if threshold is not None else settings.RELATION_CANONICAL_THRESHOLD
        )
        self.use_embedding = (
            settings.RELATION_NORMALIZE_USE_EMBEDDING
            if use_embedding is None
            else use_embedding
        )
        self._canonical_set = frozenset(CANONICAL_RELATION_TYPES)
        self._canon_vecs: dict[str, list[float]] | None = None
        self._cache: dict[str, str] = {}

    def _get_embedder(self) -> Any:
        if self._embedder is None:
            from app.services.embedding_service import EmbeddingService

            self._embedder = EmbeddingService()
        return self._embedder

    @staticmethod
    def _humanize(rel: str) -> str:
        return rel.replace("_", " ").lower().strip()

    def _ensure_canon_vecs(self) -> None:
        if self._canon_vecs is not None:
            return
        names = list(CANONICAL_RELATION_TYPES)
        vecs = self._get_embedder().embed_batch([self._humanize(n) for n in names])
        if len(vecs) != len(names):
            raise RuntimeError("Số vector canonical không khớp số loại.")
        self._canon_vecs = dict(zip(names, vecs))

    def to_canonical(self, raw: str) -> str:
        """Trả về canonical relation type cho một tên quan hệ bất kỳ."""
        key = normalize_relation_type(raw)
        if key in self._canonical_set:
            return key
        if key in self._cache:
            return self._cache[key]

        result = self._embed_match(key) if self.use_embedding else "RELATED_TO"
        self._cache[key] = result
        return result

    def _embed_match(self, key: str) -> str:
        try:
            self._ensure_canon_vecs()
            vec = self._get_embedder().embed_text(self._humanize(key))
        except Exception as e:
            logger.warning(
                "RelationNormalizer: embed '%s' lỗi (%s) — fallback RELATED_TO.", key, e
            )
            return "RELATED_TO"

        best_type, best_score = "RELATED_TO", -1.0
        for name, cvec in (self._canon_vecs or {}).items():
            score = _cosine(vec, cvec)
            if score > best_score:
                best_type, best_score = name, score

        if best_score >= self.threshold:
            logger.debug("Relation '%s' → '%s' (cos=%.3f)", key, best_type, best_score)
            return best_type

        logger.debug(
            "Relation '%s' không đạt ngưỡng (best=%s cos=%.3f) → RELATED_TO.",
            key, best_type, best_score,
        )
        return "RELATED_TO"


_default_relation_normalizer: RelationNormalizer | None = None


def get_relation_normalizer() -> RelationNormalizer:
    global _default_relation_normalizer
    if _default_relation_normalizer is None:
        _default_relation_normalizer = RelationNormalizer()
    return _default_relation_normalizer
