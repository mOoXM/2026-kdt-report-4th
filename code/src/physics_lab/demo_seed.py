"""
demo_seed.py — 데모 데이터. clone 한 뒤 이 명령 하나로 서버가 문항을 내보낼 수 있게 한다.

    uv run pl-demo-seed

만드는 것 (전부 다시 만들 수 있는 데모용 — 실행할 때마다 지우고 새로 만든다)
    build/ph1/physics.db          문항 DB        items · statements · choices
    data/ph1/concept_map.db       문항-개념 연결표 statement_concept · item_flags · statement_concept_alt
    data/ph1/images/demo_XX.png   문항 이미지 (Pillow 로 그린다)
    build/ph1/regions/*.json      문항 구역 박스 (지문 · 그림 · 보기 · 선지, 0~1000 좌표)
    build/ph1/embed/              유사 문항 엔진용 특징 벡터 (개념 기반 + 잡음. 실제 모델 대신)

문항은 이 저장소를 위해 새로 지은 쉬운 역학 문항이다 (기출 아님).
정답률·오판율도 지어낸 값이다. 계정·반은 여기서 만들지 않는다 — PL_DEV=1 서버의 DevBar "seed" 가 만든다.
"""

from __future__ import annotations

import json
import sqlite3

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .db import ANSWER_LABEL, BUILD, DATA, DEFAULT_SUBJECT, ROOT

SUBJECT = DEFAULT_SUBJECT
UNIT = "뉴턴 법칙"            # 진단 단원 (serve/student.py 의 UNIT 과 같아야 한다)
OTHER_UNIT = "운동량과 충격량"  # 개념 라벨이 없는 단원 — 시험지에는 담기고 채점은 되지만 진단 층은 없다

# 보기 조합형 선지 (①~⑤). 정답 = 참인 보기 집합과 같은 선지
COMBOS = [("ㄱ",), ("ㄷ",), ("ㄱ", "ㄴ"), ("ㄴ", "ㄷ"), ("ㄱ", "ㄴ", "ㄷ")]
CIRCLED = "①②③④⑤"

