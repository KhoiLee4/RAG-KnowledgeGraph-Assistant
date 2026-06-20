"""
drive_service.py — Kết nối và thao tác Google Drive API v3 (multi-user Web OAuth).

Luồng đăng nhập:
  1. Cấu hình OAuth Web client (GOOGLE_CLIENT_ID/SECRET hoặc credentials.json)
  2. GET /api/v1/auth/google → user đăng nhập trên trình duyệt
  3. Callback lưu token vào tokens/{user_id}.pickle
  4. POST /api/v1/drive/sync-all → quét + index Drive của user đó
"""

import io
import logging
import os
import pickle
import re
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from app.core.config import (
    settings,
    SUPPORTED_MIME_TYPES,
    SKIP_MIME_TYPES,
    MIN_FILE_SIZE_BYTES,
    MAX_FILE_SIZE_BYTES,
)

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

EXPORT_MAP: dict[str, tuple[str, str]] = {
    # "application/vnd.google-apps.document": (
    #     "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    #     ".docx",
    # ),
    # "application/vnd.google-apps.spreadsheet": (
    #     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    #     ".xlsx",
    # ),
    # "application/vnd.google-apps.presentation": (
    #     "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    #     ".pptx",
    # ),
}

SUPPORTED_TYPES: list[str] = list(SUPPORTED_MIME_TYPES.keys())

SUPPORTED_TYPE_LABELS: dict[str, str] = {
    "application/pdf": "PDF",
    # "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    # "application/msword": "DOC",
    # "application/vnd.google-apps.document": "Google Docs",
    # "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
    # "application/vnd.ms-excel": "XLS",
    # "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
    # "text/plain": "TXT",
    # "text/markdown": "Markdown",
    # "text/csv": "CSV",
    # "application/vnd.google-apps.spreadsheet": "Google Sheets",
    # "application/vnd.google-apps.presentation": "Google Slides",
}


def resolve_backend_path(relative_path: str) -> str:
    """Chuyển đường dẫn tương đối thành tuyệt đối trong thư mục backend/."""
    p = Path(relative_path)
    if p.is_absolute():
        return str(p)
    return str(_BACKEND_DIR / relative_path)


def _safe_user_id(user_id: str) -> str:
    return re.sub(r"[^\w\-]", "_", user_id)[:128]


def user_token_path(user_id: str) -> str:
    """Đường dẫn file token pickle cho một user."""
    tokens_dir = resolve_backend_path(settings.GOOGLE_TOKENS_DIR)
    os.makedirs(tokens_dir, exist_ok=True)
    return os.path.join(tokens_dir, f"{_safe_user_id(user_id)}.pickle")


