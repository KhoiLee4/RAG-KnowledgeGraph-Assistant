"""
community_service.py — Louvain community detection + Gemini summary.

Chạy sau sync-all (per owner_id): export Entity graph → NetworkX → Louvain
→ summarize → lưu Community nodes + BELONGS_TO vào Neo4j.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import networkx as nx

from app.core.config import settings
from app.db.neo4j_client import get_neo4j_client

logger = logging.getLogger(__name__)

COMMUNITY_SUMMARY_PROMPT = """Bạn là chuyên gia tổng hợp tri thức. Dựa trên nhóm thực thể và quan hệ sau,
viết 2-3 câu tiếng Việt mô tả chủ đề chung của cộng đồng này.
Không liệt kê lại tên thực thể. Không dùng markdown hay bullet.

Thực thể:
{entities_block}

Quan hệ:
{relations_block}
"""


@dataclass
class CommunityBundle:
    """Một community sau partition + merge."""

    member_ids: list[str] = field(default_factory=list)
    member_nodes: list[dict[str, Any]] = field(default_factory=list)
    internal_edges: list[dict[str, Any]] = field(default_factory=list)


class CommunityService:
    """Phát hiện community trên KG và tạo summary bằng Gemini."""

    def __init__(self) -> None:
        self._neo4j = get_neo4j_client()
        self._gemini_client = None

    def _get_gemini(self):
        if self._gemini_client is None:
            from google import genai
            self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._gemini_client

    # ── Export Neo4j → NetworkX ───────────────────────────────

    def export_entity_graph(self, owner_id: str) -> nx.Graph:
        """Export Entity subgraph của owner thành NetworkX Graph (undirected)."""
        G = nx.Graph()

        node_records = self._neo4j.run_cypher(
            """
            MATCH (e:Entity {owner_id: $owner_id})
            RETURN e.id AS id, e.name AS name, e.type AS type,
                   coalesce(e.description, '') AS description,
                   coalesce(e.name_norm, '') AS name_norm
            """,
            {"owner_id": owner_id},
        )
        for rec in node_records:
            nid = rec.get("id")
            if not nid:
                continue
            G.add_node(
                nid,
                name=rec.get("name", ""),
                type=rec.get("type", "OTHER"),
                description=rec.get("description", ""),
                name_norm=rec.get("name_norm", ""),
            )

        edge_records = self._neo4j.run_cypher(
            """
            MATCH (a:Entity {owner_id: $owner_id})-[r:RELATED_TO|COOCCURS_WITH]-(b:Entity {owner_id: $owner_id})
            WHERE elementId(a) < elementId(b)
            RETURN a.id AS source_id, b.id AS target_id,
                   type(r) AS rel_type,
                   coalesce(r.description, '') AS description
            """,
            {"owner_id": owner_id},
        )

        related_w = settings.COMMUNITY_RELATED_WEIGHT
        cooccur_w = settings.COMMUNITY_COOCCUR_WEIGHT

        for rec in edge_records:
            src = rec.get("source_id")
            tgt = rec.get("target_id")
            if not src or not tgt or src == tgt:
                continue
            if src not in G or tgt not in G:
                continue

            rel_type = str(rec.get("rel_type", "COOCCURS_WITH"))
            w = related_w if rel_type == "RELATED_TO" else cooccur_w

            if G.has_edge(src, tgt):
                G[src][tgt]["weight"] = G[src][tgt].get("weight", 0) + w
            else:
                G.add_edge(
                    src,
                    tgt,
                    weight=w,
                    rel_type=rel_type,
                    description=str(rec.get("description", "")),
                )

        logger.info(
            "[Community] export owner=%s: %d nodes, %d edges.",
            owner_id,
            G.number_of_nodes(),
            G.number_of_edges(),
        )
        return G

    # ── Louvain partition ─────────────────────────────────────

    def partition_communities(self, G: nx.Graph) -> dict[int, list[str]]:
        """Louvain → map community_id → [entity_id, ...]."""
        if G.number_of_nodes() < 2 or G.number_of_edges() == 0:
            return {}

        try:
            import community as community_louvain
        except ImportError as e:
            logger.error("python-louvain chưa cài: %s", e)
            return {}

        partition = community_louvain.best_partition(G, weight="weight")
        grouped: dict[int, list[str]] = defaultdict(list)
        for node_id, comm_id in partition.items():
            grouped[int(comm_id)].append(node_id)

        return dict(grouped)

    def _merge_small_communities(
        self,
        grouped: dict[int, list[str]],
        G: nx.Graph,
        min_size: int,
    ) -> dict[int, list[str]]:
        """Gộp community < min_size vào neighbor có tổng weight lớn nhất."""
        if not grouped:
            return {}

        result = {k: list(v) for k, v in grouped.items()}
        changed = True

        while changed:
            changed = False
            small_keys = [k for k, members in result.items() if len(members) < min_size]
            if not small_keys:
                break

            for key in sorted(small_keys, key=lambda k: len(result[k])):
                members = result.get(key, [])
                if not members or len(members) >= min_size:
                    continue

                best_target: int | None = None
                best_weight = 0.0

                for node in members:
                    if node not in G:
                        continue
                    for neighbor in G.neighbors(node):
                        for other_key, other_members in result.items():
                            if other_key == key:
                                continue
                            if neighbor in other_members:
                                edge_w = G[node][neighbor].get("weight", 1.0)
                                if edge_w > best_weight:
                                    best_weight = edge_w
                                    best_target = other_key

                if best_target is not None:
                    result[best_target].extend(members)
                    del result[key]
                    changed = True
                else:
                    # Isolated — remove from result (skip summarization)
                    del result[key]
                    changed = True

        return result

    def _build_bundles(
        self,
        grouped: dict[int, list[str]],
        G: nx.Graph,
    ) -> list[CommunityBundle]:
        bundles: list[CommunityBundle] = []
        min_size = settings.COMMUNITY_MIN_SIZE

        for members in grouped.values():
            if len(members) < min_size:
                continue

            member_set = set(members)
            nodes = []
            for mid in members:
                if mid in G:
                    nodes.append({"id": mid, **G.nodes[mid]})

            edges = []
            for u, v, data in G.edges(data=True):
                if u in member_set and v in member_set:
                    edges.append({
                        "from_id": u,
                        "to_id": v,
                        "from_name": G.nodes[u].get("name", u),
                        "to_name": G.nodes[v].get("name", v),
                        "rel_type": data.get("rel_type", "COOCCURS_WITH"),
                        "description": data.get("description", ""),
                    })

            bundles.append(CommunityBundle(
                member_ids=members,
                member_nodes=nodes,
                internal_edges=edges,
            ))

        return bundles

    # ── Gemini summary ────────────────────────────────────────

    @staticmethod
    def _format_entities_block(nodes: list[dict[str, Any]], limit: int = 15) -> str:
        lines: list[str] = []
        for n in nodes[:limit]:
            name = n.get("name", "?")
            etype = n.get("type", "OTHER")
            desc = str(n.get("description", ""))[:120].strip()
            line = f"- {name} [{etype}]"
            if desc:
                line += f": {desc}"
            lines.append(line)
        return "\n".join(lines) if lines else "(không có)"

    @staticmethod
    def _format_relations_block(edges: list[dict[str, Any]], limit: int = 20) -> str:
        lines: list[str] = []
        for e in edges[:limit]:
            desc = str(e.get("description", "")).strip()
            rel = e.get("rel_type", "RELATED_TO")
            line = f"- {e.get('from_name', '?')} —[{rel}]→ {e.get('to_name', '?')}"
            if desc:
                line += f" ({desc[:80]})"
            lines.append(line)
        return "\n".join(lines) if lines else "(không có quan hệ nội bộ)"

    def summarize_community(self, bundle: CommunityBundle) -> str:
        """Gọi Gemini tạo 2-3 câu summary cho một community."""
        from app.core.gemini_retry import call_with_gemini_retry
        from google.genai import types as genai_types

        entities_block = self._format_entities_block(bundle.member_nodes)
        relations_block = self._format_relations_block(bundle.internal_edges)
        prompt = COMMUNITY_SUMMARY_PROMPT.format(
            entities_block=entities_block,
            relations_block=relations_block,
        )
        client = self._get_gemini()

        def _call():
            return client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=prompt)],
                )],
                config=genai_types.GenerateContentConfig(temperature=0.2),
            )

        response = call_with_gemini_retry(_call, label="community_summary")
        text = (response.text or "").strip()
        return text[:2000] if text else ""

    # ── Persist Neo4j ─────────────────────────────────────────

    def _clean_stale_communities(self, owner_id: str) -> int:
        count_records = self._neo4j.run_cypher(
            "MATCH (c:Community {owner_id: $owner_id}) RETURN count(c) AS n",
            {"owner_id": owner_id},
        )
        deleted = count_records[0]["n"] if count_records else 0
        if deleted:
            self._neo4j.run_cypher(
                "MATCH (c:Community {owner_id: $owner_id}) DETACH DELETE c",
                {"owner_id": owner_id},
            )
            logger.info("[Community] Đã xóa %d Community cũ (owner=%s).", deleted, owner_id)
        return deleted

    def _persist_community(
        self,
        owner_id: str,
        bundle: CommunityBundle,
        summary: str,
    ) -> str:
        community_id = f"{owner_id}__community_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        props: dict[str, Any] = {
            "id": community_id,
            "owner_id": owner_id,
            "members": bundle.member_ids,
            "member_count": len(bundle.member_ids),
            "summary": summary,
            "created_at": now,
            "updated_at": now,
        }
        self._neo4j.merge_community_node(props)

        for entity_id in bundle.member_ids:
            self._neo4j.create_relationship(
                from_id=entity_id,
                to_id=community_id,
                relation_type="BELONGS_TO",
                from_label="Entity",
                to_label="Community",
            )

        return community_id

    # ── Main entry ────────────────────────────────────────────

    def detect_and_summarize(self, owner_id: str) -> dict[str, Any]:
        """
        Pipeline đầy đủ: export → Louvain → merge nhỏ → summary → persist.

        Best-effort: không raise; trả về stats.
        """
        stats: dict[str, Any] = {
            "status": "skipped",
            "communities_created": 0,
            "summaries_ok": 0,
            "summaries_failed": 0,
            "entities_in_communities": 0,
            "errors": 0,
            "message": "",
        }

        if not settings.GRAPH_ENABLED:
            stats["message"] = "GRAPH_ENABLED=false — bỏ qua community detection."
            return stats

        try:
            G = self.export_entity_graph(owner_id)
            if G.number_of_nodes() < 2:
                stats["message"] = "Không đủ entity để phát hiện community."
                return stats
            if G.number_of_edges() == 0:
                stats["message"] = "Không có quan hệ entity — bỏ qua Louvain."
                return stats

            raw_grouped = self.partition_communities(G)
            if not raw_grouped:
                stats["message"] = "Louvain không trả về partition."
                return stats

            merged = self._merge_small_communities(
                raw_grouped, G, settings.COMMUNITY_MIN_SIZE
            )
            bundles = self._build_bundles(merged, G)
            if not bundles:
                stats["message"] = "Không có community đủ lớn sau merge."
                return stats

            self._clean_stale_communities(owner_id)

            from app.core.gemini_retry import is_daily_quota_exhausted

            quota_stopped = False
            pause = max(0.0, settings.COMMUNITY_SUMMARY_PAUSE)

            for i, bundle in enumerate(bundles):
                summary = ""
                try:
                    if not quota_stopped:
                        summary = self.summarize_community(bundle)
                        stats["summaries_ok"] += 1
                except Exception as e:
                    stats["summaries_failed"] += 1
                    stats["errors"] += 1
                    if is_daily_quota_exhausted(e):
                        quota_stopped = True
                        logger.warning(
                            "[Community] Quota ngày hết — bỏ qua summary còn lại."
                        )
                    else:
                        logger.warning(
                            "[Community] Summary lỗi community %d: %s", i, e
                        )
                    summary = "[Chưa tổng hợp — lỗi Gemini]"

                try:
                    self._persist_community(owner_id, bundle, summary)
                    stats["communities_created"] += 1
                    stats["entities_in_communities"] += len(bundle.member_ids)
                except Exception as e:
                    stats["errors"] += 1
                    logger.error("[Community] Persist lỗi: %s", e)

                if pause > 0 and i < len(bundles) - 1 and not quota_stopped:
                    time.sleep(pause)

            stats["status"] = "success"
            stats["message"] = (
                f"Tạo {stats['communities_created']} community, "
                f"{stats['summaries_ok']} summary OK."
            )
            logger.info(
                "[Community] owner=%s: %s",
                owner_id,
                stats["message"],
            )
            return stats

        except Exception as e:
            logger.error("[Community] detect_and_summarize lỗi: %s", e, exc_info=True)
            stats["status"] = "error"
            stats["message"] = str(e)
            stats["errors"] += 1
            return stats

    def list_communities(
        self,
        owner_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Danh sách Community của user."""
        records = self._neo4j.run_cypher(
            """
            MATCH (c:Community {owner_id: $owner_id})
            RETURN c.id AS id, c.summary AS summary, c.member_count AS member_count,
                   c.members AS members, c.created_at AS created_at
            ORDER BY c.member_count DESC
            LIMIT $limit
            """,
            {"owner_id": owner_id, "limit": limit},
        )
        return [
            {
                "id": r.get("id", ""),
                "summary": r.get("summary", ""),
                "member_count": r.get("member_count", 0),
                "members": r.get("members") or [],
                "created_at": r.get("created_at", ""),
            }
            for r in records
        ]

    def find_relevant_communities(
        self,
        query: str,
        owner_id: str,
        entity_norms: list[str] | None = None,
        limit: int = 2,
    ) -> list[dict[str, Any]]:
        """Tìm Community phù hợp nhất qua entity overlap + keyword trong summary."""
        from app.services.hybrid_search import tokenize
        from app.services.entity_normalizer import EntityNormalizer

        query_tokens = set(tokenize(query, min_len=3))
        norms = list(entity_norms or [])
        if not norms:
            normalizer = EntityNormalizer()
            for tok in tokenize(query, min_len=3):
                resolved = normalizer.resolve_canonical(tok, "OTHER")
                if resolved:
                    norms.append(resolved[1])

        records = self._neo4j.run_cypher(
            """
            MATCH (c:Community {owner_id: $owner_id})
            OPTIONAL MATCH (e:Entity {owner_id: $owner_id})-[:BELONGS_TO]->(c)
            WITH c, collect(DISTINCT e.name_norm) AS member_norms,
                 collect(DISTINCT e.name) AS member_names
            RETURN c.id AS id, c.summary AS summary, c.member_count AS member_count,
                   c.members AS members, member_norms, member_names
            """,
            {"owner_id": owner_id},
        )

        scored: list[tuple[float, dict[str, Any]]] = []
        for rec in records:
            summary = str(rec.get("summary") or "")
            member_norms = set(rec.get("member_norms") or [])
            overlap = len(member_norms.intersection(set(norms)))

            keyword_hits = sum(1 for t in query_tokens if t in summary.lower())

            if overlap == 0 and keyword_hits == 0 and norms:
                continue

            score = 3.0 * overlap + keyword_hits + 0.1 * int(rec.get("member_count") or 0)
            if not norms and not query_tokens:
                score = 0.1 * int(rec.get("member_count") or 0)

            scored.append((score, {
                "id": rec.get("id", ""),
                "summary": summary,
                "member_count": rec.get("member_count", 0),
                "members": rec.get("members") or [],
                "member_names": rec.get("member_names") or [],
                "score": round(score, 3),
            }))

        scored.sort(key=lambda x: -x[0])
        results = [item for _, item in scored[:limit]]

        if not results and records:
            fallback = sorted(
                records,
                key=lambda r: -(r.get("member_count") or 0),
            )[:limit]
            results = [
                {
                    "id": r.get("id", ""),
                    "summary": str(r.get("summary") or ""),
                    "member_count": r.get("member_count", 0),
                    "members": r.get("members") or [],
                    "member_names": [],
                    "score": 0.0,
                }
                for r in fallback
            ]

        return results


_instance: CommunityService | None = None


def get_community_service() -> CommunityService:
    global _instance
    if _instance is None:
        _instance = CommunityService()
    return _instance


def run_community_detection_best_effort(owner_id: str) -> None:
    """Gọi từ sync job — không raise."""
    if not settings.GRAPH_BUILD_COMMUNITIES:
        logger.debug("[Community] GRAPH_BUILD_COMMUNITIES=false — bỏ qua.")
        return
    try:
        stats = get_community_service().detect_and_summarize(owner_id)
        logger.info("[Community] post-sync stats: %s", stats)
    except Exception as e:
        logger.warning("[Community] post-sync thất bại (bỏ qua): %s", e)
