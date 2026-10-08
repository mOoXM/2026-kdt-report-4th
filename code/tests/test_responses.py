"""
responses.py — 풀이 한 번이 세 표에 설계대로 들어가는지. tmp_path 에 responses.db (v5). data/ 불필요.
"""
import sqlite3

import pytest
from pathlib import Path

from physics_lab import db
from physics_lab import responses as R

T = "2026-09-29T04:00:00Z"
CHOICES = {"ph1_x_01": [(1, {"ㄱ"}), (2, {"ㄷ"}), (3, {"ㄱ", "ㄴ"}), (4, {"ㄴ", "ㄷ"}), (5, {"ㄱ", "ㄴ", "ㄷ"})]}


@pytest.fixture
def conn(tmp_path):
    c = db.connect(db.init_responses_db(path=tmp_path / "responses.db"))
    R.ensure_student(c, "u_s", now=T)
    c.commit()
    yield c
    c.close()


def _answers():
    return [
        {"item_key": "ph1_x_01", "label": "ㄱ", "judged_true": True, "answered_at": T},
        {"item_key": "ph1_x_01", "label": "ㄴ", "judged_true": True},
        {"item_key": "ph1_x_01", "label": "ㄷ", "judged_true": False, "changed_cnt": 2},
        {"item_key": "ph1_x_02", "label": "ㄱ", "judged_true": False},
        {"item_key": "ph1_x_02", "label": "ㄴ", "unsure": True},                      # 모르겠다
        {"item_key": "ph1_x_02", "label": "ㄷ", "judged_true": None},                 # 무응답
    ]


# ---------------------------------------------------------------- derive_choice
def test_derive_choice():
    ch = CHOICES["ph1_x_01"]
    assert R.derive_choice(ch, {"ㄱ": True, "ㄴ": True, "ㄷ": False}) == (3, "derived")
    assert R.derive_choice(ch, {"ㄱ": False, "ㄴ": False, "ㄷ": True}) == (2, "derived")
    assert R.derive_choice(ch, {"ㄱ": False, "ㄴ": True, "ㄷ": False}) == (None, "derived")   # 'ㄴ' 만 → 대응 선지 없음
    assert R.derive_choice(ch, {"ㄱ": True, "ㄴ": None, "ㄷ": False}) == (None, None)        # 판단 안 한 보기
    assert R.derive_choice(None, {"ㄱ": True}) == (None, None)                                 # choices 없음
    assert R.derive_choice(ch, {}) == (None, None)


# ---------------------------------------------------------------- save_attempt
def test_save_practice_attempt(conn):
    with conn:
        aid = R.save_attempt(conn, student_id="u_s", purpose="practice", answers=_answers(),
                             choices=CHOICES, items={"ph1_x_01": {"elapsed_ms": 4200, "shown_at": T}},
                             client={"device": "ipad", "viewport": "1180x820", "orientation": "landscape"},
                             started_at="2026-09-29T03:50:00Z", now=T)
    assert aid.startswith("a_")
    a = conn.execute("SELECT * FROM attempts WHERE attempt_id=?", (aid,)).fetchone()
    assert (a["purpose"], a["exam_set_id"], a["device"], a["orientation"], a["started_at"], a["finished_at"]) == \
        ("practice", None, "ipad", "landscape", "2026-09-29T03:50:00Z", T)
    rs = conn.execute("SELECT * FROM responses WHERE attempt_id=? ORDER BY seq", (aid,)).fetchall()
    assert [(r["item_key"], r["seq"], r["source"], r["input_format"], r["capture_method"]) for r in rs] == \
        [("ph1_x_01", 1, "self_selected", "per_statement", "app"), ("ph1_x_02", 2, "self_selected", "per_statement", "app")]
    assert (rs[0]["choice_no"], rs[0]["choice_source"], rs[0]["elapsed_ms"], rs[0]["shown_at"]) == (3, "derived", 4200, T)
    assert (rs[1]["choice_no"], rs[1]["choice_source"], rs[1]["elapsed_ms"]) == (None, None, None)   # 모르겠다가 있어 계산 안 함
    sts = conn.execute("SELECT item_key, label, judged_true, unsure, changed_cnt FROM statement_responses "
                       "WHERE attempt_id=? ORDER BY item_key, label", (aid,)).fetchall()
    assert [tuple(s) for s in sts] == [
        ("ph1_x_01", "ㄱ", 1, 0, 0), ("ph1_x_01", "ㄴ", 1, 0, 0), ("ph1_x_01", "ㄷ", 0, 0, 2),
        ("ph1_x_02", "ㄱ", 0, 0, 0), ("ph1_x_02", "ㄴ", None, 1, 0), ("ph1_x_02", "ㄷ", None, 0, 0)]
    got = R.load_attempt(conn, aid)
    assert got["attempt"]["attempt_id"] == aid and len(got["items"]) == 2 and len(got["items"][0]["statements"]) == 3
    assert R.load_attempt(conn, "a_none") is None
    lst = R.list_attempts(conn, "u_s")
    assert len(lst) == 1 and lst[0]["n_items"] == 2 and lst[0]["purpose"] == "practice"


