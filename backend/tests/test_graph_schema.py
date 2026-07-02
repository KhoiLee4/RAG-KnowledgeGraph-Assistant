"""Unit tests cho graph_schema + relation_normalizer (không cần DB/API)."""

from app.services.graph_schema import (
    CANONICAL_RELATION_TYPES,
    canonical_entity_label,
    clean_relation_key,
    community_edge_weight,
    is_canonical_relation,
    normalize_relation_type,
)
from app.services.relation_normalizer import RelationNormalizer


def test_normalize_relation_type_canonical():
    assert normalize_relation_type("WORKS_FOR") == "WORKS_FOR"
    assert normalize_relation_type("works for") == "WORKS_FOR"
    assert normalize_relation_type("PART_OF") == "PART_OF"


def test_normalize_relation_type_aliases():
    # Các biến thể đồng nghĩa gộp về canonical.
    assert normalize_relation_type("works at") == "WORKS_FOR"
    assert normalize_relation_type("employed_by") == "WORKS_FOR"
    assert normalize_relation_type("thuc_tap_tai") == "WORKS_FOR"
    assert normalize_relation_type("GIAM_DOC") == "DIRECTOR_OF"


def test_clean_relation_key_strips_vietnamese_diacritics():
    # Regression: dấu tiếng Việt phải bị bỏ (không thành "_"), đ/Đ → d/D.
    assert clean_relation_key("gây ra") == "GAY_RA"
    assert clean_relation_key("làm việc tại") == "LAM_VIEC_TAI"
    assert clean_relation_key("thực tập tại") == "THUC_TAP_TAI"
    assert clean_relation_key("đứng đầu") == "DUNG_DAU"


def test_normalize_relation_type_vietnamese_aliases():
    # Regression: alias tiếng Việt có dấu phải map đúng canonical (bug cũ → RELATED_TO).
    assert normalize_relation_type("làm việc tại") == "WORKS_FOR"
    assert normalize_relation_type("thực tập tại") == "WORKS_FOR"
    assert normalize_relation_type("giám đốc") == "DIRECTOR_OF"
    assert normalize_relation_type("quản lý") == "MANAGES"
    assert normalize_relation_type("hợp tác") == "COLLABORATES_WITH"
    assert normalize_relation_type("liên quan") == "RELATED_TO"


def test_normalize_relation_type_keeps_unknown_for_embedding():
    # Cú pháp rẻ giữ nguyên loại lạ (embedding sẽ map tiếp ở bước sau).
    assert normalize_relation_type("frobnicates") == "FROBNICATES"
    assert normalize_relation_type("") == "RELATED_TO"
    assert normalize_relation_type("!!!") == "RELATED_TO"


def test_normalize_relation_type_neo4j_safe():
    assert normalize_relation_type("123 rel").startswith("REL_")
    assert len(normalize_relation_type("A" * 200)) <= 60


def test_is_canonical_relation():
    assert is_canonical_relation("works at") is True   # alias → WORKS_FOR
    assert is_canonical_relation("frobnicates") is False


def test_canonical_entity_label():
    assert canonical_entity_label("Company") == "ORGANIZATION"
    assert canonical_entity_label("corporation") == "ORGANIZATION"
    assert canonical_entity_label("PERSON") == "PERSON"
    assert canonical_entity_label("river") == "OTHER"
    assert canonical_entity_label("") == "OTHER"


def test_community_edge_weight_prefers_semantic():
    related_w, cooccur_w = 2.0, 0.5
    assert community_edge_weight("COOCCURS_WITH", related_w, cooccur_w) == cooccur_w
    assert community_edge_weight("WORKS_FOR", related_w, cooccur_w) > related_w
    assert community_edge_weight("RELATED_TO", related_w, cooccur_w) == related_w


def test_community_edge_weight_excludes_system_relations():
    # Regression: system relation KHÔNG được boost 1.25x như semantic.
    related_w, cooccur_w = 2.0, 0.5
    for sys_rel in ("MENTIONS", "CONTAINS", "NEXT", "BELONGS_TO", "IN_COMMUNITY"):
        assert community_edge_weight(sys_rel, related_w, cooccur_w) == related_w


def test_relation_normalizer_offline():
    # Tắt embedding: alias → canonical, loại lạ → RELATED_TO.
    rn = RelationNormalizer(use_embedding=False)
    assert rn.to_canonical("employed by") == "WORKS_FOR"
    assert rn.to_canonical("PART_OF") == "PART_OF"
    assert rn.to_canonical("frobnicates") == "RELATED_TO"


def test_relation_normalizer_embedding_maps_to_nearest():
    # Stub embedder tất định: "leads to" và query "brings about" cùng vector [1,0];
    # mọi canonical khác vector [0,1]. => query phải map về LEADS_TO.
    def _vec_for(text: str) -> list[float]:
        return [1.0, 0.0] if text in ("leads to", "brings about") else [0.0, 1.0]

    class StubEmbedder:
        def embed_batch(self, texts):
            return [_vec_for(t) for t in texts]

        def embed_text(self, text):
            return _vec_for(text)

    rn = RelationNormalizer(embedder=StubEmbedder(), threshold=0.9, use_embedding=True)
    assert rn.to_canonical("brings about") == "LEADS_TO"


def test_relation_normalizer_embedding_below_threshold():
    # Query trực giao với mọi canonical → cosine thấp → RELATED_TO.
    class OrthoEmbedder:
        def embed_batch(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def embed_text(self, text):
            return [0.0, 1.0]

    rn = RelationNormalizer(embedder=OrthoEmbedder(), threshold=0.5, use_embedding=True)
    assert rn.to_canonical("xyzzy") == "RELATED_TO"
