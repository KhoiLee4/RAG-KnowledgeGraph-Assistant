"""
hybrid_retrieval_service.py — Full hybrid retrieval: analyzer → router → fusion.

Kết hợp Community summary + Graph facts + Vector chunks cho ChatService.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.services.citation_formatter import format_location_label
from app.services.community_service import get_community_service
from app.services.graph_service import GraphService
from app.services.query_analyzer import QueryAnalysis, get_query_analyzer, is_relationship_query
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    s = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _entity_mentioned_in_query(entity_name: str, query: str) -> bool:
    """Kiểm tra tên entity có xuất hiện trong câu hỏi (tránh quan hệ graph nhiễu)."""
    en = _normalize_text(entity_name)
    qn = _normalize_text(query)
    if not en or not qn:
        return False
    if en in qn:
        return True
    return any(len(tok) >= 4 and tok in qn for tok in en.split())


@dataclass
class RetrievalBundle:
    """Kết quả retrieval đầy đủ trước khi đưa vào Gemini."""

    context: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    vector_chunks: list[dict[str, Any]] = field(default_factory=list)
    graph_facts_text: str = ""
    community_summaries: list[dict[str, Any]] = field(default_factory=list)
    query_type: str = "combined"
    route: str = ""
    analysis: QueryAnalysis | None = None

    @property
    def is_empty(self) -> bool:
        return not self.context.strip()


class HybridRetrievalService:
    """Query-type-aware retrieval orchestrator."""

    def __init__(self) -> None:
        self._analyzer = get_query_analyzer()
        self._retrieval = RetrievalService()
        self._graph = GraphService()
        self._community = get_community_service()

    def _budgets(self, query_type: str) -> dict[str, int]:
        total = settings.RETRIEVAL_CONTEXT_MAX_CHARS
        if query_type == "factual":
            return {"community": 800, "graph": 2000, "vector": total - 2800}
        if query_type == "descriptive":
            return {"community": 1500, "graph": 500, "vector": total - 2000}
        return {"community": 1000, "graph": 1500, "vector": total - 2500}

    def _build_community_section(
        self,
        communities: list[dict[str, Any]],
        ref_start: int,
        max_chars: int,
    ) -> tuple[str, list[dict[str, Any]], int]:
        if not communities:
            return "", [], ref_start

        lines = ["=== TỔNG QUAN CHỦ ĐỀ (COMMUNITY) ===", ""]
        citations: list[dict[str, Any]] = []
        ref = ref_start

        for comm in communities:
            summary = str(comm.get("summary") or "").strip()
            if not summary:
                continue
            members = comm.get("member_names") or comm.get("members") or []
            member_label = f"{comm.get('member_count', len(members))} entities"
            entry = f"[{ref}] {summary}\n(Community — {member_label})"
            if len("\n".join(lines) + entry) > max_chars:
                entry = entry[: max_chars - len("\n".join(lines))] + "..."
            lines.append(entry)
            lines.append("")
            citations.append({
                "source_type": "community",
                "community_id": comm.get("id", ""),
                "summary_preview": summary[:200],
                "member_count": str(comm.get("member_count", 0)),
                "score": f"{comm.get('score', 0):.3f}",
                "file_name": f"Community ({member_label})",
                "chunk_index": "0",
                "drive_link": "",
                "page_estimate": "0",
                "source": "community",
            })
            ref += 1
            break  # one primary community in context

        return "\n".join(lines).strip(), citations, ref

    def _filter_graph_relations(
        self,
        relations: list[dict[str, Any]],
        query: str,
        query_type: str,
    ) -> list[dict[str, Any]]:
        if query_type in ("relationship", "combined"):
            return relations
        filtered: list[dict[str, Any]] = []
        for rel in relations:
            frm = str(rel.get("from", ""))
            to = str(rel.get("to", ""))
            if _entity_mentioned_in_query(frm, query) or _entity_mentioned_in_query(
                to, query
            ):
                filtered.append(rel)
        return filtered

    def _build_graph_section(
        self,
        path_relations: list[dict[str, Any]],
        graph_facts: dict[str, Any],
        ref_start: int,
        max_chars: int,
        query: str = "",
        query_type: str = "combined",
    ) -> tuple[str, list[dict[str, Any]], int]:
        fact_relations = self._filter_graph_relations(
            graph_facts.get("relations") or [], query, query_type
        )
        relations = path_relations + fact_relations
        chunk_refs = graph_facts.get("chunk_refs") or []

        if not relations:
            return "", [], ref_start

        lines = ["=== QUAN HỆ & SỰ THẬT (GRAPH) ===", ""]
        citations: list[dict[str, Any]] = []
        ref = ref_start
        seen_rel: set[str] = set()

        for rel in relations[:10]:
            rel_key = f"{rel.get('from', '')}|{rel.get('to', '')}|{rel.get('rel_type', '')}"
            if rel_key in seen_rel:
                continue
            seen_rel.add(rel_key)

            desc = str(rel.get("description", "")).strip()
            rel_type = str(rel.get("rel_type", "RELATED_TO")).replace("_", " ").lower()
            line = f"[{ref}] {rel.get('from', '')} — {rel_type} → {rel.get('to', '')}"
            if desc:
                line += f" ({desc})"

            if len("\n".join(lines) + line) > max_chars:
                break

            lines.append(line)
            lines.append("")

            source_file = ""
            drive_link = ""
            file_id = ""
            for cref in chunk_refs:
                fn = str(cref.get("file_name", ""))
                if fn:
                    source_file = fn
                    drive_link = str(cref.get("drive_link", ""))
                    cid = str(cref.get("chunk_id", ""))
                    if "__chunk_" in cid:
                        file_id = cid.split("__chunk_")[0]
                    break

            citations.append({
                "source_type": "graph",
                "ref": ref,
                "file_name": f"{rel.get('from', '')} → {rel.get('to', '')}",
                "drive_link": drive_link,
                "file_id": file_id,
                "page_estimate": "0",
                "score": "1.000",
                "source": "graph",
                "relation": rel_type,
                "snippet": desc,
                "source_file": source_file,
            })
            ref += 1

        return "\n".join(lines).strip(), citations, ref

    def _build_vector_section(
        self,
        chunks: list[dict[str, Any]],
        ref_start: int,
        max_chars: int,
    ) -> tuple[str, list[dict[str, Any]], int]:
        if not chunks:
            return "", [], ref_start

        lines = ["=== ĐOẠN VĂN BẢN TÀI LIỆU (VECTOR) ===", ""]
        citations: list[dict[str, Any]] = []
        ref = ref_start
        total = 0

        for chunk in chunks:
            location = format_location_label(
                chunk.get("page_estimate"),
                chunk.get("line_start"),
                chunk.get("line_end"),
            )
            header = f"[{ref}] Nguồn: {chunk.get('file_name', 'Unknown')}"
            if location:
                header += f" ({location})"
            body = str(chunk.get("text", ""))
            entry = f"{header}\n{body}"
            if total + len(entry) > max_chars:
                remain = max_chars - total
                if remain > 200:
                    entry = entry[:remain] + "...[truncated]"
                    lines.append(entry)
                    citations.append(self._chunk_citation(chunk, ref))
                    ref += 1
                break
            lines.append(entry)
            lines.append("")
            citations.append(self._chunk_citation(chunk, ref))
            ref += 1
            total += len(entry)

        return "\n".join(lines).strip(), citations, ref

    @staticmethod
    def _chunk_citation(chunk: dict[str, Any], ref: int) -> dict[str, Any]:
        return {
            "source_type": chunk.get("source", "vector"),
            "ref": ref,
            "file_name": chunk.get("file_name", ""),
            "file_id": chunk.get("file_id", ""),
            "chunk_index": str(chunk.get("chunk_index", 0)),
            "drive_link": chunk.get("drive_link", ""),
            "page_estimate": str(chunk.get("page_estimate", 1)),
            "line_start": str(chunk.get("line_start", 0) or 0),
            "line_end": str(chunk.get("line_end", 0) or 0),
            "score": f"{chunk.get('score', chunk.get('combined_score', 0)):.3f}",
            "source": chunk.get("source", "vector"),
            "snippet": str(chunk.get("text", ""))[:200],
        }

    def _fuse_context(
        self,
        query_type: str,
        community_text: str,
        graph_text: str,
        vector_text: str,
    ) -> str:
        sections: list[str] = []
        if query_type == "factual":
            order = [vector_text, graph_text, community_text]
        elif query_type == "descriptive":
            order = [community_text, vector_text, graph_text]
        else:
            order = [community_text, graph_text, vector_text]

        for section in order:
            if section and section.strip():
                sections.append(section.strip())

        return "\n\n---\n\n".join(sections)

    def retrieve_all(
        self,
        query: str,
        collection_name: str | None = None,
        owner_id: str | None = None,
        n_results: int | None = None,
        retrieval_mode: str = "rag",
    ) -> RetrievalBundle:
        """Full pipeline: classify → route → retrieve → fuse."""
        col = collection_name or settings.CHROMA_DEFAULT_COLLECTION
        default_k = n_results or settings.RETRIEVAL_TOP_K

        if retrieval_mode == "rag" or not settings.GRAPH_ENABLED:
            chunks = self._retrieval.retrieve(query, col, n_results=default_k)
            context = self._retrieval.format_context(chunks)
            citations = [self._chunk_citation(c, i + 1) for i, c in enumerate(chunks)]
            return RetrievalBundle(
                context=context,
                citations=citations,
                vector_chunks=chunks,
                route="rag_only",
                query_type="combined",
            )

        analysis = self._analyzer.classify(query)
        qtype = analysis.query_type
        alpha = self._analyzer.alpha_for_type(qtype)
        top_k = self._analyzer.vector_top_k(qtype, default_k)
        budgets = self._budgets(qtype)

        entity_norms = self._graph.resolve_query_entity_norms(
            query,
            owner_id=owner_id,
            use_gemini_fallback=(qtype == "factual"),
        )

        if len(entity_norms) < 2 and (
            is_relationship_query(query) or qtype == "factual"
        ):
            entity_norms = self._graph.resolve_query_entity_norms(
                query,
                owner_id=owner_id,
                use_gemini_fallback=True,
            )

        path_data: dict[str, Any] = {"text": "", "paths": [], "relations": []}
        if len(entity_norms) >= 2:
            path_data = self._graph.find_entity_paths(entity_norms, owner_id=owner_id)

        communities: list[dict[str, Any]] = []
        if owner_id and qtype in ("descriptive", "combined"):
            communities = self._community.find_relevant_communities(
                query, owner_id, entity_norms=entity_norms, limit=2
            )
        elif owner_id and qtype == "factual" and entity_norms:
            communities = self._community.find_relevant_communities(
                query, owner_id, entity_norms=entity_norms, limit=1
            )

        graph_facts = {"text": "", "relations": [], "chunk_refs": []}
        if qtype in ("factual", "combined") and entity_norms:
            graph_facts = self._graph.get_graph_facts(entity_norms, owner_id=owner_id)
        elif qtype == "descriptive" and entity_norms:
            graph_facts = self._graph.get_graph_facts(
                entity_norms, owner_id=owner_id, limit=15
            )

        path_relations = path_data.get("relations") or []

        vector_chunks: list[dict[str, Any]] = []
        if settings.GRAPH_ENABLED:
            vector_chunks = self._graph.hybrid_retrieve(
                query=query,
                collection_name=col,
                n_results=top_k,
                alpha=alpha,
                owner_id=owner_id,
                entity_norms=entity_norms or None,
                use_gemini_entities=False,
            )
            if vector_chunks and entity_norms:
                for chunk in vector_chunks:
                    chunk.setdefault("source", "hybrid")
        else:
            vector_chunks = self._retrieval.retrieve(query, col, n_results=top_k)

        if not vector_chunks and qtype == "descriptive" and owner_id:
            vector_chunks = self._retrieval.retrieve(query, col, n_results=top_k)

        ref = 1
        if qtype == "factual":
            vec_text, vec_cites, ref = self._build_vector_section(
                vector_chunks, ref, budgets["vector"]
            )
            graph_text, graph_cites, ref = self._build_graph_section(
                path_relations, graph_facts, ref, budgets["graph"], query, qtype
            )
            comm_text, comm_cites, ref = self._build_community_section(
                communities, ref, budgets["community"]
            )
            all_citations = vec_cites + graph_cites + comm_cites
        else:
            comm_text, comm_cites, ref = self._build_community_section(
                communities, ref, budgets["community"]
            )
            graph_text, graph_cites, ref = self._build_graph_section(
                path_relations, graph_facts, ref, budgets["graph"], query, qtype
            )
            vec_text, vec_cites, _ = self._build_vector_section(
                vector_chunks, ref, budgets["vector"]
            )
            all_citations = comm_cites + graph_cites + vec_cites

        fused = self._fuse_context(qtype, comm_text, graph_text, vec_text)

        bundle = RetrievalBundle(
            context=fused,
            citations=all_citations,
            vector_chunks=vector_chunks,
            graph_facts_text=graph_text,
            community_summaries=communities,
            query_type=qtype,
            route=f"hybrid_{qtype}_alpha{alpha}",
            analysis=analysis,
        )

        logger.info(
            "HybridRetrieval '%s...' type=%s alpha=%.2f chunks=%d communities=%d graph_facts=%s",
            query[:50],
            qtype,
            alpha,
            len(vector_chunks),
            len(communities),
            bool(graph_text),
        )
        return bundle


_instance: HybridRetrievalService | None = None


def get_hybrid_retrieval_service() -> HybridRetrievalService:
    global _instance
    if _instance is None:
        _instance = HybridRetrievalService()
    return _instance
