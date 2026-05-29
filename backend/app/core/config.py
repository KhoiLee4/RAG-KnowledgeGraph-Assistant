"""
config.py — Tải và quản lý toàn bộ biến môi trường của ứng dụng.

Sử dụng pydantic-settings để validate tự động khi khởi động,
phát hiện lỗi thiếu config sớm thay vì crash lúc runtime.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Lớp chứa tất cả cấu hình, tự động đọc từ file .env."""

    # ── Gemini AI ──────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    # google-genai: dùng gemini-embedding-001 (text-embedding-004 đã 404 trên API mới)
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"

    # ── Google OAuth2 / Drive ──────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_CREDENTIALS_FILE: str = "credentials.json"  # Tải từ Google Cloud Console
    GOOGLE_TOKEN_FILE: str = "token.pickle"             # Token lưu sau OAuth flow
    GOOGLE_DRIVE_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    # ── Neo4j Graph DB ─────────────────────────────────────────
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "yourpassword"

    # ── ChromaDB Vector DB ─────────────────────────────────────
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8000
    CHROMA_DEFAULT_COLLECTION: str = "knowledge_base"

    # ── Tesseract OCR (Windows cần set đường dẫn tuyệt đối) ───
    TESSERACT_CMD: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    OCR_LANG: str = "vie+eng"

    # ── Chunking ───────────────────────────────────────────────
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50

    # ── Retrieval (hybrid vector + keyword) ───────────────────
    RETRIEVAL_TOP_K: int = 5
    RETRIEVAL_MIN_SCORE: float = 0.12
    RETRIEVAL_VECTOR_WEIGHT: float = 0.80
    RETRIEVAL_KEYWORD_WEIGHT: float = 0.20
    RETRIEVAL_CANDIDATE_MULTIPLIER: int = 3

    # ── FastAPI ────────────────────────────────────────────────
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8081
    APP_DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Trả về singleton Settings (cache bằng lru_cache).
    Dùng trong FastAPI Depends: Depends(get_settings).
    """
    return Settings()


# Singleton dùng trực tiếp ở các module khác
settings = get_settings()


# ══════════════════════════════════════════════════════════════
# Whitelist / Blacklist MIME types cho hệ thống filter file
# Đặt ngoài Settings vì đây là hằng số tĩnh, không đọc từ .env
# ══════════════════════════════════════════════════════════════

# Map MIME type → extension tương ứng.
# Chỉ những file có MIME type trong dict này mới được index.
SUPPORTED_MIME_TYPES: dict[str, str] = {
    # PDF
    "application/pdf": ".pdf",
    # Word
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    # Excel
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    # PowerPoint (tùy chọn — comment lại nếu không cần)
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    # Text thuần
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    # Google Workspace — phải export qua API, không download trực tiếp
    "application/vnd.google-apps.document": ".docx",       # Google Docs  → DOCX
    "application/vnd.google-apps.spreadsheet": ".xlsx",    # Google Sheets → XLSX
    "application/vnd.google-apps.presentation": ".pptx",  # Google Slides → PPTX
}

# Danh sách MIME type bị bỏ qua hoàn toàn — ảnh, video, audio, binary.
# Các loại này thường gây OCR rác, embeddings nhiễu và tốn token không cần thiết.
SKIP_MIME_TYPES: set[str] = {
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "video/mp4", "video/avi",
    "audio/mpeg", "audio/wav",
    "application/zip", "application/x-rar-compressed",
    "application/octet-stream",      # file nhị phân không xác định
    "application/x-msdownload",      # .exe, .dll
}

# Giới hạn kích thước file được phép index
MIN_FILE_SIZE_BYTES: int = 100           # Bỏ qua file rỗng / stub (< 100 bytes)
MAX_FILE_SIZE_BYTES: int = 50_000_000    # Bỏ qua file > 50 MB — tránh OOM và timeout


# ── Test độc lập ──────────────────────────────────────────────
if __name__ == "__main__":
    s = get_settings()
    print("=== Cấu hình hiện tại ===")
    print(f"  Gemini model   : {s.GEMINI_MODEL}")
    print(f"  Embedding model: {s.GEMINI_EMBEDDING_MODEL}")
    print(f"  Neo4j URI      : {s.NEO4J_URI}")
    print(f"  ChromaDB       : {s.CHROMA_HOST}:{s.CHROMA_PORT}")
    print(f"  Collection     : {s.CHROMA_DEFAULT_COLLECTION}")
    print(f"  API Key set    : {'Yes' if s.GEMINI_API_KEY else 'NO — cần set GEMINI_API_KEY'}")
