# Đánh giá RAG / GraphRAG

Khung 4 lớp: indexing stats → retrieval metrics → answer scoring → so sánh theo nhóm câu hỏi.

## Yêu cầu

- Docker: ChromaDB + Neo4j đang chạy
- `.env` có `GEMINI_API_KEY`
- Đã index tài liệu (sync Drive)

Chạy từ thư mục `backend` với venv:

```powershell
cd backend
..\venv\Scripts\python.exe scripts\evaluate.py indexing-stats
```

## Lớp 1 — Thống kê indexing

```powershell
..\venv\Scripts\python.exe scripts\evaluate.py indexing-stats --owner-id YOUR_GOOGLE_USER_ID
```

Hoặc qua API (đã đăng nhập): `GET /api/v1/evaluation/indexing-stats`

## Lớp 2 — Retrieval (Hit@k, MRR…)

1. Tìm chunk đúng cho từng câu hỏi:

```powershell
..\venv\Scripts\python.exe scripts\evaluate.py discover -q "RAG là gì?" --mode rag
..\venv\Scripts\python.exe scripts\evaluate.py discover -q "RAG là gì?" --mode graph_rag
```

2. Copy `chunk_key` vào `expected_chunks` trong `evaluation/questions.json`.

3. Chạy benchmark chỉ retrieval (không tốn token LLM):

```powershell
..\venv\Scripts\python.exe scripts\evaluate.py run --retrieval-only --modes rag graph_rag
```

## Lớp 3 & 4 — Câu trả lời + so sánh nhóm

Chạy full (gọi Gemini):

```powershell
..\venv\Scripts\python.exe scripts\evaluate.py run --modes rag graph_rag
```

Sau khi chấm tay thang 2-1-0, điền `"human_score": 0|1|2` vào từng câu trong `questions.json` rồi chạy lại.

Báo cáo JSON: `evaluation/results/report_*.json`

## Cấu hình dataset

Trong `evaluation/questions.json`:

| Trường | Ý nghĩa |
|--------|---------|
| `category` | factual / descriptive / relationship / combined / edge_case |
| `expected_chunks` | `[{"chunk_id": "fileId__chunk_0"}]` hoặc `{file_id, chunk_index}` |
| `ground_truth_keywords` | Proxy tự động (không thay chấm tay) |
| `should_refuse` | `true` cho câu không có trong tài liệu |
| `human_score` | 0 / 1 / 2 sau khi chấm tay |

Đặt `owner_id` và `collection_name` trong file JSON nếu dùng multi-user (`kb_<user_id>`).

## Unit tests

```powershell
..\venv\Scripts\pytest.exe tests\test_evaluation_metrics.py -q
```
