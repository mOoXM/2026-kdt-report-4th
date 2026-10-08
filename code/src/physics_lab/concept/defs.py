"""
defs.py — 세부 개념 체계 (공개본: 교육과정 성취기준 수준의 예시 8개)

보기 하나(판단 단위)에 개념 코드를 하나 이상 붙인다. 연결표(data/ph1/concept_map.db 의 statement_concept)가
"이 보기를 옳게 판단하려면 어떤 개념이 필요한가" 를 담고, 진단 엔진은 그 표로 개념별 이해 수준을 낸다.

코드는 C01 부터. 키는 라벨링 도구의 단축키 자리다.
"""

from __future__ import annotations

# (키, 코드, 이름, 설명)
CONCEPT_LIST = [
    ("1", "C01", "알짜힘",            "여러 힘의 합. 알짜힘이 0 이면 속도가 변하지 않는다"),
    ("2", "C02", "관성 법칙",          "알짜힘이 0 이면 정지 또는 등속 직선 운동"),
    ("3", "C03", "가속도 법칙",        "a = F/m. 알짜힘과 가속도의 방향 · 크기 관계"),
    ("4", "C04", "작용 반작용 법칙",    "두 물체가 주고받는 힘. 힘의 평형과 구분"),
    ("5", "C05", "연결된 물체의 운동",   "실 · 접촉으로 함께 움직이는 물체들"),
    ("6", "C06", "운동 그래프 해석",    "위치 · 속도 · 가속도 그래프의 기울기와 넓이"),
    ("7", "C07", "운동량과 충격량",     "운동량 보존, 충격량 = 운동량 변화"),
    ("8", "C08", "역학적 에너지",       "운동 에너지와 퍼텐셜 에너지의 전환과 보존"),
]

KEY_TO_CODE = {k: code for k, code, _, _ in CONCEPT_LIST if k}
CODES = [code for _, code, _, _ in CONCEPT_LIST]

# 단원별로 화면에 펼쳐 둘 개념 (화면 필터. 한 개념이 여러 단원에 들어갈 수 있다)
CONCEPTS_BY_UNIT = {
    "뉴턴 법칙": ["C01", "C02", "C03", "C04", "C05", "C06"],
    "운동량과 충격량": ["C03", "C06", "C07"],
    "역학적 에너지 보존": ["C01", "C06", "C08"],
}


def concepts_for_unit(unit: str) -> list[str]:
    """그 단원에서 펼쳐 둘 개념 코드. 정의가 없으면 전체."""
    return CONCEPTS_BY_UNIT.get(unit, CODES)


def concept_order(code: str) -> int:
    """C2 < C10 이 되도록 숫자로 정렬한다."""
    try:
        return int(code[1:])
    except ValueError:
        return 999


def sort_concept(codes) -> list[str]:
    return sorted(set(c for c in codes if c), key=concept_order)


def join_concept(codes) -> str:
    return ",".join(sort_concept(codes))


def split_concept(s: str | None) -> list[str]:
    return [x for x in (s or "").split(",") if x]
