"""
chroma_client.py — Client kết nối và thao tác ChromaDB Vector Database.

ChromaDB lưu trữ embedding vector của các chunk văn bản,
phục vụ tìm kiếm semantic similarity trong hệ thống RAG.
"""

import logging
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection

from app.core.config import settings

logger = logging.getLogger(__name__)


class ChromaClient:
    """
    Wrapper quanh chromadb.HttpClient.
    Kết nối tới ChromaDB server đang chạy trên Docker.
    """

    def __init__(self, host: str | None = None, port: int | None = None):
        """
        Khởi tạo ChromaClient và kiểm tra kết nối.

        Args:
            host: ChromaDB host (mặc định từ settings).
            port: ChromaDB port (mặc định từ settings).
        """
        self._host = host or settings.CHROMA_HOST
        self._port = port or settings.CHROMA_PORT
        self._client = chromadb.HttpClient(host=self._host, port=self._port)
        # Kiểm tra server phản hồi
        self._client.heartbeat()
        logger.info("ChromaDB kết nối thành công — %s:%s", self._host, self._port)

    # ── Quản lý collection ────────────────────────────────────

    def _get_or_create(self, collection_name: str) -> Collection:
        """
        Lấy collection nếu tồn tại, tạo mới nếu chưa có.
        Dùng cosine distance để so sánh embedding.

        Args:
            collection_name: Tên collection.

        Returns:
            Collection object của ChromaDB.
        """
        return self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def delete_collection(self, collection_name: str) -> bool:
        """
        Xóa toàn bộ collection và tất cả document bên trong.

        Args:
            collection_name: Tên collection cần xóa.

        Returns:
            True nếu thành công.
        """
        try:
            self._client.delete_collection(collection_name)
            logger.info("Đã xóa collection '%s'.", collection_name)
            return True
        except Exception as e:
            logger.error("delete_collection '%s' lỗi: %s", collection_name, e)
            raise

    def get_collection_info(self, collection_name: str) -> dict[str, Any]:
        """
        Lấy thông tin tổng quan về một collection.

        Args:
            collection_name: Tên collection cần xem.

        Returns:
            Dict gồm: name, count (số document), metadata của collection.
        """
        try:
            col = self._get_or_create(collection_name)
            return {
                "name": col.name,
                "count": col.count(),
                "metadata": col.metadata,
            }
        except Exception as e:
            logger.error("get_collection_info '%s' lỗi: %s", collection_name, e)
            raise

    # ── Thêm / tìm kiếm document ──────────────────────────────

    def add_documents(
        self,
        chunks: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        ids: list[str],
        collection_name: str | None = None,
    ) -> bool:
        """
        Thêm (hoặc cập nhật) danh sách chunk văn bản vào collection.
        Sử dụng upsert: nếu id đã tồn tại thì ghi đè.

        Args:
            chunks: Danh sách văn bản gốc (document text).
            embeddings: Danh sách vector embedding tương ứng.
            metadatas: Danh sách metadata cho từng chunk
                       (ví dụ: file_id, file_name, chunk_index).
            ids: Danh sách ID duy nhất cho mỗi chunk.
            collection_name: Tên collection, mặc định từ settings.

        Returns:
            True nếu upsert thành công.
        """
        if not (len(chunks) == len(embeddings) == len(metadatas) == len(ids)):
            raise ValueError("chunks, embeddings, metadatas, ids phải có cùng độ dài.")

        col_name = collection_name or settings.CHROMA_DEFAULT_COLLECTION
        try:
            col = self._get_or_create(col_name)
            col.upsert(
                documents=chunks,
                embeddings=embeddings,
                metadatas=metadatas,
                ids=ids,
            )
            logger.info(
                "Upsert %d chunk vào collection '%s'.", len(ids), col_name
            )
            return True
        except Exception as e:
            logger.error("add_documents lỗi: %s", e)
            raise

    def search_similar(
        self,
        query_embedding: list[float],
        collection_name: str | None = None,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Tìm kiếm chunk gần nhất với query_embedding bằng cosine similarity.

        Args:
            query_embedding: Vector embedding của câu truy vấn.
            collection_name: Tên collection cần tìm.
            n_results: Số lượng kết quả trả về (mặc định 5).
            where: Bộ lọc metadata, ví dụ {"file_id": "abc123"}.

        Returns:
            Danh sách dict, mỗi dict gồm: id, document, metadata, distance.
            distance = 0 nghĩa là giống hoàn toàn.
        """
        col_name = collection_name or settings.CHROMA_DEFAULT_COLLECTION
        try:
            col = self._get_or_create(col_name)

            params: dict[str, Any] = {
                "query_embeddings": [query_embedding],
                "n_results": min(n_results, col.count() or 1),
                "include": ["documents", "metadatas", "distances"],
            }
            if where:
                params["where"] = where

            raw = col.query(**params)

            results = []
            for i, doc_id in enumerate(raw["ids"][0]):
                results.append({
                    "id": doc_id,
                    "document": raw["documents"][0][i],
                    "metadata": raw["metadatas"][0][i],
                    "distance": raw["distances"][0][i],
                })
            return results
        except Exception as e:
            logger.error("search_similar lỗi: %s", e)
            raise

    def get_by_ids(
        self,
        ids: list[str],
        collection_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Lấy chunk theo danh sách ID (dùng cho graph expansion).

        Args:
            ids: Danh sách chunk ID cần lấy.
            collection_name: Tên collection.

        Returns:
            Danh sách dict gồm id, document, metadata.
        """
        col_name = collection_name or settings.CHROMA_DEFAULT_COLLECTION
        try:
            col = self._get_or_create(col_name)
            raw = col.get(ids=ids, include=["documents", "metadatas"])
            results = []
            for i, doc_id in enumerate(raw.get("ids", [])):
                results.append({
                    "id": doc_id,
                    "document": raw["documents"][i],
                    "metadata": raw["metadatas"][i],
                })
            return results
        except Exception as e:
            logger.error("get_by_ids lỗi: %s", e)
            raise


# ── Singleton ─────────────────────────────────────────────────

_instance: ChromaClient | None = None


def get_chroma_client() -> ChromaClient:
    """Trả về singleton ChromaClient (tạo lần đầu khi gọi)."""
    global _instance
    if _instance is None:
        _instance = ChromaClient()
    return _instance


# ── Test độc lập ──────────────────────────────────────────────
if __name__ == "__main__":
    import random

    print("=== Test ChromaClient ===")
    client = ChromaClient()

    # Tạo embedding giả (1536 chiều)
    fake_embedding = [random.random() for _ in range(1536)]

    # Thêm document thử
    client.add_documents(
        chunks=["Đây là đoạn văn bản thử nghiệm.", "Đây là đoạn thứ hai."],
        embeddings=[fake_embedding, [random.random() for _ in range(1536)]],
        metadatas=[
            {"file_id": "test_001", "file_name": "test.pdf", "chunk_index": 0},
            {"file_id": "test_001", "file_name": "test.pdf", "chunk_index": 1},
        ],
        ids=["test_001__chunk_0", "test_001__chunk_1"],
        collection_name="test_collection",
    )

    # Lấy thông tin collection
    info = client.get_collection_info("test_collection")
    print(f"Collection info: {info}")

    # Tìm kiếm
    results = client.search_similar(fake_embedding, "test_collection", n_results=2)
    print(f"Tìm được {len(results)} kết quả:")
    for r in results:
        print(f"  - {r['id']} (distance={r['distance']:.4f}): {r['document'][:50]}")

    # Dọn dẹp
    client.delete_collection("test_collection")
    print("Đã xóa collection test.")