# (번호, 단원, 그림, 지문, [(라벨, 보기, 참?, 오판율, 개념)], 정답률)   — 보기형
# (번호, 단원, 그림, 지문, ("답", 선지 값 5개, 정답 번호, 개념), 정답률) — 계산형
ITEMS = [
    (1, UNIT, "block", "그림과 같이 마찰이 없는 수평면 위에 정지해 있던 물체에 수평 방향으로 일정한 힘 F 가 작용한다.",
     [("ㄱ", "물체의 가속도 크기는 시간이 지날수록 커진다.", 0, 27.0, "C03"),
      ("ㄴ", "F 가 작용하는 동안 물체의 속력은 일정하다.", 0, 18.0, "C03"),
      ("ㄷ", "F 를 제거하면 물체는 그 순간의 속도로 등속 운동한다.", 1, 31.0, "C02")], 64.0),
    (2, UNIT, "stack", "그림과 같이 수평면 위에 물체 A 를 놓고 그 위에 물체 B 를 올려 두었다. A, B 는 정지해 있다.",
     [("ㄱ", "A 가 B 를 떠받치는 힘과 B 에 작용하는 중력은 작용 반작용 관계이다.", 0, 47.0, "C04"),
      ("ㄴ", "B 에 작용하는 알짜힘은 0 이다.", 1, 9.0, "C01"),
      ("ㄷ", "수평면이 A 를 떠받치는 힘의 크기는 A 의 무게보다 크다.", 1, 28.0, "C01")], 41.0),
    (3, UNIT, "pulley", "그림과 같이 질량이 각각 m, 2m 인 물체 A, B 를 실로 연결하고 도르래에 걸었더니 A, B 가 함께 운동한다. 마찰은 무시한다.",
     [("ㄱ", "실이 A 를 당기는 힘의 크기는 B 의 무게와 같다.", 0, 44.0, "C05"),
      ("ㄴ", "A 와 B 의 가속도 크기는 같다.", 1, 11.0, "C05"),
      ("ㄷ", "B 의 질량만 커지면 A 의 가속도 크기도 커진다.", 1, 26.0, "C03")], 38.0),
    (4, UNIT, "push", "그림과 같이 학생이 벽을 손으로 밀고 있다. 학생과 벽은 정지해 있다.",
     [("ㄱ", "손이 벽을 미는 힘과 벽이 손을 미는 힘의 크기는 같다.", 1, 8.0, "C04"),
      ("ㄴ", "손이 벽을 미는 힘과 벽이 손을 미는 힘은 힘의 평형 관계이다.", 0, 39.0, "C04"),
      ("ㄷ", "학생에게 작용하는 알짜힘은 0 이 아니다.", 0, 15.0, "C01")], 52.0),
    (5, UNIT, "graph", "그림은 직선 위에서 운동하는 물체의 속도를 시간에 따라 나타낸 것이다.",
     [("ㄱ", "0 초부터 2 초까지 물체에 작용하는 알짜힘의 방향은 운동 방향과 같다.", 1, 21.0, "C06"),
      ("ㄴ", "2 초부터 4 초까지 물체에 작용하는 알짜힘은 0 이다.", 1, 24.0, "C02"),
      ("ㄷ", "4 초부터 6 초까지 물체의 가속도 크기는 0 초부터 2 초까지보다 작다.", 1, 36.0, "C06")], 33.0),
    (6, UNIT, "block", "그림과 같이 수평면 위의 물체에 서로 반대 방향으로 크기가 5 N, 3 N 인 두 힘이 작용한다. 물체의 질량은 2 kg 이고 마찰은 무시한다.",
     [("ㄱ", "물체에 작용하는 알짜힘의 크기는 2 N 이다.", 1, 10.0, "C01"),
      ("ㄴ", "물체의 가속도 크기는 1 m/s² 이다.", 1, 22.0, "C03"),
      ("ㄷ", "3 N 의 힘을 제거하면 가속도 크기는 처음의 2 배가 된다.", 0, 41.0, "C03")], 47.0),
    (7, UNIT, "pulley", "그림과 같이 수평면 위의 물체 A 와 매달린 물체 B 를 실로 연결했더니 A, B 가 함께 운동한다. 마찰은 무시한다.",
     [("ㄱ", "A 와 B 를 한 물체로 보면 알짜힘은 B 의 무게와 같다.", 1, 33.0, "C05"),
      ("ㄴ", "실이 B 를 당기는 힘의 크기는 B 의 무게보다 작다.", 1, 29.0, "C05"),
      ("ㄷ", "A 의 질량이 커지면 실이 A 를 당기는 힘의 크기도 커진다.", 1, 52.0, "C05")], 27.0),
    (8, UNIT, "stack", "그림과 같이 엘리베이터 바닥에 놓인 물체가 엘리베이터와 함께 위쪽으로 일정한 속력으로 움직인다.",
     [("ㄱ", "물체에 작용하는 알짜힘은 0 이다.", 1, 19.0, "C02"),
      ("ㄴ", "바닥이 물체를 떠받치는 힘의 크기는 물체의 무게보다 크다.", 0, 46.0, "C01"),
      ("ㄷ", "물체가 바닥을 누르는 힘의 반작용은 지구가 물체를 당기는 힘이다.", 0, 35.0, "C04")], 44.0),
    (9, UNIT, "block", "그림과 같이 마찰이 없는 수평면 위에 정지해 있던 질량 2 kg 인 물체에 수평 방향으로 6 N 의 힘이 계속 작용한다. 2 초 후 물체의 속력은?",
     (ANSWER_LABEL, ["3 m/s", "4 m/s", "6 m/s", "8 m/s", "12 m/s"], 3, "C03"), 58.0),
    (10, OTHER_UNIT, "collide", "그림과 같이 수평면에서 질량 1 kg 인 물체가 4 m/s 의 속력으로 운동하여 정지해 있던 질량 1 kg 인 물체와 충돌한 뒤 두 물체가 붙어서 함께 움직였다. 충돌 후 속력은?",
     (ANSWER_LABEL, ["1 m/s", "2 m/s", "3 m/s", "4 m/s", "8 m/s"], 2, None), 61.0),
]

CONCEPTS = ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08"]

W = 1000                          # 이미지 폭 (px). 높이는 내용에 맞춘다
PAD = 40


