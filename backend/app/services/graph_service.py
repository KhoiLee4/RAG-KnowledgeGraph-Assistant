"""
graph_service.py — Graph Enhancement: Extract entities và Graph-based retrieval.

[PHASE 5 — Triển khai sau khi Vector RAG (Phase 1-4) chạy ổn định]

Kiến trúc GraphRAG đầy đủ:
  1. Extract entities từ chunk văn bản bằng Gemini.
  2. Xây dựng Knowledge Graph (entity nodes + relations) trong Neo4j.
  3. Graph retrieval: tìm kiếm qua graph relationships để lấy context rộng hơn.

Ưu điểm so với Vector-only RAG:
  - Xử lý tốt câu hỏi liên quan nhiều entity (multi-hop).
  - Giữ ngữ cảnh mối quan hệ giữa các khái niệm.
  - Trả lời câu hỏi suy luận (reasoning) tốt hơn.
"""

import json
import logging
from typing import Any

from app.core.config import settings
from app.db.neo4j_client import get_neo4j_client

logger = logging.getLogger(__name__)

# Prompt dùng để extract entities từ văn bản
ENTITY_EXTRACTION_PROMPT = """Phân tích đoạn văn bản sau và trích xuất các thực thể quan trọng.

Văn bản:
{text}

Trả về JSON với format:
{{
  "entities": [
    {{"name": "tên entity", "type": "PERSON|ORGANIZATION|CONCEPT|LOCATION|DATE|OTHER", "description": "mô tả ngắn"}}
  ],
  "relations": [
    {{"from": "entity A", "to": "entity B", "relation": "LOẠI_QUAN_HỆ", "description": "mô tả"}}
  ]
}}

Chỉ trả về JSON thuần, không thêm markdown hay giải thích.
"""


