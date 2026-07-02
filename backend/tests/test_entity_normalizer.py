"""Unit tests cho EntityNormalizer — 3 fix gộp entity (không cần DB/API)."""

from app.services.entity_normalizer import (
    CanonicalRegistry,
    EntityNormalizer,
    preferred_entity_type,
    strip_person_title,
)


def test_normalize_name_strips_dj():
    # Fix 1: đ/Đ phải thành 'd' (NFKD không tách được).
    n = EntityNormalizer.normalize_name
    assert n("LÊ ĐÌNH KHÔI") == "le dinh khoi"
    assert n("KIẾN ĐỨC THỊNH") == "kien duc thinh"
    assert n("Đà Nẵng") == "da nang"


def test_strip_person_title():
    # Fix 2: bỏ kính ngữ đứng đầu tên người.
    assert strip_person_title("Ông/Bà: LÊ ĐÌNH KHÔI") == "LÊ ĐÌNH KHÔI"
    assert strip_person_title("Ông KIẾN ĐỨC THỊNH") == "KIẾN ĐỨC THỊNH"
    assert strip_person_title("Bà Nguyễn Thị A") == "Nguyễn Thị A"
    assert strip_person_title("LÊ ĐÌNH KHÔI") == "LÊ ĐÌNH KHÔI"


def test_resolve_canonical_person_variants_same_norm():
    # Các biến thể cùng một người → cùng canonical_norm → cùng entity id.
    n = EntityNormalizer()
    r1 = n.resolve_canonical("LÊ ĐÌNH KHÔI", "PERSON")
    r2 = n.resolve_canonical("Ông/Bà: LÊ ĐÌNH KHÔI", "PERSON")
    assert r1 is not None and r2 is not None
    assert r1[1] == r2[1] == "le dinh khoi"


def test_resolve_canonical_does_not_strip_location():
    # Không được cắt nhầm tiền tố với LOCATION (vd 'Bà Rịa-Vũng Tàu').
    n = EntityNormalizer()
    r = n.resolve_canonical("Bà Rịa-Vũng Tàu", "LOCATION")
    assert r is not None
    assert r[1] == "ba ria vung tau"


def test_preferred_entity_type():
    # Fix 3: PERSON ưu tiên hơn ORGANIZATION.
    assert preferred_entity_type("ORGANIZATION", "PERSON") == "PERSON"
    assert preferred_entity_type("PERSON", "ORGANIZATION") == "PERSON"
    assert preferred_entity_type("OTHER", "CONCEPT") == "CONCEPT"


def test_cross_type_dedup_person_priority():
    # Fix 3: cùng norm, khác nhãn giữa các chunk → gộp 1 entity id, type = PERSON.
    n = EntityNormalizer()
    reg = CanonicalRegistry()
    e1, _, _ = n.normalize_entities(
        [{"name": "KIẾN ĐỨC THỊNH", "type": "ORGANIZATION"}], [], registry=reg
    )
    e2, _, _ = n.normalize_entities(
        [{"name": "Ông KIẾN ĐỨC THỊNH", "type": "PERSON"}], [], registry=reg
    )
    id1 = EntityNormalizer.build_entity_id(e1[0]["name_norm"], "u1")
    id2 = EntityNormalizer.build_entity_id(e2[0]["name_norm"], "u1")
    assert id1 == id2
    assert reg.stable_type(e1[0]["name_norm"], "ORGANIZATION") == "PERSON"
    assert e2[0]["type"] == "PERSON"
