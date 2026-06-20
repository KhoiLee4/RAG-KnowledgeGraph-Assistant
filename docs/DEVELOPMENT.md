# Hướng dẫn phát triển

## Yêu cầu

- Python 3.11+
- Node.js 18+
- Docker Desktop (Neo4j + ChromaDB)
- Tesseract OCR (tùy chọn, cho PDF/ảnh — hiện chỉ index Word)

## Thiết lập lần đầu

```powershell
# 1. Clone và tạo venv
python -m venv venv
.\venv\Scripts\pip install -r backend\requirements.txt

# 2. Cấu hình môi trường (một file .env ở thư mục gốc repo)
copy .env.example .env
# Điền GEMINI_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SESSION_SECRET

# 3. Database
docker compose up -d

# 4. Frontend
cd frontend
npm install
```

## Chạy hàng ngày

Mở **3 terminal** (hoặc dùng `.\start.ps1` ở root cho hướng dẫn):

```powershell
# Terminal 1 — DB (nếu chưa chạy)
docker compose up -d

# Terminal 2 — Backend
cd backend
.\start.ps1

# Terminal 3 — Frontend
cd frontend
npm run dev
```

- Frontend: http://localhost:3000
- Backend: http://127.0.0.1:8081
- Swagger: http://127.0.0.1:8081/docs
- Neo4j Browser: http://localhost:7474

## Cấu trúc cổng

| Dịch vụ | Cổng |
|---------|------|
| Frontend (Vite) | 3000 |
| Backend (FastAPI) | 8081 |
| ChromaDB | 8000 |
| Neo4j Bolt | 7687 |
| Neo4j Browser | 7474 |

## Thêm/sửa API endpoint

1. Tạo hoặc sửa file trong `backend/app/api/` (ví dụ `graph_routes.py`)
2. Đăng ký router trong `backend/app/api/routes.py`
3. Thêm hàm gọi API trong `frontend/src/api/client.js`
4. Cập nhật component tương ứng

## Chạy test

```powershell
cd backend
..\venv\Scripts\python.exe -m pytest tests/ -v
```

## Lưu ý Gemini quota

- GraphRAG tốn nhiều API call (embed + entity extraction mỗi chunk)
- Free tier dễ gặp `429 RESOURCE_EXHAUSTED`
- Giải pháp: bật billing, sync ít file, tăng `INDEX_FILE_PAUSE` / `GRAPH_ENTITY_BATCH_PAUSE`
- Model khuyến nghị: `gemini-2.0-flash` (quota cao hơn 2.5-flash free tier)

## File không commit

- `.env` (thư mục gốc repo) — API keys và cấu hình backend
- `backend/tokens/*.pickle` — OAuth tokens
- `credentials.json`
- `frontend/node_modules/`, `frontend/dist/`

## Tài liệu liên quan

- [README.md](../README.md) — hướng dẫn cài đặt và OAuth
- [ARCHITECTURE.md](./ARCHITECTURE.md) — kiến trúc chi tiết
- [privacy-policy.html](./privacy-policy.html) — Privacy Policy cho Google OAuth
