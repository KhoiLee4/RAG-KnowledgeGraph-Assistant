"""
chat_service.py — Dịch vụ hội thoại RAG: retrieve context → build prompt → Gemini → answer + citations.

Luồng:
  1. Nhận câu hỏi + (tùy chọn) lịch sử hội thoại.
  2. Retrieve context liên quan từ ChromaDB.
  3. Xây dựng prompt yêu cầu Gemini trả lời dựa trên context.
  4. Parse response → trả về answer + danh sách citations rõ ràng.

Package: google-genai, model: gemini-2.0-flash
"""

import logging
import re
from typing import Any

from google import genai
from google.genai import types as genai_types

from app.core.config import settings
from app.core.gemini_retry import call_with_gemini_retry, format_gemini_error, is_quota_error
from app.services.citation_formatter import format_citations
from app.services.hybrid_retrieval_service import get_hybrid_retrieval_service
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

# System prompt định nghĩa hành vi của trợ lý
SYSTEM_PROMPT = """Bạn là trợ lý ảo thông minh, chuyên trả lời dựa trên tài liệu cá nhân của người dùng.

QUY TẮC BẮT BUỘC:
1. Chỉ dùng thông tin từ CONTEXT. Không bịa đặt thêm.
2. Trả lời tự nhiên, mạch lạc, lịch sự — bằng tiếng Việt nếu người dùng hỏi tiếng Việt, tiếng Anh nếu hỏi tiếng Anh.
3. Cấu trúc rõ ràng: câu mở đầu ngắn gọn → chi tiết → tóm tắt ngắn nếu phù hợp.
4. Khi liệt kê nhiều mục (nhiệm vụ, địa chỉ, quy định…), dùng gạch đầu dòng.
5. Trích dẫn nguồn bằng [1], [2]… đặt CUỐI câu hoặc cuối đoạn liên quan.
6. KHÔNG viết "Knowledge Graph", "Community", "Vector", "chunk", "context" hay thuật ngữ kỹ thuật trong câu trả lời.
7. Nếu CONTEXT thiếu thông tin, trả lời: "Tôi không tìm thấy thông tin này trong tài liệu của bạn." và gợi ý hỏi cụ thể hơn nếu có thể.
"""