class DriveService:
    """
    Service quản lý Google Drive API v3 cho một user cụ thể.
    Token lưu per-user trong backend/tokens/{user_id}.pickle.
    """

    def __init__(self, user_id: str, auto_authenticate: bool = True):
        if not user_id:
            raise ValueError("user_id là bắt buộc cho DriveService.")
        self.user_id = user_id
        self._service = None
        self._credentials: Credentials | None = None
        if auto_authenticate:
            self.load_credentials()

    # ── Token per-user ────────────────────────────────────────

    @staticmethod
    def save_user_credentials(user_id: str, creds: Credentials) -> None:
        """Lưu OAuth credentials cho user."""
        path = user_token_path(user_id)
        with open(path, "wb") as f:
            pickle.dump(creds, f)
        logger.info("Đã lưu token Drive cho user %s", user_id)

    @staticmethod
    def delete_user_credentials(user_id: str) -> None:
        """Xóa token của user (đăng xuất Drive)."""
        path = user_token_path(user_id)
        if os.path.exists(path):
            os.remove(path)

    @classmethod
    def get_auth_status(cls, user_id: str | None = None) -> dict[str, Any]:
        """
        Kiểm tra trạng thái đăng nhập Drive của user (không mở browser).

        Args:
            user_id: Google user ID. None = chưa đăng nhập app.
        """
        from app.services.oauth_config import is_oauth_configured

        status: dict[str, Any] = {
            "oauth_configured": is_oauth_configured(),
            "has_credentials": is_oauth_configured(),
            "has_token": False,
            "authenticated": False,
            "email": None,
            "display_name": None,
            "message": "",
        }

        if not user_id:
            status["message"] = "Chưa đăng nhập. Bấm 'Đăng nhập Google' để kết nối Drive."
            return status

        if not status["oauth_configured"]:
            status["message"] = (
                "OAuth chưa cấu hình — set GOOGLE_CLIENT_ID/SECRET và "
                "GOOGLE_REDIRECT_URI trong .env"
            )
            return status

        token_path = user_token_path(user_id)
        status["has_token"] = os.path.exists(token_path)
        status["token_path"] = token_path

        if not status["has_token"]:
            status["message"] = "Chưa cấp quyền Drive — đăng nhập lại Google."
            return status

        try:
            with open(token_path, "rb") as f:
                creds = pickle.load(f)

            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                cls.save_user_credentials(user_id, creds)

            if creds.valid:
                service = build("drive", "v3", credentials=creds)
                about = service.about().get(fields="user").execute()
                user = about.get("user", {})
                status["authenticated"] = True
                status["email"] = user.get("emailAddress")
                status["display_name"] = user.get("displayName")
                status["message"] = "Đã kết nối Google Drive."
            else:
                status["message"] = "Token hết hạn — đăng nhập lại Google."

        except Exception as e:
            logger.warning("get_auth_status user=%s lỗi: %s", user_id, e)
            status["message"] = f"Token không hợp lệ: {e}. Hãy đăng nhập lại."

        return status

    def load_credentials(self) -> dict[str, Any]:
        """
        Load và refresh token của user, khởi tạo Drive API client.

        Returns:
            Dict email, display_name, message.

        Raises:
            FileNotFoundError: User chưa có token (chưa OAuth).
            RuntimeError: Token hết hạn và không refresh được.
        """
        token_path = user_token_path(self.user_id)

        if not os.path.exists(token_path):
            raise FileNotFoundError(
                "Chưa đăng nhập Google Drive. "
                "Hãy bấm 'Đăng nhập Google' trên giao diện web."
            )

        with open(token_path, "rb") as f:
            creds = pickle.load(f)

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self.save_user_credentials(self.user_id, creds)
                logger.info("Đã refresh token Drive cho user %s", self.user_id)
            except Exception as e:
                logger.warning("Refresh token thất bại user=%s: %s", self.user_id, e)
                raise RuntimeError(
                    "Token Google Drive hết hạn. Hãy đăng nhập lại."
                ) from e

        if not creds.valid:
            raise RuntimeError("Token Google Drive không hợp lệ. Hãy đăng nhập lại.")

        self._credentials = creds
        self._service = build("drive", "v3", credentials=creds)

        about = self._service.about().get(fields="user").execute()
        user = about.get("user", {})
        email = user.get("emailAddress", "")

        logger.info("Drive sẵn sàng — user=%s email=%s", self.user_id, email)
        return {
            "authenticated": True,
            "email": email,
            "display_name": user.get("displayName"),
            "message": f"Đã kết nối Google Drive: {email}",
        }

    def authenticate(self) -> dict[str, Any]:
        """Alias tương thích code cũ — chỉ load token, không mở browser."""
        return self.load_credentials()

    def list_all_supported_files(
        self,
        folder_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Liệt kê tất cả file hợp lệ để index trên Drive của user."""
        if not self._service:
            self.load_credentials()
        return self.list_files(mime_types=SUPPORTED_TYPES, folder_id=folder_id)

    def list_files(
        self,
        mime_types: list[str] | None = None,
        folder_id: str | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Liệt kê file trong Google Drive, lọc theo MIME type và kích thước."""
        if not self._service:
            raise RuntimeError("Chưa xác thực Drive — gọi load_credentials() trước.")

        types = mime_types or SUPPORTED_TYPES
        mime_conditions = " or ".join([f"mimeType='{t}'" for t in types])
        q = f"({mime_conditions}) and trashed=false"

        if folder_id:
            q += f" and '{folder_id}' in parents"

        all_files: list[dict] = []
        page_token: str | None = None

        try:
            while True:
                req_params: dict[str, Any] = {
                    "q": q,
                    "pageSize": min(page_size, 1000),
                    "fields": (
                        "nextPageToken, "
                        "files(id, name, mimeType, modifiedTime, size, webViewLink, parents)"
                    ),
                }
                if page_token:
                    req_params["pageToken"] = page_token

                resp = self._service.files().list(**req_params).execute()
                all_files.extend(resp.get("files", []))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

            filtered: list[dict] = []
            for f in all_files:
                mime = f.get("mimeType", "")
                name = f.get("name", f.get("id", ""))

                if mime in SKIP_MIME_TYPES:
                    continue

                is_workspace = mime.startswith("application/vnd.google-apps.")
                if not is_workspace:
                    size_raw = f.get("size")
                    try:
                        size = int(size_raw) if size_raw is not None else 0
                    except (ValueError, TypeError):
                        size = 0

                    if size < MIN_FILE_SIZE_BYTES or size > MAX_FILE_SIZE_BYTES:
                        continue

                filtered.append(f)

            logger.info(
                "User %s: %d/%d file hợp lệ trên Drive.",
                self.user_id, len(filtered), len(all_files),
            )
            return filtered

        except HttpError as e:
            logger.error("list_files lỗi user=%s: %s", self.user_id, e)
            raise

    def download_file_content(
        self,
        file_id: str,
        mime_type: str,
    ) -> tuple[bytes, str]:
        """Tải nội dung file từ Google Drive về dạng bytes."""
        if not self._service:
            raise RuntimeError("Chưa xác thực Drive.")

        if mime_type not in SUPPORTED_MIME_TYPES and mime_type not in EXPORT_MAP:
            raise ValueError(
                f"MIME type '{mime_type}' không được hỗ trợ. "
                f"Chỉ hỗ trợ: {list(SUPPORTED_MIME_TYPES.keys())}"
            )

        try:
            buffer = io.BytesIO()

            if mime_type in EXPORT_MAP:
                export_mime, _ext = EXPORT_MAP[mime_type]
                request = self._service.files().export_media(
                    fileId=file_id, mimeType=export_mime
                )
                actual_mime = export_mime
            else:
                request = self._service.files().get_media(fileId=file_id)
                actual_mime = mime_type

            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            return buffer.getvalue(), actual_mime

        except HttpError as e:
            logger.error("download_file_content '%s' lỗi: %s", file_id, e)
            raise

    def get_file_metadata(self, file_id: str) -> dict[str, Any]:
        """Lấy metadata một file theo ID."""
        if not self._service:
            raise RuntimeError("Chưa xác thực Drive.")

        try:
            return (
                self._service.files()
                .get(
                    fileId=file_id,
                    fields="id, name, mimeType, modifiedTime, size, webViewLink, parents",
                )
                .execute()
            )
        except HttpError as e:
            logger.error("get_file_metadata '%s' lỗi: %s", file_id, e)
            raise
