"""
gemini_retry.py — Retry và thông báo lỗi thân thiện cho Gemini API (429 quota, rate limit).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

QUOTA_USER_MESSAGE = (
    "Đã vượt quota Gemini API (free tier). "
    "Vui lòng đợi 1–2 phút rồi thử lại, hoặc bật billing / dùng API key khác. "
    "Tab Tài liệu vẫn xem được danh sách file đã index."
)

QUOTA_DAILY_EXHAUSTED_MESSAGE = (
    "Quota Gemini free tier đã HẾT cho hôm nay (limit: 0). "
    "Chờ đến ngày mai (reset ~0h PST) hoặc bật billing tại https://aistudio.google.com/. "
    "Không nên bấm sync thêm — sẽ chỉ chờ vô ích."
)


def is_quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        k in msg
        for k in ("429", "resource_exhausted", "quota", "rate limit", "rate_limit")
    )


def is_daily_quota_exhausted(exc: BaseException) -> bool:
    """
    True khi Google báo hết quota NGÀY (limit: 0 hoặc PerDay).
    Retry phút/giây sẽ không giúp — phải đợi reset hoặc bật billing.
    """
    msg = str(exc).lower()
    if "perday" in msg or "per_day" in msg:
        if "limit: 0" in msg or "'quotavalue': '0'" in msg:
            return True
    # Một số response chỉ có limit: 0 lặp lại
    if msg.count("limit: 0") >= 2 and "free_tier" in msg:
        return True
    return False


def parse_retry_seconds(exc: BaseException, default: float = 8.0) -> float:
    """Đọc gợi ý retry từ response Google (vd. 'retry in 5.23s')."""
    m = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", str(exc), re.I)
    if m:
        return min(float(m.group(1)) + 1.0, 120.0)
    return default


def format_gemini_error(exc: BaseException) -> str:
    if is_daily_quota_exhausted(exc):
        return QUOTA_DAILY_EXHAUSTED_MESSAGE
    if is_quota_error(exc):
        return QUOTA_USER_MESSAGE
    text = str(exc).strip()
    if len(text) > 400:
        text = text[:400] + "..."
    return f"Lỗi Gemini API: {text}"


def call_with_gemini_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 5,
    label: str = "gemini",
) -> T:
    """Gọi fn(); retry khi quota/rate-limit/503."""
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            # Hết quota NGÀY → không retry (tránh chờ 59s x N lần vô ích)
            if is_daily_quota_exhausted(e):
                logger.error("%s: quota ngày đã hết — dừng retry.", label)
                raise
            retriable = any(
                k in msg
                for k in ("quota", "rate", "timeout", "503", "429", "resource_exhausted")
            )
            if attempt < max_attempts and retriable:
                wait = parse_retry_seconds(e, default=RETRY_DELAY * attempt)
                logger.warning(
                    "%s lỗi (attempt %d/%d) — chờ %.1fs: %s",
                    label,
                    attempt,
                    max_attempts,
                    wait,
                    e,
                )
                time.sleep(wait)
            else:
                raise
    assert last_exc is not None
    raise last_exc


RETRY_DELAY = 3.0
