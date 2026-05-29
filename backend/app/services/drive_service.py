"""
drive_service.py — Kết nối và thao tác Google Drive API v3.

Luồng đăng nhập + đọc file:
  1. Đặt credentials.json (OAuth Desktop) trong thư mục backend/
  2. POST /api/v1/drive/login → mở trình duyệt, đăng nhập Google
  3. POST /api/v1/drive/sync-all → quét + index toàn bộ file được hỗ trợ

Yêu cầu: Google Cloud Console → bật Drive API → OAuth 2.0 Client (Desktop)
"""

import io
import logging
import os
import pickle
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
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

# Thư mục backend/ (cha của app/)
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

# Google Workspace MIME type → (export MIME type, extension)
# Các file Google Docs/Sheets/Slides không thể tải trực tiếp,
# phải dùng files().export() với MIME type tương ứng bên dưới.
EXPORT_MAP: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}

# Danh sách MIME type được hỗ trợ — lấy trực tiếp từ config để đảm bảo nhất quán
SUPPORTED_TYPES: list[str] = list(SUPPORTED_MIME_TYPES.keys())

# Nhãn hiển thị thân thiện cho từng MIME type
SUPPORTED_TYPE_LABELS: dict[str, str] = {
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "application/msword": "DOC",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
    "application/vnd.ms-excel": "XLS",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
    "text/plain": "TXT",
    "text/markdown": "Markdown",
    "text/csv": "CSV",
    "application/vnd.google-apps.document": "Google Docs",
    "application/vnd.google-apps.spreadsheet": "Google Sheets",
    "application/vnd.google-apps.presentation": "Google Slides",
}


def resolve_backend_path(relative_path: str) -> str:
    """
    Chuyển đường dẫn tương đối (credentials.json, token.pickle)
    thành đường dẫn tuyệt đối trong thư mục backend/.

    Args:
        relative_path: Tên file hoặc path tương đối.

    Returns:
        Đường dẫn tuyệt đối.
    """
    p = Path(relative_path)
    if p.is_absolute():
        return str(p)
    return str(_BACKEND_DIR / relative_path)


