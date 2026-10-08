"""
diagnosis.py — 학생 응답으로 세부 개념별 이해 수준을 낸다 (기본 진단 엔진)

    from physics_lab.engine.diagnosis import BasicDiagnosis, Response

    engine = BasicDiagnosis.from_db(PHYSICS_DB, CONCEPT_MAP_DB, cat="뉴턴 법칙")
    diag = engine.estimate([Response("demo_01", "ㄱ", True), ...])
    diag.weak()                                   # 약한 개념, 점수 낮은 순

방법
----
보기 하나 = 판단 단위 하나. 연결표가 보기마다 필요한 개념을 알려 준다.
개념 점수 = 그 개념이 붙은 보기 가운데 학생이 옳게 판단한 비율 (단순 정답률).
판단 단위가 MIN_UNITS 개보다 적으면 "자료 부족" 으로 둔다.

소규모 데이터에서도 동작하는 기본형이다. 같은 약속(engine/interfaces.py 의 DiagnosisEngine)을 지키는
정밀 진단 모델로 바꿔 끼울 수 있다.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..concept.defs import CONCEPT_LIST, concept_order, split_concept
from ..db import CM, connect

# 이해했다고 볼 최소 점수
DIAGNOSIS_THRESHOLD = 0.6
# 판정에 필요한 최소 판단 단위 수
MIN_UNITS = 2


@dataclass(frozen=True)
class Response:
    """학생이 보기 하나에 대해 내린 판단."""
    item_key: str
    label: str
    answer: bool        # 학생이 '참'이라고 판단했는가


@dataclass
class ConceptResult:
    code: str
    name: str
    desc: str
    score: float | None          # 정답률 0~1. 자료 부족이면 None
    n_units: int                 # 학생이 만난 판단 단위 수
    n_correct: int
    wrong: list[tuple[str, str, float | None]] = field(default_factory=list)
    # (item_key, label, error_rate) — 틀린 보기들

    @property
    def status(self) -> str:
        if self.score is None:
            return "자료 부족"
        return "숙달" if self.score >= DIAGNOSIS_THRESHOLD else "미숙달"

    @property
    def is_weak(self) -> bool:
        return self.score is not None and self.score < DIAGNOSIS_THRESHOLD


@dataclass
class Diagnosis:
    concepts: list[ConceptResult]
    n_answered: int
    n_correct: int

    def weak(self) -> list[ConceptResult]:
        """약한 개념을 점수가 낮은 순으로."""
        return sorted((k for k in self.concepts if k.is_weak), key=lambda k: (k.score, concept_order(k.code)))

    def by_code(self) -> dict[str, ConceptResult]:
        return {k.code: k for k in self.concepts}


class BasicDiagnosis:
    """연결표(보기 → 개념)와 정답(보기 → 참/거짓)을 들고 있다가 학생 응답을 받아 개념별 결과를 낸다."""

    def __init__(self, units: dict[tuple[str, str], dict]):
        # units[(item_key, label)] = {"is_true", "error_rate", "concept": [...]}
        self.units = units

    @classmethod
    def from_db(cls, physics_db: Path, concept_map_db: Path, cat: str | None = None) -> "BasicDiagnosis":
        conn = connect(physics_db, [(concept_map_db, CM)])
        sql = f"""
            SELECT s.item_key, s.label, s.is_true, s.error_rate, k.concept
            FROM statements s
            JOIN items i ON i.item_key = s.item_key
            JOIN {CM}.statement_concept k ON k.item_key = s.item_key AND k.label = s.label
            WHERE k.concept != '' AND s.is_true IS NOT NULL
        """
        params: tuple = ()
        if cat:
            sql += " AND i.cat_1 = ?"
            params = (cat,)
        units = {(r["item_key"], r["label"]): {"is_true": bool(r["is_true"]),
                                               "error_rate": r["error_rate"],
                                               "concept": split_concept(r["concept"])}
                 for r in conn.execute(sql, params)}
        conn.close()
        return cls(units)

    def estimate(self, responses: list[Response]) -> Diagnosis:
        acc = {code: {"n": 0, "correct": 0, "wrong": []} for _, code, _, _ in CONCEPT_LIST}
        n_answered = n_correct = 0
        for r in responses:
            u = self.units.get((r.item_key, r.label))
            if u is None:
                continue                                # 연결표에 없는 보기
            ok = r.answer == u["is_true"]
            n_answered += 1
            n_correct += ok
            for code in u["concept"]:
                a = acc.get(code)
                if a is None:
                    continue
                a["n"] += 1
                if ok:
                    a["correct"] += 1
                else:
                    a["wrong"].append((r.item_key, r.label, u["error_rate"]))

        results = []
        for _, code, name, desc in CONCEPT_LIST:
            a = acc[code]
            score = a["correct"] / a["n"] if a["n"] >= MIN_UNITS else None
            results.append(ConceptResult(code=code, name=name, desc=desc,
                                         score=round(score, 3) if score is not None else None,
                                         n_units=a["n"], n_correct=a["correct"],
                                         wrong=sorted(a["wrong"])))
        return Diagnosis(concepts=results, n_answered=n_answered, n_correct=n_correct)

    def recommend(self, diag: Diagnosis, seen: set[tuple[str, str]], limit: int = 5) -> list[dict]:
        """약한 개념이 붙은 보기를 가진 문항. 약한 개념을 많이 다루는 문항부터."""
        weak = {k.code for k in diag.weak()}
        if not weak:
            return []
        by_item: dict[str, set[str]] = {}
        for (item_key, label), u in self.units.items():
            if (item_key, label) in seen:
                continue
            hit = weak & set(u["concept"])
            if hit:
                by_item.setdefault(item_key, set()).update(hit)
        ranked = sorted(by_item.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:limit]
        return [{"item_key": k, "score": float(len(c)), "concepts": sorted(c, key=concept_order)} for k, c in ranked]


def main() -> None:
    """가상 학생 하나로 엔진이 도는지 본다. `uv run pl-diagnosis` (먼저 pl-demo-seed)"""
    from ..db import CONCEPT_MAP_DB, PHYSICS_DB

    engine = BasicDiagnosis.from_db(PHYSICS_DB, CONCEPT_MAP_DB, cat="뉴턴 법칙")
    print(f"판단 단위 {len(engine.units)}개 적재")
    if not engine.units:
        print("연결표가 비어 있다. uv run pl-demo-seed 를 먼저.")
        sys.exit(1)

    # 가상 학생: 작용 반작용(C04)이 붙은 보기만 틀린다
    responses = [Response(k, lab, (not u["is_true"]) if "C04" in u["concept"] else u["is_true"])
                 for (k, lab), u in engine.units.items()]
    diag = engine.estimate(responses)
    print(f"\n응답 {diag.n_answered}개 중 {diag.n_correct}개 정답\n")
    for k in diag.concepts:
        if k.n_units:
            score = "  —  " if k.score is None else f"{k.score:.2f}"
            print(f"  {k.code}  {k.name:12s} {score} ({k.n_correct}/{k.n_units})  {k.status}")
    print("\n약한 개념:", [k.code for k in diag.weak()])
    print("추천 문항:", [r["item_key"] for r in engine.recommend(diag, seen=set())])


if __name__ == "__main__":
    main()
