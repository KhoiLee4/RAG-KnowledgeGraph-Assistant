"""
graph_service.py — Graph Enhancement: Extract entities và Graph-based retrieval.

Kiến trúc GraphRAG:
  1. extract_entities: Dùng Gemini trích xuất entity/relation từ chunk văn bản.
  2. build_graph_from_chunks: Xây dựng KG trong Neo4j (Entity nodes + relations).
  3. graph_retrieve: Tìm chunk liên quan qua graph traversal.
  4. hybrid_retrieve: Kết hợp vector search + graph search với trọng số alpha.

Ưu điểm so với Vector-only RAG:
  - Xử lý tốt câu hỏi liên quan nhiều entity (multi-hop).
  - Giữ ngữ cảnh mối quan hệ giữa các khái niệm.
  - Trả lời câu hỏi suy luận (reasoning) tốt hơn.
"""

import json
import logging
import time
from typing import Any

from app.core.config import settings
from app.db.neo4j_client import get_neo4j_client
from app.services.entity_normalizer import (
    CanonicalRegistry,
    EntityNormalizer,
    get_entity_normalizer,
)
from app.services.graph_schema import (
    BATCH_ENTITY_EXTRACTION_PROMPT,
    ENTITY_EXTRACTION_PROMPT,
    ENTITY_REL_CYPHER_PATTERN,
    PATH_REL_CYPHER_PATTERN,
    normalize_relation_type,
)

logger = logging.getLogger(__name__)


