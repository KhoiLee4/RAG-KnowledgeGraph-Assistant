"""
indexing_service.py — Pipeline chính: parse → chunk → embed → lưu ChromaDB + Neo4j.

Đây là service trung tâm kết nối tất cả các bước xử lý tài liệu.
Luồng:
  1. Nhận file_bytes + mime_type
  2. Kiểm tra MIME type có được hỗ trợ (SUPPORTED_MIME_TYPES) không
  3. Parse → trích xuất văn bản thuần
  4. Chunk → chia thành các đoạn nhỏ có overlap
  5. Embed → tạo vector bằng Gemini API
  6. Lưu vào ChromaDB (vector) + Neo4j (metadata graph)
"""

import hashlib
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from app.core.config import SKIP_MIME_TYPES, SUPPORTED_MIME_TYPES, settings
from app.core.gemini_retry import format_gemini_error, is_daily_quota_exhausted, is_quota_error
from app.db.chroma_client import get_chroma_client
from app.db.neo4j_client import get_neo4j_client
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.parser_service import ParserService

logger = logging.getLogger(__name__)


def content_hash(text: str) -> str:
    """SHA256 nội dung chunk — dedup khi sync/index lại."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def dedupe_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bỏ chunk trùng nội dung trong cùng một lần index."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for c in chunks:
        h = content_hash(c["text"])
        if h in seen:
            continue
        seen.add(h)
        unique.append({**c, "content_hash": h})
    removed = len(chunks) - len(unique)
    if removed:
        logger.info("dedupe_chunks: bỏ %d chunk trùng nội dung.", removed)
    return unique


# ══════════════════════════════════════════════════════════════
# Dataclass kết quả index
# ══════════════════════════════════════════════════════════════

@dataclass
class IndexResult:
    """
    Kết quả xử lý một file trong pipeline index.

    Attributes:
        file_id: Google Drive file ID.
        file_name: Tên file gốc.
        status: "success" | "skipped" | "error"
        reason: Lý do bỏ qua hoặc thông báo lỗi (rỗng nếu thành công).
        chunks_count: Số chunk đã tạo và lưu (0 nếu không index).
    """
    file_id: str
    file_name: str
    status: str         # "success" | "skipped" | "error"
    reason: str = ""
    chunks_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Chuyển IndexResult thành dict thuần để trả về JSON."""
        return asdict(self)


# ══════════════════════════════════════════════════════════════
# Hàm tiện ích kiểm tra MIME type
# ══════════════════════════════════════════════════════════════

def is_supported_file(mime_type: str) -> bool:
    """
    Kiểm tra MIME type có nằm trong whitelist được hỗ trợ index không.

    Args:
        mime_type: MIME type cần kiểm tra.

    Returns:
        True nếu mime_type nằm trong SUPPORTED_MIME_TYPES.
    """
    return mime_type in SUPPORTED_MIME_TYPES


def get_file_extension(mime_type: str) -> str:
    """
    Lấy extension file tương ứng với MIME type.

    Args:
        mime_type: MIME type cần tra cứu.

    Returns:
        Extension (ví dụ ".pdf", ".docx"), hoặc chuỗi rỗng nếu không hỗ trợ.
    """
    return SUPPORTED_MIME_TYPES.get(mime_type, "")


