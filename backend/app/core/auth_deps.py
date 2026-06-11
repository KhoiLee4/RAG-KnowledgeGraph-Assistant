"""
auth_deps.py — Session user và dependency injection cho FastAPI.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, Request

SESSION_USER_KEY = "user"


def safe_user_id(user_id: str) -> str:
    """Chuẩn hóa Google user ID để dùng làm tên file / collection."""
    return re.sub(r"[^\w\-]", "_", user_id)[:128]


def user_collection_name(user_id: str) -> str:
    """Tên ChromaDB collection riêng cho từng user."""
    return f"kb_{safe_user_id(user_id)}"


def get_session_user(request: Request) -> dict[str, Any] | None:
    """Lấy thông tin user từ session cookie (None nếu chưa đăng nhập)."""
    user = request.session.get(SESSION_USER_KEY)
    if not user or not user.get("user_id"):
        return None
    return user


def require_user(request: Request) -> dict[str, Any]:
    """Bắt buộc đã đăng nhập — raise 401 nếu chưa."""
    user = get_session_user(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Chưa đăng nhập. Hãy đăng nhập Google trước.",
        )
    return user
