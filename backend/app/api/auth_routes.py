"""
auth_routes.py — Google OAuth2 Web flow + session cho multi-user Drive.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.core.auth_deps import SESSION_USER_KEY, safe_user_id
from app.core.config import settings
from app.services.drive_service import DriveService
from app.services.oauth_config import OAUTH_SCOPES, get_oauth_client_config, is_oauth_configured

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

# Dev localhost dùng http — oauthlib mặc định bắt buộc https
import os
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
if "localhost" in settings.GOOGLE_REDIRECT_URI or "127.0.0.1" in settings.GOOGLE_REDIRECT_URI:
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


def _create_flow(state: str | None = None) -> Flow:
    client_config = get_oauth_client_config()
    return Flow.from_client_config(
        client_config,
        scopes=OAUTH_SCOPES,
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
        state=state,
    )


def _frontend_redirect(path: str = "", query: dict[str, str] | None = None) -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    url = f"{base}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    return url


@router.get("/config", summary="Cấu hình OAuth (public)")
async def auth_config() -> dict[str, Any]:
    """Frontend kiểm tra OAuth đã sẵn sàng chưa."""
    configured = is_oauth_configured()
    return {
        "oauth_configured": configured,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI if configured else None,
        "login_url": "/api/v1/auth/google" if configured else None,
    }


@router.get("/me", summary="Thông tin user đang đăng nhập")
async def auth_me(request: Request) -> dict[str, Any]:
    user = request.session.get(SESSION_USER_KEY)
    if not user:
        return {"logged_in": False}

    user_id = user["user_id"]
    drive_status = DriveService.get_auth_status(user_id)

    return {
        "logged_in": True,
        "user_id": user_id,
        "email": user.get("email"),
        "display_name": user.get("display_name"),
        "drive_authenticated": drive_status.get("authenticated", False),
        "collection_name": user.get("collection_name"),
    }


@router.get("/google", summary="Bắt đầu đăng nhập Google (redirect)")
async def auth_google_start(request: Request) -> RedirectResponse:
    """
    Redirect user tới Google OAuth consent screen.
    Sau khi cấp quyền, Google gọi lại /auth/google/callback.
    """
    if not is_oauth_configured():
        raise HTTPException(
            status_code=400,
            detail=(
                "OAuth chưa cấu hình. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
                "GOOGLE_REDIRECT_URI trong .env hoặc đặt credentials.json (Web app)."
            ),
        )

    flow = _create_flow()
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account consent",
    )
    request.session["oauth_state"] = state
    # PKCE: code_verifier phải giữ từ lúc bắt đầu đến callback
    if flow.code_verifier:
        request.session["oauth_code_verifier"] = flow.code_verifier
    return RedirectResponse(url=authorization_url)


@router.get("/google/callback", summary="OAuth callback từ Google")
async def auth_google_callback(request: Request) -> RedirectResponse:
    """Nhận authorization code, lưu token theo user, tạo session."""
    error = request.query_params.get("error")
    if error:
        logger.warning("OAuth callback lỗi: %s", error)
        return RedirectResponse(
            url=_frontend_redirect("/docs", {"login": "error", "reason": error})
        )

    state = request.query_params.get("state")
    saved_state = request.session.pop("oauth_state", None)
    if not state or state != saved_state:
        return RedirectResponse(
            url=_frontend_redirect("/docs", {"login": "error", "reason": "invalid_state"})
        )

    try:
        flow = _create_flow(state=state)
        code_verifier = request.session.pop("oauth_code_verifier", None)
        if code_verifier:
            flow.code_verifier = code_verifier
        # Dùng GOOGLE_REDIRECT_URI thay vì request.url (Vite proxy đổi port)
        query = request.url.query
        auth_response = (
            f"{settings.GOOGLE_REDIRECT_URI}?{query}"
            if query
            else settings.GOOGLE_REDIRECT_URI
        )
        flow.fetch_token(authorization_response=auth_response)
        creds = flow.credentials

        oauth2 = build("oauth2", "v2", credentials=creds)
        profile = oauth2.userinfo().get().execute()

        user_id = profile.get("id") or profile.get("email", "")
        if not user_id:
            raise ValueError("Không lấy được Google user ID.")

        email = profile.get("email", "")
        display_name = profile.get("name", email)

        DriveService.save_user_credentials(user_id, creds)

        request.session[SESSION_USER_KEY] = {
            "user_id": user_id,
            "email": email,
            "display_name": display_name,
            "collection_name": f"kb_{safe_user_id(user_id)}",
        }

        logger.info("User đăng nhập: %s (%s)", email, user_id)
        return RedirectResponse(
            url=_frontend_redirect("/docs", {"login": "success"})
        )

    except Exception as e:
        logger.error("OAuth callback thất bại: %s", e, exc_info=True)
        return RedirectResponse(
            url=_frontend_redirect("/docs", {"login": "error", "reason": "token_exchange"})
        )


@router.post("/logout", summary="Đăng xuất (xóa session)")
async def auth_logout(request: Request) -> dict[str, str]:
    request.session.clear()
    return {"status": "ok", "message": "Đã đăng xuất."}
