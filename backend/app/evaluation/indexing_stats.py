"""Thu thập chỉ số Lớp 1: pipeline indexing / graph."""

from __future__ import annotations

from typing import Any

from app.core.config import settings


def collect_indexing_stats(
    owner_id: str | None = None,
    collection_name: str | None = None,
) -> dict[str, Any]:
    """Tổng hợp số liệu indexing từ Neo4j, ChromaDB và cấu hình chunk."""
    col = collection_name or settings.CHROMA_DEFAULT_COLLECTION
    stats: dict[str, Any] = {
        "collection_name": col,
        "owner_id": owner_id,
        "chunking": {
            "chunk_size": settings.CHUNK_SIZE,
            "chunk_overlap": settings.CHUNK_OVERLAP,
        },
        "data": {},
        "embedding": {},
        "graph": {},
        "vector_store": {},
    }

    try:
        from app.db.neo4j_client import get_neo4j_client

        neo4j = get_neo4j_client()
        docs = neo4j.list_documents(limit=500, owner_id=owner_id)

        mime_counts: dict[str, int] = {}
        total_chunks = 0
        for doc in docs:
            mime = str(doc.get("mime_type", "unknown"))
            mime_counts[mime] = mime_counts.get(mime, 0) + 1
            total_chunks += int(doc.get("chunk_count", 0) or 0)

        stats["data"] = {
            "file_count": len(docs),
            "mime_types": mime_counts,
            "total_chunks_from_documents": total_chunks,
            "files": [
                {
                    "file_id": d.get("id", d.get("file_id", "")),
                    "file_name": d.get("file_name", ""),
                    "mime_type": d.get("mime_type", ""),
                    "chunk_count": int(d.get("chunk_count", 0) or 0),
                }
                for d in docs
            ],
        }
    except Exception as e:
        stats["data"] = {"error": str(e)}

    try:
        from app.db.chroma_client import get_chroma_client

        chroma = get_chroma_client()
        info = chroma.get_collection_info(col)
        stats["vector_store"] = {
            "collection": col,
            "chunk_vectors": info.get("count", 0),
        }
    except Exception as e:
        stats["vector_store"] = {"error": str(e)}

    try:
        from app.services.graph_service import GraphService

        graph_stats = GraphService().get_graph_stats(owner_id=owner_id)
        relations = graph_stats.get("relations_by_type") or {}
        total_relations = sum(int(v) for v in relations.values())

        doc_count = 0
        chunk_node_count = 0
        try:
            from app.db.neo4j_client import get_neo4j_client

            neo4j = get_neo4j_client()
            if owner_id:
                doc_records = neo4j.run_cypher(
                    "MATCH (d:Document {owner_id: $oid}) RETURN count(d) AS c",
                    {"oid": owner_id},
                )
                chunk_records = neo4j.run_cypher(
                    "MATCH (c:Chunk {owner_id: $oid}) RETURN count(c) AS c",
                    {"oid": owner_id},
                )
            else:
                doc_records = neo4j.run_cypher(
                    "MATCH (d:Document) RETURN count(d) AS c"
                )
                chunk_records = neo4j.run_cypher(
                    "MATCH (c:Chunk) RETURN count(c) AS c"
                )
            doc_count = doc_records[0]["c"] if doc_records else 0
            chunk_node_count = chunk_records[0]["c"] if chunk_records else 0
        except Exception:
            pass

        stats["graph"] = {
            "document_nodes": doc_count,
            "chunk_nodes": chunk_node_count,
            "entity_nodes": graph_stats.get("total_entities", 0),
            "community_nodes": graph_stats.get("total_communities", 0),
            "relations_by_type": relations,
            "total_relations": total_relations,
            "entity_types": graph_stats.get("entity_types", {}),
        }
    except Exception as e:
        stats["graph"] = {"error": str(e)}

    stats["embedding"] = {
        "model": settings.GEMINI_EMBEDDING_MODEL,
        "note": (
            "Thời gian embedding và số lỗi API chưa được ghi persist; "
            "xem log khi sync/index."
        ),
    }

    return stats
