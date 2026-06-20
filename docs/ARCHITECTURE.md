# Kiến trúc hệ thống

## Tổng quan

```
┌─────────────┐     OAuth + REST      ┌──────────────────────────────────────┐
│  Frontend   │ ────────────────────► │  Backend (FastAPI :8081)           │
│  React/Vite │ ◄────────────────────── │  /api/v1/*  +  /api/v1/auth/*      │
│  :3000      │     SSE stream /chat    └──────────┬─────────────┬─────────────┘
└─────────────┘                                  │             │
                                                 ▼             ▼
                                    ┌────────────────┐  ┌──────────────┐
                                    │  ChromaDB      │  │  Neo4j       │
                                    │  (vectors)     │  │  (graph)     │
                                    │  :8000         │  │  :7687       │
                                    └────────────────┘  └──────────────┘
                                                 │
                                                 ▼
                                    ┌────────────────┐  ┌──────────────┐
                                    │  Google Drive  │  │  Gemini API  │
                                    │  (tài liệu)    │  │  embed + LLM │
                                    └────────────────┘  └──────────────┘
```

## Luồng index tài liệu

1. User đăng nhập Google OAuth → session cookie `rag_session`
2. **Sync Drive** → `DriveService` liệt kê file Word (.doc, .docx, Google Docs)
3. **Parse** → `parser_service` trích xuất text
4. **Chunk** → `chunking_service` chia đoạn (512 token, overlap 50)
5. **Embed** → `embedding_service` gọi Gemini embedding → lưu ChromaDB
6. **Cấu trúc** → `neo4j_client` tạo node `Document`, `Chunk`, quan hệ `HAS_CHUNK`
7. **GraphRAG** (nếu `GRAPH_BUILD_ON_INDEX=true`) → `graph_service` trích entity bằng Gemini batch → node `Entity`, quan hệ `MENTIONS`, `RELATED_TO`, `COOCCURS_WITH`

Mỗi user có `owner_id` riêng — dữ liệu vector và graph được cô lập theo tài khoản.

## Luồng hỏi đáp (RAG)

1. `POST /chat` nhận câu hỏi + lịch sử hội thoại
2. **Retrieval** (`retrieval_service` + `graph_service.hybrid_retrieve`):
   - Vector search trên ChromaDB (cosine similarity)
   - Keyword boost (`hybrid_search`)
   - Graph traversal 1–2 hop trên Neo4j (nếu `GRAPH_ENABLED=true`)
   - Fusion: `score = α × vector + (1-α) × graph` (`GRAPH_ALPHA`)
3. **Generation** → Gemini 2.0 Flash với context chunks + citations
4. Trả về answer + citations (nguồn: `vector` / `graph` / `hybrid`)

## Cấu trúc backend

```
backend/
├── main.py                 # FastAPI entry, middleware, lifecycle
├── start.ps1               # Chạy uvicorn qua venv
├── requirements.txt
├── .env.example
├── tests/
└── app/
    ├── api/
    │   ├── routes.py           # Gộp router /api/v1
    │   ├── auth_routes.py      # Google OAuth
    │   ├── chat_routes.py
    │   ├── drive_routes.py
    │   ├── document_routes.py
    │   ├── graph_routes.py
    │   ├── health_routes.py
    │   ├── schemas.py          # Pydantic models
    │   ├── deps.py             # Service singletons
    │   └── sync_helpers.py     # Drive sync-all logic
    ├── core/
    │   ├── config.py           # Settings + MIME whitelist
    │   ├── auth_deps.py        # Session user
    │   └── gemini_retry.py     # 429 / quota handling
    ├── db/
    │   ├── chroma_client.py
    │   └── neo4j_client.py
    └── services/
        ├── indexing_service.py   # Pipeline index end-to-end
        ├── chat_service.py       # RAG Q&A
        ├── retrieval_service.py  # Vector + keyword retrieval
        ├── graph_service.py      # Entity extraction + graph ops
        ├── embedding_service.py
        ├── drive_service.py
        ├── parser_service.py
        ├── chunking_service.py
        ├── hybrid_search.py
        ├── sync_job_store.py     # In-memory async sync jobs
        └── oauth_config.py
```

## Cấu trúc frontend

```
frontend/src/
├── main.jsx              # ThemeProvider + Router
├── App.jsx               # Sidebar layout + routes
├── api/client.js         # Axios client (credentials: include)
├── lib/utils.js          # cn() helper
├── index.css             # Design tokens (light/dark)
└── components/
    ├── ChatInterface.jsx
    ├── DocumentList.jsx
    ├── GraphStats.jsx
    ├── HealthPage.jsx
    └── layout/           # AppSidebar, PageHeader, ThemeToggle
```

## API chính

| Method | Path | Mô tả |
|--------|------|--------|
| GET | `/api/v1/health` | Health check |
| POST | `/api/v1/chat` | Hỏi đáp (JSON hoặc SSE) |
| GET | `/api/v1/auth/google` | Bắt đầu OAuth |
| GET | `/api/v1/drive/status` | Trạng thái Drive |
| POST | `/api/v1/drive/sync-all/async` | Sync nền (trả job_id) |
| GET | `/api/v1/documents` | Danh sách tài liệu |
| GET | `/api/v1/graph/stats` | Thống kê Knowledge Graph |
| POST | `/api/v1/graph/rebuild/{file_id}` | Rebuild graph cho 1 file |

Swagger UI: http://127.0.0.1:8081/docs

## Multi-user

- Mỗi user Google có collection ChromaDB: `knowledge_base__{user_id}`
- Neo4j nodes/relationships gắn `owner_id`
- OAuth token lưu trong `backend/tokens/{google_sub}.pickle`

## GraphRAG config (`.env`)

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `GRAPH_ENABLED` | `true` | Bật hybrid retrieval |
| `GRAPH_ALPHA` | `0.7` | Trọng số vector (0–1) |
| `GRAPH_BUILD_ON_INDEX` | `true` | Tự build KG khi index |
| `GRAPH_ENTITY_BATCH_SIZE` | `8` | Chunk/batch cho NER |
| `INDEX_FILE_PAUSE` | `5.0` | Giây nghỉ giữa các file |

Xem đầy đủ trong `.env.example` (thư mục gốc repo).
