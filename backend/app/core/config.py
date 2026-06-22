"""
config.py — Tải và quản lý toàn bộ biến môi trường của ứng dụng.

Sử dụng pydantic-settings để validate tự động khi khởi động,
phát hiện lỗi thiếu config sớm thay vì crash lúc runtime.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent


def resolve_env_file() -> Path:
    """Một file .env duy nhất ở thư mục gốc repo (fallback backend/.env khi migrate)."""
    for candidate in (_PROJECT_ROOT / ".env", _BACKEND_DIR / ".env"):
        if candidate.is_file():
            return candidate
    return _PROJECT_ROOT / ".env"


ENV_FILE_PATH = resolve_env_file()


class Settings(BaseSettings):
    """Lớp chứa tất cả cấu hình, tự động đọc từ file .env ở thư mục gốc repo."""

    # ── Gemini AI ──────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    # google-genai: dùng gemini-embedding-001 (text-embedding-004 đã 404 trên API mới)
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"

    # ── Google OAuth2 / Drive ──────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_CREDENTIALS_FILE: str = "credentials.json"  # OAuth Web client JSON (fallback)
    GOOGLE_TOKEN_FILE: str = "token.pickle"             # Legacy single-user token (deprecated)
    GOOGLE_TOKENS_DIR: str = "tokens"                   # Thư mục token per-user
    GOOGLE_REDIRECT_URI: str = "http://localhost:3000/api/v1/auth/google/callback"
    FRONTEND_URL: str = "http://localhost:3000"
    SESSION_SECRET: str = "change-me-in-production-use-long-random-string"
    GOOGLE_DRIVE_SCOPES: list[str] = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
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

    # ── GraphRAG ───────────────────────────────────────────────
    GRAPH_ENABLED: bool = True          # Bật/tắt GraphRAG retrieval
    GRAPH_ALPHA: float = 0.7            # Trọng số vector trong hybrid (0.0–1.0)
    GRAPH_BUILD_ON_INDEX: bool = True   # Tự động build KG khi index tài liệu
    GRAPH_ENTITY_BATCH_SIZE: int = 8    # Số chunk gộp / 1 lần gọi Gemini extract entity
    GRAPH_ENTITY_BATCH_PAUSE: float = 3.0  # Giây nghỉ giữa các batch (tránh 429)

    # ── Entity normalization ───────────────────────────────────
    ENTITY_FUZZY_THRESHOLD: int = 85    # Ngưỡng thefuzz token_sort_ratio (0–100)
    ENTITY_ALIAS_MAP_PATH: str = "data/entity_aliases.json"

    # ── Community detection (Louvain + summary) ────────────────
    GRAPH_BUILD_COMMUNITIES: bool = True   # Chạy sau sync-all async
    COMMUNITY_MIN_SIZE: int = 3            # Ngưỡng merge / bỏ qua community nhỏ
    COMMUNITY_SUMMARY_PAUSE: float = 2.0   # Giây nghỉ giữa Gemini summary calls
    COMMUNITY_RELATED_WEIGHT: float = 2.0    # Trọng số cạnh RELATED_TO
    COMMUNITY_COOCCUR_WEIGHT: float = 1.0   # Trọng số cạnh COOCCURS_WITH

    # ── Hybrid retrieval context ───────────────────────────────
    RETRIEVAL_CONTEXT_MAX_CHARS: int = 8000  # Budget tổng context gửi Gemini

    # ── Indexing throttle (tránh 429 khi sync nhiều file) ─────
    INDEX_FILE_PAUSE: float = 5.0           # Giây nghỉ giữa mỗi file
    INDEX_QUOTA_COOLDOWN: float = 45.0      # Giây chờ khi gặp 429 rồi retry file
    INDEX_QUOTA_MAX_RETRIES: int = 2        # Số lần retry / file khi quota
    EMBED_BATCH_PAUSE: float = 2.5          # Giây nghỉ giữa batch embedding

    # ── FastAPI ────────────────────────────────────────────────
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8081
    APP_DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH),
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
    # Google Workspace → export qua EXPORT_MAP trong drive_service
    "application/vnd.google-apps.document": ".docx",
    "application/vnd.google-apps.spreadsheet": ".xlsx",
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
