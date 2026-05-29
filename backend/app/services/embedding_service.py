"""
embedding_service.py — Tạo vector embedding dùng Gemini Embedding API.

Model: gemini-embedding-001 (3072 chiều mặc định; có thể giảm qua output_dimensionality)
Package: google-genai (KHÔNG dùng google-generativeai)

Hỗ trợ:
  - Embed từng text đơn lẻ.
  - Embed batch nhiều text một lần (giảm số lần gọi API).
  - Retry tự động khi gặp lỗi rate-limit.
"""

import logging
import time
from typing import Any

from google import genai
from google.genai import types as genai_types

from app.core.config import settings
from app.core.gemini_retry import call_with_gemini_retry, parse_retry_seconds

logger = logging.getLogger(__name__)

# Số lần retry khi gặp lỗi tạm thời (429 quota free tier)
MAX_RETRIES = 6
RETRY_DELAY = 3.0
EMBED_BATCH_PAUSE = 1.5  # giây giữa các batch — tránh vượt RPM


class EmbeddingService:
    """
    Service tạo vector embedding từ văn bản qua Gemini API.
    Sử dụng model gemini-embedding-001 (Google AI API).
    """

    def __init__(self, api_key: str | None = None):
        """
        Khởi tạo EmbeddingService với Gemini client.

        Args:
            api_key: Gemini API key. Mặc định đọc từ settings.
        """
        self._client = genai.Client(api_key=api_key or settings.GEMINI_API_KEY)
        self._model = settings.GEMINI_EMBEDDING_MODEL
        logger.info("EmbeddingService khởi tạo — model: %s", self._model)

    # ── Embed đơn lẻ ─────────────────────────────────────────

    def embed_text(self, text: str) -> list[float]:
        """
        Tạo vector embedding cho một đoạn văn bản (dùng khi index document).

        Args:
            text: Văn bản cần embed. Không được rỗng.

        Returns:
            List[float] là vector embedding (mặc định 3072 chiều).

        Raises:
            ValueError: Nếu text rỗng.
            Exception: Nếu API lỗi sau MAX_RETRIES lần thử.
        """
        if not text or not text.strip():
            raise ValueError("embed_text: text không được rỗng.")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = self._client.models.embed_content(
                    model=self._model,
                    contents=text,
                    config=genai_types.EmbedContentConfig(
                        task_type="RETRIEVAL_DOCUMENT",
                    ),
                )
                vector = list(result.embeddings[0].values)
                logger.debug("embed_text: %d ký tự → %d chiều.", len(text), len(vector))
                return vector

            except Exception as e:
                msg = str(e).lower()
                is_retriable = any(k in msg for k in ("quota", "rate", "timeout", "503", "429"))
                if attempt < MAX_RETRIES and is_retriable:
                    wait = parse_retry_seconds(e, RETRY_DELAY * attempt)
                    logger.warning(
                        "embed_text lỗi (attempt %d/%d) — retry sau %.1fs: %s",
                        attempt, MAX_RETRIES, wait, e,
                    )
                    time.sleep(wait)
                else:
                    logger.error("embed_text thất bại: %s", e)
                    raise

    def embed_query(self, text: str) -> list[float]:
        """
        Tạo vector embedding cho câu truy vấn (dùng task_type RETRIEVAL_QUERY).
        Vector query sẽ match tốt hơn với vector document khi tìm kiếm.

        Args:
            text: Câu truy vấn của người dùng.

        Returns:
            List[float] vector embedding của query.
        """
        if not text or not text.strip():
            raise ValueError("embed_query: text không được rỗng.")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = self._client.models.embed_content(
                    model=self._model,
                    contents=text,
                    config=genai_types.EmbedContentConfig(
                        task_type="RETRIEVAL_QUERY",
                    ),
                )
                return list(result.embeddings[0].values)

            except Exception as e:
                msg = str(e).lower()
                is_retriable = any(k in msg for k in ("quota", "rate", "timeout", "503", "429"))
                if attempt < MAX_RETRIES and is_retriable:
                    time.sleep(parse_retry_seconds(e, RETRY_DELAY * attempt))
                else:
                    logger.error("embed_query thất bại: %s", e)
                    raise

    # ── Embed batch ───────────────────────────────────────────

    def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 100,
    ) -> list[list[float]]:
        """
        Tạo vector embedding cho nhiều văn bản một lần.
        Chia thành batch nhỏ để tránh vượt giới hạn API.

        Args:
            texts: Danh sách văn bản cần embed.
            batch_size: Số text mỗi lần gọi API (tối đa 100 với Gemini).

        Returns:
            List[List[float]]: Danh sách vector, thứ tự tương ứng với texts.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        total_batches = (len(texts) + batch_size - 1) // batch_size

        logger.info(
            "embed_batch: %d text, %d batch (size=%d).",
            len(texts), total_batches, batch_size,
        )

        for batch_num, start in enumerate(range(0, len(texts), batch_size), 1):
            batch = texts[start: start + batch_size]

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    result = self._client.models.embed_content(
                        model=self._model,
                        contents=batch,
                        config=genai_types.EmbedContentConfig(
                            task_type="RETRIEVAL_DOCUMENT",
                        ),
                    )
                    vectors = [list(e.values) for e in result.embeddings]
                    all_embeddings.extend(vectors)
                    logger.debug(
                        "Batch %d/%d: %d embeddings.", batch_num, total_batches, len(vectors)
                    )
                    if batch_num < total_batches:
                        time.sleep(EMBED_BATCH_PAUSE)
                    break

                except Exception as e:
                    msg = str(e).lower()
                    is_retriable = any(k in msg for k in ("quota", "rate", "timeout", "503", "429"))
                    if attempt < MAX_RETRIES and is_retriable:
                        wait = parse_retry_seconds(e, RETRY_DELAY * attempt)
                        logger.warning(
                            "embed_batch lỗi (batch %d, attempt %d/%d) — retry sau %.1fs",
                            batch_num, attempt, MAX_RETRIES, wait,
                        )
                        time.sleep(wait)
                    else:
                        logger.error("embed_batch thất bại tại batch %d: %s", batch_num, e)
                        raise

        logger.info("embed_batch hoàn tất: %d/%d vectors.", len(all_embeddings), len(texts))
        return all_embeddings


# ── Test độc lập ──────────────────────────────────────────────
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    if not os.getenv("GEMINI_API_KEY"):
        print("Cần set GEMINI_API_KEY trong .env để test.")
        exit(1)

    print("=== Test EmbeddingService ===")
    svc = EmbeddingService()

    # Test embed_text
    vec = svc.embed_text("Xin chào! Đây là thử nghiệm embedding.")
    print(f"embed_text: {len(vec)} chiều | 5 giá trị đầu: {vec[:5]}")

    # Test embed_query
    query_vec = svc.embed_query("Hệ thống RAG là gì?")
    print(f"embed_query: {len(query_vec)} chiều | 5 giá trị đầu: {query_vec[:5]}")

    # Test embed_batch
    texts = [
        "Vector Database lưu trữ embedding.",
        "Knowledge Graph lưu trữ quan hệ.",
        "Gemini là mô hình AI của Google.",
    ]
    vectors = svc.embed_batch(texts)
    print(f"embed_batch: {len(vectors)} vectors, mỗi vector {len(vectors[0])} chiều.")