class GraphService:
    """
    Service xây dựng và truy vấn Knowledge Graph từ tài liệu đã index.
    """

    def __init__(self):
        self._neo4j = get_neo4j_client()
        self._gemini_client = None
        self._normalizer: EntityNormalizer = get_entity_normalizer()

    def _get_gemini(self):
        if self._gemini_client is None:
            from google import genai
            self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._gemini_client

    @staticmethod
    def _normalize_name(name: str) -> str:
        return EntityNormalizer.normalize_name(name)

    # ── Extract entities ──────────────────────────────────────

    def extract_entities(self, text: str) -> dict[str, Any]:
        """
        Dùng Gemini trích xuất entities và relations từ đoạn văn bản.

        Args:
            text: Văn bản cần phân tích (tự động truncate tối đa 2000 ký tự).

        Returns:
            Dict: {"entities": [...], "relations": [...]}
              entities item: {name, type, description}
              relations item: {from, to, relation, description}
        """
        from app.core.gemini_retry import call_with_gemini_retry
        from google.genai import types as genai_types

        text_snippet = text[:2000]
        prompt = ENTITY_EXTRACTION_PROMPT.format(text=text_snippet)
        client = self._get_gemini()

        def _call():
            return client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=prompt)],
                )],
                config=genai_types.GenerateContentConfig(temperature=0.0),
            )

        try:
            response = call_with_gemini_retry(_call, label="extract_entities")
            raw = response.text or ""
            return self._parse_entity_json(raw)
        except Exception as e:
            logger.warning("extract_entities thất bại: %s — trả về rỗng.", e)
            return {"entities": [], "relations": []}

    def extract_entities_batch(
        self,
        chunk_items: list[dict[str, Any]],
    ) -> dict[int, dict[str, Any]]:
        """
        Trích xuất entity cho nhiều chunk trong một lần gọi Gemini.
        Giảm số request API so với gọi từng chunk riêng lẻ.

        Args:
            chunk_items: [{chunk_index, text}, ...]

        Returns:
            Map chunk_index → {"entities": [...], "relations": [...]}
        """
        from app.core.gemini_retry import call_with_gemini_retry
        from google.genai import types as genai_types

        if not chunk_items:
            return {}

        if len(chunk_items) == 1:
            item = chunk_items[0]
            return {
                item["chunk_index"]: self.extract_entities(item["text"]),
            }

        sections: list[str] = []
        for item in chunk_items:
            idx = item["chunk_index"]
            snippet = item["text"][:1200]
            sections.append(f"[CHUNK_{idx}]\n{snippet}")

        prompt = BATCH_ENTITY_EXTRACTION_PROMPT.format(texts="\n\n".join(sections))
        client = self._get_gemini()

        def _call():
            return client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=prompt)],
                )],
                config=genai_types.GenerateContentConfig(temperature=0.0),
            )

        try:
            response = call_with_gemini_retry(_call, label="extract_entities_batch")
            raw = response.text or ""
            return self._parse_batch_entity_json(raw, chunk_items)
        except Exception as e:
            logger.warning(
                "extract_entities_batch thất bại (%d chunk) — fallback từng chunk: %s",
                len(chunk_items),
                e,
            )
            # Fallback: gọi từng chunk nếu batch lỗi
            result: dict[int, dict[str, Any]] = {}
            for item in chunk_items:
                result[item["chunk_index"]] = self.extract_entities(item["text"])
            return result

    def _persist_chunk_entities(
        self,
        chunk_id: str,
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        owner_id: str | None,
        stats: dict[str, int],
        registry: CanonicalRegistry | None = None,
    ) -> None:
        """Lưu entity + relation của một chunk vào Neo4j (sau chuẩn hóa)."""
        entities, relations, _ = self._normalizer.normalize_entities(
            entities, relations, registry=registry
        )

        name_to_id: dict[str, str] = {}

        for ent in entities:
            canonical_name = str(ent.get("name", "")).strip()
            if not canonical_name:
                continue

            name_norm = str(ent.get("name_norm", "")).strip() or self._normalize_name(
                canonical_name
            )
            ent_id = EntityNormalizer.build_entity_id(name_norm, owner_id)
            aliases = ent.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []

            props: dict[str, Any] = {
                "id": ent_id,
                "name": canonical_name,
                "name_norm": name_norm,
                "type": str(ent.get("type", "OTHER")),
                "description": str(ent.get("description", "")),
                "aliases": aliases,
            }
            if owner_id:
                props["owner_id"] = owner_id

            try:
                self._neo4j.merge_canonical_entity(props)
                name_to_id[canonical_name.lower()] = ent_id
                name_to_id[name_norm] = ent_id
                for alias in aliases:
                    if alias:
                        name_to_id[str(alias).lower()] = ent_id
                        name_to_id[self._normalize_name(str(alias))] = ent_id
                stats["entities_created"] += 1
            except Exception as e:
                logger.warning("Tạo Entity node lỗi (%s): %s", canonical_name, e)
                stats["errors"] += 1
                continue

            try:
                self._neo4j.create_relationship(
                    from_id=chunk_id,
                    to_id=ent_id,
                    relation_type="MENTIONS",
                    from_label="Chunk",
                    to_label="Entity",
                )
                stats["relations_created"] += 1
            except Exception as e:
                logger.warning("Tạo MENTIONS lỗi (%s → %s): %s", chunk_id, ent_id, e)

        for rel in relations:
            from_raw = str(rel.get("from", "")).strip()
            to_raw = str(rel.get("to", "")).strip()
            if not from_raw or not to_raw:
                continue

            from_id = name_to_id.get(from_raw.lower()) or name_to_id.get(
                self._normalize_name(from_raw)
            )
            to_id = name_to_id.get(to_raw.lower()) or name_to_id.get(
                self._normalize_name(to_raw)
            )
            if not from_id or not to_id or from_id == to_id:
                continue

            rel_type = normalize_relation_type(str(rel.get("relation", "RELATED_TO")))
            try:
                self._neo4j.create_relationship(
                    from_id=from_id,
                    to_id=to_id,
                    relation_type=rel_type,
                    properties={"description": str(rel.get("description", ""))},
                    from_label="Entity",
                    to_label="Entity",
                )
                stats["relations_created"] += 1
            except Exception as e:
                logger.warning("Tạo quan hệ Entity lỗi (%s): %s", rel_type, e)

        unique_ids = list(set(name_to_id.values()))
        for i, eid1 in enumerate(unique_ids):
            for eid2 in unique_ids[i + 1:]:
                try:
                    self._neo4j.create_relationship(
                        from_id=eid1,
                        to_id=eid2,
                        relation_type="COOCCURS_WITH",
                        from_label="Entity",
                        to_label="Entity",
                    )
                    stats["relations_created"] += 1
                except Exception:
                    pass

    # ── Build Knowledge Graph ─────────────────────────────────

    def build_graph_from_chunks(
        self,
        chunks: list[dict[str, Any]],
        file_id: str,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Xây dựng Knowledge Graph từ danh sách chunk của một tài liệu.

        Với mỗi chunk:
          1. Gọi Gemini extract entities + relations.
          2. Tạo Entity nodes (MERGE theo id để tránh trùng).
          3. Tạo Chunk-[:MENTIONS]->Entity relations.
          4. Tạo Entity-[:RELATED_TO]->Entity từ extracted relations.
          5. Tạo Entity-[:COOCCURS_WITH]->Entity cho các entity cùng chunk.

        Args:
            chunks: Danh sách chunk dict (cần có keys: text, chunk_index, id hoặc file_id).
            file_id: Google Drive file ID của tài liệu gốc.
            owner_id: User ID để phân tách dữ liệu multi-user.

        Returns:
            Dict thống kê: {entities_created, relations_created, errors, chunks_processed}
        """
        stats: dict[str, int] = {
            "entities_created": 0,
            "relations_created": 0,
            "errors": 0,
            "chunks_processed": 0,
        }

        # Chuẩn bị danh sách chunk đủ điều kiện
        eligible: list[dict[str, Any]] = []
        for chunk in chunks:
            chunk_idx = chunk.get("chunk_index", 0)
            chunk_id = chunk.get("id") or f"{file_id}__chunk_{chunk_idx}"
            text = chunk.get("text", "")
            if len(text.strip()) < 50:
                continue
            eligible.append({
                "chunk_index": chunk_idx,
                "chunk_id": chunk_id,
                "text": text,
            })

        if not eligible:
            return stats

        registry = CanonicalRegistry()
        batch_size = max(1, settings.GRAPH_ENTITY_BATCH_SIZE)
        total_batches = (len(eligible) + batch_size - 1) // batch_size

        for batch_num, start in enumerate(range(0, len(eligible), batch_size), 1):
            batch = eligible[start: start + batch_size]
            batch_items = [
                {"chunk_index": c["chunk_index"], "text": c["text"]}
                for c in batch
            ]

            try:
                extracted_map = self.extract_entities_batch(batch_items)
            except Exception as e:
                logger.error("build_graph batch %d/%d lỗi: %s", batch_num, total_batches, e)
                stats["errors"] += len(batch)
                continue

            for item in batch:
                chunk_id = item["chunk_id"]
                chunk_idx = item["chunk_index"]
                extracted = extracted_map.get(
                    chunk_idx,
                    {"entities": [], "relations": []},
                )
                try:
                    self._persist_chunk_entities(
                        chunk_id=chunk_id,
                        entities=extracted.get("entities", []),
                        relations=extracted.get("relations", []),
                        owner_id=owner_id,
                        stats=stats,
                        registry=registry,
                    )
                    stats["chunks_processed"] += 1
                except Exception as e:
                    logger.error("build_graph chunk '%s' lỗi: %s", chunk_id, e)
                    stats["errors"] += 1

            # Nghỉ giữa các batch để tránh 429 (trừ batch cuối)
            if batch_num < total_batches and settings.GRAPH_ENTITY_BATCH_PAUSE > 0:
                time.sleep(settings.GRAPH_ENTITY_BATCH_PAUSE)

        logger.info(
            "[GraphService] build_graph '%s': %d entity, %d relation, %d lỗi / %d chunk "
            "(%d batch, size=%d).",
            file_id,
            stats["entities_created"],
            stats["relations_created"],
            stats["errors"],
            stats["chunks_processed"],
            total_batches,
            batch_size,
        )
        return stats

    # ── Graph Retrieval ───────────────────────────────────────

    def resolve_query_entity_norms(
        self,
        query: str,
        owner_id: str | None = None,
        use_gemini_fallback: bool = False,
    ) -> list[str]:
        """
        Trích entity_norm từ query — keyword/normalizer trước, Gemini tùy chọn.
        """
        query_norm = self._normalize_name(query)
        norms: list[str] = []
        seen: set[str] = set()

        def _add(norm: str) -> None:
            if norm and norm not in seen and len(norm) >= 2:
                seen.add(norm)
                norms.append(norm)

        tokens = [t for t in query_norm.split() if len(t) >= 2]
        for i, tok in enumerate(tokens):
            resolved = self._normalizer.resolve_canonical(tok, "OTHER")
            if resolved:
                _add(resolved[1])
            if i + 1 < len(tokens):
                bigram = f"{tok} {tokens[i + 1]}"
                resolved2 = self._normalizer.resolve_canonical(bigram, "OTHER")
                if resolved2:
                    _add(resolved2[1])

        if owner_id:
            try:
                records = self._neo4j.run_cypher(
                    """
                    MATCH (e:Entity {owner_id: $owner_id})
                    WHERE size(e.name_norm) >= 3
                      AND ($query_norm CONTAINS e.name_norm
                           OR e.name_norm IN $tokens
                           OR any(t IN $tokens WHERE size(t) >= 3 AND e.name_norm CONTAINS t))
                    RETURN DISTINCT e.name_norm AS name_norm
                    ORDER BY size(e.name_norm) DESC
                    LIMIT 15
                    """,
                    {
                        "owner_id": owner_id,
                        "query_norm": query_norm,
                        "tokens": tokens,
                    },
                )
                for rec in records:
                    _add(str(rec.get("name_norm", "")))
            except Exception as e:
                logger.warning("resolve_query_entity_norms cypher lỗi: %s", e)

        if not norms and use_gemini_fallback:
            extracted = self.extract_entities(query)
            for ent in extracted.get("entities", []):
                raw = str(ent.get("name", "")).strip()
                if not raw:
                    continue
                resolved = self._normalizer.resolve_canonical(
                    raw, str(ent.get("type", "OTHER"))
                )
                if resolved:
                    _add(resolved[1])

        return norms

    def get_graph_facts(
        self,
        entity_norms: list[str],
        owner_id: str | None = None,
        limit: int = 40,
    ) -> dict[str, Any]:
        """
        Lấy structured graph facts (entities + relations + chunk refs) cho LLM context.
        """
        if not entity_norms:
            return {"text": "", "entities": [], "relations": [], "chunk_refs": []}

        if owner_id:
            cypher = f"""
            MATCH (e:Entity {{owner_id: $owner_id}})
            WHERE e.name_norm IN $entity_norms
            OPTIONAL MATCH (e)-[r:{ENTITY_REL_CYPHER_PATTERN}]-(e2:Entity {{owner_id: $owner_id}})
            OPTIONAL MATCH (c:Chunk)-[:MENTIONS]->(e)
            OPTIONAL MATCH (d:Document {{owner_id: $owner_id}})-[:CONTAINS]->(c)
            RETURN e.name AS name, e.type AS type,
                   coalesce(e.description, '') AS description,
                   e2.name AS related_name, type(r) AS rel_type,
                   coalesce(r.description, '') AS rel_desc,
                   c.id AS chunk_id, d.file_name AS file_name,
                   d.drive_link AS drive_link
            LIMIT $limit
            """
            params: dict[str, Any] = {
                "owner_id": owner_id,
                "entity_norms": entity_norms,
                "limit": limit,
            }
        else:
            cypher = f"""
            MATCH (e:Entity)
            WHERE e.name_norm IN $entity_norms
            OPTIONAL MATCH (e)-[r:{ENTITY_REL_CYPHER_PATTERN}]-(e2:Entity)
            OPTIONAL MATCH (c:Chunk)-[:MENTIONS]->(e)
            OPTIONAL MATCH (d:Document)-[:CONTAINS]->(c)
            RETURN e.name AS name, e.type AS type,
                   coalesce(e.description, '') AS description,
                   e2.name AS related_name, type(r) AS rel_type,
                   coalesce(r.description, '') AS rel_desc,
                   c.id AS chunk_id, d.file_name AS file_name,
                   d.drive_link AS drive_link
            LIMIT $limit
            """
            params = {"entity_norms": entity_norms, "limit": limit}

        try:
            records = self._neo4j.run_cypher(cypher, params)
        except Exception as e:
            logger.warning("get_graph_facts lỗi: %s", e)
            return {"text": "", "entities": [], "relations": [], "chunk_refs": []}

        entities_map: dict[str, dict[str, str]] = {}
        relations: list[dict[str, str]] = []
        rel_seen: set[str] = set()
        chunk_refs: list[dict[str, str]] = []
        chunk_seen: set[str] = set()

        for rec in records:
            name = rec.get("name", "")
            if name and name not in entities_map:
                entities_map[name] = {
                    "name": name,
                    "type": rec.get("type", "OTHER"),
                    "description": str(rec.get("description", ""))[:120],
                }

            rel_name = rec.get("related_name")
            if name and rel_name:
                key = f"{name}|{rel_name}|{rec.get('rel_type', '')}"
                if key not in rel_seen:
                    rel_seen.add(key)
                    relations.append({
                        "from": name,
                        "to": rel_name,
                        "rel_type": str(rec.get("rel_type", "RELATED_TO")),
                        "description": str(rec.get("rel_desc", ""))[:80],
                    })

            cid = rec.get("chunk_id")
            if cid and cid not in chunk_seen:
                chunk_seen.add(cid)
                chunk_refs.append({
                    "chunk_id": cid,
                    "file_name": rec.get("file_name", ""),
                    "drive_link": rec.get("drive_link", ""),
                })

        lines: list[str] = ["=== SỰ THẬT TỪ KNOWLEDGE GRAPH ===", ""]
        if entities_map:
            lines.append("Thực thể:")
            for ent in entities_map.values():
                desc = ent["description"]
                line = f"- {ent['name']} [{ent['type']}]"
                if desc:
                    line += f": {desc}"
                lines.append(line)
            lines.append("")

        if relations:
            lines.append("Quan hệ:")
            for rel in relations[:20]:
                desc = rel["description"]
                line = f"- {rel['from']} —[{rel['rel_type']}]→ {rel['to']}"
                if desc:
                    line += f" ({desc})"
                lines.append(line)
            lines.append("")

        if chunk_refs:
            refs = ", ".join(
                r["file_name"] or r["chunk_id"]
                for r in chunk_refs[:8]
            )
            lines.append(f"Nguồn tài liệu liên quan: {refs}")

        text = "\n".join(lines).strip()
        return {
            "text": text,
            "entities": list(entities_map.values()),
            "relations": relations,
            "chunk_refs": chunk_refs,
        }

    def find_entity_paths(
        self,
        entity_norms: list[str],
        owner_id: str | None = None,
        max_paths: int = 5,
        max_hops: int = 5,
    ) -> dict[str, Any]:
        """
        Tìm đường đi ngắn nhất giữa các cặp entity (câu hỏi quan hệ multi-entity).
        """
        from itertools import combinations

        norms = list(dict.fromkeys(n for n in entity_norms if n))[:4]
        if len(norms) < 2:
            return {"text": "", "paths": [], "relations": []}

        paths: list[dict[str, Any]] = []
        relations: list[dict[str, str]] = []
        rel_seen: set[str] = set()

        def _run_path_query(norm_a: str, norm_b: str, rel_pattern: str) -> list[dict[str, Any]]:
            if owner_id:
                cypher = f"""
                MATCH (a:Entity {{owner_id: $oid, name_norm: $norm_a}})
                MATCH (b:Entity {{owner_id: $oid, name_norm: $norm_b}})
                WHERE a <> b
                MATCH path = shortestPath(
                  (a)-[:{rel_pattern}*..{max_hops}]-(b)
                )
                RETURN [n IN nodes(path) | {{name: n.name, type: n.type}}] AS nodes,
                       [r IN relationships(path) | {{
                         type: type(r), desc: coalesce(r.description, '')
                       }}] AS rels,
                       length(path) AS hops
                LIMIT 1
                """
                params = {"oid": owner_id, "norm_a": norm_a, "norm_b": norm_b}
            else:
                cypher = f"""
                MATCH (a:Entity {{name_norm: $norm_a}})
                MATCH (b:Entity {{name_norm: $norm_b}})
                WHERE a <> b
                MATCH path = shortestPath(
                  (a)-[:{rel_pattern}*..{max_hops}]-(b)
                )
                RETURN [n IN nodes(path) | {{name: n.name, type: n.type}}] AS nodes,
                       [r IN relationships(path) | {{
                         type: type(r), desc: coalesce(r.description, '')
                       }}] AS rels,
                       length(path) AS hops
                LIMIT 1
                """
                params = {"norm_a": norm_a, "norm_b": norm_b}
            try:
                return self._neo4j.run_cypher(cypher, params)
            except Exception as e:
                logger.warning("find_entity_paths (%s ↔ %s) lỗi: %s", norm_a, norm_b, e)
                return []

        for norm_a, norm_b in combinations(norms, 2):
            if len(paths) >= max_paths:
                break

            records = _run_path_query(norm_a, norm_b, PATH_REL_CYPHER_PATTERN)
            if not records:
                records = _run_path_query(norm_a, norm_b, ENTITY_REL_CYPHER_PATTERN)
            if not records:
                continue

            rec = records[0]
            node_list = rec.get("nodes") or []
            rel_list = rec.get("rels") or []
            if len(node_list) < 2:
                continue

            names = [str(n.get("name", "")) for n in node_list if n.get("name")]
            if len(names) < 2:
                continue

            steps: list[str] = []
            for i, rel in enumerate(rel_list):
                rt = str(rel.get("type", "RELATED_TO"))
                desc = str(rel.get("desc", "")).strip()
                from_name = names[i] if i < len(names) else "?"
                to_name = names[i + 1] if i + 1 < len(names) else "?"
                step = f"{from_name} —[{rt}]→ {to_name}"
                if desc:
                    step += f" ({desc})"
                steps.append(step)

                rel_key = f"{from_name}|{to_name}|{rt}"
                if rel_key not in rel_seen:
                    rel_seen.add(rel_key)
                    relations.append({
                        "from": from_name,
                        "to": to_name,
                        "rel_type": rt,
                        "description": desc[:80],
                    })

            paths.append({
                "from_norm": norm_a,
                "to_norm": norm_b,
                "from_name": names[0],
                "to_name": names[-1],
                "hops": rec.get("hops", len(rel_list)),
                "steps": steps,
            })

        if not paths:
            return {"text": "", "paths": [], "relations": []}

        lines = ["=== QUAN HỆ GRAPH (PATH) ===", ""]
        for i, path in enumerate(paths, 1):
            lines.append(
                f"Đường {i}: {path['from_name']} ↔ {path['to_name']} "
                f"({path['hops']} bước)"
            )
            for step in path["steps"]:
                lines.append(f"  • {step}")
            lines.append("")

        return {
            "text": "\n".join(lines).strip(),
            "paths": paths,
            "relations": relations,
        }

    def graph_retrieve(
        self,
        query: str,
        max_results: int = 10,
        owner_id: str | None = None,
        collection_name: str | None = None,
        entity_norms: list[str] | None = None,
        use_gemini_entities: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Tìm kiếm chunk liên quan qua Knowledge Graph traversal.

        Luồng:
          1. Extract entities từ query bằng Gemini.
          2. Tìm Entity nodes trong Neo4j khớp tên.
          3. 1-hop: Entity<-[:MENTIONS]-Chunk<-[:CONTAINS]-Document.
          4. 2-hop: Entity-[:RELATED_TO|COOCCURS_WITH]-Entity<-[:MENTIONS]-Chunk.
          5. Lấy text chunk từ ChromaDB, trả về kèm graph_score.

        Returns:
            Danh sách dict: {id, text, file_name, file_id, chunk_index, score,
                             graph_score, drive_link, page_estimate, entities, source}
        """
        from app.db.chroma_client import get_chroma_client

        if entity_norms is not None:
            resolved_norms = entity_norms
        else:
            resolved_norms = self.resolve_query_entity_norms(
                query,
                owner_id=owner_id,
                use_gemini_fallback=use_gemini_entities,
            )
        entity_norms = resolved_norms

        if not entity_norms:
            logger.info("graph_retrieve: query không chứa entity rõ ràng.")
            return []

        chunk_scores: dict[str, float] = {}
        chunk_meta: dict[str, dict[str, Any]] = {}

        for name_norm in entity_norms:
            # 1-hop: Chunk -[:MENTIONS]-> Entity
            if owner_id:
                cypher_1hop = """
                MATCH (e:Entity {owner_id: $owner_id, name_norm: $name_norm})
                MATCH (c:Chunk)-[:MENTIONS]->(e)
                MATCH (d:Document)-[:CONTAINS]->(c)
                RETURN c.id AS chunk_id, d.file_name AS file_name, d.id AS file_id,
                       d.drive_link AS drive_link, e.name AS entity_name, e.type AS entity_type
                LIMIT $limit
                """
                params_1hop: dict[str, Any] = {
                    "owner_id": owner_id,
                    "name_norm": name_norm,
                    "limit": max_results * 2,
                }
            else:
                cypher_1hop = """
                MATCH (e:Entity {name_norm: $name_norm})
                MATCH (c:Chunk)-[:MENTIONS]->(e)
                MATCH (d:Document)-[:CONTAINS]->(c)
                RETURN c.id AS chunk_id, d.file_name AS file_name, d.id AS file_id,
                       d.drive_link AS drive_link, e.name AS entity_name, e.type AS entity_type
                LIMIT $limit
                """
                params_1hop = {
                    "name_norm": name_norm,
                    "limit": max_results * 2,
                }

            try:
                records = self._neo4j.run_cypher(cypher_1hop, params_1hop)
            except Exception as e:
                logger.warning("graph_retrieve 1-hop lỗi (%s): %s", name_norm, e)
                records = []

            for rec in records:
                cid = rec.get("chunk_id")
                if not cid:
                    continue
                chunk_scores[cid] = chunk_scores.get(cid, 0.0) + 1.0
                if cid not in chunk_meta:
                    chunk_meta[cid] = {
                        "file_name": rec.get("file_name", ""),
                        "file_id": rec.get("file_id", ""),
                        "drive_link": rec.get("drive_link", ""),
                        "entities": [],
                    }
                chunk_meta[cid]["entities"].append(
                    f"{rec.get('entity_name', '')} ({rec.get('entity_type', '')})"
                )

            # 2-hop: Entity -[:RELATED_TO|COOCCURS_WITH]- Entity -[:MENTIONS]- Chunk
            if owner_id:
                cypher_2hop = f"""
                MATCH (e1:Entity {{owner_id: $owner_id, name_norm: $name_norm}})
                      -[:{ENTITY_REL_CYPHER_PATTERN}]-(e2:Entity)
                MATCH (c:Chunk)-[:MENTIONS]->(e2)
                MATCH (d:Document)-[:CONTAINS]->(c)
                RETURN c.id AS chunk_id, d.file_name AS file_name, d.id AS file_id,
                       d.drive_link AS drive_link, e2.name AS entity_name, e2.type AS entity_type
                LIMIT $limit
                """
                hop2_params = {
                    "owner_id": owner_id,
                    "name_norm": name_norm,
                    "limit": max_results,
                }
            else:
                cypher_2hop = f"""
                MATCH (e1:Entity {{name_norm: $name_norm}})-[:{ENTITY_REL_CYPHER_PATTERN}]-(e2:Entity)
                MATCH (c:Chunk)-[:MENTIONS]->(e2)
                MATCH (d:Document)-[:CONTAINS]->(c)
                RETURN c.id AS chunk_id, d.file_name AS file_name, d.id AS file_id,
                       d.drive_link AS drive_link, e2.name AS entity_name, e2.type AS entity_type
                LIMIT $limit
                """
                hop2_params = {
                    "name_norm": name_norm,
                    "limit": max_results,
                }
            try:
                hop2_records = self._neo4j.run_cypher(cypher_2hop, hop2_params)
            except Exception as e:
                logger.debug("graph_retrieve 2-hop lỗi: %s", e)
                hop2_records = []

            for rec in hop2_records:
                cid = rec.get("chunk_id")
                if not cid:
                    continue
                # 2-hop có trọng số thấp hơn 1-hop
                chunk_scores[cid] = chunk_scores.get(cid, 0.0) + 0.5
                if cid not in chunk_meta:
                    chunk_meta[cid] = {
                        "file_name": rec.get("file_name", ""),
                        "file_id": rec.get("file_id", ""),
                        "drive_link": rec.get("drive_link", ""),
                        "entities": [],
                    }

        if not chunk_scores:
            logger.info("graph_retrieve: không tìm được chunk nào qua graph.")
            return []

        # Lấy top chunk IDs theo score
        sorted_ids = sorted(chunk_scores, key=lambda x: -chunk_scores[x])[:max_results * 2]

        # Lấy text từ ChromaDB
        chroma = get_chroma_client()
        try:
            chroma_results = chroma.get_by_ids(sorted_ids, collection_name=collection_name)
        except Exception as e:
            logger.error("graph_retrieve get_by_ids lỗi: %s", e)
            return []

        max_score = max(chunk_scores.values()) if chunk_scores else 1.0

        results: list[dict[str, Any]] = []
        for r in chroma_results:
            cid = r["id"]
            meta = r.get("metadata", {})
            path_info = chunk_meta.get(cid, {})
            raw_score = chunk_scores.get(cid, 0.0)
            graph_score = round(raw_score / max_score, 4) if max_score > 0 else 0.0

            results.append({
                "id": cid,
                "text": r.get("document", ""),
                "file_name": path_info.get("file_name") or meta.get("file_name", "Unknown"),
                "file_id": path_info.get("file_id") or meta.get("file_id", ""),
                "chunk_index": int(meta.get("chunk_index", 0)),
                "score": graph_score,
                "graph_score": graph_score,
                "vector_score": 0.0,
                "combined_score": graph_score,
                "drive_link": path_info.get("drive_link") or meta.get(
                    "drive_link",
                    f"https://drive.google.com/file/d/{meta.get('file_id', '')}/view",
                ),
                "page_estimate": int(meta.get("page_estimate", 1)),
                "line_start": int(meta.get("line_start", 0) or 0),
                "line_end": int(meta.get("line_end", 0) or 0),
                "entities": path_info.get("entities", []),
                "source": "graph",
            })

        results.sort(key=lambda x: -x["graph_score"])
        logger.info(
            "graph_retrieve '%s...': %d kết quả qua graph (%d entity).",
            query[:60],
            len(results),
            len(entity_norms),
        )
        return results[:max_results]

    # ── Hybrid Retrieval ──────────────────────────────────────

    def hybrid_retrieve(
        self,
        query: str,
        collection_name: str | None = None,
        n_results: int = 5,
        alpha: float | None = None,
        owner_id: str | None = None,
        entity_norms: list[str] | None = None,
        use_gemini_entities: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Kết hợp vector search (ChromaDB) và graph search (Neo4j).

        Args:
            query: Câu truy vấn.
            collection_name: ChromaDB collection.
            n_results: Số kết quả trả về.
            alpha: Trọng số cho vector score [0.0–1.0].
                   alpha=1.0 → chỉ vector, alpha=0.0 → chỉ graph.
                   Mặc định: settings.GRAPH_ALPHA.
            owner_id: User ID để phân tách dữ liệu.

        Returns:
            Danh sách chunk đã rerank theo combined_score.
            Mỗi item có thêm field: source = "vector" | "graph" | "hybrid".
        """
        from app.services.retrieval_service import RetrievalService

        if alpha is None:
            alpha = settings.GRAPH_ALPHA

        # Vector search
        vector_results: list[dict[str, Any]] = []
        try:
            vector_results = RetrievalService().retrieve(
                query=query,
                collection_name=collection_name,
                n_results=n_results * 2,
            )
        except Exception as e:
            logger.warning("hybrid_retrieve: vector search lỗi: %s", e)

        # Graph search (bỏ qua nếu alpha = 1.0)
        graph_results: list[dict[str, Any]] = []
        if alpha < 1.0 and settings.GRAPH_ENABLED:
            try:
                graph_results = self.graph_retrieve(
                    query=query,
                    max_results=n_results * 2,
                    owner_id=owner_id,
                    collection_name=collection_name,
                    entity_norms=entity_norms,
                    use_gemini_entities=use_gemini_entities and entity_norms is None,
                )
            except Exception as e:
                logger.warning("hybrid_retrieve: graph search lỗi: %s", e)

        # Nếu graph rỗng → fallback vector only
        if not graph_results:
            for r in vector_results:
                r.setdefault("source", "vector")
                r["combined_score"] = r.get("score", 0.0)
            return vector_results[:n_results]

        # Nếu vector rỗng → fallback graph only
        if not vector_results:
            for r in graph_results:
                r.setdefault("source", "graph")
                r["combined_score"] = r.get("graph_score", 0.0)
            return graph_results[:n_results]

        # Merge kết quả theo chunk_id
        merged: dict[str, dict[str, Any]] = {}

        for r in vector_results:
            cid = r.get("id", "")
            if not cid:
                continue
            merged[cid] = {
                **r,
                "vector_score": r.get("score", 0.0),
                "graph_score": 0.0,
                "source": "vector",
            }

        for r in graph_results:
            cid = r.get("id", "")
            if not cid:
                continue
            if cid in merged:
                merged[cid]["graph_score"] = r.get("graph_score", 0.0)
                merged[cid]["source"] = "hybrid"
            else:
                merged[cid] = {
                    **r,
                    "graph_score": r.get("graph_score", 0.0),
                    "source": "graph",
                }

        # Tính combined_score
        for item in merged.values():
            vs = item.get("vector_score", 0.0)
            gs = item.get("graph_score", 0.0)
            item["combined_score"] = round(alpha * vs + (1.0 - alpha) * gs, 4)
            item["score"] = item["combined_score"]

        final = sorted(merged.values(), key=lambda x: -x["combined_score"])
        logger.info(
            "hybrid_retrieve '%s...': vector=%d, graph=%d, merged=%d (alpha=%.2f).",
            query[:60],
            len(vector_results),
            len(graph_results),
            len(final),
            alpha,
        )
        return final[:n_results]

    # ── Graph Statistics ──────────────────────────────────────

    def get_graph_stats(self, owner_id: str | None = None) -> dict[str, Any]:
        """
        Thống kê Knowledge Graph hiện tại.

        Returns:
            Dict: {total_entities, relations_by_type, entity_types, top_entities}
        """
        try:
            stats: dict[str, Any] = {}

            if owner_id:
                entity_records = self._neo4j.run_cypher(
                    "MATCH (e:Entity {owner_id: $oid}) RETURN count(e) AS count",
                    {"oid": owner_id},
                )
                rel_records = self._neo4j.run_cypher(
                    "MATCH (e:Entity {owner_id: $oid})-[r]-() "
                    "RETURN type(r) AS type, count(r) AS cnt",
                    {"oid": owner_id},
                )
                type_records = self._neo4j.run_cypher(
                    "MATCH (e:Entity {owner_id: $oid}) "
                    "RETURN e.type AS type, count(e) AS cnt ORDER BY cnt DESC LIMIT 10",
                    {"oid": owner_id},
                )
                top_records = self._neo4j.run_cypher(
                    "MATCH (e:Entity {owner_id: $oid})<-[:MENTIONS]-(c:Chunk) "
                    "RETURN e.name AS name, e.type AS type, count(c) AS mentions "
                    "ORDER BY mentions DESC LIMIT 10",
                    {"oid": owner_id},
                )
                community_records = self._neo4j.run_cypher(
                    "MATCH (c:Community {owner_id: $oid}) RETURN count(c) AS count",
                    {"oid": owner_id},
                )
            else:
                entity_records = self._neo4j.run_cypher(
                    "MATCH (e:Entity) RETURN count(e) AS count"
                )
                rel_records = self._neo4j.run_cypher(
                    "MATCH ()-[r:MENTIONS|RELATED_TO|COOCCURS_WITH]->() "
                    "RETURN type(r) AS type, count(r) AS cnt"
                )
                type_records = self._neo4j.run_cypher(
                    "MATCH (e:Entity) "
                    "RETURN e.type AS type, count(e) AS cnt ORDER BY cnt DESC LIMIT 10"
                )
                top_records = self._neo4j.run_cypher(
                    "MATCH (e:Entity)<-[:MENTIONS]-(c:Chunk) "
                    "RETURN e.name AS name, e.type AS type, count(c) AS mentions "
                    "ORDER BY mentions DESC LIMIT 10"
                )
                community_records = self._neo4j.run_cypher(
                    "MATCH (c:Community) RETURN count(c) AS count"
                )

            stats["total_entities"] = entity_records[0]["count"] if entity_records else 0
            stats["total_communities"] = (
                community_records[0]["count"] if community_records else 0
            )
            stats["relations_by_type"] = {r["type"]: r["cnt"] for r in rel_records}
            stats["entity_types"] = {r["type"]: r["cnt"] for r in type_records}
            stats["top_entities"] = [
                {"name": r["name"], "type": r["type"], "mentions": r["mentions"]}
                for r in top_records
            ]
            return stats
        except Exception as e:
            logger.error("get_graph_stats lỗi: %s", e)
            return {"error": str(e), "total_entities": 0}

    def get_entities_for_document(
        self,
        file_id: str,
        owner_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Lấy danh sách entity được trích xuất từ một tài liệu cụ thể.

        Returns:
            Danh sách dict: {name, type, description, mentions}
        """
        try:
            if owner_id:
                cypher = """
                MATCH (d:Document {id: $file_id, owner_id: $owner_id})-[:CONTAINS]->(c:Chunk)
                MATCH (c)-[:MENTIONS]->(e:Entity)
                RETURN DISTINCT e.name AS name, e.type AS type,
                       e.description AS description, count(c) AS mentions
                ORDER BY mentions DESC
                LIMIT $limit
                """
                params: dict[str, Any] = {
                    "file_id": file_id,
                    "owner_id": owner_id,
                    "limit": limit,
                }
            else:
                cypher = """
                MATCH (d:Document {id: $file_id})-[:CONTAINS]->(c:Chunk)
                MATCH (c)-[:MENTIONS]->(e:Entity)
                RETURN DISTINCT e.name AS name, e.type AS type,
                       e.description AS description, count(c) AS mentions
                ORDER BY mentions DESC
                LIMIT $limit
                """
                params = {"file_id": file_id, "limit": limit}

            records = self._neo4j.run_cypher(cypher, params)
            return [
                {
                    "name": r.get("name", ""),
                    "type": r.get("type", "OTHER"),
                    "description": r.get("description", ""),
                    "mentions": r.get("mentions", 0),
                }
                for r in records
            ]
        except Exception as e:
            logger.error("get_entities_for_document '%s' lỗi: %s", file_id, e)
            return []

    # ── Helpers ───────────────────────────────────────────────

    def _parse_batch_entity_json(
        self,
        raw_json: str,
        chunk_items: list[dict[str, Any]],
    ) -> dict[int, dict[str, Any]]:
        """Parse JSON batch từ Gemini, fallback rỗng cho chunk thiếu."""
        cleaned = raw_json.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1]).strip()

        expected_indices = {item["chunk_index"] for item in chunk_items}
        empty = {"entities": [], "relations": []}
        result: dict[int, dict[str, Any]] = {idx: dict(empty) for idx in expected_indices}

        try:
            data = json.loads(cleaned)
            chunks_data = data.get("chunks", []) if isinstance(data, dict) else []
            if not isinstance(chunks_data, list):
                return result

            for entry in chunks_data:
                if not isinstance(entry, dict):
                    continue
                idx = entry.get("chunk_index")
                if idx not in expected_indices:
                    continue
                entities = entry.get("entities", [])
                relations = entry.get("relations", [])
                result[idx] = {
                    "entities": entities if isinstance(entities, list) else [],
                    "relations": relations if isinstance(relations, list) else [],
                }
            return result
        except json.JSONDecodeError as e:
            logger.warning("Parse batch entity JSON thất bại: %s", e)
            return result

    def _parse_entity_json(self, raw_json: str) -> dict[str, Any]:
        """Parse JSON response từ Gemini, xử lý cả trường hợp có markdown code block."""
        cleaned = raw_json.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Bỏ dòng đầu (```json) và dòng cuối (```)
            cleaned = "\n".join(lines[1:-1]).strip()
        try:
            result = json.loads(cleaned)
            if not isinstance(result, dict):
                return {"entities": [], "relations": []}
            result.setdefault("entities", [])
            result.setdefault("relations", [])
            # Đảm bảo entities và relations là list
            if not isinstance(result["entities"], list):
                result["entities"] = []
            if not isinstance(result["relations"], list):
                result["relations"] = []
            return result
        except json.JSONDecodeError as e:
            logger.warning("Parse entity JSON thất bại: %s | Raw: %.120s", e, cleaned)
            return {"entities": [], "relations": []}


# ── Singleton ──────────────────────────────────────────────────

_instance: GraphService | None = None


def get_graph_service() -> GraphService:
    """Trả về singleton GraphService."""
    global _instance
    if _instance is None:
        _instance = GraphService()
    return _instance
