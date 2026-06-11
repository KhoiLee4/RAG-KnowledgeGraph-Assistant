"""
oauth_config.py — Đọc cấu hình OAuth client (Web application) từ env hoặc credentials.json.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.core.config import settings
from app.services.drive_service import resolve_backend_path

logger = logging.getLogger(__name__)

OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_oauth_client_config() -> dict[str, Any]:
    """
    Trả về client config dạng {"web": {...}} cho google_auth_oauthlib.flow.Flow.

    Ưu tiên GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET từ .env,
    fallback đọc credentials.json (web hoặc installed).
    """
    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        return {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

    creds_path = resolve_backend_path(settings.GOOGLE_CREDENTIALS_FILE)
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"Thiếu OAuth client config.\n"
            f"Đặt GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET trong .env\n"
            f"hoặc tải credentials.json (Web application) vào {creds_path}"
        )

    with open(creds_path, encoding="utf-8") as f:
        data = json.load(f)

    if "web" in data:
        return data

    if "installed" in data:
        inst = data["installed"]
        logger.warning(
            "credentials.json là Desktop app — nên tạo OAuth Client loại "
            "'Web application' trên Google Cloud Console cho multi-user."
        )
        return {
            "web": {
                "client_id": inst["client_id"],
                "client_secret": inst["client_secret"],
                "auth_uri": inst.get(
                    "auth_uri", "https://accounts.google.com/o/oauth2/auth"
                ),
                "token_uri": inst.get(
                    "token_uri", "https://oauth2.googleapis.com/token"
                ),
            }
        }

    raise ValueError(
        "credentials.json không hợp lệ — cần key 'web' hoặc 'installed'."
    )


def is_oauth_configured() -> bool:
    """Kiểm tra đã có OAuth client config chưa (không raise)."""
    try:
        get_oauth_client_config()
        return bool(settings.GOOGLE_REDIRECT_URI)
    except (FileNotFoundError, ValueError):
        return False
