"""Tests for citation_formatter."""

from app.services.citation_formatter import build_location_link, format_citation, format_citations


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
            "drive_link": "https://drive.google.com/file/d/fid1/view",
            "source": "vector",
            "text": "Nội dung mẫu về hợp đồng lao động.",
        },
        1,
    )
    assert cite["label"] == "HopDong.pdf"
    assert cite["location"] == "Trang 3"
    assert cite["index"] == "1"
    assert "#page=3" in cite["location_link"]
    assert "chunk" not in cite.get("chunk_index", "")


def test_format_citations_dedupes():
    raw = [
        {"file_name": "A.pdf", "page_estimate": "1", "source": "vector", "drive_link": ""},
        {"file_name": "A.pdf", "page_estimate": "1", "source": "vector", "drive_link": ""},
        {"file_name": "B.pdf", "page_estimate": "2", "source": "vector", "drive_link": ""},
    ]
    result = format_citations(raw)
    assert len(result) == 2
