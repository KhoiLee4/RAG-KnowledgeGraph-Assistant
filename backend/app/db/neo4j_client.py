"""
neo4j_client.py — Client kết nối và thao tác Neo4j Graph Database.

Lưu trữ Knowledge Graph gồm các entity (Document, Chunk, Person, Concept...)
và quan hệ giữa chúng, phục vụ Graph-enhanced RAG retrieval.
"""

import logging
from typing import Any

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import AuthError, ServiceUnavailable

from app.core.config import settings

logger = logging.getLogger(__name__)


class Neo4jClient:
    """
    Wrapper quanh Neo4j Python driver.
    Cung cấp các thao tác CRUD cơ bản và graph traversal.
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        """
        Khởi tạo kết nối tới Neo4j server.

        Args:
            uri: Bolt URI (mặc định từ settings).
            user: Tên đăng nhập (mặc định từ settings).
            password: Mật khẩu (mặc định từ settings).
        """
        self._uri = uri or settings.NEO4J_URI
        self._user = user or settings.NEO4J_USER
        self._password = password or settings.NEO4J_PASSWORD
        self._driver: Driver | None = None
        self._connect()

    # ── Kết nối ───────────────────────────────────────────────

    def _connect(self) -> None:
        """Tạo driver và xác nhận kết nối. Raise lỗi rõ ràng nếu thất bại."""
        try:
            self._driver = GraphDatabase.driver(
                self._uri, auth=(self._user, self._password)
            )
            self._driver.verify_connectivity()
            logger.info("Neo4j kết nối thành công — %s", self._uri)
        except AuthError as e:
            raise AuthError(f"Neo4j xác thực thất bại — sai user/password: {e}") from e
        except ServiceUnavailable as e:
            raise ServiceUnavailable(
                f"Neo4j không khả dụng tại {self._uri} — kiểm tra Docker: {e}"
            ) from e

    def close(self) -> None:
        """Đóng driver, giải phóng tài nguyên connection pool."""
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("Neo4j driver đã đóng.")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _run(self, cypher: str, params: dict | None = None) -> list[dict[str, Any]]:
        """
        Chạy câu Cypher và trả về danh sách record dạng dict.

        Args:
            cypher: Câu lệnh Cypher.
            params: Tham số truyền vào (an toàn, tránh injection).

        Returns:
            Danh sách dict từ kết quả query.
        """
        with self._driver.session() as session:
            result = session.run(cypher, params or {})
            return [record.data() for record in result]

    # ── CRUD node ─────────────────────────────────────────────

    def create_entity_node(
        self,
        entity_type: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Tạo hoặc cập nhật một entity node trong Knowledge Graph.
        Dùng MERGE theo id để tránh tạo node trùng.

        Args:
            entity_type: Loại entity (nhãn node Neo4j), ví dụ:
                         "Document", "Chunk", "Person", "Concept".
            properties: Thuộc tính của node. Nếu có key "id",
                        MERGE theo id; ngược lại CREATE mới.

        Returns:
            Dict thuộc tính của node đã tạo/cập nhật.
        """
        try:
            if "id" in properties:
                cypher = (
                    f"MERGE (n:{entity_type} {{id: $id}}) "
                    "SET n += $props "
                    "RETURN n"
                )
                params = {"id": properties["id"], "props": properties}
            else:
                cypher = f"CREATE (n:{entity_type} $props) RETURN n"
                params = {"props": properties}

            records = self._run(cypher, params)
            result = dict(records[0]["n"]) if records else {}
            logger.debug(
                "Tạo/merge node (%s) id=%s", entity_type, result.get("id", "?")
            )
            return result
        except Exception as e:
            logger.error("create_entity_node (%s) lỗi: %s", entity_type, e)
            raise

    def create_relationship(
        self,
        from_id: str,
        to_id: str,
        relation_type: str,
        properties: dict[str, Any] | None = None,
        from_label: str = "",
        to_label: str = "",
    ) -> bool:
        """
        Tạo quan hệ có hướng giữa hai node: (from)-[RELATION]->(to).
        Dùng MERGE để tránh tạo quan hệ trùng.

        Args:
            from_id: id của node nguồn.
            to_id: id của node đích.
            relation_type: Kiểu quan hệ (VIẾT HOA), ví dụ "CONTAINS", "MENTIONS", "NEXT".
            properties: Thuộc tính kèm quan hệ (tùy chọn).
            from_label: Nhãn node nguồn (bỏ qua nếu để trống).
            to_label: Nhãn node đích (bỏ qua nếu để trống).

        Returns:
            True nếu tạo thành công.
        """
        try:
            # Xây dựng pattern MATCH linh hoạt theo label
            from_pattern = f"(a:{from_label} {{id: $from_id}})" if from_label else "(a {id: $from_id})"
            to_pattern = f"(b:{to_label} {{id: $to_id}})" if to_label else "(b {id: $to_id})"

            cypher = (
                f"MATCH {from_pattern} "
                f"MATCH {to_pattern} "
                f"MERGE (a)-[r:{relation_type}]->(b) "
                "SET r += $props "
                "RETURN r"
            )
            self._run(cypher, {
                "from_id": from_id,
                "to_id": to_id,
                "props": properties or {},
            })
            logger.debug("Quan hệ (%s)-[%s]->(%s)", from_id, relation_type, to_id)
            return True
        except Exception as e:
            logger.error(
                "create_relationship %s-[%s]->%s lỗi: %s",
                from_id, relation_type, to_id, e,
            )
            raise

    # ── Graph traversal ───────────────────────────────────────

    def find_related_entities(
        self,
        entity_name: str,
        depth: int = 2,
        entity_label: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Tìm tất cả entity liên quan trong đồ thị bằng cách duyệt từ node gốc.
        Phục vụ bước Graph Retrieval trong GraphRAG.

        Args:
            entity_name: Tên hoặc id của entity gốc.
            depth: Số bước duyệt (hops), mặc định 2.
            entity_label: Nhãn của entity gốc (tùy chọn, giúp tìm nhanh hơn).

        Returns:
            Danh sách dict gồm: entity (thuộc tính), relation_type, labels.
        """
        try:
            # Tìm theo cả id lẫn name để linh hoạt
            label_part = f":{entity_label}" if entity_label else ""
            cypher = f"""
            MATCH (root{label_part})
            WHERE root.id = $name OR root.name = $name
            MATCH (root)-[r*1..{depth}]-(related)
            RETURN DISTINCT
                related AS entity,
                labels(related) AS labels,
                type(r[-1]) AS last_relation
            LIMIT 50
            """
            records = self._run(cypher, {"name": entity_name})
            return [
                {
                    "entity": dict(r["entity"]),
                    "labels": r["labels"],
                    "relation": r["last_relation"],
                }
                for r in records
            ]
        except Exception as e:
            logger.error("find_related_entities '%s' lỗi: %s", entity_name, e)
            raise

    def get_document_metadata(self, file_id: str) -> dict[str, Any] | None:
        """
        Lấy metadata của Document node từ Neo4j theo file_id.
        Dùng để kiểm tra file đã được index chưa.

        Args:
            file_id: Google Drive file ID (là thuộc tính id của Document node).

        Returns:
            Dict metadata của document, hoặc None nếu chưa được index.
        """
        try:
            cypher = "MATCH (d:Document {id: $file_id}) RETURN d"
            records = self._run(cypher, {"file_id": file_id})
            if records:
                return dict(records[0]["d"])
            return None
        except Exception as e:
            logger.error("get_document_metadata '%s' lỗi: %s", file_id, e)
            raise

    def save_document_metadata(
        self,
        file_id: str,
        file_name: str,
        mime_type: str = "",
        chunk_count: int = 0,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Lưu hoặc cập nhật metadata của tài liệu đã index.

        Args:
            file_id: Google Drive file ID.
            file_name: Tên file.
            mime_type: MIME type của file.
            chunk_count: Số chunk đã được index.
            extra: Metadata bổ sung tùy ý.

        Returns:
            Dict thuộc tính của Document node.
        """
        props = {
            "id": file_id,
            "file_name": file_name,
            "mime_type": mime_type,
            "chunk_count": chunk_count,
            "drive_link": f"https://drive.google.com/file/d/{file_id}/view",
            **(extra or {}),
        }
        return self.create_entity_node("Document", props)

    def list_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Liệt kê tất cả Document node đã được index.

        Args:
            limit: Số lượng tối đa.

        Returns:
            Danh sách dict metadata của từng document.
        """
        try:
            records = self._run(
                "MATCH (d:Document) RETURN d ORDER BY d.file_name LIMIT $limit",
                {"limit": limit},
            )
            return [dict(r["d"]) for r in records]
        except Exception as e:
            logger.error("list_documents lỗi: %s", e)
            raise

    def delete_document_graph(self, file_id: str) -> bool:
        """
        Xóa toàn bộ node và quan hệ liên quan tới một document.

        Args:
            file_id: Google Drive file ID.

        Returns:
            True nếu thành công.
        """
        try:
            # Xóa Document node và Chunk nodes
            self._run(
                "MATCH (d:Document {id: $id}) DETACH DELETE d",
                {"id": file_id},
            )
            self._run(
                "MATCH (c:Chunk {file_id: $id}) DETACH DELETE c",
                {"id": file_id},
            )
            logger.info("Đã xóa document graph: %s", file_id)
            return True
        except Exception as e:
            logger.error("delete_document_graph '%s' lỗi: %s", file_id, e)
            raise

    def run_cypher(self, cypher: str, params: dict | None = None) -> list[dict]:
        """
        Chạy câu Cypher tùy ý. Dùng để query linh hoạt trong graph_service.

        Args:
            cypher: Câu lệnh Cypher.
            params: Tham số đầu vào.

        Returns:
            Danh sách record dạng dict.
        """
        return self._run(cypher, params)


# ── Singleton ─────────────────────────────────────────────────

_instance: Neo4jClient | None = None


def get_neo4j_client() -> Neo4jClient:
    """Trả về singleton Neo4jClient."""
    global _instance
    if _instance is None:
        _instance = Neo4jClient()
    return _instance


# ── Test độc lập ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Test Neo4jClient ===")
    client = Neo4jClient()

    # Tạo Document node
    doc = client.save_document_metadata(
        file_id="drive_abc123",
        file_name="Báo cáo Q1 2024.pdf",
        mime_type="application/pdf",
        chunk_count=12,
    )
    print(f"Document node: {doc}")

    # Tạo Chunk node
    chunk = client.create_entity_node("Chunk", {
        "id": "drive_abc123__chunk_0",
        "file_id": "drive_abc123",
        "chunk_index": 0,
        "preview": "Đây là nội dung chunk đầu tiên...",
    })
    print(f"Chunk node: {chunk}")

    # Tạo quan hệ Document -> Chunk
    client.create_relationship(
        from_id="drive_abc123",
        to_id="drive_abc123__chunk_0",
        relation_type="CONTAINS",
        from_label="Document",
        to_label="Chunk",
    )
    print("Quan hệ CONTAINS tạo thành công.")

    # Kiểm tra metadata
    meta = client.get_document_metadata("drive_abc123")
    print(f"Metadata document: {meta}")

    # Tìm entity liên quan
    related = client.find_related_entities("drive_abc123", depth=1)
    print(f"Entity liên quan: {related}")

    # Dọn dẹp
    client.delete_document_graph("drive_abc123")
    print("Đã xóa test data.")

    client.close()
    print("Kết nối đã đóng.")
