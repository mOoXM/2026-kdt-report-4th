"""
evaluate.py — 연결표에서 문항별 개념 라벨을 읽는다 (유사 문항 엔진의 개념 제안 · 평가에 쓴다)

사람이 붙였거나 확인한 라벨만 쓴다. AI 제안 상태(status = 'ai')인 보기는 뺀다.
"""
from __future__ import annotations

import sqlite3

from ..db import concept_map_db

DONE = ("confirmed", "edited", "human")


def load_labels(subject: str) -> dict[str, set[str]]:
    """문항 → 확정된 개념 집합 (보기 라벨의 합집합)."""
    conn = sqlite3.connect(f"file:{concept_map_db(subject)}?mode=ro", uri=True)
    out: dict[str, set[str]] = {}
    for key, concept, status in conn.execute("SELECT item_key, concept, status FROM statement_concept"):
        if (status or "human") not in DONE or not concept:
            continue
        out.setdefault(key, set()).update(c.strip() for c in concept.split(",") if c.strip())
    conn.close()
    return {k: v for k, v in out.items() if v}
