"""
interfaces.py — 교체 가능한 부품의 약속

진단 방식 · 문항 선택 방식 · AI 제공자를 인터페이스로 나눠 두었다. 지금 들어 있는 것은 기본 구현이고,
데이터가 쌓이면 같은 약속을 지키는 다른 구현(예: 정밀 진단 모델)으로 바꿔 끼운다.
라우터(serve/)는 이 약속만 보고 부른다.

    DiagnosisEngine     engine/diagnosis.py   BasicDiagnosis
    ItemPicker          engine/exam_pick.py   pick (round-robin)
    ExtractionProvider  offline/extractor.py  생성형 AI 제공자 (문항 이미지 → 구조화된 JSON)
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .diagnosis import Diagnosis, Response


class DiagnosisEngine(Protocol):
    # (item_key, label) → {"is_true": bool, "error_rate": float | None, "concept": [코드, ...]}
    units: dict[tuple[str, str], dict]

    def estimate(self, responses: list[Response]) -> Diagnosis:
        """학생 응답 → 개념별 결과."""
        ...

    def recommend(self, diag: Diagnosis, seen: set[tuple[str, str]], limit: int = 5) -> list[dict]:
        """약한 개념을 연습할 문항. [{item_key, score, concepts}]"""
        ...


class ItemPicker(Protocol):
    def __call__(self, bank: list[dict], concepts: list[str], n_statements: int, n_numeric: int,
                 exclude: set[str] | None = None, keep: list[str] | None = None) -> dict:
        """문항 은행 + 진단할 개념 → {"item_keys", "coverage", "short", "pool"}"""
        ...


class ExtractionProvider(Protocol):
    name: str

    def generate(self, prompt: str, image: Path, schema: dict) -> dict:
        """문항 이미지 하나 + 지시문 + 응답 스키마 → 스키마를 따르는 JSON."""
        ...