def test_exam_requires_exam_set_and_all_or_nothing(conn):
    with pytest.raises(R.BadAnswer, match="exam_set_id"):
        with conn:
            R.save_attempt(conn, student_id="u_s", purpose="exam", answers=_answers(), now=T)
    conn.execute("INSERT INTO exam_sets (exam_set_id, class_id, title, created_at) VALUES ('e1','c1','9월',?)", (T,))
    conn.commit()
    with conn:
        aid = R.save_attempt(conn, student_id="u_s", purpose="exam", exam_set_id="e1", answers=_answers(), now=T)
    r = conn.execute("SELECT source FROM responses WHERE attempt_id=?", (aid,)).fetchone()
    assert r["source"] == "exam_set"                                                          # purpose 로 정해진 source
    # 잘못된 보기가 섞이면 (같은 보기 두 번) 전부 안 들어간다
    bad = _answers() + [{"item_key": "ph1_x_01", "label": "ㄱ", "judged_true": False}]
    with pytest.raises(R.BadAnswer, match="두 번"):
        with conn:
            R.save_attempt(conn, student_id="u_s", purpose="practice", answers=bad, now=T)
    assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


def test_bad_answers(conn):
    with pytest.raises(R.BadAnswer, match="동시에"):
        R.save_attempt(conn, student_id="u_s", purpose="practice",
                       answers=[{"item_key": "k", "label": "ㄱ", "judged_true": True, "unsure": True}], now=T)
    with pytest.raises(R.BadAnswer, match="비었다"):
        R.save_attempt(conn, student_id="u_s", purpose="practice", answers=[], now=T)
    with pytest.raises(R.BadAnswer, match="purpose"):
        R.save_attempt(conn, student_id="u_s", purpose="quiz", answers=_answers(), now=T)
    with pytest.raises(R.BadAnswer, match="반응시간"):
        R.save_attempt(conn, student_id="u_s", purpose="practice", answers=_answers(), capture_method="photo",
                       items={"ph1_x_01": {"elapsed_ms": 10}}, now=T)
    with pytest.raises(sqlite3.IntegrityError):                                                 # students 에 없는 학생 → FK
        R.save_attempt(conn, student_id="u_none", purpose="practice", answers=_answers(), now=T)
    conn.rollback()


def test_ensure_student_is_idempotent(conn):
    with conn:
        R.ensure_student(conn, "u_s", now=T)
        R.ensure_student(conn, "u_t", consent=1, now=T)
    rows = conn.execute("SELECT student_id, consent FROM students ORDER BY 1").fetchall()
    assert [tuple(r) for r in rows] == [("u_s", 0), ("u_t", 1)]


# ---------------------------------------------------------------- v5: 선지 · 단답 형식
TEXTS = {"ph1_n_01": {1: "2 kg", 2: "4 kg", 3: "6 kg", 4: "8 kg", 5: "10 kg"},
         "ph1_n_02": {1: "(5/2)L", 2: "3L", 3: "(7/2)L", 4: "4L", 5: "(9/2)L"}}


def test_normalize_and_derive_short():
    assert R.normalize_answer(" 4 kg ") == "4kg"
    assert R.normalize_answer("(5/2) L") == R.normalize_answer("5/2L") == "5/2l"
    assert R.normalize_answer("３ × L") == "3*l"
    assert R.derive_short(TEXTS["ph1_n_01"], "4kg") == (2, "derived")
    assert R.derive_short(TEXTS["ph1_n_02"], "5/2 L") == (1, "derived")
    assert R.derive_short(TEXTS["ph1_n_01"], "5 kg") == (None, "derived")       # 선지에 없는 오답 — 계산은 했다
    assert R.derive_short(TEXTS["ph1_n_01"], "") == (None, None)
    assert R.derive_short(None, "4 kg") == (None, None)


