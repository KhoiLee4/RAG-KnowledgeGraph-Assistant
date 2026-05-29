"""Unit tests cho hybrid keyword scoring (không cần DB/API)."""

from app.services.hybrid_search import keyword_score, merge_hybrid_scores, tokenize


def test_tokenize_splits_underscores():
    tokens = tokenize("Bao_cao_do_an.pdf")
    assert "bao" in tokens and "cao" in tokens


def test_keyword_score_file_name_match():
    score = keyword_score(
        "báo cáo đồ án",
        "Nội dung không liên quan.",
        file_name="Bao_cao_do_an.pdf",
    )
    assert score > 0.2


def test_merge_hybrid_boosts_keyword_match():
    candidates = [
        {
            "text": "Stripe API key rotation policy",
            "file_name": "payments.docx",
            "score": 0.55,
        },
        {
            "text": "Nội dung chung chung về công ty.",
            "file_name": "hr.pdf",
            "score": 0.70,
        },
    ]
    merged = merge_hybrid_scores(
        candidates,
        "Stripe API",
        vector_weight=0.80,
        keyword_weight=0.20,
    )
    assert merged[0]["file_name"] == "payments.docx"
    assert merged[0]["combined_score"] >= merged[1]["combined_score"]
