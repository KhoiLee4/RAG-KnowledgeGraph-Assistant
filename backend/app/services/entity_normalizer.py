"""
entity_normalizer.py — Chuẩn hóa entity trước khi lưu Neo4j.

Pipeline: pronoun filter → alias map → fuzzy dedup → canonical merge.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Static alias map (normalized key → canonical display name) ─────────────

DEFAULT_ALIASES: dict[str, str] = {
    # Vietnam locations
    "tp hcm": "TP. Hồ Chí Minh",
    "tp ho chi minh": "TP. Hồ Chí Minh",
    "thanh pho ho chi minh": "TP. Hồ Chí Minh",
    "hcm": "TP. Hồ Chí Minh",
    "sai gon": "TP. Hồ Chí Minh",
    "ha noi": "Hà Nội",
    "tp ha noi": "Hà Nội",
    "thanh pho ha noi": "Hà Nội",
    "da nang": "Đà Nẵng",
    "tp da nang": "Đà Nẵng",
    "can tho": "Cần Thơ",
    "hai phong": "Hải Phòng",
    "tp hai phong": "Hải Phòng",
    # Countries
    "usa": "Hoa Kỳ",
    "us": "Hoa Kỳ",
    "hoa ky": "Hoa Kỳ",
    "united states": "Hoa Kỳ",
    "uk": "Vương quốc Anh",
    "anh quoc": "Vương quốc Anh",
    # Tech orgs
    "openai": "OpenAI",
    "open ai": "OpenAI",
    "google": "Google",
    "microsoft": "Microsoft",
    "meta": "Meta",
    "facebook": "Meta",
    "anthropic": "Anthropic",
    # RAG / AI concepts
    "rag": "RAG",
    "llm": "LLM",
    "graphrag": "GraphRAG",
    "knowledge graph": "Knowledge Graph",
}

# ── Vietnamese pronouns / generic terms to block (normalized) ─────────────────

PRONOUN_BLOCKLIST: frozenset[str] = frozenset({
    # 1st person
    "toi", "tao", "minh", "ta", "chung toi", "chung ta",
    # 2nd person
    "ban", "anh", "chi", "em", "ong", "ba", "co", "chu", "bac",
    # 3rd person
    "ho", "no", "y", "nguoi ta", "han", "ay", "kia",
    # Demonstratives
    "nay", "do", "day",
})

GENERIC_OTHER_BLOCKLIST: frozenset[str] = frozenset({
    "nguoi", "cong ty", "to chuc", "he thong",
})


@dataclass
class CanonicalEntry:
    canonical_name: str
    canonical_norm: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)


class CanonicalRegistry:
    """Registry in-memory để dedupe entity xuyên chunk trong một lần build graph."""

    def __init__(self) -> None:
        self._by_norm: dict[str, CanonicalEntry] = {}

    def get(self, canonical_norm: str) -> CanonicalEntry | None:
        return self._by_norm.get(canonical_norm)

    def register(
        self,
        canonical_name: str,
        canonical_norm: str,
        entity_type: str,
        raw_name: str,
    ) -> CanonicalEntry:
        entry = self._by_norm.get(canonical_norm)
        if entry is None:
            entry = CanonicalEntry(
                canonical_name=canonical_name,
                canonical_norm=canonical_norm,
                entity_type=entity_type,
                aliases=[raw_name] if raw_name != canonical_name else [],
            )
            self._by_norm[canonical_norm] = entry
            return entry

        if raw_name and raw_name not in entry.aliases and raw_name != entry.canonical_name:
            entry.aliases.append(raw_name)
        return entry

    def entries_for_type(self, entity_type: str) -> list[CanonicalEntry]:
        return [e for e in self._by_norm.values() if e.entity_type == entity_type]

    def all_entries(self) -> list[CanonicalEntry]:
        return list(self._by_norm.values())


class EntityNormalizer:
    """Chuẩn hóa entity raw từ Gemini thành canonical form."""

    def __init__(
        self,
        fuzzy_threshold: int | None = None,
        alias_map: dict[str, str] | None = None,
    ) -> None:
        self.fuzzy_threshold = fuzzy_threshold or settings.ENTITY_FUZZY_THRESHOLD
        self._alias_map = alias_map if alias_map is not None else self._load_alias_map()

    @staticmethod
    def _load_alias_map() -> dict[str, str]:
        path = Path(settings.ENTITY_ALIAS_MAP_PATH)
        if not path.is_file():
            return dict(DEFAULT_ALIASES)
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception as e:
            logger.warning("Không đọc được alias map %s: %s — dùng mặc định.", path, e)
        return dict(DEFAULT_ALIASES)

    @staticmethod
    def normalize_name(name: str) -> str:
        """Lowercase, bỏ dấu, chuẩn hóa dấu câu → khoảng trắng."""
        nfkd = unicodedata.normalize("NFKD", name.lower().strip())
        ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
        ascii_name = re.sub(r"[^\w\s]", " ", ascii_name)
        return re.sub(r"\s+", " ", ascii_name).strip()

    @staticmethod
    def build_entity_id(canonical_norm: str, owner_id: str | None) -> str:
        if owner_id:
            return f"{owner_id}__{canonical_norm}"
        return f"entity__{canonical_norm}"

    def is_blocked_entity(self, name: str, entity_type: str) -> bool:
        """Lọc đại từ / từ generic không phải proper noun."""
        stripped = name.strip()
        if not stripped or len(stripped) < 2:
            return True

        norm = self.normalize_name(stripped)
        if not norm:
            return True

        # Chỉ chặn token đơn khớp blocklist (giữ "Bà Rịa-Vũng Tàu", "ông Nguyễn Văn A")
        if " " not in norm and norm in PRONOUN_BLOCKLIST:
            return True

        ent_type = str(entity_type or "OTHER").upper()
        if ent_type == "PERSON" and norm in PRONOUN_BLOCKLIST:
            return True
        if ent_type == "OTHER" and norm in GENERIC_OTHER_BLOCKLIST:
            return True

        return False

    def _lookup_alias(self, name_norm: str) -> str | None:
        if name_norm in self._alias_map:
            return self._alias_map[name_norm]
        # Thử không khoảng trắng: "openai" từ alias key đã normalize
        compact = name_norm.replace(" ", "")
        for key, canonical in self._alias_map.items():
            if key.replace(" ", "") == compact:
                return canonical
        return None

    def _fuzzy_match(
        self,
        name_norm: str,
        entity_type: str,
        registry: CanonicalRegistry | None,
        chunk_candidates: list[CanonicalEntry],
    ) -> CanonicalEntry | None:
        if len(name_norm) < 4:
            return None

        try:
            from thefuzz import fuzz
        except ImportError:
            logger.warning("thefuzz chưa cài — bỏ qua fuzzy dedup.")
            return None

        threshold = self.fuzzy_threshold
        ent_type = str(entity_type or "OTHER").upper()
        candidates: list[CanonicalEntry] = list(chunk_candidates)
        if registry:
            candidates.extend(registry.entries_for_type(ent_type))

        seen_norms: set[str] = set()
        best_entry: CanonicalEntry | None = None
        best_score = 0

        for entry in candidates:
            if entry.entity_type != ent_type:
                continue
            if entry.canonical_norm in seen_norms:
                continue
            seen_norms.add(entry.canonical_norm)

            score = fuzz.token_sort_ratio(name_norm, entry.canonical_norm)
            if score >= threshold and score > best_score:
                best_score = score
                best_entry = entry

        if best_entry:
            logger.debug(
                "Fuzzy match '%s' → '%s' (score=%d)",
                name_norm,
                best_entry.canonical_name,
                best_score,
            )
        return best_entry

    def resolve_canonical(
        self,
        name: str,
        entity_type: str,
        *,
        registry: CanonicalRegistry | None = None,
        chunk_candidates: list[CanonicalEntry] | None = None,
    ) -> tuple[str, str] | None:
        """
        Trả về (canonical_name, canonical_norm) hoặc None nếu bị lọc.
        """
        raw = name.strip()
        if self.is_blocked_entity(raw, entity_type):
            logger.debug("Blocked entity: '%s' (%s)", raw, entity_type)
            return None

        name_norm = self.normalize_name(raw)
        ent_type = str(entity_type or "OTHER").upper()

        alias_hit = self._lookup_alias(name_norm)
        if alias_hit:
            canonical_name = alias_hit
        else:
            fuzzy_hit = self._fuzzy_match(
                name_norm,
                ent_type,
                registry,
                chunk_candidates or [],
            )
            if fuzzy_hit:
                canonical_name = fuzzy_hit.canonical_name
            else:
                canonical_name = raw

        canonical_norm = self.normalize_name(canonical_name)
        return canonical_name, canonical_norm

    def normalize_entities(
        self,
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        *,
        registry: CanonicalRegistry | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
        """
        Chuẩn hóa entities + rewrite relations.

        Returns:
            (normalized_entities, normalized_relations, raw_to_canonical_map)
        """
        raw_to_canonical: dict[str, str] = {}
        chunk_candidates: list[CanonicalEntry] = []
        by_norm: dict[str, dict[str, Any]] = {}

        for ent in entities:
            raw_name = str(ent.get("name", "")).strip()
            if not raw_name:
                continue

            ent_type = str(ent.get("type", "OTHER")).upper()
            resolved = self.resolve_canonical(
                raw_name,
                ent_type,
                registry=registry,
                chunk_candidates=chunk_candidates,
            )
            if resolved is None:
                continue

            canonical_name, canonical_norm = resolved
            raw_to_canonical[raw_name] = canonical_name
            raw_to_canonical[raw_name.lower()] = canonical_name

            description = str(ent.get("description", "")).strip()

            if canonical_norm in by_norm:
                existing = by_norm[canonical_norm]
                if raw_name not in existing["aliases"] and raw_name != canonical_name:
                    existing["aliases"].append(raw_name)
                if len(description) > len(existing.get("description", "")):
                    existing["description"] = description
                continue

            normalized = {
                "raw_name": raw_name,
                "name": canonical_name,
                "canonical_name": canonical_name,
                "name_norm": canonical_norm,
                "type": ent_type,
                "description": description,
                "aliases": [raw_name] if raw_name != canonical_name else [],
            }
            by_norm[canonical_norm] = normalized

            entry = CanonicalEntry(
                canonical_name=canonical_name,
                canonical_norm=canonical_norm,
                entity_type=ent_type,
                aliases=list(normalized["aliases"]),
            )
            chunk_candidates.append(entry)

            if registry:
                reg_entry = registry.register(
                    canonical_name, canonical_norm, ent_type, raw_name
                )
                normalized["aliases"] = list(
                    dict.fromkeys(normalized["aliases"] + reg_entry.aliases)
                )

        normalized_entities = list(by_norm.values())

        normalized_relations: list[dict[str, Any]] = []
        for rel in relations:
            from_raw = str(rel.get("from", "")).strip()
            to_raw = str(rel.get("to", "")).strip()
            if not from_raw or not to_raw:
                continue

            from_canon = raw_to_canonical.get(from_raw) or raw_to_canonical.get(
                from_raw.lower()
            )
            to_canon = raw_to_canonical.get(to_raw) or raw_to_canonical.get(
                to_raw.lower()
            )
            if not from_canon or not to_canon or from_canon == to_canon:
                continue

            normalized_relations.append({
                "from": from_canon,
                "to": to_canon,
                "relation": rel.get("relation", "RELATED_TO"),
                "description": str(rel.get("description", "")),
            })

        return normalized_entities, normalized_relations, raw_to_canonical


_default_normalizer: EntityNormalizer | None = None


def get_entity_normalizer() -> EntityNormalizer:
    global _default_normalizer
    if _default_normalizer is None:
        _default_normalizer = EntityNormalizer()
    return _default_normalizer
