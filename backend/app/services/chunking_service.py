"""
chunking_service.py — Chia văn bản thành các chunk nhỏ để embedding và indexing.

Chiến lược:
  1. Tách theo đoạn văn (paragraph) để giữ ngữ cảnh liên kết.
  2. Nếu đoạn vượt chunk_size → tách tiếp theo câu.
  3. Overlap giữa các chunk để tránh mất thông tin tại ranh giới.
  4. Ước tính page_estimate dựa trên vị trí ký tự.
"""

import logging
import re
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# Ước tính số ký tự trung bình mỗi trang A4 (dùng để tính page_estimate)
CHARS_PER_PAGE = 2500


def _char_to_line(text: str, char_pos: int) -> int:
    """Chuyển vị trí ký tự trong văn bản gốc thành số dòng (1-based)."""
    return text[: max(0, char_pos)].count("\n") + 1


def _locate_chunk_in_text(text: str, chunk_text: str, search_from: int = 0) -> tuple[int, int]:
    """Tìm vị trí chunk trong văn bản gốc (char_start, char_end)."""
    idx = text.find(chunk_text, search_from)
    if idx >= 0:
        return idx, idx + len(chunk_text)

    anchor_len = min(100, len(chunk_text))
    if anchor_len > 0:
        idx = text.find(chunk_text[:anchor_len], search_from)
        if idx >= 0:
            return idx, idx + len(chunk_text)

    return search_from, search_from + len(chunk_text)


_PAGE_MARKER_RE = re.compile(r"\[Trang (\d+)\]")


def _page_from_marker(text: str, char_start: int) -> int | None:
    """Lấy số trang thực từ marker [Trang N] (PDF) gần nhất trước vị trí chunk."""
    matches = list(_PAGE_MARKER_RE.finditer(text[: char_start + 1]))
    if not matches:
        return None
    page = int(matches[-1].group(1))
    return page if page > 0 else None


