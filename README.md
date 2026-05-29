# RAG KnowledgeGraph Assistant

Trợ lý ảo quản trị tri thức cá nhân tích hợp Google Drive,  
sử dụng kỹ thuật GraphRAG + ChromaDB + Neo4j + Gemini API.

## Tech Stack

- **Backend:** Python, FastAPI
- **AI:** Google Gemini API, Tesseract OCR
- **Database:** ChromaDB (Vector), Neo4j (Graph)
- **Frontend:** ReactJS + Vite
- **Infra:** Docker, Google Drive API

## Chạy local (Windows)

### 1) Docker — ChromaDB + Neo4j

```powershell
docker compose up -d
```

### 2) Backend (terminal 1) — **bắt buộc trước frontend**

```powershell
# Cách nhanh nhất (dùng venv, cổng 8081):
cd backend
.\start.ps1
```

Hoặc thủ công:

```powershell
cd backend
copy .env.example .env          # nếu chưa có — điền GEMINI_API_KEY
# credentials.json (OAuth Desktop app) đặt trong backend/
..\venv\Scripts\uvicorn.exe main:app --host 127.0.0.1 --port 8081 --reload
```

> **Lưu ý:** Không chạy `uvicorn` trực tiếp nếu chưa `activate` venv — sẽ lỗi `No module named 'pydantic_settings'`.  
> Cổng **8080** trên Windows hay bị `WinError 10013` → dùng **8081**.

Kiểm tra: http://127.0.0.1:8081/api/v1/health

### 3) Frontend (terminal 2)

```powershell
cd frontend
npm install
npm run dev
```

Mở http://localhost:3000 — Vite proxy `/api` → `localhost:8081`.

## Cấu trúc cổng

| Dịch vụ        | Cổng  |
|----------------|-------|
| Frontend Vite  | 3000  |
| Backend FastAPI| 8081  |
| ChromaDB       | 8000  |
| Neo4j          | 7687  |
