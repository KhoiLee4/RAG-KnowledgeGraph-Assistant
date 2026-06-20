# RAG Knowledge Graph Assistant

Trợ lý ảo quản trị tri thức cá nhân — đồ án tốt nghiệp DATN.

Tích hợp **Google Drive**, **GraphRAG**, **ChromaDB** (vector), **Neo4j** (graph), **Gemini 2.0 Flash**.

## Tính năng

- Đăng nhập Google OAuth — mỗi user có Drive và knowledge base riêng
- Đồng bộ tài liệu Word (.doc, .docx, Google Docs) từ Drive
- Index: parse → chunk → embed → lưu vector + cấu trúc graph
- GraphRAG: trích xuất entity, quan hệ; hybrid retrieval khi chat
- Chat streaming (SSE) với citations và nguồn vector/graph/hybrid
- Dashboard: tài liệu, thống kê graph, system health

## Tech stack

| Layer | Công nghệ |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, pydantic-settings |
| AI | Google Gemini (LLM + embedding) |
| Vector DB | ChromaDB |
| Graph DB | Neo4j 5 |
| Frontend | React 18, Vite, Tailwind CSS, React Router |
| Infra | Docker Compose |

## Cấu trúc dự án

```
RAG-KnowledgeGraph-Assistant/
├── backend/          # FastAPI API server
├── frontend/         # React UI (Vite)
├── docs/             # Tài liệu kỹ thuật + privacy policy
├── docker-compose.yml
└── README.md
```

Chi tiết kiến trúc: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)  
Hướng dẫn dev: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

## Chạy local (Windows)

### 1. Docker — ChromaDB + Neo4j

```powershell
docker compose up -d
```

### 2. Backend

```powershell
# Lần đầu: tạo venv + cài dependencies
python -m venv venv
.\venv\Scripts\pip install -r backend\requirements.txt

# Cấu hình (một file .env ở thư mục gốc repo)
copy .env.example .env    # điền GEMINI_API_KEY, OAuth, SESSION_SECRET

# Chạy server (cổng 8081)
cd backend
.\start.ps1
```

Kiểm tra: http://127.0.0.1:8081/api/v1/health

### 3. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Mở http://localhost:3000 — Vite proxy `/api` → `localhost:8081`.

## Google OAuth

1. [Google Cloud Console](https://console.cloud.google.com/) → bật **Google Drive API**
2. Tạo **OAuth Client ID** loại **Web application**
3. **Authorized redirect URI:** `http://localhost:3000/api/v1/auth/google/callback`
4. Thêm vào `.env` (thư mục gốc repo):

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:3000/api/v1/auth/google/callback
SESSION_SECRET=<chuỗi ngẫu nhiên dài>
```

### Publish OAuth (cho mọi Gmail)

1. Sửa email trong `docs/privacy-policy.html`
2. Host qua GitHub Pages (folder `/docs`)
3. OAuth consent screen → thêm Privacy Policy URL → **Publish app**

Chi tiết: xem mục OAuth trong README cũ hoặc [DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Cấu hình GraphRAG (tùy chọn)

Trong `.env` (thư mục gốc repo):

```env
GRAPH_ENABLED=true
GRAPH_ALPHA=0.7
GRAPH_BUILD_ON_INDEX=true
GRAPH_ENTITY_BATCH_SIZE=8
INDEX_FILE_PAUSE=5.0
```

## Cổng mạng

| Dịch vụ | Cổng |
|---------|------|
| Frontend | 3000 |
| Backend | 8081 |
| ChromaDB | 8000 |
| Neo4j | 7687 / 7474 |

## API docs

- Swagger: http://127.0.0.1:8081/docs
- ReDoc: http://127.0.0.1:8081/redoc

## License

Đồ án học tập — DATN.
