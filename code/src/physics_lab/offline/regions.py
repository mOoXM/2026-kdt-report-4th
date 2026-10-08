"""
regions.py — 문항 이미지의 구역 박스를 서버가 읽는 창구

읽는 것   build/{과목}/regions/{item_key}.json
          [{"label": text|figure|statement|options, "box_2d": [ymin, xmin, ymax, xmax], "tag": "ㄱ"|None, "conf"}]
          좌표는 0~1000 (이미지 크기 무관). 사전 처리(문항 구역 분리 모델)가 쓴다. 공개본은 demo_seed.py 가 쓴다.

주는 것   regions_of(item_key) →
          {"options":    [ymin, xmin, ymax, xmax] | None,      # 선지 묶음 — 진단 모드가 가린다
           "figures":    [{"tag": "(가)", "box": [...]}, ...],
           "statements": [{"tag": "ㄱ",   "box": [...]}, ...],
           "texts":      [[...], ...]}
          파일이 없으면 None — 화면은 "가릴 것 없음" 으로 처리한다.

캐시: 파일 mtime 으로. 서버를 안 내려도 파일을 다시 쓰면 다음 요청에 반영된다.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..db import BUILD, DEFAULT_SUBJECT

Box = list[int]                      # [ymin, xmin, ymax, xmax] 0~1000

_cache: dict[Path, tuple[float, dict | None]] = {}


def regions_dir(subject: str = DEFAULT_SUBJECT) -> Path:
    return BUILD / subject / "regions"


def _union(a: Box | None, b: Box) -> Box:
    return b if a is None else [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _shape(blocks: list[dict]) -> dict:
    out: dict = {"options": None, "figures": [], "statements": [], "texts": []}
    for b in blocks:
        label, box = b.get("label"), b.get("box_2d")
        if not box or len(box) != 4:
            continue
        if label == "options":
            out["options"] = _union(out["options"], box)
        elif label == "figure":
            out["figures"].append({"tag": b.get("tag"), "box": box})
        elif label == "statement":
            out["statements"].append({"tag": b.get("tag"), "box": box})
        elif label == "text":
            out["texts"].append(box)
    return out


def regions_of(item_key: str, subject: str = DEFAULT_SUBJECT) -> dict | None:
    p = regions_dir(subject) / f"{item_key}.json"
    try:
        mtime = p.stat().st_mtime
    except FileNotFoundError:
        return None
    hit = _cache.get(p)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        shaped = _shape(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        shaped = None
    _cache[p] = (mtime, shaped)
    return shaped