def _font(size: int) -> ImageFont.ImageFont:
    for f in (r"C:\Windows\Fonts\malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
              "/System/Library/Fonts/AppleSDGothicNeo.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split(" "):
        nxt = f"{cur} {word}".strip()
        if draw.textlength(nxt, font=font) <= width:
            cur = nxt
        else:
            lines.append(cur)
            cur = word
    return lines + [cur] if cur else lines


def _figure(draw: ImageDraw.ImageDraw, kind: str, top: int, font) -> int:
    """그림 하나를 그리고 바닥 y 를 돌려준다. 높이 220."""
    y0, cx = top, W // 2
    ground = y0 + 170
    line = dict(fill="black", width=3)
    if kind in ("block", "push", "collide", "stack"):
        draw.line([(PAD + 60, ground), (W - PAD - 60, ground)], **line)
    if kind == "block":
        draw.rectangle([cx - 60, ground - 90, cx + 60, ground], outline="black", width=3)
        draw.line([(cx + 60, ground - 45), (cx + 200, ground - 45)], **line)
        draw.polygon([(cx + 200, ground - 55), (cx + 220, ground - 45), (cx + 200, ground - 35)], fill="black")
        draw.text((cx + 120, ground - 85), "F", font=font, fill="black")
    elif kind == "stack":
        draw.rectangle([cx - 90, ground - 70, cx + 90, ground], outline="black", width=3)
        draw.rectangle([cx - 50, ground - 140, cx + 50, ground - 70], outline="black", width=3)
        draw.text((cx - 10, ground - 55), "A", font=font, fill="black")
        draw.text((cx - 10, ground - 125), "B", font=font, fill="black")
    elif kind == "pulley":
        table = y0 + 80
        draw.line([(PAD + 80, table), (cx + 120, table)], **line)
        draw.rectangle([cx - 140, table - 60, cx - 40, table], outline="black", width=3)
        draw.ellipse([cx + 105, table - 15, cx + 135, table + 15], outline="black", width=3)
        draw.line([(cx - 40, table - 30), (cx + 120, table - 30)], fill="black", width=2)
        draw.line([(cx + 135, table), (cx + 135, y0 + 140)], fill="black", width=2)
        draw.rectangle([cx + 105, y0 + 140, cx + 165, y0 + 200], outline="black", width=3)
        draw.text((cx - 100, table - 50), "A", font=font, fill="black")
        draw.text((cx + 125, y0 + 155), "B", font=font, fill="black")
    elif kind == "push":
        draw.line([(cx + 120, y0 + 10), (cx + 120, ground)], fill="black", width=6)
        draw.ellipse([cx - 100, y0 + 20, cx - 60, y0 + 60], outline="black", width=3)
        draw.line([(cx - 80, y0 + 60), (cx - 80, ground - 50)], **line)
        draw.line([(cx - 80, y0 + 80), (cx + 117, y0 + 80)], **line)
        draw.line([(cx - 80, ground - 50), (cx - 110, ground)], **line)
        draw.line([(cx - 80, ground - 50), (cx - 50, ground)], **line)
    elif kind == "collide":
        draw.rectangle([cx - 220, ground - 70, cx - 140, ground], outline="black", width=3)
        draw.rectangle([cx + 40, ground - 70, cx + 120, ground], outline="black", width=3)
        draw.line([(cx - 130, ground - 35), (cx - 30, ground - 35)], **line)
        draw.polygon([(cx - 30, ground - 45), (cx - 10, ground - 35), (cx - 30, ground - 25)], fill="black")
        draw.text((cx - 120, ground - 75), "4 m/s", font=font, fill="black")
    elif kind == "graph":
        ox, oy = cx - 200, y0 + 190
        draw.line([(ox, oy), (ox + 420, oy)], **line)
        draw.line([(ox, oy), (ox, y0 + 10)], **line)
        pts = [(ox, oy), (ox + 120, oy - 140), (ox + 240, oy - 140), (ox + 360, oy - 70)]
        draw.line(pts, fill="black", width=3)
        for i, x in enumerate([0, 120, 240, 360]):
            draw.text((ox + x - 5, oy + 5), str(i * 2), font=font, fill="black")
        draw.text((ox + 430, oy - 15), "t(s)", font=font, fill="black")
        draw.text((ox - 30, y0), "v", font=font, fill="black")
    return y0 + 220


def draw_item(no: int, kind: str, stem: str, body) -> tuple[Image.Image, list[dict]]:
    """문항 이미지와 구역 박스(0~1000)를 만든다. 박스 형식은 offline/regions.py 가 읽는 것과 같다."""
    big, small = _font(30), _font(26)
    canvas = Image.new("RGB", (W, 1600), "white")
    d = ImageDraw.Draw(canvas)
    blocks: list[tuple[str, tuple[int, int, int, int], str | None]] = []   # (label, (y0, x0, y1, x1) px, tag)
    y = PAD
    text_top = y
    for line in _wrap(d, f"{no}. {stem}", big, W - 2 * PAD):
        d.text((PAD, y), line, font=big, fill="black")
        y += 42
    blocks.append(("text", (text_top, PAD, y, W - PAD), None))
    y += 10
    fig_top = y
    y = _figure(d, kind, y, small)
    blocks.append(("figure", (fig_top, PAD + 40, y, W - PAD - 40), None))
    y += 20
    if isinstance(body, list):                                   # 보기형
        d.text((PAD, y), "이에 대한 설명으로 옳은 것만을 <보기>에서 있는 대로 고른 것은?", font=big, fill="black")
        y += 56
        box_top = y
        y += 15
        for lab, s, *_ in body:
            top = y
            for j, line in enumerate(_wrap(d, s, small, W - 4 * PAD - 40)):
                if j == 0:
                    d.text((PAD + 20, y), f"{lab}.", font=small, fill="black")
                d.text((PAD + 60, y), line, font=small, fill="black")
                y += 34
            y += 16
            blocks.append(("statement", (top, PAD + 15, y - 12, W - PAD - 15), lab))
        d.rectangle([PAD, box_top, W - PAD, y], outline="black", width=2)
        y += 25
        opts = "    ".join(f"{CIRCLED[i]} {', '.join(c)}" for i, c in enumerate(COMBOS))
    else:                                                         # 계산형
        _, values, _, _ = body
        opts = "    ".join(f"{CIRCLED[i]} {v}" for i, v in enumerate(values))
    top = y
    d.text((PAD + 20, y), opts, font=big, fill="black")
    y += 48
    blocks.append(("options", (top, PAD, y, W - PAD), None))
    h = y + PAD
    img = canvas.crop((0, 0, W, h))
    boxes = [{"label": lab, "box_2d": [round(y0 * 1000 / h), round(x0 * 1000 / W), round(y1 * 1000 / h), round(x1 * 1000 / W)],
              "tag": tag, "conf": 1.0} for lab, (y0, x0, y1, x1), tag in blocks]
    return img, boxes


PHYSICS_SCHEMA = """
CREATE TABLE items (
    item_key TEXT PRIMARY KEY, subject TEXT NOT NULL, year INTEGER, mon INTEGER, number INTEGER,
    source TEXT, source_type TEXT, cat_1 TEXT, leaf TEXT, is_mechanics INTEGER,
    answer INTEGER, correct_rate REAL, no_response REAL, item_format TEXT, intent TEXT,
    image_path TEXT, stem TEXT, has_diagram INTEGER, diagram_desc TEXT, prompt_hash TEXT, vlm_model TEXT
);
CREATE TABLE statements (
    item_key TEXT NOT NULL, label TEXT NOT NULL, text TEXT, is_true INTEGER, error_rate REAL,
    PRIMARY KEY (item_key, label), FOREIGN KEY (item_key) REFERENCES items (item_key)
);
CREATE TABLE choices (
    item_key TEXT NOT NULL, choice_no INTEGER NOT NULL, picks TEXT, text TEXT, rate REAL, is_answer INTEGER,
    PRIMARY KEY (item_key, choice_no), FOREIGN KEY (item_key) REFERENCES items (item_key)
);
"""

CONCEPT_MAP_SCHEMA = """
CREATE TABLE statement_concept (
    item_key TEXT NOT NULL, label TEXT NOT NULL, concept TEXT, note TEXT,
    status TEXT DEFAULT 'human',          -- human = 사람이 붙이거나 확인함 · ai = AI 제안을 받아들임
    ai_concept TEXT, ai_note TEXT,        -- AI 제안 (확인 전에는 진단에 안 쓴다)
    PRIMARY KEY (item_key, label)
);
CREATE TABLE item_flags (item_key TEXT PRIMARY KEY, item_type TEXT, note TEXT);
CREATE TABLE statement_concept_alt (
    item_key TEXT NOT NULL, label TEXT NOT NULL, concept TEXT NOT NULL, note TEXT,
    PRIMARY KEY (item_key, label)
);
"""


def _fresh_db(path, schema: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        p = path.with_name(path.name + suffix)
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(schema)
    return conn


def _unit_vec(rng: np.random.Generator, concepts: list[str], dim: int, noise: float) -> np.ndarray:
    """개념 one-hot 합 + 잡음 → 같은 개념을 가진 문항끼리 가깝게. 실제 특징 추출 모델 대신 쓰는 데모 벡터."""
    v = rng.normal(0, noise, dim)
    for c in concepts:
        v[CONCEPTS.index(c)] += 1.0
    return (v / np.linalg.norm(v)).astype(np.float32)


def main() -> int:
    physics_path = BUILD / SUBJECT / "physics.db"
    concept_path = DATA / SUBJECT / "concept_map.db"
    img_dir = DATA / SUBJECT / "images"
    region_dir = BUILD / SUBJECT / "regions"
    embed = BUILD / SUBJECT / "embed"
    for d in (img_dir, region_dir, embed):
        d.mkdir(parents=True, exist_ok=True)

    pconn = _fresh_db(physics_path, PHYSICS_SCHEMA)
    cconn = _fresh_db(concept_path, CONCEPT_MAP_SCHEMA)
    rng = np.random.default_rng(7)
    fig_rows, fig_vecs, txt_rows, txt_vecs = [], [], [], []

    for no, unit, kind, stem, body, correct in ITEMS:
        key = f"demo_{no:02d}"
        img, boxes = draw_item(no, kind, stem, body)
        img_rel = (img_dir / f"{key}.png").relative_to(ROOT).as_posix()
        img.save(ROOT / img_rel)
        (region_dir / f"{key}.json").write_text(json.dumps(boxes, ensure_ascii=False, indent=1), encoding="utf-8")

        if isinstance(body, list):
            truth = tuple(lab for lab, _, t, _, _ in body if t)
            answer = COMBOS.index(truth) + 1
            fmt, concepts = "statements", sorted({c for *_, c in body})
            for lab, text, t, err, c in body:
                pconn.execute("INSERT INTO statements VALUES (?,?,?,?,?)", (key, lab, text, t, err))
                cconn.execute("INSERT INTO statement_concept (item_key, label, concept) VALUES (?,?,?)", (key, lab, c))
            choice_rows = [(i + 1, ",".join(c), None) for i, c in enumerate(COMBOS)]
        else:
            _, values, answer, c = body
            fmt, concepts = "numeric", [c] if c else []
            pconn.execute("INSERT INTO statements VALUES (?,?,?,?,?)", (key, ANSWER_LABEL, None, 1, round(100 - correct, 1)))
            if c:
                cconn.execute("INSERT INTO statement_concept (item_key, label, concept) VALUES (?,?,?)", (key, ANSWER_LABEL, c))
            choice_rows = [(i + 1, None, v) for i, v in enumerate(values)]
        # 오답 선지 비율은 (100 - 정답률) 을 나머지 넷에 고르게
        for cno, picks, text in choice_rows:
            rate = correct if cno == answer else round((100 - correct) / 4, 1)
            pconn.execute("INSERT INTO choices VALUES (?,?,?,?,?,?)", (key, cno, picks, text, rate, int(cno == answer)))
        pconn.execute("""INSERT INTO items (item_key, subject, year, mon, number, source, source_type, cat_1, is_mechanics,
                         answer, correct_rate, no_response, item_format, image_path, stem, has_diagram, diagram_desc)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (key, SUBJECT, 2026, 1, no, "demo", "demo", unit, 1, answer, correct, 0.0, fmt, img_rel, stem, 1, kind))

        fig = next(b for b in boxes if b["label"] == "figure")
        fig_rows.append({"item_key": key, "tag": None, "box": fig["box_2d"], "cat_1": unit})
        fig_vecs.append(_unit_vec(rng, concepts, 32, 0.6))
        txt_rows.append({"item_key": key, "cat_1": unit})
        txt_vecs.append(_unit_vec(rng, concepts, 32, 0.4))

    pconn.commit(); pconn.close()
    cconn.commit(); cconn.close()
    np.save(embed / "figures.npy", np.stack(fig_vecs))
    np.save(embed / "texts.npy", np.stack(txt_vecs))
    (embed / "figures.json").write_text(json.dumps(fig_rows, ensure_ascii=False), encoding="utf-8")
    (embed / "texts.json").write_text(json.dumps(txt_rows, ensure_ascii=False), encoding="utf-8")
    (embed / "meta.json").write_text(json.dumps({"figures": {"model": "demo", "n": len(fig_rows)},
                                                 "texts": {"model": "demo", "n": len(txt_rows)}}, indent=1), encoding="utf-8")
    print(f"demo: {len(ITEMS)} items")
    for p in (physics_path, concept_path, img_dir, region_dir, embed):
        print("  ", p.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