def test_save_choice_and_short(conn):
    answers = [
        {"item_key": "ph1_x_01", "choice_no": 3, "answered_at": T},               # 실전: 보기형 문항을 선지로
        {"item_key": "ph1_n_01", "answer_text": "4 kg"},                           # 진단: 계산형을 단답으로
        {"item_key": "ph1_n_02", "answer_text": "5 L"},                            # 선지에 없는 값
        {"item_key": "ph1_n_03", "answer_text": ""},                               # 단답 무응답
    ]
    with conn:
        aid = R.save_attempt(conn, student_id="u_s", purpose="practice", answers=answers, choice_texts=TEXTS, now=T)
    got = {r["item_key"]: dict(r) for r in conn.execute("SELECT * FROM responses WHERE attempt_id = ?", (aid,))}
    assert got["ph1_x_01"]["input_format"] == "choice"
    assert (got["ph1_x_01"]["choice_no"], got["ph1_x_01"]["choice_source"]) == (3, "given")
    assert got["ph1_x_01"]["answer_text"] is None and got["ph1_x_01"]["answered_at"] == T
    assert got["ph1_n_01"]["input_format"] == "short"
    assert (got["ph1_n_01"]["choice_no"], got["ph1_n_01"]["choice_source"], got["ph1_n_01"]["answer_text"]) == (2, "derived", "4 kg")
    assert (got["ph1_n_02"]["choice_no"], got["ph1_n_02"]["choice_source"], got["ph1_n_02"]["answer_text"]) == (None, "derived", "5 L")
    assert (got["ph1_n_03"]["choice_no"], got["ph1_n_03"]["choice_source"], got["ph1_n_03"]["answer_text"]) == (None, None, None)
    # 선지·단답 문항은 보기 행이 없다
    assert conn.execute("SELECT COUNT(*) FROM statement_responses WHERE attempt_id = ?", (aid,)).fetchone()[0] == 0
    assert [i["item_key"] for i in R.load_attempt(conn, aid)["items"]] == ["ph1_x_01", "ph1_n_01", "ph1_n_02", "ph1_n_03"]


def test_mixed_formats_rejected(conn):
    with pytest.raises(R.BadAnswer, match="두 형식"):
        R.save_attempt(conn, student_id="u_s", purpose="practice", now=T, answers=[
            {"item_key": "ph1_x_01", "label": "ㄱ", "judged_true": True},
            {"item_key": "ph1_x_01", "choice_no": 1}])
    with pytest.raises(R.BadAnswer, match="1~5"):
        R.save_attempt(conn, student_id="u_s", purpose="practice", now=T, answers=[{"item_key": "ph1_x_01", "choice_no": 7}])
    with pytest.raises(R.BadAnswer, match="두 번"):
        R.save_attempt(conn, student_id="u_s", purpose="practice", now=T, answers=[
            {"item_key": "ph1_n_01", "answer_text": "4 kg"}, {"item_key": "ph1_n_01", "answer_text": "6 kg"}])
    with pytest.raises(R.BadAnswer, match="하나는"):
        R.save_attempt(conn, student_id="u_s", purpose="practice", now=T, answers=[{"item_key": "ph1_x_01"}])


def test_schema_v5_columns(conn):
    assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "6"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(exam_sets)")}
    assert "mode" in cols and {"opened_at", "closed_at"} <= cols                   # v6
    with pytest.raises(sqlite3.IntegrityError):                                   # 모드 값은 둘뿐
        conn.execute("INSERT INTO exam_sets (exam_set_id, class_id, title, created_at, mode) VALUES ('e', 'c', 't', ?, 'x')", (T,))
    with pytest.raises(sqlite3.IntegrityError):                                   # 단답값은 short 에서만
        conn.execute("INSERT INTO attempts (attempt_id, student_id, purpose, started_at) VALUES ('a', 'u_s', 'practice', ?)", (T,))
        conn.execute("INSERT INTO responses (attempt_id, item_key, seq, source, input_format, answer_text) "
                     "VALUES ('a', 'k', 1, 'self_selected', 'choice', '4 kg')")


def test_migrate_v5_to_v6(tmp_path):
    """v5 로 만든(열이 없는) DB 를 init_responses_db 가 ALTER 로 맞춘다. 두 번 불러도 조용하다."""
    import sqlite3 as _sq
    from physics_lab import db as _db
    p = tmp_path / "old.db"
    sql = (Path(_db.__file__).parent / "responses_schema.sql").read_text(encoding="utf-8")
    sql = sql.replace("    opened_at       TEXT,", "").replace("    closed_at       TEXT,", "").replace("'6', '2026-10-07T00:00:00Z'", "'5', '2026-10-01T00:00:00Z'")
    c = _sq.connect(p); c.executescript(sql); c.close()
    assert _db.migrate_responses_db(p) == ["exam_sets.opened_at", "exam_sets.closed_at"]
    assert _db.migrate_responses_db(p) == []
    _db.init_responses_db(path=p)
    c = _db.connect(p)
    assert {"opened_at", "closed_at"} <= {r[1] for r in c.execute("PRAGMA table_info(exam_sets)")}
    assert c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "6"
    c.close()
