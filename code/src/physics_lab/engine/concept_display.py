"""
concept_display.py — 개념 코드를 학생 · 강사 화면에 어떻게 쓸 것인가 (표현 계층)

defs.py 는 무엇을 재는지(측정 체계), 여기는 어떻게 보여 줄지만 정한다. 여기를 고쳐도 진단 결과는 안 바뀐다.

    label(code)        화면 문구
    group(code)        화면 섹션 제목
    tiers(concepts)    약한 개념을 점수 구간별로 묶은 요약 문장
    as_sections(...)   진단 결과를 그룹 단위로 접기
    also(...)          틀린 보기에 함께 필요했던 다른 약한 개념
    catalog()          /api/student/concepts
"""

from __future__ import annotations

from ..concept.defs import CODES, CONCEPT_LIST, concept_order, sort_concept

GROUPS: list[tuple[str, list[str]]] = [
    ("힘과 운동 법칙", ["C01", "C02", "C03", "C04"]),
    ("운동 해석",      ["C05", "C06"]),
    ("운동량과 에너지", ["C07", "C08"]),
]

LABEL: dict[str, str] = {code: name for _, code, name, _ in CONCEPT_LIST}
GROUP_OF: dict[str, str] = {c: title for title, codes in GROUPS for c in codes}


def _self_check() -> None:
    """개념을 추가하고 여기를 안 고치면 import 할 때 바로 알 수 있게."""
    grouped = [c for _, codes in GROUPS for c in codes]
    missing = [c for c in CODES if c not in grouped]
    unknown = [c for c in grouped if c not in CODES]
    if missing or unknown:
        raise RuntimeError(f"concept_display.GROUPS 가 defs.py 와 어긋난다 — 빠짐 {missing} / 모름 {unknown}")


_self_check()


def label(code: str) -> str:
    """화면 문구. 모르는 코드는 코드 그대로."""
    return LABEL.get(code, code)


def group(code: str) -> str:
    return GROUP_OF.get(code, "기타")


def _listing(codes) -> str:
    return ", ".join(f"「{label(c)}」" for c in sort_concept(codes))


# (위 경계, 제목, 문장 끝)
TIERS = [
    (0.3, "먼저 복습할 개념", " — 여기부터 다시 보세요."),
    (0.6, "다음에 복습할 개념", " — 조금 더 연습하면 됩니다."),
]


def tiers(concepts) -> list[dict]:
    """
    약한 개념(status '미숙달')을 점수 구간별로 묶어 한 문장씩. concepts 는 {"code", "score", "status"} dict 목록.
    비어 있는 구간은 내보내지 않는다.
    """
    weak = [k for k in concepts if k.get("status") == "미숙달" and k.get("score") is not None]
    out, lo = [], -1.0
    for hi, title, suffix in TIERS:
        band = [k["code"] for k in weak if lo < k["score"] <= hi]
        lo = hi
        if band:
            out.append({"title": title, "text": _listing(band) + suffix, "codes": sort_concept(band)})
    return out


def also(codes, weak, exclude: str) -> list[str]:
    """이 보기에 함께 필요했던 다른 약한 개념의 문구."""
    weak = set(weak)
    return [label(c) for c in sort_concept(codes) if c in weak and c != exclude]


def decorate(concepts: list[dict]) -> list[dict]:
    """진단 결과에 화면용 필드(label, group)를 붙이고 정의용 필드(name, desc)를 뗀다."""
    out = []
    for k in concepts:
        d = {kk: vv for kk, vv in k.items() if kk not in ("name", "desc")}
        d["label"] = label(k["code"])
        d["group"] = group(k["code"])
        out.append(d)
    return out


def as_sections(concepts: list[dict]) -> list[dict]:
    """그룹 단위로 접어서 돌려준다. 비어 있는 그룹은 안 내보낸다."""
    by: dict[str, list[dict]] = {title: [] for title, _ in GROUPS}
    for k in sorted(decorate(concepts), key=lambda d: concept_order(d["code"])):
        by.setdefault(k["group"], []).append(k)
    return [{"group": title, "concepts": items} for title, items in by.items() if items]


def catalog() -> list[dict]:
    return [{"group": title, "concepts": [{"code": c, "label": label(c)} for c in sort_concept(codes)]}
            for title, codes in GROUPS]
