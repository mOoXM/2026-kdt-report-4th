"""
exam_pick.py — 진단할 개념과 문항 수를 주면 시험 문항을 골라 준다 (강사 앱 "자동으로 담기")

규칙
  - 개념마다 최소 MIN_PER_CONCEPT 문항을 목표로 한다
  - 보기형(ㄱㄴㄷ) · 계산형 문항 수는 강사가 각각 정한다
  - exclude 로 받은 문항(이 반이 이미 본 것)은 고르지 않는다
  - 결과는 제안이다. 강사가 화면에서 빼고 더한다

고르는 법 — round-robin. 목표 개념을 차례로 돌면서, 그 개념이 붙은 문항 가운데 아직 안 고른 첫 문항을 담는다.
남은 자리가 없거나 후보가 떨어지면 멈춘다.
순수 함수 — DB 를 모른다. teacher.load_bank() 의 문항 목록을 받는다.
"""

from __future__ import annotations

MIN_PER_CONCEPT = 2


def pick(bank: list[dict], concepts: list[str], n_statements: int, n_numeric: int,
         exclude: set[str] | None = None, keep: list[str] | None = None) -> dict:
    """
    bank: [{item_key, format('statements'|'numeric'), concepts[list], ...}]
    반환 {"item_keys": [keep… + 고른 것], "coverage": {개념: 문항 수}, "short": [목표에 못 미친 개념], "pool": {"statements": n, "numeric": n}}
    """
    target = [k for k in concepts if k]
    exclude = set(exclude or ())
    by_key = {it["item_key"]: it for it in bank}
    picked = [k for k in (keep or []) if k in by_key]

    pools: dict[str, list[dict]] = {"statements": [], "numeric": []}
    for it in bank:
        if it["item_key"] in exclude or it["item_key"] in picked:
            continue
        if set(target) & set(it["concepts"]):
            pools.setdefault(it.get("format") or "statements", []).append(it)
    quota = {"statements": max(0, n_statements), "numeric": max(0, n_numeric)}

    progressed = True
    while target and any(quota.values()) and progressed:
        progressed = False
        for concept in target:
            cand = next((it for fmt, pool in pools.items() if quota.get(fmt, 0) > 0
                         for it in pool if it["item_key"] not in picked and concept in it["concepts"]), None)
            if cand is None:
                continue
            picked.append(cand["item_key"])
            quota[cand.get("format") or "statements"] -= 1
            progressed = True
            if not any(quota.values()):
                break

    coverage = {k: sum(1 for key in picked if k in by_key[key]["concepts"]) for k in target}
    return {
        "item_keys": picked,
        "coverage": coverage,
        "short": [k for k in target if coverage[k] < MIN_PER_CONCEPT],
        "pool": {fmt: len(p) for fmt, p in pools.items()},
    }
