"""
main.py — FastAPI application entry point.

Khởi động:
  cd backend
  .\\start.ps1

Hoặc:
  ..\\venv\\Scripts\\uvicorn.exe main:app --host 127.0.0.1 --port 8081 --reload
"""

import logging
import sys
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from starlette.middleware.sessions import SessionMiddleware

from app.api.auth_routes import router as auth_router
from app.api.routes import router
from app.core.config import ENV_FILE_PATH, settings

# ── Cấu hình logging toàn ứng dụng ──────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.APP_DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# Tạo FastAPI app
# ══════════════════════════════════════════════════════════════

app = FastAPI(
    title="RAG Knowledge Graph Assistant",
    description=(
        "Hệ thống trợ lý ảo quản trị tri thức cá nhân tích hợp Google Drive.\n\n"
        "**Tech Stack:** FastAPI · Gemini 2.0 Flash · ChromaDB · Neo4j · GraphRAG"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ══════════════════════════════════════════════════════════════
# Middleware
# ══════════════════════════════════════════════════════════════

# Session cookie — lưu user_id sau OAuth (multi-user Drive)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET,
    session_cookie="rag_session",
    max_age=60 * 60 * 24 * 7,  # 7 ngày
    same_site="lax",
    https_only=False,
)

# CORS — cho phép React frontend và Swagger UI gọi API
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:
    """
    Middleware ghi log mỗi request/response với timing.
    Format: METHOD /path → STATUS (Xms) [request_id]
    """
    request_id = str(uuid.uuid4())[:8]
    start_time = time.perf_counter()

    logger.info(
        "[%s] → %s %s (from %s)",
        request_id,
        request.method,
        request.url.path,
        request.client.host if request.client else "unknown",
    )

    response = await call_next(request)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "[%s] ← %s %s | %d | %.1fms",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )

    # Thêm request ID vào response header để debug dễ hơn
    response.headers["X-Request-ID"] = request_id
    return response


# ══════════════════════════════════════════════════════════════
# Lifecycle events
# ══════════════════════════════════════════════════════════════

@app.on_event("startup")
async def on_startup():
    """
    Chạy khi server khởi động.
    Kiểm tra kết nối ChromaDB và Neo4j.
    """
    logger.info("=" * 60)
    logger.info("RAG Knowledge Graph Assistant — đang khởi động...")
    logger.info("  Env file      : %s", ENV_FILE_PATH)
    logger.info("  Gemini model  : %s", settings.GEMINI_MODEL)
    logger.info("  Embedding     : %s", settings.GEMINI_EMBEDDING_MODEL)
    logger.info("  ChromaDB      : %s:%d", settings.CHROMA_HOST, settings.CHROMA_PORT)
    logger.info("  Neo4j         : %s", settings.NEO4J_URI)
    logger.info("  Collection    : %s", settings.CHROMA_DEFAULT_COLLECTION)
    logger.info("  Debug mode    : %s", settings.APP_DEBUG)

    # Kiểm tra ChromaDB
    try:
        from app.db.chroma_client import get_chroma_client
        chroma = get_chroma_client()
        info = chroma.get_collection_info(settings.CHROMA_DEFAULT_COLLECTION)
        logger.info("  ChromaDB ✓ — %d documents đã index.", info.get("count", 0))
    except Exception as e:
        logger.warning("  ChromaDB ✗ — %s", e)

    # Kiểm tra Neo4j
    try:
        from app.db.neo4j_client import get_neo4j_client
        neo4j = get_neo4j_client()
        records = neo4j.run_cypher("RETURN 1 AS ping")
        logger.info("  Neo4j ✓ — kết nối OK.")
    except Exception as e:
        logger.warning("  Neo4j ✗ — %s", e)

    logger.info("Server sẵn sàng: http://%s:%d", settings.APP_HOST, settings.APP_PORT)
    logger.info("Swagger UI    : http://%s:%d/docs", settings.APP_HOST, settings.APP_PORT)
    logger.info("=" * 60)


@app.on_event("shutdown")
async def on_shutdown():
    """Chạy khi server tắt — đóng kết nối DB sạch sẽ."""
    logger.info("Server đang tắt, đóng kết nối...")
    try:
        from app.db import neo4j_client as _mod
        if _mod._instance:
            _mod._instance.close()
    except Exception:
        pass
    logger.info("Server đã tắt.")


# ══════════════════════════════════════════════════════════════
# Global exception handler
# ══════════════════════════════════════════════════════════════

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Bắt tất cả exception chưa được xử lý.
    Trả về JSON thay vì HTML 500 để frontend luôn parse được.
    """
    logger.error(
        "Unhandled exception | %s %s | %s: %s",
        request.method, request.url.path,
        type(exc).__name__, exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "detail": str(exc),
            "path": str(request.url.path),
        },
    )


# ══════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════

app.include_router(auth_router)
app.include_router(router)


@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint — trả về thông tin cơ bản."""
    return {
        "name": "RAG Knowledge Graph Assistant",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


# ══════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_DEBUG,
        log_level="debug" if settings.APP_DEBUG else "info",
    )