class ChatService:
    """
    Service xử lý hội thoại RAG đầu-cuối với Gemini.
    Hỗ trợ multi-turn conversation (lịch sử hội thoại).
    """

    def __init__(self):
        """Khởi tạo ChatService với Gemini client, RetrievalService và GraphService."""
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._retrieval = RetrievalService()
        self._hybrid = get_hybrid_retrieval_service()
        self._model = settings.GEMINI_MODEL
        logger.info("ChatService khởi tạo — model: %s", self._model)

    # ── Build prompt ──────────────────────────────────────────

    def _build_prompt_contents(
        self,
        question: str,
        context: str,
        history: list[dict[str, str]] | None = None,
    ) -> list[genai_types.Content]:
        """
        Xây dựng danh sách Content cho Gemini API (multi-turn format).
        Bao gồm: lịch sử hội thoại + context + câu hỏi hiện tại.

        Args:
            question: Câu hỏi của người dùng.
            context: Context văn bản từ retrieval.
            history: Lịch sử hội thoại dạng list[{role, content}].
                     role phải là "user" hoặc "model".

        Returns:
            Danh sách Content objects theo format Gemini.
        """
        contents: list[genai_types.Content] = []

        # Thêm lịch sử hội thoại (tối đa 6 turn gần nhất)
        if history:
            for turn in history[-6:]:
                role = "user" if turn.get("role") == "user" else "model"
                contents.append(genai_types.Content(
                    role=role,
                    parts=[genai_types.Part(text=turn.get("content", ""))],
                ))

        # Câu hỏi hiện tại kèm context
        user_message = (
            f"=== TÀI LIỆU THAM KHẢO (CONTEXT) ===\n"
            f"{context}\n"
            f"=== HẾT CONTEXT ===\n\n"
            f"Câu hỏi: {question}"
        )
        contents.append(genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=user_message)],
        ))

        return contents

    def _extract_citations(
        self,
        citations: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Chuẩn hóa citations thân thiện với người dùng."""
        return format_citations(citations)

    def _run_retrieval(
        self,
        question: str,
        collection_name: str,
        top_k: int,
        owner_id: str | None,
        retrieval_mode: str = "auto",
    ):
        """Retrieve context bundle — hybrid hoặc vector-only."""
        if retrieval_mode == "rag" or not settings.GRAPH_ENABLED:
            chunks = self._retrieval.retrieve(
                question, collection_name, n_results=top_k
            )
            context = self._retrieval.format_context(chunks)
            from app.services.hybrid_retrieval_service import RetrievalBundle
            citations = [
                {
                    "file_name": c.get("file_name", ""),
                    "file_id": c.get("file_id", ""),
                    "chunk_index": str(c.get("chunk_index", 0)),
                    "drive_link": c.get("drive_link", ""),
                    "page_estimate": str(c.get("page_estimate", 1)),
                    "score": f"{c.get('score', 0):.3f}",
                    "source": "vector",
                    "source_type": "vector",
                    "snippet": str(c.get("text", ""))[:200],
                }
                for c in chunks
            ]
            return RetrievalBundle(
                context=context,
                citations=citations,
                vector_chunks=chunks,
                route="rag_only",
            )

        return self._hybrid.retrieve_all(
            query=question,
            collection_name=collection_name,
            owner_id=owner_id,
            n_results=top_k,
            retrieval_mode=retrieval_mode,
        )

    def _try_list_documents_answer(self, question: str) -> dict[str, Any] | None:
        """
        Trả lời câu hỏi meta ('tôi có những gì', 'danh sách tài liệu') không cần gọi Gemini.
        """
        q = question.lower().strip()
        patterns = (
            r"tôi (đang )?có (những )?gì",
            r"co nhung gi",
            r"danh sách tài liệu",
            r"liệt kê tài liệu",
            r"có bao nhiêu tài liệu",
            r"what (documents|files) do i have",
        )
        if not any(re.search(p, q) for p in patterns):
            return None

        return self._build_documents_list_answer()

    def _try_topics_answer(self, question: str) -> dict[str, Any] | None:
        """Trả lời câu hỏi về lĩnh vực/chủ đề có thể hỏi — không cần Gemini."""
        q = question.lower().strip()
        patterns = (
            r"lĩnh vực",
            r"linh vuc",
            r"chủ đề",
            r"chu de",
            r"bạn (có thể )?trả lời",
            r"ban co the tra loi",
            r"hỏi (về )?gì",
            r"hoi (ve )?gi",
            r"what (topics|subjects|areas)",
            r"what can you (answer|help)",
        )
        if not any(re.search(p, q) for p in patterns):
            return None

        try:
            from app.db.neo4j_client import get_neo4j_client

            docs = get_neo4j_client().list_documents(limit=100)
        except Exception as e:
            logger.warning("Không liệt kê được tài liệu: %s", e)
            return None

        if not docs:
            return {
                "answer": (
                    "Chưa có tài liệu nào được index. "
                    "Sau khi đồng bộ Drive, tôi có thể trả lời theo nội dung file của bạn."
                ),
                "citations": [],
                "sources_count": 0,
                "context_used": "",
            }

        by_type: dict[str, list[str]] = {}
        for d in docs:
            mime = d.get("mime_type") or "unknown"
            label = {
                "application/pdf": "PDF",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
                "application/msword": "Word",
                "application/vnd.google-apps.document": "Google Docs",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
                "application/vnd.ms-excel": "Excel",
                "application/vnd.google-apps.spreadsheet": "Google Sheets",
                "text/plain": "TXT",
            }.get(mime, mime.split("/")[-1].upper() if "/" in mime else "Khác")
            name = d.get("file_name") or d.get("id", "?")
            by_type.setdefault(label, []).append(name)

        lines = [
            f"Dựa trên {len(docs)} tài liệu đã index, bạn có thể hỏi về các nhóm sau:\n"
        ]
        for label, names in sorted(by_type.items(), key=lambda x: -len(x[1])):
            samples = ", ".join(names[:4])
            extra = f" (+{len(names) - 4} file)" if len(names) > 4 else ""
            lines.append(f"• {label} ({len(names)} file): {samples}{extra}")

        lines.append(
            "\nHãy hỏi cụ thể theo tên file hoặc nội dung, ví dụ:\n"
            "  - \"Tóm tắt file Mô tả thuật toán\"\n"
            "  - \"TEST API EXTERNAL là gì?\""
        )

        return {
            "answer": "\n".join(lines),
            "citations": [
                {
                    "file_name": d.get("file_name", ""),
                    "chunk_index": "0",
                    "drive_link": d.get("drive_link", ""),
                    "page_estimate": "1",
                    "score": "1.000",
                }
                for d in docs[:8]
            ],
            "sources_count": len(docs),
            "context_used": "",
        }

    def _build_documents_list_answer(self) -> dict[str, Any]:
        """Liệt kê tài liệu từ Neo4j."""
        try:
            from app.db.neo4j_client import get_neo4j_client

            docs = get_neo4j_client().list_documents(limit=100)
        except Exception as e:
            logger.warning("Không liệt kê được tài liệu: %s", e)
            return {
                "answer": "Không đọc được danh sách tài liệu lúc này.",
                "citations": [],
                "sources_count": 0,
                "context_used": "",
            }

        if not docs:
            return {
                "answer": "Bạn chưa index tài liệu nào. Vào tab Tài liệu → Đồng bộ Drive.",
                "citations": [],
                "sources_count": 0,
                "context_used": "",
            }

        lines = [f"Bạn đang có {len(docs)} tài liệu trong knowledge base:\n"]
        for i, d in enumerate(docs[:30], 1):
            name = d.get("file_name") or d.get("id", "?")
            chunks = d.get("chunk_count", 0)
            lines.append(f"{i}. {name} ({chunks} chunks)")
        if len(docs) > 30:
            lines.append(f"\n... và {len(docs) - 30} tài liệu khác (xem tab Tài liệu).")

        return {
            "answer": "\n".join(lines),
            "citations": [
                {
                    "file_name": d.get("file_name", ""),
                    "chunk_index": "0",
                    "drive_link": d.get("drive_link", ""),
                    "page_estimate": "1",
                    "score": "1.000",
                }
                for d in docs[:10]
            ],
            "sources_count": len(docs),
            "context_used": "",
        }

    def _try_meta_answer(self, question: str) -> dict[str, Any] | None:
        """Câu hỏi meta — trả lời ngay, không RAG/Gemini."""
        return self._try_list_documents_answer(question) or self._try_topics_answer(question)

    # ── Chat chính ────────────────────────────────────────────

    def chat(
        self,
        question: str,
        collection_name: str | None = None,
        history: list[dict[str, str]] | None = None,
        n_context: int | None = None,
        owner_id: str | None = None,
        retrieval_mode: str = "auto",
    ) -> dict[str, Any]:
        """
        Xử lý câu hỏi theo pipeline GraphRAG và trả về câu trả lời kèm citations.

        Pipeline:
          QueryAnalyzer → HybridRetrieval (community + graph + vector) → Gemini

        Args:
            question: Câu hỏi của người dùng.
            collection_name: ChromaDB collection cần tìm kiếm. Mặc định từ settings.
            history: Lịch sử hội thoại dạng [{"role": "user"/"model", "content": "..."}].
            n_context: Số chunk context lấy về (mặc định từ settings.RETRIEVAL_TOP_K).
            owner_id: User ID để phân tách graph theo từng người dùng.

        Returns:
            Dict gồm:
              - answer (str): Câu trả lời từ Gemini.
              - citations (list): Danh sách nguồn trích dẫn, mỗi phần tử:
                  {file_name, chunk_index, drive_link, page_estimate, score, source}
              - sources_count (int): Số nguồn tìm được.
              - context_used (str): Context đã dùng (dùng để debug).
        """
        if not question or not question.strip():
            return {
                "answer": "Vui lòng nhập câu hỏi.",
                "citations": [],
                "sources_count": 0,
                "context_used": "",
            }

        top_k = n_context or settings.RETRIEVAL_TOP_K
        col_name = collection_name or settings.CHROMA_DEFAULT_COLLECTION

        logger.info("ChatService.chat — câu hỏi: '%s...'", question[:80])

        meta = self._try_meta_answer(question)
        if meta:
            return meta

        try:
            bundle = self._run_retrieval(
                question, col_name, top_k, owner_id, retrieval_mode
            )
            if bundle.is_empty:
                return {
                    "answer": (
                        "Tôi không tìm thấy thông tin liên quan trong tài liệu của bạn. "
                        "Hãy thử hỏi cụ thể hơn hoặc đồng bộ thêm tài liệu từ Drive."
                    ),
                    "citations": [],
                    "sources_count": 0,
                    "context_used": "",
                }
            context = bundle.context
            citations = self._extract_citations(bundle.citations)
            contents = self._build_prompt_contents(question, context, history)

            def _generate():
                return self._client.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.1,
                        max_output_tokens=2048,
                    ),
                )

            response = call_with_gemini_retry(_generate, label="chat")

            answer = response.text or "Không nhận được phản hồi từ Gemini."

            logger.info(
                "ChatService.chat thành công — %d từ, %d citations, route=%s.",
                len(answer.split()),
                len(citations),
                bundle.route,
            )

            return {
                "answer": answer,
                "citations": citations,
                "sources_count": len(citations),
                "context_used": context,
            }

        except Exception as e:
            logger.error("ChatService.chat lỗi: %s", e)
            if is_quota_error(e):
                return {
                    "answer": format_gemini_error(e),
                    "citations": [],
                    "sources_count": 0,
                    "context_used": "",
                }
            raise

    # ── Streaming (Server-Sent Events) ───────────────────────

    async def chat_stream(
        self,
        question: str,
        collection_name: str | None = None,
        history: list[dict[str, str]] | None = None,
        owner_id: str | None = None,
        retrieval_mode: str = "auto",
    ):
        """
        Streaming version của chat, yield từng đoạn văn bản khi Gemini trả về.
        Dùng với FastAPI StreamingResponse (SSE format).

        Args:
            question: Câu hỏi của người dùng.
            collection_name: ChromaDB collection.
            history: Lịch sử hội thoại.

        Yields:
            Chuỗi SSE format: "data: {text}\\n\\n"
            Kết thúc bằng: "data: [DONE]\\n\\n"
        """
        import json

        if not question.strip():
            yield "data: Vui lòng nhập câu hỏi.\n\n"
            return

        col_name = collection_name or settings.CHROMA_DEFAULT_COLLECTION

        meta = self._try_meta_answer(question)
        if meta:
            yield f"data: {meta['answer'].replace(chr(10), '\\n')}\n\n"
            yield f"data: [CITATIONS]{json.dumps(meta['citations'], ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return

        try:
            bundle = self._run_retrieval(
                question, col_name, settings.RETRIEVAL_TOP_K, owner_id, retrieval_mode
            )
            if bundle.is_empty:
                msg = (
                    "Tôi không tìm thấy thông tin liên quan trong tài liệu của bạn. "
                    "Hãy thử hỏi cụ thể hơn hoặc đồng bộ thêm tài liệu từ Drive."
                )
                yield f"data: {msg.replace(chr(10), '\\n')}\n\n"
                yield "data: [CITATIONS][]\n\n"
                yield "data: [DONE]\n\n"
                return

            context = bundle.context
            contents = self._build_prompt_contents(question, context, history)

            def _stream():
                return self._client.models.generate_content_stream(
                    model=self._model,
                    contents=contents,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.1,
                        max_output_tokens=2048,
                    ),
                )

            stream = call_with_gemini_retry(_stream, label="chat_stream")

            for chunk in stream:
                if chunk.text:
                    # Escape newline trong SSE
                    text = chunk.text.replace("\n", "\\n")
                    yield f"data: {text}\n\n"

            # Gửi citations sau khi stream xong
            citations = self._extract_citations(bundle.citations)
            yield f"data: [CITATIONS]{json.dumps(citations, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error("ChatService.chat_stream lỗi: %s", e)
            yield f"data: [ERROR]{format_gemini_error(e)}\n\n"


# ── Test độc lập ──────────────────────────────────────────────
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    from app.core.config import ENV_FILE_PATH

    load_dotenv(ENV_FILE_PATH)

    if not os.getenv("GEMINI_API_KEY"):
        print("Cần set GEMINI_API_KEY trong .env.")
        exit(1)

    print("=== Test ChatService ===")
    print("Cần ChromaDB đang chạy và đã có dữ liệu index.\n")

    svc = ChatService()

    question = "Hệ thống RAG hoạt động như thế nào?"
    print(f"Câu hỏi: {question}\n")

    try:
        result = svc.chat(question)
        print(f"Trả lời:\n{result['answer']}\n")
        print(f"Số nguồn: {result['sources_count']}")
        print("Citations:")
        for c in result["citations"]:
            print(f"  - {c['file_name']} | Trang ~{c['page_estimate']} | {c['drive_link']}")
    except Exception as e:
        print(f"Lỗi: {e}")
        print("Hint: Cần index tài liệu trước bằng IndexingService.")
