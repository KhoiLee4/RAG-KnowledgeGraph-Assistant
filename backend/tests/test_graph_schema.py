"""Unit tests cho graph_schema (không cần DB/API)."""

from app.services.graph_schema import (
    community_edge_weight,
    normalize_relation_type,
)


def test_normalize_relation_type_canonical():
    assert normalize_relation_type("WORKS_AT") == "WORKS_AT"
    assert normalize_relation_type("works at") == "WORKS_AT"


def test_normalize_relation_type_aliases():
    assert normalize_relation_type("thuc_tap_tai") == "INTERNS_AT"
    assert normalize_relation_type("GIAM_DOC") == "DIRECTOR_OF"
    assert normalize_relation_type("intern at") == "INTERNS_AT"


def test_normalize_relation_type_fallback():
    assert normalize_relation_type("") == "RELATED_TO"
    assert normalize_relation_type("unknown_relation_xyz") == "RELATED_TO"


def test_community_edge_weight_prefers_semantic():
    related_w, cooccur_w = 2.0, 0.5
    assert community_edge_weight("COOCCURS_WITH", related_w, cooccur_w) == cooccur_w
    assert community_edge_weight("WORKS_AT", related_w, cooccur_w) > related_w
    assert community_edge_weight("RELATED_TO", related_w, cooccur_w) == related_w
