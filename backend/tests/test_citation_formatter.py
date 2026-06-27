"""Tests for citation_formatter."""

from app.services.citation_formatter import (
    build_location_link,
    format_citation,
    format_citations,
    format_location_label,
)


def test_build_location_link_pdf_page():
    link = build_location_link(
        "https://drive.google.com/file/d/abc123/view",
        file_id="abc123",
        page=5,
        file_name="report.pdf",
    )
    assert "abc123" in link
    assert "#page=5" in link
    assert "/preview" in link


def test_format_citation_document():
    cite = format_citation(
        {
            "file_name": "HopDong.pdf",
            "file_id": "fid1",
            "page_estimate": "3",
            "line_start": "12",
            "line_end": "15",
            "drive_link": "https://drive.google.com/file/d/fid1/view",
            "source": "vector",
            "text": "Nội dung mẫu về hợp đồng lao động.",
        },
        1,
    )
    assert cite["label"] == "HopDong.pdf"
    assert cite["location"] == "Trang 3, dòng 12–15"
    assert cite["index"] == "1"
    assert "#page=3" in cite["location_link"]
    assert "chunk" not in cite.get("chunk_index", "")


def test_format_location_label_page_only():
    assert format_location_label(page=2) == "Trang 2"


def test_format_location_label_lines_only():
    assert format_location_label(line_start=5, line_end=8) == "dòng 5–8"


def test_format_citations_dedupes():
    raw = [
        {"file_name": "A.pdf", "page_estimate": "1", "source": "vector", "drive_link": ""},
        {"file_name": "A.pdf", "page_estimate": "1", "source": "vector", "drive_link": ""},
        {"file_name": "B.pdf", "page_estimate": "2", "source": "vector", "drive_link": ""},
    ]
    result = format_citations(raw)
    assert len(result) == 2
