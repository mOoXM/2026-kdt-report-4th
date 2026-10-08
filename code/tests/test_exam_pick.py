"""exam_pick.pick — 순수 함수. DB 없이."""
from physics_lab.engine.exam_pick import pick


def _it(key, fmt, concepts):
    return {"item_key": key, "format": fmt, "concepts": concepts}


BANK = [
    _it("s1", "statements", ["C03"]),
    _it("s2", "statements", ["C03", "C05"]),
    _it("s3", "statements", ["C05"]),
    _it("s4", "statements", ["C01"]),                 # 목표 밖
    _it("s5", "statements", ["C03", "C05", "C06"]),
    _it("n1", "numeric", ["C03", "C05"]),
    _it("n2", "numeric", ["C07"]),
]


def test_round_robin_covers_targets_and_respects_quotas():
    r = pick(BANK, ["C03", "C05"], n_statements=3, n_numeric=1)
    keys = r["item_keys"]
    assert len(keys) == 4
    assert sum(1 for k in keys if k.startswith("n")) == 1
    assert "s4" not in keys and "n2" not in keys       # 목표 개념이 없는 문항은 안 담는다
    assert keys[:2] == ["s1", "s2"]                    # C03 → C05 차례로
    assert r["coverage"]["C03"] >= 2 and r["coverage"]["C05"] >= 2
    assert r["short"] == []


def test_short_when_pool_is_small():
    r = pick(BANK, ["C07"], n_statements=2, n_numeric=2)
    assert r["item_keys"] == ["n2"]
    assert r["short"] == ["C07"]


def test_keep_and_exclude():
    r = pick(BANK, ["C03"], n_statements=1, n_numeric=0, exclude={"s1"}, keep=["s2"])
    assert r["item_keys"][0] == "s2" and "s1" not in r["item_keys"] and len(r["item_keys"]) == 2
