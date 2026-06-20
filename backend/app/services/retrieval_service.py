"""
retrieval_service.py — Tìm kiếm context liên quan từ knowledge base.

Luồng:
  1. Embed câu truy vấn (RETRIEVAL_QUERY task type).
  2. Vector search ChromaDB (lấy nhiều ứng viên hơn top_k).
  3. Hybrid rerank: 85% vector + 15% keyword (token overlap).
  4. Lọc theo min_score, trả về top_k chunk kèm citation metadata.

Kết quả mỗi chunk:
  {text, file_name, file_id, chunk_index, score, drive_link, page_estimate}
"""

import logging
from typing import Any

from app.core.config import settings
from app.db.chroma_client import get_chroma_client
from app.services.embedding_service import EmbeddingService
from app.services.hybrid_search import merge_hybrid_scores

logger = logging.getLogger(__name__)


class RetrievalService:
    """
    Service thực hiện Retrieval bước trong pipeline RAG.
    Nhận câu truy vấn, trả về các chunk context liên quan.
    """

    def __init__(self):
        """Khởi tạo RetrievalService với ChromaDB client và EmbeddingService."""
        self._chroma = get_chroma_client()
        self._embedder = EmbeddingService()
        logger.info("RetrievalService khởi tạo thành công.")

    def _distance_to_score(self, distance: float) -> float:
        """Chuyển cosine distance [0,2] → similarity [0,1]."""
        return max(0.0, 1.0 - distance / 2.0)

    def _raw_to_candidate(self, r: dict[str, Any]) -> dict[str, Any]:
        """Chuẩn hóa một dòng kết quả ChromaDB thành candidate dict."""
        meta = r.get("metadata", {})
        distance = r.get("distance", 1.0)
        vector_score = self._distance_to_score(distance)
        return {
            "text": r.get("document", ""),
            "file_name": meta.get("file_name", "Unknown"),
            "file_id": meta.get("file_id", ""),
            "chunk_index": int(meta.get("chunk_index", 0)),
            "score": round(vector_score, 4),
            "vector_score": round(vector_score, 4),
            "drive_link": meta.get(
                "drive_link",
                f"https://drive.google.com/file/d/{meta.get('file_id', '')}/view",
            ),
            "page_estimate": int(meta.get("page_estimate", 1)),
            "distance": round(distance, 4),
            "id": r.get("id", ""),
        }

    def retrieve(
        self,
        query: str,
        collection_name: str | None = None,
        n_results: int | None = None,
        file_id_filter: str | None = None,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Hybrid retrieval: vector search + keyword rerank + ngưỡng min_score.

        Args:
            query: Câu truy vấn của người dùng.
            collection_name: Tên ChromaDB collection.
            n_results: Số chunk trả về (mặc định RETRIEVAL_TOP_K).
            file_id_filter: Giới hạn trong một file Drive.
            min_score: Ngưỡng combined_score tối thiểu.

        Returns:
            Danh sách chunk đã xếp hạng, mỗi phần tử có score = combined_score.
        """
        col_name = collection_name or settings.CHROMA_DEFAULT_COLLECTION
        top_k = n_results or settings.RETRIEVAL_TOP_K
        threshold = min_score if min_score is not None else settings.RETRIEVAL_MIN_SCORE
        multiplier = max(1, settings.RETRIEVAL_CANDIDATE_MULTIPLIER)
        n_candidates = min(top_k * multiplier, 50)

        try:
            query_vector = self._embedder.embed_query(query)
        except Exception as e:
            logger.error("retrieve: embed query thất bại: %s", e)
            raise

        try:
            where = {"file_id": file_id_filter} if file_id_filter else None
            raw_results = self._chroma.search_similar(
                query_embedding=query_vector,
                collection_name=col_name,
                n_results=n_candidates,
                where=where,
            )
        except Exception as e:
            logger.error("retrieve: ChromaDB search thất bại: %s", e)
            raise

        candidates = [self._raw_to_candidate(r) for r in raw_results]
        if not candidates:
            logger.info("retrieve '%s...': không có ứng viên.", query[:60])
            return []

        merged = merge_hybrid_scores(
            candidates,
            query,
            vector_weight=settings.RETRIEVAL_VECTOR_WEIGHT,
            keyword_weight=settings.RETRIEVAL_KEYWORD_WEIGHT,
        )

        filtered = [c for c in merged if c["combined_score"] >= threshold]
        results = filtered[:top_k]

        if merged and not results:
            logger.info(
                "retrieve '%s...': %d ứng viên nhưng không đạt min_score=%.2f "
                "(best=%.3f).",
                query[:60],
                len(merged),
                threshold,
                merged[0]["combined_score"],
            )
        else:
            logger.info(
                "retrieve '%s...': %d/%d kết quả (min_score=%.2f, hybrid %.0f/%.0f).",
                query[:60],
                len(results),
                len(candidates),
                threshold,
                settings.RETRIEVAL_VECTOR_WEIGHT * 100,
                settings.RETRIEVAL_KEYWORD_WEIGHT * 100,
            )
        return results

    def format_context(
        self,
        results: list[dict[str, Any]],
        max_chars: int = 8000,
    ) -> str:
        """
        Định dạng danh sách chunk thành chuỗi context để đưa vào LLM prompt.
        """
        if not results:
            return "Không tìm thấy thông tin liên quan trong knowledge base."

        sections: list[str] = []
        total_chars = 0

        for i, r in enumerate(results, 1):
            header = (
                f"[{i}] Nguồn: {r['file_name']} "
                f"(Trang ~{r['page_estimate']}, Chunk {r['chunk_index']})"
            )
            entry = f"{header}\n{r['text']}"

            if total_chars + len(entry) > max_chars:
                remaining = max_chars - total_chars
                if remaining > 200:
                    entry = entry[:remaining] + "...[truncated]"
                    sections.append(entry)
                break

            sections.append(entry)
            total_chars += len(entry)

        return "\n\n---\n\n".join(sections)


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    from app.core.config import ENV_FILE_PATH

    load_dotenv(ENV_FILE_PATH)

    if not os.getenv("GEMINI_API_KEY"):
        print("Cần set GEMINI_API_KEY trong .env để test.")
        exit(1)

    print("=== Test RetrievalService (hybrid) ===")
    svc = RetrievalService()
    query = "Hệ thống RAG hoạt động như thế nào?"
    try:
        results = svc.retrieve(query, n_results=3)
        print(f"\nCâu hỏi: {query}")
        print(f"Tìm được {len(results)} kết quả:")
        for r in results:
            print(
                f"\n  [{r['chunk_index']}] {r['file_name']} "
                f"(combined={r['score']:.3f}, vec={r.get('vector_score', 0):.3f}, "
                f"kw={r.get('keyword_score', 0):.3f})"
            )
            print(f"  {r['text'][:100]}...")
    except Exception as e:
        print(f"Lỗi: {e}")
