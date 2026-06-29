"""
routes.py — Gộp tất cả API router dưới prefix /api/v1.

Các module con:
  health_routes   — GET  /health
  chat_routes     — POST /chat
  drive_routes    — Drive sync, /sync-drive
  document_routes — /documents, /supported-types
  graph_routes    — /graph/*
  auth_routes     — /auth/* (đăng ký riêng trong main.py)
"""

from fastapi import APIRouter

from app.api import (
    chat_routes,
    document_routes,
    drive_routes,
    evaluation_routes,
    graph_routes,
    health_routes,
)

router = APIRouter(prefix="/api/v1", tags=["RAG Knowledge Base"])

router.include_router(health_routes.router)
router.include_router(chat_routes.router)
router.include_router(drive_routes.router)
router.include_router(document_routes.router)
router.include_router(graph_routes.router)
router.include_router(evaluation_routes.router)