class IndexingService:
    """
    Orchestrator thực hiện toàn bộ pipeline index tài liệu.
    """

    def __init__(self):
        """Khởi tạo tất cả service phụ thuộc."""
        self._parser = ParserService()
        self._chunker = ChunkingService()
        self._embedder = EmbeddingService()
        self._chroma = get_chroma_client()
        self._neo4j = get_neo4j_client()
        logger.info("IndexingService khởi tạo thành công.")

    # ── Kiểm tra trạng thái ───────────────────────────────────

    def check_already_indexed(self, file_id: str, owner_id: str | None = None) -> bool:
        """Kiểm tra tài liệu đã được index chưa (theo user nếu có owner_id)."""
        try:
            meta = self._neo4j.get_document_metadata(file_id, owner_id=owner_id)
            return meta is not None
        except Exception as e:
            logger.warning("check_already_indexed '%s' lỗi: %s", file_id, e)
            return False

    # ── Index một file ────────────────────────────────────────

    def index_file(
        self,
        file_id: str,
        file_name: str,
        file_bytes: bytes,
        mime_type: str,
        collection_name: str | None = None,
        drive_link: str | None = None,
        force_reindex: bool = False,
        owner_id: str | None = None,
    ) -> IndexResult:
        """
        Index một tài liệu vào hệ thống knowledge base.

        Pipeline thực hiện:
          validate mime_type → parse file_bytes → chunk text → embed batch
          → lưu ChromaDB → lưu Neo4j

        Args:
            file_id: ID tài liệu (Google Drive file ID hoặc custom ID).
            file_name: Tên file (dùng cho metadata và citation).
            file_bytes: Nội dung file dạng bytes.
            mime_type: MIME type, ví dụ "application/pdf".
            collection_name: ChromaDB collection (mặc định từ settings).
            drive_link: Link xem file trên Drive (tùy chọn).
            force_reindex: Nếu True, xóa và index lại dù đã tồn tại.

        Returns:
            IndexResult với status "success" | "skipped" | "error".
        """
        col_name = collection_name or settings.CHROMA_DEFAULT_COLLECTION
        link = drive_link or f"https://drive.google.com/file/d/{file_id}/view"

        # ── Bước 0: Kiểm tra MIME type có được hỗ trợ không ──────
        if not is_supported_file(mime_type):
            if mime_type in SKIP_MIME_TYPES:
                reason = (
                    f"MIME type '{mime_type}' nằm trong danh sách bị cấm "
                    f"(ảnh/video/audio/binary — không thể index có nghĩa)."
                )
            else:
                ext = get_file_extension(mime_type)
                reason = (
                    f"MIME type '{mime_type}' không nằm trong whitelist hỗ trợ. "
                    f"Chỉ hỗ trợ: {list(SUPPORTED_MIME_TYPES.keys())}"
                )
            logger.warning(
                "BỎ QUA file '%s' (id=%s): %s", file_name, file_id, reason
            )
            return IndexResult(
                file_id=file_id,
                file_name=file_name,
                status="skipped",
                reason=reason,
            )

        # ── Bước 0a: force_reindex → xóa bản cũ trước khi ghi mới ──
        if force_reindex and self.check_already_indexed(file_id, owner_id=owner_id):
            logger.info("force_reindex: xóa index cũ của '%s'.", file_name)
            self.delete_index(file_id, col_name, owner_id=owner_id)

        # ── Bước 0b: Kiểm tra đã index chưa (bỏ qua nếu force_reindex) ──
        if not force_reindex and self.check_already_indexed(file_id, owner_id=owner_id):
            reason = "File đã được index trước đó (dùng force_reindex=True để index lại)."
            logger.info("BỎ QUA '%s': %s", file_name, reason)
            return IndexResult(
                file_id=file_id,
                file_name=file_name,
                status="skipped",
                reason=reason,
            )

        logger.info(
            "Bắt đầu index file '%s' (id=%s, mime=%s, %d bytes).",
            file_name, file_id, mime_type, len(file_bytes),
        )

        try:
            # ── Bước 1: Parse ───────────────────────────────
            text = self._parser.parse_file(file_bytes, mime_type)
            if not text.strip():
                reason = "Parser không extract được văn bản từ file (file rỗng hoặc bị mã hóa)."
                logger.warning("index_file '%s': %s", file_name, reason)
                return IndexResult(
                    file_id=file_id,
                    file_name=file_name,
                    status="error",
                    reason=reason,
                )

            # ── Bước 2: Chunk ───────────────────────────────
            metadata = {
                "file_id": file_id,
                "file_name": file_name,
                "mime_type": mime_type,
                "drive_link": link,
                "source": "drive",
            }
            chunks = dedupe_chunks(self._chunker.chunk_document(text, metadata))
            if not chunks:
                reason = "Chunking không tạo được chunk nào từ văn bản đã parse."
                logger.warning("index_file '%s': %s", file_name, reason)
                return IndexResult(
                    file_id=file_id,
                    file_name=file_name,
                    status="error",
                    reason=reason,
                )

            # ── Bước 3: Embed ───────────────────────────────
            texts = [c["text"] for c in chunks]
            embeddings = self._embedder.embed_batch(texts)

            # ── Bước 4: Lưu vào ChromaDB ────────────────────
            chunk_ids = [
                self._chunker.generate_chunk_id(file_id, c["chunk_index"])
                for c in chunks
            ]
            # Chroma chỉ chấp nhận metadata dạng str/int/float/bool
            chroma_metas = [
                {
                    "file_id": c["file_id"],
                    "file_name": c["file_name"],
                    "chunk_index": c["chunk_index"],
                    "total_chunks": c["total_chunks"],
                    "page_estimate": c["page_estimate"],
                    "line_start": c.get("line_start", 0),
                    "line_end": c.get("line_end", 0),
                    "drive_link": c.get("drive_link", link),
                    "source": c.get("source", "drive"),
                    "content_hash": c.get("content_hash", content_hash(c["text"])),
                }
                for c in chunks
            ]

            self._chroma.add_documents(
                chunks=texts,
                embeddings=embeddings,
                metadatas=chroma_metas,
                ids=chunk_ids,
                collection_name=col_name,
            )

            # ── Bước 5: Lưu metadata vào Neo4j ──────────────
            self._save_graph(
                file_id=file_id,
                file_name=file_name,
                mime_type=mime_type,
                chunk_count=len(chunks),
                chunks=chunks,
                chunk_ids=chunk_ids,
                drive_link=link,
                owner_id=owner_id,
            )

            # ── Bước 6: Build Knowledge Graph (best-effort) ──
            if settings.GRAPH_BUILD_ON_INDEX and settings.GRAPH_ENABLED:
                self._build_entity_graph(chunks, file_id, owner_id)

            logger.info(
                "Index '%s' thành công: %d chunk đã lưu.", file_name, len(chunks)
            )
            return IndexResult(
                file_id=file_id,
                file_name=file_name,
                status="success",
                chunks_count=len(chunks),
            )

        except Exception as e:
            logger.error("index_file '%s' thất bại: %s", file_name, e, exc_info=True)
            return IndexResult(
                file_id=file_id,
                file_name=file_name,
                status="error",
                reason=str(e),
            )

    # ── Batch index nhiều file ────────────────────────────────

    def index_drive(
        self,
        file_ids: list[str],
        collection_name: str | None = None,
        force_reindex: bool = False,
        on_progress: Callable[[int, int], None] | None = None,
        drive: Any | None = None,
        owner_id: str | None = None,
    ) -> list[IndexResult]:
        """
        Index nhiều file từ Google Drive theo danh sách ID.
        Cần DriveService đã xác thực để tải nội dung.

        Luồng cho mỗi file_id:
          lấy metadata → kiểm tra MIME type → tải bytes → index_file()

        Args:
            file_ids: Danh sách Google Drive file ID cần index.
            collection_name: ChromaDB collection.
            force_reindex: Xóa và index lại dù đã tồn tại.

        Returns:
            Danh sách IndexResult cho từng file (success / skipped / error).
        """
        # Import lazy để tránh circular import
        from app.services.drive_service import DriveService

        if drive is None:
            if not owner_id:
                raise ValueError("index_drive cần drive instance hoặc owner_id.")
            drive = DriveService(user_id=owner_id)
        results: list[IndexResult] = []
        consecutive_quota_failures = 0
        daily_quota_exhausted = False

        logger.info("Bắt đầu index %d file từ Drive.", len(file_ids))
        total = len(file_ids)

        for idx, file_id in enumerate(file_ids, start=1):
            if daily_quota_exhausted:
                results.append(IndexResult(
                    file_id=file_id,
                    file_name=file_id,
                    status="error",
                    reason=format_gemini_error(Exception("daily quota exhausted")),
                ))
                if on_progress:
                    on_progress(idx, total)
                continue

            if consecutive_quota_failures >= settings.INDEX_QUOTA_MAX_RETRIES + 2:
                results.append(IndexResult(
                    file_id=file_id,
                    file_name=file_id,
                    status="error",
                    reason=format_gemini_error(Exception("429 quota")),
                ))
                if on_progress:
                    on_progress(idx, total)
                continue

            try:
                # Lấy metadata để biết tên file và mime_type
                meta = drive.get_file_metadata(file_id)
                file_name = meta.get("name", file_id)
                mime_type = meta.get("mimeType", "")
                drive_link = meta.get("webViewLink", "")

                logger.info(
                    "Đang xử lý: '%s' (mime=%s)", file_name, mime_type
                )

                # Kiểm tra MIME type sớm — tránh tải file không cần thiết
                if not is_supported_file(mime_type):
                    reason = (
                        f"MIME type '{mime_type}' không được hỗ trợ — "
                        "bỏ qua để tiết kiệm bandwidth và token."
                    )
                    logger.info("BỎ QUA '%s': %s", file_name, reason)
                    results.append(IndexResult(
                        file_id=file_id,
                        file_name=file_name,
                        status="skipped",
                        reason=reason,
                    ))
                    continue

                # Tải nội dung file (Google Workspace dùng export, file thường dùng get_media)
                content_bytes, actual_mime = drive.download_file_content(
                    file_id, mime_type
                )

                # Chạy pipeline index — retry khi gặp 429
                result = self.index_file(
                    file_id=file_id,
                    file_name=file_name,
                    file_bytes=content_bytes,
                    mime_type=actual_mime,
                    collection_name=collection_name,
                    drive_link=drive_link,
                    force_reindex=force_reindex,
                    owner_id=owner_id,
                )
                quota_retries = 0
                while (
                    result.status == "error"
                    and is_quota_error(Exception(result.reason))
                    and not daily_quota_exhausted
                    and quota_retries < settings.INDEX_QUOTA_MAX_RETRIES
                ):
                    if is_daily_quota_exhausted(Exception(result.reason)):
                        daily_quota_exhausted = True
                        break
                    wait = settings.INDEX_QUOTA_COOLDOWN
                    logger.warning(
                        "index_drive: quota 429 '%s' — chờ %.0fs rồi retry (%d/%d).",
                        file_name,
                        wait,
                        quota_retries + 1,
                        settings.INDEX_QUOTA_MAX_RETRIES,
                    )
                    time.sleep(wait)
                    result = self.index_file(
                        file_id=file_id,
                        file_name=file_name,
                        file_bytes=content_bytes,
                        mime_type=actual_mime,
                        collection_name=collection_name,
                        drive_link=drive_link,
                        force_reindex=force_reindex,
                        owner_id=owner_id,
                    )
                    quota_retries += 1

                if result.status == "success":
                    consecutive_quota_failures = 0
                elif result.status == "error" and is_quota_error(Exception(result.reason)):
                    consecutive_quota_failures += 1
                    if is_daily_quota_exhausted(Exception(result.reason)):
                        daily_quota_exhausted = True
                else:
                    consecutive_quota_failures = 0

                results.append(result)
                time.sleep(settings.INDEX_FILE_PAUSE)

            except Exception as e:
                if is_daily_quota_exhausted(e):
                    daily_quota_exhausted = True
                    logger.error("index_drive: quota NGÀY đã hết — dừng index file mới.")
                elif is_quota_error(e):
                    consecutive_quota_failures += 1
                    logger.error(
                        "index_drive: quota Gemini — chờ %.0fs trước file tiếp theo.",
                        settings.INDEX_QUOTA_COOLDOWN,
                    )
                    time.sleep(settings.INDEX_QUOTA_COOLDOWN)
                logger.error(
                    "index_drive: lỗi khi xử lý file '%s': %s", file_id, e,
                    exc_info=not is_quota_error(e),
                )
                results.append(IndexResult(
                    file_id=file_id,
                    file_name=file_id,
                    status="error",
                    reason=format_gemini_error(e) if is_quota_error(e) else str(e),
                ))

            if on_progress:
                on_progress(idx, total)

        success = sum(1 for r in results if r.status == "success")
        skipped = sum(1 for r in results if r.status == "skipped")
        errors = sum(1 for r in results if r.status == "error")
        logger.info(
            "index_drive hoàn tất: %d thành công / %d bỏ qua / %d lỗi (tổng %d file).",
            success, skipped, errors, len(file_ids),
        )
        return results

    # ── Xóa index ─────────────────────────────────────────────

    def delete_index(
        self,
        file_id: str,
        collection_name: str | None = None,
        owner_id: str | None = None,
    ) -> bool:
        """
        Xóa tài liệu khỏi ChromaDB và Neo4j.

        Args:
            file_id: ID tài liệu cần xóa.
            collection_name: ChromaDB collection.

        Returns:
            True nếu thành công.
        """
        col_name = collection_name or settings.CHROMA_DEFAULT_COLLECTION
        try:
            # Lấy danh sách chunk ID từ ChromaDB theo filter
            collection = self._chroma._get_or_create(col_name)
            existing = collection.get(
                where={"file_id": file_id},
                include=[],  # Chỉ lấy IDs
            )
            chunk_ids = existing.get("ids", [])
            if chunk_ids:
                collection.delete(ids=chunk_ids)
                logger.info("Đã xóa %d chunk từ ChromaDB.", len(chunk_ids))

            # Xóa graph trong Neo4j
            self._neo4j.delete_document_graph(file_id)
            return True

        except Exception as e:
            logger.error("delete_index '%s' lỗi: %s", file_id, e)
            raise

    # ── Lưu graph vào Neo4j ───────────────────────────────────

    def _save_graph(
        self,
        file_id: str,
        file_name: str,
        mime_type: str,
        chunk_count: int,
        chunks: list[dict],
        chunk_ids: list[str],
        drive_link: str,
        owner_id: str | None = None,
    ) -> None:
        """
        Lưu cấu trúc Knowledge Graph vào Neo4j:
          - 1 node Document
          - N node Chunk
          - Quan hệ Document-[:CONTAINS]->Chunk
          - Quan hệ Chunk-[:NEXT]->Chunk (liên kết tuần tự)

        Args:
            file_id: ID tài liệu.
            file_name: Tên file.
            mime_type: MIME type.
            chunk_count: Số chunk.
            chunks: Danh sách chunk dict.
            chunk_ids: Danh sách ID của các chunk.
            drive_link: Link Drive.
        """
        # Tạo Document node
        extra: dict[str, Any] = {"drive_link": drive_link}
        if owner_id:
            extra["owner_id"] = owner_id
        self._neo4j.save_document_metadata(
            file_id=file_id,
            file_name=file_name,
            mime_type=mime_type,
            chunk_count=chunk_count,
            extra=extra,
        )

        # Tạo Chunk nodes và quan hệ
        prev_id: str | None = None
        for chunk, chunk_id in zip(chunks, chunk_ids):
            self._neo4j.create_entity_node("Chunk", {
                "id": chunk_id,
                "file_id": file_id,
                "chunk_index": chunk["chunk_index"],
                "page_estimate": chunk["page_estimate"],
                "preview": chunk["text"][:150],
            })

            # Document → Chunk
            self._neo4j.create_relationship(
                from_id=file_id,
                to_id=chunk_id,
                relation_type="CONTAINS",
                from_label="Document",
                to_label="Chunk",
            )

            # Chunk → Chunk kế tiếp
            if prev_id:
                self._neo4j.create_relationship(
                    from_id=prev_id,
                    to_id=chunk_id,
                    relation_type="NEXT",
                    from_label="Chunk",
                    to_label="Chunk",
                )
            prev_id = chunk_id

        logger.debug("Neo4j: đã lưu graph Document + %d Chunk.", chunk_count)

    def _build_entity_graph(
        self,
        chunks: list[dict[str, Any]],
        file_id: str,
        owner_id: str | None = None,
    ) -> None:
        """
        Gọi GraphService để trích xuất entity và xây dựng KG từ các chunk.
        Chạy best-effort: lỗi không làm index_file thất bại.
        """
        try:
            from app.services.graph_service import GraphService
            graph_svc = GraphService()
            stats = graph_svc.build_graph_from_chunks(chunks, file_id, owner_id=owner_id)
            logger.info(
                "[Graph] '%s': +%d entity, +%d relation.",
                file_id,
                stats.get("entities_created", 0),
                stats.get("relations_created", 0),
            )
        except Exception as e:
            logger.warning(
                "[Graph] build_entity_graph '%s' thất bại (bỏ qua, vector vẫn OK): %s",
                file_id,
                e,
            )


# ── Test độc lập ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Test IndexingService ===")

    svc = IndexingService()

    # Test với văn bản giả lập
    sample_text = """
    Đây là tài liệu thử nghiệm về hệ thống RAG.

    RAG (Retrieval-Augmented Generation) kết hợp tìm kiếm thông tin
    với khả năng sinh ngôn ngữ của mô hình ngôn ngữ lớn.

    Hệ thống gồm ba thành phần chính: indexing, retrieval và generation.
    Mỗi thành phần đóng vai trò quan trọng trong pipeline xử lý.
    """

    result = svc.index_file(
        file_id="test_file_001",
        file_name="test_rag_doc.txt",
        file_bytes=sample_text.encode("utf-8"),
        mime_type="text/plain",
        collection_name="test_index_col",
        force_reindex=True,
    )
    print(f"Kết quả index: {result}")

    # Kiểm tra đã index chưa
    is_indexed = svc.check_already_indexed("test_file_001")
    print(f"Đã index: {is_indexed}")

    # Xóa test
    svc.delete_index("test_file_001", "test_index_col")
    print("Đã xóa test data.")
