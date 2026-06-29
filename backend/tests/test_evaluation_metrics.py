"""Unit tests cho evaluation metrics (không cần DB/API)."""

from app.evaluation.metrics import (
    chunk_key,
    compute_retrieval_metrics,
    detect_refusal,
    keyword_overlap_score,
)


def test_chunk_key_format():
    assert chunk_key("abc123", 2) == "abc123__chunk_2"


def test_hit_recall_precision_mrr():
    retrieved = [
        "wrong__chunk_0",
        "good__chunk_1",
        "good__chunk_2",
        "other__chunk_0",
    ]
    expected = [{"file_id": "good", "chunk_index": 1}, {"file_id": "good", "chunk_index": 2}]
    m = compute_retrieval_metrics(retrieved, expected, k=3)
    assert m["hit_at_k"] == 1
    assert m["recall_at_k"] == 1.0
    assert m["precision_at_k"] == round(2 / 3, 4)
    assert m["mrr"] == 0.5


def test_retrieval_skipped_without_expected():
    m = compute_retrieval_metrics(["a__chunk_0"], [], k=5)
    assert m["skipped"] is True
    assert m["hit_at_k"] is None


def test_detect_refusal_vietnamese():
    assert detect_refusal("Tôi không tìm thấy thông tin này trong tài liệu của bạn.")
    assert not detect_refusal("GraphRAG kết hợp vector search và knowledge graph.")


def test_keyword_overlap():
    score = keyword_overlap_score(
        "Hệ thống dùng ChromaDB và Neo4j cho GraphRAG.",
        ["ChromaDB", "Neo4j", "không có"],
    )
    assert score == round(2 / 3, 4)
