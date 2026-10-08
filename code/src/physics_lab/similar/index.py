"""
index.py — 유사 문항 엔진. 특징값(벡터) 적재 + 코사인 최근접 (numpy 만 쓴다)

읽는 것   build/{과목}/embed/
              figures.npy  figures.json   그림 특징값 (그림 하나에 한 행. 한 문항에 그림이 여러 개일 수 있다)
              texts.npy    texts.json     문제 글 특징값 (문항 하나에 한 행)
          행은 모두 길이 1 로 정규화되어 있다.

점수      문항의 그림 벡터 = 그 문항 그림들의 평균. 그림 · 글 각각 코사인 유사도를 구해
          alpha · 그림 + (1 - alpha) · 글 로 섞는다. 한쪽만 있으면 그쪽만. alpha 1 = 그림만, 0 = 글만.
개념 제안  이웃 문항들의 개념을 다수결로 모은다 (vote_concept · predict_concept).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..db import BUILD, DEFAULT_SUBJECT


def embed_dir(subject: str = DEFAULT_SUBJECT) -> Path:
    return BUILD / subject / "embed"


def _normalize(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(n == 0, 1, n)


class SimilarIndex:
    def __init__(self, fig_vecs: np.ndarray, fig_rows: list[dict], txt_vecs: np.ndarray | None, txt_rows: list[dict]):
        fig_of: dict[str, list[int]] = {}
        for i, r in enumerate(fig_rows):
            fig_of.setdefault(r["item_key"], []).append(i)
        self.txt_of: dict[str, int] = {r["item_key"]: i for i, r in enumerate(txt_rows)}
        self.items: list[str] = sorted(set(fig_of) | set(self.txt_of))
        self._item_no = {k: n for n, k in enumerate(self.items)}
        self.cat_of: dict[str, str | None] = {}
        for r in fig_rows + txt_rows:
            self.cat_of.setdefault(r["item_key"], r.get("cat_1"))

        dim_f = fig_vecs.shape[1] if len(fig_vecs) else 0
        dim_t = txt_vecs.shape[1] if txt_vecs is not None and len(txt_vecs) else 0
        # 문항 순서로 정렬한 행렬. 없는 쪽은 0 벡터 + has_* 플래그
        self.fig = np.zeros((len(self.items), dim_f), dtype=np.float32)
        self.txt = np.zeros((len(self.items), dim_t), dtype=np.float32)
        self.has_fig = np.zeros(len(self.items), dtype=bool)
        self.has_txt = np.zeros(len(self.items), dtype=bool)
        for k, rows in fig_of.items():
            self.fig[self._item_no[k]] = fig_vecs[rows].mean(axis=0)
            self.has_fig[self._item_no[k]] = True
        for k, i in self.txt_of.items():
            self.txt[self._item_no[k]] = txt_vecs[i]
            self.has_txt[self._item_no[k]] = True
        self.fig = _normalize(self.fig)
        self.txt = _normalize(self.txt)

    @classmethod
    def load(cls, subject: str = DEFAULT_SUBJECT) -> "SimilarIndex":
        d = embed_dir(subject)
        fig_vecs = np.load(d / "figures.npy")
        fig_rows = json.loads((d / "figures.json").read_text(encoding="utf-8"))
        txt_vecs = np.load(d / "texts.npy") if (d / "texts.npy").is_file() else None
        txt_rows = json.loads((d / "texts.json").read_text(encoding="utf-8")) if (d / "texts.json").is_file() else []
        return cls(fig_vecs, fig_rows, txt_vecs, txt_rows)

    def scores(self, item_key: str, alpha: float = 0.5) -> np.ndarray:
        """질의 문항과 모든 문항의 점수. 비교할 수 없는 문항은 nan."""
        q = self._item_no[item_key]
        f = np.where(self.has_fig & self.has_fig[q], self.fig @ self.fig[q], np.nan) if self.fig.shape[1] else np.full(len(self.items), np.nan)
        t = np.where(self.has_txt & self.has_txt[q], self.txt @ self.txt[q], np.nan) if self.txt.shape[1] else np.full(len(self.items), np.nan)
        if alpha >= 1:                     # 그림만
            return f
        if alpha <= 0:                     # 글만
            return t
        both = ~np.isnan(f) & ~np.isnan(t)
        return np.where(both, alpha * f + (1 - alpha) * t, np.where(np.isnan(f), t, f))

    def neighbors(self, item_key: str, k: int = 5, alpha: float = 0.5, cat: str | None = None) -> list[tuple[str, float]]:
        """문항 하나의 이웃 (자기 자신 제외), 점수 높은 순."""
        s = self.scores(item_key, alpha)
        out = []
        for j in np.argsort(-np.nan_to_num(s, nan=-np.inf)):
            key = self.items[j]
            if np.isnan(s[j]):
                break
            if key == item_key or (cat and self.cat_of.get(key) != cat):
                continue
            out.append((key, float(s[j])))
            if len(out) >= k:
                break
        return out

    @staticmethod
    def vote_concept(neighbors: list[tuple[str, float]], labels: dict[str, set[str]]) -> dict[str, float]:
        """이웃마다 자기 개념에 한 표씩. 라벨 없는 이웃은 건너뛴다."""
        votes: dict[str, float] = {}
        for key, _s in neighbors:
            for concept in labels.get(key, ()):
                votes[concept] = votes.get(concept, 0.0) + 1.0
        return votes

    @staticmethod
    def predict_concept(votes: dict[str, float], neighbors: list[tuple[str, float]], labels: dict[str, set[str]],
                        frac: float = 0.5) -> set[str]:
        """라벨 있는 이웃 가운데 frac 이상이 가진 개념."""
        n = sum(1 for key, _ in neighbors if key in labels)
        return {c for c, v in votes.items() if n and v >= frac * n}
