"""
ocr_service.py — Dịch vụ OCR (Optical Character Recognition) dùng Tesseract.

Trích xuất văn bản từ file ảnh (JPEG, PNG, WebP) hoặc từ bytes,
phục vụ pipeline xử lý tài liệu scan / ảnh chụp màn hình.

Yêu cầu: Tesseract đã cài đặt trên hệ thống + package pytesseract, Pillow
"""

import io
import logging
import os
from pathlib import Path
from typing import Union

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cấu hình đường dẫn tới binary Tesseract (cần thiết trên Windows)
if os.name == "nt":  # Windows
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD


class OCRService:
    """
    Service thực hiện OCR với Tesseract.
    Hỗ trợ tiếng Việt + tiếng Anh, có tiền xử lý ảnh để tăng độ chính xác.
    """

    def __init__(self, language: str | None = None):
        """
        Khởi tạo OCR service.

        Args:
            language: Mã ngôn ngữ Tesseract, ví dụ "vie+eng".
                      Mặc định đọc từ settings.OCR_LANGUAGE.
        """
        self.language = language or settings.OCR_LANGUAGE
        self._verify_tesseract()

    def _verify_tesseract(self) -> None:
        """Kiểm tra Tesseract có thể chạy được không. Raise lỗi rõ ràng nếu thiếu."""
        try:
            version = pytesseract.get_tesseract_version()
            logger.info("Tesseract version: %s | language: %s", version, self.language)
        except pytesseract.TesseractNotFoundError:
            raise EnvironmentError(
                "Tesseract không tìm thấy!\n"
                f"Windows: kiểm tra đường dẫn TESSERACT_CMD = {settings.TESSERACT_CMD}\n"
                "Linux/Mac: chạy 'sudo apt install tesseract-ocr tesseract-ocr-vie'"
            )

    # ──────────────────────────────────────────────────────────
    # Tiền xử lý ảnh
    # ──────────────────────────────────────────────────────────

    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Tiền xử lý ảnh để tăng độ chính xác OCR:
          1. Chuyển sang grayscale (loại bỏ nhiễu màu).
          2. Tăng độ tương phản.
          3. Áp dụng bộ lọc làm sắc nét.

        Args:
            image: PIL Image object.

        Returns:
            PIL Image đã xử lý.
        """
        # Chuyển sang grayscale nếu chưa phải
        if image.mode != "L":
            image = image.convert("L")

        # Tăng độ tương phản (factor > 1 = tăng, 1 = giữ nguyên)
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)

        # Làm sắc nét chữ viết
        image = image.filter(ImageFilter.SHARPEN)

        return image

    # ──────────────────────────────────────────────────────────
    # OCR các định dạng đầu vào
    # ──────────────────────────────────────────────────────────

    def extract_text_from_image(
        self,
        image_path: Union[str, Path],
        preprocess: bool = True,
    ) -> str:
        """
        Trích xuất văn bản từ file ảnh trên disk.

        Args:
            image_path: Đường dẫn tới file ảnh (JPEG, PNG, WebP, BMP, TIFF...).
            preprocess: Có áp dụng tiền xử lý ảnh không (mặc định True).

        Returns:
            Văn bản trích xuất được, đã strip whitespace.
        """
        try:
            image = Image.open(image_path)
            if preprocess:
                image = self._preprocess_image(image)

            text = pytesseract.image_to_string(
                image,
                lang=self.language,
                config="--psm 3",  # PSM 3: Auto page segmentation
            )
            cleaned = text.strip()
            logger.info(
                "OCR file '%s': trích xuất được %d ký tự.",
                image_path, len(cleaned),
            )
            return cleaned
        except FileNotFoundError:
            logger.error("OCR: không tìm thấy file ảnh: %s", image_path)
            raise
        except Exception as e:
            logger.error("OCR extract_text_from_image lỗi: %s", e)
            raise

    def extract_text_from_bytes(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        preprocess: bool = True,
    ) -> str:
        """
        Trích xuất văn bản từ dữ liệu ảnh dạng bytes.
        Dùng khi nhận ảnh tải từ Drive hoặc upload từ frontend.

        Args:
            image_bytes: Nội dung file ảnh dưới dạng bytes.
            mime_type: MIME type gợi ý (hiện không bắt buộc, PIL tự nhận dạng).
            preprocess: Có áp dụng tiền xử lý ảnh không.

        Returns:
            Văn bản trích xuất được.
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))
            if preprocess:
                image = self._preprocess_image(image)

            text = pytesseract.image_to_string(
                image,
                lang=self.language,
                config="--psm 3",
            )
            cleaned = text.strip()
            logger.info(
                "OCR từ bytes (%d bytes): trích xuất được %d ký tự.",
                len(image_bytes), len(cleaned),
            )
            return cleaned
        except Exception as e:
            logger.error("OCR extract_text_from_bytes lỗi: %s", e)
            raise

    def extract_text_with_confidence(
        self,
        image_bytes: bytes,
        min_confidence: float = 60.0,
    ) -> dict[str, any]:
        """
        Trích xuất văn bản kèm điểm tin cậy (confidence score).
        Chỉ giữ lại các từ có confidence >= min_confidence.

        Args:
            image_bytes: Nội dung file ảnh dưới dạng bytes.
            min_confidence: Ngưỡng confidence tối thiểu (0-100).

        Returns:
            Dict gồm: text (văn bản lọc), avg_confidence (độ tin cậy trung bình).
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))
            image = self._preprocess_image(image)

            # Lấy dữ liệu OCR chi tiết bao gồm confidence
            data = pytesseract.image_to_data(
                image,
                lang=self.language,
                output_type=pytesseract.Output.DICT,
            )

            words = []
            confidences = []

            for i, word in enumerate(data["text"]):
                conf = int(data["conf"][i])
                if conf >= min_confidence and word.strip():
                    words.append(word)
                    confidences.append(conf)

            filtered_text = " ".join(words)
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

            logger.info(
                "OCR với confidence: %d từ hợp lệ, avg_confidence=%.1f%%",
                len(words), avg_conf,
            )
            return {
                "text": filtered_text,
                "avg_confidence": round(avg_conf, 2),
                "word_count": len(words),
            }
        except Exception as e:
            logger.error("OCR extract_text_with_confidence lỗi: %s", e)
            raise
