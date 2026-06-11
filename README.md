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

### 4) Google OAuth (multi-user Drive)

1. [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → **Enable Google Drive API**
2. Credentials → **Create OAuth Client ID** → loại **Web application**
3. **Authorized redirect URIs:** `http://localhost:3000/api/v1/auth/google/callback`
4. Copy Client ID + Secret vào `backend/.env`:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:3000/api/v1/auth/google/callback
SESSION_SECRET=<chuỗi ngẫu nhiên dài>
```

Mỗi user đăng nhập Google trên web sẽ có Drive và knowledge base riêng.

### 5) Publish OAuth — cho phép mọi tài khoản Google đăng nhập

Mặc định app ở chế độ **Testing** → chỉ email trong **Test users** mới vào được.  
Để **bất kỳ Gmail nào** cũng đăng nhập:

#### Bước A — Chuẩn bị Privacy Policy (Google bắt buộc với scope Drive)

1. Sửa email trong `docs/privacy-policy.html` (mục Liên hệ)
2. Đẩy repo lên GitHub → bật **GitHub Pages** (Settings → Pages → branch `main`, folder `/docs`)
3. URL sẽ dạng: `https://<username>.github.io/<repo>/privacy-policy.html`  
   (hoặc host file HTML ở bất kỳ URL HTTPS công khai nào)

#### Bước B — Cấu hình OAuth consent screen

1. [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services** → **OAuth consent screen**
2. **User type:** External (nếu chưa chọn)
3. Điền đủ:
   - App name: `rag-knowledge-assistant`
   - User support email
   - Developer contact email
   - **Application home page:** URL GitHub repo hoặc `http://localhost:3000` (dev)
   - **Privacy Policy link:** URL từ bước A (bắt buộc)
4. **Scopes** → đảm bảo có `.../auth/drive.readonly` (+ email, profile, openid)
5. **Save**

#### Bước C — Publish

1. Trên trang **OAuth consent screen**, kéo lên **Publishing status**
2. Bấm **Publish app** → xác nhận **Move to production**
3. Trạng thái chuyển từ **Testing** → **In production**

Sau khi publish, mọi Gmail có thể đăng nhập (không cần thêm Test users).

> **Lưu ý:** App chưa qua **Google verification** thì user vẫn thấy cảnh báo *"Google chưa xác minh ứng dụng"* — bấm **Nâng cao** → **Tiếp tục đến rag-knowledge-assistant** là được.  
> Verification đầy đủ (bỏ cảnh báo) mất vài tuần, không bắt buộc cho đồ án local.

## Cấu trúc cổng

| Dịch vụ        | Cổng  |
|----------------|-------|
| Frontend Vite  | 3000  |
| Backend FastAPI| 8081  |
| ChromaDB       | 8000  |
| Neo4j          | 7687  |