class ChunkingService:
    """
    Service chia văn bản thành list[dict] chuẩn bị cho embedding.
    """

    def __init__(self, chunk_size: int | None = None, overlap: int | None = None):
        """
        Khởi tạo ChunkingService.

        Args:
            chunk_size: Số ký tự tối đa mỗi chunk (mặc định từ settings).
            overlap: Số ký tự overlap giữa hai chunk liền kề (mặc định từ settings).
        """
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.overlap = overlap or settings.CHUNK_OVERLAP
        logger.info(
            "ChunkingService: chunk_size=%d, overlap=%d",
            self.chunk_size, self.overlap,
        )

    # ── Tách đơn vị nhỏ ──────────────────────────────────────

    def _split_paragraphs(self, text: str) -> list[str]:
        """
        Tách văn bản thành danh sách đoạn theo dấu xuống dòng kép.

        Args:
            text: Văn bản đầu vào.

        Returns:
            Danh sách đoạn văn không rỗng.
        """
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        paras = re.split(r"\n{2,}", normalized)
        return [p.strip() for p in paras if p.strip()]

    def _split_sentences(self, text: str) -> list[str]:
        """
        Tách đoạn văn thành câu dựa trên dấu câu và xuống dòng đơn.

        Args:
            text: Đoạn văn cần tách câu.

        Returns:
            Danh sách câu không rỗng.
        """
        # Tách theo . ! ? tiếp theo là khoảng trắng + chữ hoa (kể cả có dấu tiếng Việt)
        parts = re.split(r"(?<=[.!?])\s+", text)
        result = []
        for part in parts:
            # Tách thêm theo dấu xuống dòng đơn bên trong
            sub = [s.strip() for s in part.split("\n") if s.strip()]
            result.extend(sub)
        return result

    # ── API chính ─────────────────────────────────────────────

    def chunk_text(
        self,
        text: str,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Chia văn bản thành danh sách chunk cơ bản.

        Args:
            text: Văn bản cần chia.
            chunk_size: Override chunk_size (tùy chọn).
            overlap: Override overlap (tùy chọn).

        Returns:
            Danh sách dict, mỗi phần tử gồm:
              - text (str): Nội dung văn bản của chunk.
              - chunk_index (int): Thứ tự chunk (bắt đầu từ 0).
              - total_chunks (int): Tổng số chunk của văn bản này.
        """
        if not text or not text.strip():
            logger.warning("chunk_text nhận văn bản rỗng.")
            return []

        size = chunk_size or self.chunk_size
        ovlp = overlap if overlap is not None else self.overlap

        # Bước 1: Gom câu/đoạn vào buffer, flush thành chunk khi đủ size
        paragraphs = self._split_paragraphs(text)
        raw_chunks: list[str] = []
        buffer: list[str] = []
        buffer_len = 0

        flush_at = max(size // 2, 200)

        for para in paragraphs:
            units = [para] if len(para) <= size else self._split_sentences(para)
            for unit in units:
                if not unit:
                    continue
                # Flush sớm tại ranh giới đoạn khi buffer ~50% chunk_size (giữ ngữ cảnh đoạn)
                if (
                    buffer
                    and buffer_len >= flush_at
                    and buffer_len + len(unit) + 1 > flush_at
                ):
                    raw_chunks.append(" ".join(buffer))
                    overlap_text = " ".join(buffer)[-ovlp:] if ovlp else ""
                    buffer = [overlap_text] if overlap_text else []
                    buffer_len = len(overlap_text)
                if buffer_len + len(unit) + 1 > size and buffer:
                    raw_chunks.append(" ".join(buffer))
                    # Overlap: giữ lại phần cuối của chunk trước
                    overlap_text = " ".join(buffer)[-ovlp:] if ovlp else ""
                    buffer = [overlap_text] if overlap_text else []
                    buffer_len = len(overlap_text)
                buffer.append(unit)
                buffer_len += len(unit) + 1

        if buffer:
            raw_chunks.append(" ".join(buffer))

        total = len(raw_chunks)
        result = [
            {"text": chunk_text, "chunk_index": i, "total_chunks": total}
            for i, chunk_text in enumerate(raw_chunks)
        ]

        logger.info(
            "chunk_text: %d ký tự → %d chunk (size=%d, overlap=%d).",
            len(text), total, size, ovlp,
        )
        return result

    def chunk_document(
        self,
        text: str,
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Chia tài liệu thành chunk và gắn đầy đủ metadata.

        Args:
            text: Nội dung văn bản của tài liệu.
            metadata: Dict chứa ít nhất: file_id, file_name.
                      Có thể thêm source, drive_link, mime_type...

        Returns:
            Danh sách dict, mỗi phần tử gồm:
              - text (str): Nội dung chunk.
              - chunk_index (int): Thứ tự chunk.
              - total_chunks (int): Tổng số chunk.
              - file_id (str): ID tài liệu nguồn.
              - file_name (str): Tên file nguồn.
              - page_estimate (int): Ước tính trang trong tài liệu gốc.
              + toàn bộ key trong metadata được merge vào.
        """
        base_chunks = self.chunk_text(text)
        if not base_chunks:
            return []

        file_id = metadata.get("file_id", "unknown")
        file_name = metadata.get("file_name", "unknown")

        result: list[dict[str, Any]] = []
        search_from = 0

        for chunk in base_chunks:
            char_start, char_end = _locate_chunk_in_text(
                text, chunk["text"], search_from
            )
            search_from = char_start + 1
            marker_page = _page_from_marker(text, char_start)
            page_estimate = marker_page or max(1, (char_start // CHARS_PER_PAGE) + 1)
            line_start = _char_to_line(text, char_start)
            line_end = _char_to_line(text, char_end)

            doc_chunk = {
                **chunk,              # text, chunk_index, total_chunks
                "file_id": file_id,
                "file_name": file_name,
                "page_estimate": page_estimate,
                "char_start": char_start,
                "char_end": char_end,
                "line_start": line_start,
                "line_end": line_end,
                **{k: v for k, v in metadata.items() if k not in ("file_id", "file_name")},
            }
            result.append(doc_chunk)

        logger.info(
            "chunk_document '%s': %d chunk.", file_name, len(result)
        )
        return result

    def generate_chunk_id(self, file_id: str, chunk_index: int) -> str:
        """
        Tạo ID duy nhất cho chunk theo format chuẩn.

        Args:
            file_id: ID file gốc.
            chunk_index: Thứ tự chunk.

        Returns:
            Chuỗi ID dạng "{file_id}__chunk_{chunk_index}".
        """
        return f"{file_id}__chunk_{chunk_index}"


# ── Test độc lập ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Test ChunkingService ===")
    svc = ChunkingService(chunk_size=200, overlap=30)

    sample = """
    Hệ thống GraphRAG kết hợp Vector Database và Knowledge Graph để tìm kiếm thông tin.

    Vector Database lưu trữ embedding của các đoạn văn bản, cho phép tìm kiếm ngữ nghĩa.
    Knowledge Graph lưu trữ quan hệ giữa các entity, cho phép suy luận logic.

    Khi người dùng đặt câu hỏi, hệ thống:
    1. Embed câu hỏi thành vector.
    2. Tìm kiếm chunk gần nhất trong Vector DB.
    3. Mở rộng context qua Knowledge Graph.
    4. Tổng hợp câu trả lời bằng LLM.
    """

    # Test chunk_text
    chunks = svc.chunk_text(sample)
    print(f"\nchunk_text → {len(chunks)} chunk:")
    for c in chunks:
        print(f"  [{c['chunk_index']}/{c['total_chunks']-1}] {c['text'][:80]}...")

    # Test chunk_document
    doc_chunks = svc.chunk_document(sample, {
        "file_id": "drive_xyz789",
        "file_name": "GraphRAG_Overview.pdf",
        "source": "drive",
    })
    print(f"\nchunk_document → {len(doc_chunks)} chunk:")
    for c in doc_chunks:
        print(f"  [{c['chunk_index']}] page~{c['page_estimate']} | {c['text'][:60]}...")
        print(f"      chunk_id: {svc.generate_chunk_id(c['file_id'], c['chunk_index'])}")
