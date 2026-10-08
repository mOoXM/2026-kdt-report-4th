"""demo_seed — tmp 폴더에 데모 데이터를 만들고 앞뒤가 맞는지 본다."""
import json
import sqlite3

from physics_lab import demo_seed
from physics_lab.concept.defs import CODES


def test_seed_is_consistent(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_seed, "ROOT", tmp_path)
    monkeypatch.setattr(demo_seed, "BUILD", tmp_path / "build")
    monkeypatch.setattr(demo_seed, "DATA", tmp_path / "data")
    assert demo_seed.main() == 0

    p = sqlite3.connect(tmp_path / "build" / "ph1" / "physics.db")
    c = sqlite3.connect(tmp_path / "data" / "ph1" / "concept_map.db")
    items = p.execute("SELECT item_key, answer, item_format, image_path FROM items").fetchall()
    assert len(items) == len(demo_seed.ITEMS)
    for key, answer, fmt, image in items:
        assert (tmp_path / image).is_file()
        regions = json.loads((tmp_path / "build" / "ph1" / "regions" / f"{key}.json").read_text(encoding="utf-8"))
        assert {"text", "figure", "options"} <= {b["label"] for b in regions}
        # 보기형: 정답 선지의 조합 == 참인 보기 집합
        if fmt == "statements":
            truth = {lab for lab, t in p.execute("SELECT label, is_true FROM statements WHERE item_key = ?", (key,)) if t}
            picks = p.execute("SELECT picks FROM choices WHERE item_key = ? AND is_answer = 1", (key,)).fetchone()[0]
            assert set(picks.split(",")) == truth
            assert p.execute("SELECT choice_no FROM choices WHERE item_key = ? AND is_answer = 1", (key,)).fetchone()[0] == answer
    used = {x for (s,) in c.execute("SELECT concept FROM statement_concept") for x in s.split(",")}
    assert used <= set(CODES)