class GraphService:
    """
    Service xây dựng và truy vấn Knowledge Graph từ tài liệu đã index.

    [TODO] Tất cả method đều có implementation skeleton.
    Triển khai chi tiết ở Phase 5 sau khi Vector RAG hoàn chỉnh.
    """

    def __init__(self):
        """Khởi tạo GraphService với Neo4j client và Gemini client."""
        self._neo4j = get_neo4j_client()

        # Lazy init Gemini client (tránh import lỗi nếu API key chưa set)
        self._gemini_client = None

    def _get_gemini(self):
        """Lazy khởi tạo Gemini client."""
        if self._gemini_client is None:
            from google import genai
            self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._gemini_client

    # ── Extract entities ──────────────────────────────────────

    def extract_entities(self, text: str) -> list[dict[str, Any]]:
        """
        Dùng Gemini để trích xuất entities và relations từ đoạn văn bản.

        Args:
            text: Văn bản cần phân tích.

        Returns:
            Danh sách dict entity:
              {name, type, description}

        [TODO Phase 5] Implementation:
          1. Gọi Gemini với ENTITY_EXTRACTION_PROMPT.
          2. Parse JSON response.
          3. Validate và clean kết quả.
          4. Return entities list.
        """
        # TODO Phase 5: Implement entity extraction bằng Gemini
        logger.info("[GraphService] extract_entities — TODO Phase 5")
        raise NotImplementedError(
            "extract_entities chưa được triển khai (Phase 5).\n"
            "Vector RAG (Phase 1-4) vẫn hoạt động bình thường."
        )

    def build_graph_from_chunks(
        self,
        chunks: list[dict[str, Any]],
        file_id: str,
    ) -> dict[str, Any]:
        """
        Xây dựng Knowledge Graph từ danh sách chunk của một tài liệu.

        Args:
            chunks: Danh sách chunk dict (từ ChunkingService.chunk_document).
            file_id: ID tài liệu gốc.

        Returns:
            Dict thống kê: {entities_created, relations_created, errors}.

        [TODO Phase 5] Implementation:
          1. Với mỗi chunk, gọi extract_entities(chunk["text"]).
          2. Tạo entity nodes trong Neo4j (type: PERSON, ORG, CONCEPT...).
          3. Tạo MENTIONS relation: Chunk-[:MENTIONS]->Entity.
          4. Tạo quan hệ giữa entities theo relations trích xuất.
          5. Tạo COOCCURS_WITH nếu cùng xuất hiện trong 1 chunk.
        """
        # TODO Phase 5: Implement graph building pipeline
        logger.info("[GraphService] build_graph_from_chunks — TODO Phase 5")
        raise NotImplementedError(
            "build_graph_from_chunks chưa được triển khai (Phase 5)."
        )

    def graph_retrieve(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Tìm kiếm qua Knowledge Graph để lấy context phong phú hơn.
        Kết hợp với vector search trong hybrid retrieval.

        Args:
            query: Câu truy vấn của người dùng.
            max_results: Số lượng kết quả tối đa.

        Returns:
            Danh sách dict kết quả:
              {chunk_id, text, file_name, file_id, relation_path, relevance_score}

        [TODO Phase 5] Implementation:
          1. Extract entities từ query (extract_entities).
          2. Tìm entity nodes trong Neo4j khớp tên.
          3. Graph traversal: entity → MENTIONS → Chunk → Document.
          4. Mở rộng theo quan hệ: entity → RELATED_TO → entity → Chunk.
          5. Kết hợp với vector score để ranking.

        Ví dụ Cypher query để implement:
          MATCH (e:Entity)
          WHERE e.name CONTAINS $entity_name
          MATCH (e)<-[:MENTIONS]-(c:Chunk)<-[:CONTAINS]-(d:Document)
          RETURN c, d, e
          LIMIT $limit
        """
        # TODO Phase 5: Implement graph-based retrieval
        logger.info("[GraphService] graph_retrieve — TODO Phase 5")
        raise NotImplementedError(
            "graph_retrieve chưa được triển khai (Phase 5)."
        )

    def hybrid_retrieve(
        self,
        query: str,
        collection_name: str | None = None,
        n_results: int = 5,
        alpha: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Kết hợp vector search và graph search với trọng số alpha.

        Args:
            query: Câu truy vấn.
            collection_name: ChromaDB collection.
            n_results: Số kết quả trả về.
            alpha: Trọng số cho vector score [0.0-1.0].
                   alpha=1.0 = chỉ dùng vector,
                   alpha=0.0 = chỉ dùng graph.

        Returns:
            Danh sách chunk đã rerank theo combined score.

        [TODO Phase 5] Implementation:
          vector_results = RetrievalService.retrieve(...)
          graph_results = self.graph_retrieve(...)
          combined = merge_and_rerank(vector_results, graph_results, alpha)
          return combined[:n_results]
        """
        # TODO Phase 5: Implement hybrid retrieval
        # Fallback tạm thời: chỉ dùng vector search
        logger.warning(
            "[GraphService] hybrid_retrieve chưa có graph — fallback về vector only."
        )
        from app.services.retrieval_service import RetrievalService
        return RetrievalService().retrieve(
            query=query,
            collection_name=collection_name,
            n_results=n_results,
        )

    # ── Graph analytics (bonus) ───────────────────────────────

    def get_graph_stats(self) -> dict[str, Any]:
        """
        Lấy thống kê về Knowledge Graph hiện tại.
        Dùng để monitor và debug graph quality.

        Returns:
            Dict thống kê: {total_entities, total_relations, entity_types, top_entities}.
        """
        # TODO Phase 5: Thêm thống kê chi tiết hơn
        try:
            stats = {}

            # Đếm entity nodes
            records = self._neo4j.run_cypher(
                "MATCH (e:Entity) RETURN count(e) AS count"
            )
            stats["total_entities"] = records[0]["count"] if records else 0

            # Đếm relation
            records = self._neo4j.run_cypher(
                "MATCH ()-[r:MENTIONS|RELATED_TO|COOCCURS_WITH]->() "
                "RETURN type(r) AS type, count(r) AS count"
            )
            stats["relations_by_type"] = {r["type"]: r["count"] for r in records}

            return stats
        except Exception as e:
            logger.error("get_graph_stats lỗi: %s", e)
            return {"error": str(e)}

    def _parse_entity_json(self, raw_json: str) -> dict[str, Any]:
        """
        Parse JSON response từ Gemini entity extraction.
        Xử lý các trường hợp JSON không hợp lệ.

        [TODO Phase 5] Helper cho extract_entities.
        """
        # Loại bỏ markdown code block nếu có
        cleaned = raw_json.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1])
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("Parse entity JSON thất bại: %s | Raw: %s", e, cleaned[:200])
            return {"entities": [], "relations": []}


# ── Test độc lập ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=== GraphService — Phase 5 Skeleton ===")
    print()
    print("Status: Phase 5 chưa được triển khai.")
    print("Vector RAG (Phase 1-4) vẫn hoạt động đầy đủ.")
    print()

    svc = GraphService()

    # Test graph stats (method này đã implement)
    try:
        stats = svc.get_graph_stats()
        print(f"Graph stats hiện tại: {stats}")
    except Exception as e:
        print(f"Graph stats lỗi (có thể Neo4j chưa chạy): {e}")

    # Các method chưa implement
    print()
    print("Các method TODO Phase 5:")
    print("  - extract_entities(text) — Gemini NER")
    print("  - build_graph_from_chunks(chunks, file_id) — Build KG")
    print("  - graph_retrieve(query) — Graph traversal retrieval")
    print("  - hybrid_retrieve(query, alpha=0.7) — Vector + Graph fusion")
