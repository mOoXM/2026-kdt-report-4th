"""similar.index — 작은 가짜 벡터로 그림 평균 · 그림+글 결합 · 다수결 투표를 확인한다."""
import numpy as np

from physics_lab.similar.index import SimilarIndex


def _unit(v):
    v = np.array(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def _idx():
    # a 는 그림 두 개 (평균하면 [1,1,0] 방향), b 는 a 의 평균과 같은 방향, c 는 글만 a 와 같다
    fig = np.stack([_unit([1, 0, 0]), _unit([0, 1, 0]), _unit([1, 1, 0]), _unit([0, 0, 1])])
    fig_rows = [{"item_key": "a", "cat_1": "X"}, {"item_key": "a", "cat_1": "X"},
                {"item_key": "b", "cat_1": "X"}, {"item_key": "c", "cat_1": "Y"}]
    txt = np.stack([_unit([0, 0, 1]), _unit([0, 0, 1])])
    txt_rows = [{"item_key": "a", "cat_1": "X"}, {"item_key": "c", "cat_1": "Y"}]
    return SimilarIndex(fig, fig_rows, txt, txt_rows)


def test_figure_mean_and_mix():
    idx = _idx()
    nb = idx.neighbors("b", k=2, alpha=1.0)                  # 그림만: a 의 그림 평균이 b 와 같다
    assert nb[0][0] == "a" and nb[0][1] > 0.99
    nb_txt = idx.neighbors("a", k=1, alpha=0.0)              # 글만: a 와 c 의 글이 같다
    assert nb_txt[0][0] == "c"
    nb_mix = idx.neighbors("a", k=3, alpha=0.5)
    assert {k for k, _ in nb_mix} == {"b", "c"}
    assert idx.neighbors("a", k=3, cat="Y") == [nb_mix[[k for k, _ in nb_mix].index("c")]]


def test_majority_vote():
    nb = [("a", 0.9), ("c", 0.8), ("z", 0.7)]                # z 는 라벨 없음 → 투표에서 빠진다
    labels = {"a": {"C03", "C05"}, "c": {"C03"}}
    votes = SimilarIndex.vote_concept(nb, labels)
    assert votes == {"C03": 2.0, "C05": 1.0}
    assert SimilarIndex.predict_concept(votes, nb, labels) == {"C03", "C05"}             # 라벨 이웃 2개의 절반 이상
    assert SimilarIndex.predict_concept(votes, nb, labels, frac=0.75) == {"C03"}