class DriveService:
    """
    Service quản lý OAuth2 và Google Drive API v3.
    Token lưu dạng pickle để tái sử dụng.
    """

    def __init__(self, auto_authenticate: bool = True):
        """
        Khởi tạo DriveService.

        Args:
            auto_authenticate: True = tự động xác thực ngay (mở browser nếu cần).
        """
        self._service = None
        self._credentials: Credentials | None = None
        if auto_authenticate:
            self.authenticate()

    # ── Xác thực OAuth2 ───────────────────────────────────────

    @classmethod
    def get_auth_status(cls) -> dict[str, Any]:
        """
        Kiểm tra trạng thái đăng nhập Google Drive (không mở browser).

        Returns:
            Dict gồm:
              - has_credentials: có file credentials.json không
              - has_token: có file token.pickle không
              - authenticated: token còn hợp lệ không
              - email: email tài khoản Google (nếu đã đăng nhập)
              - message: hướng dẫn bước tiếp theo
        """
        creds_path = resolve_backend_path(settings.GOOGLE_CREDENTIALS_FILE)
        token_path = resolve_backend_path(settings.GOOGLE_TOKEN_FILE)

        status: dict[str, Any] = {
            "has_credentials": os.path.exists(creds_path),
            "has_token": os.path.exists(token_path),
            "authenticated": False,
            "email": None,
            "credentials_path": creds_path,
            "token_path": token_path,
            "supported_types": [SUPPORTED_TYPE_LABELS.get(t, t) for t in SUPPORTED_TYPES],
            "message": "",
        }

        if not status["has_credentials"]:
            status["message"] = (
                "Thiếu credentials.json — tải từ Google Cloud Console "
                "(OAuth 2.0 Client ID → Desktop app) và đặt vào thư mục backend/"
            )
            return status

        if not status["has_token"]:
            status["message"] = (
                "Chưa đăng nhập Google. Gọi POST /api/v1/drive/login "
                "(trình duyệt sẽ mở trên máy chạy backend)."
            )
            return status

        try:
            with open(token_path, "rb") as f:
                creds = pickle.load(f)

            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                cls._save_token(creds)

            if creds.valid:
                service = build("drive", "v3", credentials=creds)
                about = service.about().get(fields="user,storageQuota").execute()
                user = about.get("user", {})
                status["authenticated"] = True
                status["email"] = user.get("emailAddress")
                status["display_name"] = user.get("displayName")
                status["message"] = "Đã đăng nhập Google Drive."
            else:
                status["message"] = "Token hết hạn — gọi POST /api/v1/drive/login để đăng nhập lại."

        except Exception as e:
            logger.warning("get_auth_status lỗi: %s", e)
            status["message"] = f"Token không hợp lệ: {e}. Hãy đăng nhập lại."

        return status

    @staticmethod
    def _save_token(creds: Credentials) -> None:
        """Lưu credentials vào token.pickle."""
        token_path = resolve_backend_path(settings.GOOGLE_TOKEN_FILE)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    def authenticate(self) -> dict[str, Any]:
        """
        Đăng nhập Google Drive qua OAuth2 (Desktop flow).

        Thứ tự:
          1. Đọc token.pickle nếu có
          2. Refresh nếu hết hạn
          3. Mở browser (run_local_server) nếu chưa có token hợp lệ
          4. Lưu token.pickle

        Returns:
            Dict: email, display_name, message.

        Raises:
            FileNotFoundError: Thiếu credentials.json
        """
        creds: Credentials | None = None
        token_path = resolve_backend_path(settings.GOOGLE_TOKEN_FILE)
        creds_path = resolve_backend_path(settings.GOOGLE_CREDENTIALS_FILE)

        # Bước 1: Load token đã lưu
        if os.path.exists(token_path):
            with open(token_path, "rb") as f:
                creds = pickle.load(f)
            logger.info("Đã load token từ %s", token_path)

        # Bước 2: Làm mới token nếu hết hạn
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("Đã làm mới Google token.")
            except Exception as e:
                logger.warning("Làm mới token thất bại: %s — chạy lại OAuth.", e)
                creds = None

        # Bước 3: OAuth flow — mở trình duyệt đăng nhập Google
        if not creds or not creds.valid:
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    f"Không tìm thấy {creds_path}.\n"
                    "Tải credentials.json từ Google Cloud Console → "
                    "APIs & Services → Credentials → OAuth 2.0 Client ID (Desktop)."
                )
            logger.info(
                "Đang mở trình duyệt để đăng nhập Google Drive... "
                "(chọn tài khoản và cho phép quyền đọc Drive)"
            )
            flow = InstalledAppFlow.from_client_secrets_file(
                creds_path, settings.GOOGLE_DRIVE_SCOPES
            )
            creds = flow.run_local_server(port=0, prompt="consent")
            logger.info("OAuth2 đăng nhập thành công.")

        # Bước 4: Lưu token
        self._save_token(creds)

        self._credentials = creds
        self._service = build("drive", "v3", credentials=creds)

        # Lấy thông tin user
        about = self._service.about().get(fields="user").execute()
        user = about.get("user", {})
        email = user.get("emailAddress", "")

        logger.info("Google Drive sẵn sàng — tài khoản: %s", email)
        return {
            "authenticated": True,
            "email": email,
            "display_name": user.get("displayName"),
            "message": f"Đã đăng nhập Google Drive: {email}",
        }

    def list_all_supported_files(
        self,
        folder_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Liệt kê tất cả file hợp lệ để index trên Drive.

        Áp dụng đầy đủ filter: MIME type whitelist, SKIP_MIME_TYPES,
        MIN_FILE_SIZE_BYTES và MAX_FILE_SIZE_BYTES.

        Args:
            folder_id: Giới hạn trong một folder (None = toàn bộ Drive).

        Returns:
            Danh sách file metadata đã qua filter.
        """
        if not self._service:
            self.authenticate()
        return self.list_files(mime_types=SUPPORTED_TYPES, folder_id=folder_id)

    # ── Liệt kê file ─────────────────────────────────────────

    def list_files(
        self,
        mime_types: list[str] | None = None,
        folder_id: str | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Liệt kê file trong Google Drive, lọc theo MIME type và kích thước.

        Các file bị bỏ qua tự động:
          - MIME type nằm trong SKIP_MIME_TYPES (ảnh, video, binary...)
          - Kích thước < MIN_FILE_SIZE_BYTES (file rỗng / stub)
          - Kích thước > MAX_FILE_SIZE_BYTES (file quá lớn)
          - Google Workspace files (Docs/Sheets/Slides) không áp dụng
            kiểm tra kích thước vì chúng không có size trong Drive API.

        Args:
            mime_types: Danh sách MIME type (mặc định SUPPORTED_TYPES).
            folder_id: ID folder (None = quét toàn Drive).
            page_size: Số file mỗi trang API (max 1000).

        Returns:
            Danh sách dict: id, name, mimeType, modifiedTime, size, webViewLink.
        """
        if not self._service:
            raise RuntimeError("Chưa xác thực Drive — gọi authenticate() trước.")

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

            logger.info(
                "Drive API trả về %d file trước khi filter kích thước.",
                len(all_files),
            )

            # ── Áp dụng filter kích thước và MIME type ──────────────
            filtered: list[dict] = []
            for f in all_files:
                mime = f.get("mimeType", "")
                name = f.get("name", f.get("id", ""))

                # Bỏ qua các MIME type bị cấm (ảnh, video, audio, binary)
                if mime in SKIP_MIME_TYPES:
                    logger.info(
                        "BỎ QUA '%s' — MIME type bị cấm: %s", name, mime
                    )
                    continue

                # Google Workspace files (Docs/Sheets/Slides) không có trường
                # 'size' trong Drive API — bỏ qua kiểm tra kích thước.
                is_workspace = mime.startswith("application/vnd.google-apps.")
                if not is_workspace:
                    size_raw = f.get("size")
                    try:
                        size = int(size_raw) if size_raw is not None else 0
                    except (ValueError, TypeError):
                        size = 0

                    if size < MIN_FILE_SIZE_BYTES:
                        logger.info(
                            "BỎ QUA '%s' — file quá nhỏ: %d bytes (ngưỡng tối thiểu: %d bytes)",
                            name, size, MIN_FILE_SIZE_BYTES,
                        )
                        continue

                    if size > MAX_FILE_SIZE_BYTES:
                        logger.info(
                            "BỎ QUA '%s' — file quá lớn: %d bytes (ngưỡng tối đa: %d MB)",
                            name, size, MAX_FILE_SIZE_BYTES // 1_000_000,
                        )
                        continue

                logger.debug("SẼ INDEX: '%s' (%s)", name, mime)
                filtered.append(f)

            logger.info(
                "Sau filter: %d/%d file hợp lệ để index.",
                len(filtered), len(all_files),
            )
            return filtered

        except HttpError as e:
            logger.error("list_files lỗi: %s", e)
            raise

    # ── Tải nội dung file ─────────────────────────────────────

    def download_file_content(
        self,
        file_id: str,
        mime_type: str,
    ) -> tuple[bytes, str]:
        """
        Tải nội dung file từ Google Drive về dạng bytes.

        Quan trọng:
          - Google Workspace files (Docs/Sheets/Slides) PHẢI dùng files().export()
            thay vì files().get_media() vì chúng không có binary content trực tiếp.
          - Các file thông thường (PDF, DOCX, TXT...) dùng files().get_media().

        Args:
            file_id: ID file trên Drive.
            mime_type: MIME type gốc của file.

        Returns:
            Tuple (content_bytes, actual_mime_type).

        Raises:
            ValueError: MIME type không được hỗ trợ.
            HttpError: Lỗi từ Google Drive API.
        """
        if not self._service:
            raise RuntimeError("Chưa xác thực Drive.")

        # Kiểm tra MIME type có được hỗ trợ không trước khi tải
        if mime_type not in SUPPORTED_MIME_TYPES and mime_type not in EXPORT_MAP:
            raise ValueError(
                f"MIME type '{mime_type}' không được hỗ trợ. "
                f"Chỉ hỗ trợ: {list(SUPPORTED_MIME_TYPES.keys())}"
            )

        try:
            buffer = io.BytesIO()

            if mime_type in EXPORT_MAP:
                # Google Workspace files: bắt buộc dùng export API
                export_mime, ext = EXPORT_MAP[mime_type]
                logger.info(
                    "Tải Google Workspace file '%s' qua export API → %s",
                    file_id, ext,
                )
                request = self._service.files().export_media(
                    fileId=file_id, mimeType=export_mime
                )
                actual_mime = export_mime
            else:
                # File thông thường: tải trực tiếp qua get_media
                logger.info(
                    "Tải file '%s' trực tiếp (MIME: %s)",
                    file_id, mime_type,
                )
                request = self._service.files().get_media(fileId=file_id)
                actual_mime = mime_type

            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            content = buffer.getvalue()
            logger.info(
                "Đã tải xong file '%s': %d bytes (MIME thực tế: %s).",
                file_id, len(content), actual_mime,
            )
            return content, actual_mime

        except HttpError as e:
            logger.error("download_file_content '%s' lỗi HTTP: %s", file_id, e)
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


# ── Test độc lập ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Test DriveService ===\n")

    status = DriveService.get_auth_status()
    print("Trạng thái:", status)

    if not status["has_credentials"]:
        print("\n→ Đặt credentials.json vào:", status["credentials_path"])
        exit(1)

    print("\nĐang đăng nhập (mở browser nếu cần)...")
    svc = DriveService()
    auth = svc.authenticate()
    print("Đăng nhập:", auth)

    files = svc.list_all_supported_files()
    print(f"\nTìm thấy {len(files)} file được hỗ trợ:")
    for f in files[:10]:
        label = SUPPORTED_TYPE_LABELS.get(f.get("mimeType", ""), "?")
        print(f"  [{label}] {f['name']}")
