"""engine.diagnosis — 기본 진단 엔진 (DB 없이 units 를 직접 준다)."""
from physics_lab.engine.diagnosis import DIAGNOSIS_THRESHOLD, MIN_UNITS, BasicDiagnosis, Response
from physics_lab.engine.concept_display import as_sections, tiers

UNITS = {
    ("i1", "ㄱ"): {"is_true": True, "error_rate": 10.0, "concept": ["C01"]},
    ("i1", "ㄴ"): {"is_true": False, "error_rate": 40.0, "concept": ["C04"]},
    ("i1", "ㄷ"): {"is_true": True, "error_rate": 30.0, "concept": ["C01", "C03"]},
    ("i2", "ㄱ"): {"is_true": False, "error_rate": 50.0, "concept": ["C04"]},
    ("i2", "ㄴ"): {"is_true": True, "error_rate": 20.0, "concept": ["C03"]},
    ("i3", "ㄱ"): {"is_true": True, "error_rate": 25.0, "concept": ["C04", "C05"]},
}


def _answer(wrong: set):
    return [Response(k, lab, (not u["is_true"]) if (k, lab) in wrong else u["is_true"]) for (k, lab), u in UNITS.items()]


def test_plain_correct_rate_per_concept():
    engine = BasicDiagnosis(UNITS)
    diag = engine.estimate(_answer({("i1", "ㄴ"), ("i2", "ㄱ")}))           # C04 보기 셋 중 둘을 틀림
    by = diag.by_code()
    assert diag.n_answered == 6 and diag.n_correct == 4
    assert by["C01"].score == 1.0 and by["C03"].score == 1.0
    assert by["C04"].score == round(1 / 3, 3) and by["C04"].status == "미숙달"
    assert by["C05"].score is None and by["C05"].n_units == 1 < MIN_UNITS      # 자료 부족
    assert [k.code for k in diag.weak()] == ["C04"]
    assert by["C04"].wrong == [("i1", "ㄴ", 40.0), ("i2", "ㄱ", 50.0)]


def test_recommend_unseen_items_with_weak_concepts():
    engine = BasicDiagnosis(UNITS)
    diag = engine.estimate(_answer({("i1", "ㄴ"), ("i2", "ㄱ")}))
    rec = engine.recommend(diag, seen={("i1", "ㄴ"), ("i2", "ㄱ")})
    assert [r["item_key"] for r in rec] == ["i3"] and rec[0]["concepts"] == ["C04"]
    assert engine.recommend(engine.estimate(_answer(set())), seen=set()) == []        # 약한 개념이 없으면 빈 목록


def test_display_tiers_and_sections():
    diag = BasicDiagnosis(UNITS).estimate(_answer({("i1", "ㄴ"), ("i2", "ㄱ")}))
    rows = [{"code": k.code, "score": k.score, "status": k.status, "n_units": k.n_units} for k in diag.concepts if k.n_units]
    t = tiers(rows)
    assert len(t) == 1 and t[0]["codes"] == ["C04"] and DIAGNOSIS_THRESHOLD > 1 / 3
    groups = [s["group"] for s in as_sections(rows)]
    assert groups == ["힘과 운동 법칙", "운동 해석"]
