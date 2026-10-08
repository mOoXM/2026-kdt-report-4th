"""
강사 흐름 끝까지 (serve/teacher.py + student.py 시험 길 + dev.fill).
작은 FastAPI 앱에 auth·student·teacher·dev 를 달고, tmp 에 가짜 physics.db·concept_map.db(문항 3개)와 빈 accounts·responses 를 둔다.
data/ 가 없는 기계(Cowork VM)에서도 돈다.

흐름: 강사 가입 → 반 → 명단 3명(키·pin) → 문항 은행 → 시험지(진단 모드) → 구성 중엔 학생에게 안 보임 → 열기 →
      학생 로그인 → 열린 시험 → 문항 → 제출(결과 숨김) → 두 번 제출 409 → 강사 결과 표 → 학생 상세 → 닫기 → 원장 overview.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from physics_lab import db
from physics_lab.serve import auth, dev, student, teacher

ITEMS = [
    # item_key, cat, format, answer, statements [(label, is_true, error_rate, concept)], choices [(no, picks, text, is_answer)]
    ("t_2026_01_05", "뉴턴 법칙", "statements", 3,
     [("ㄱ", 1, 20.0, "C01"), ("ㄴ", 0, 35.0, "C02,C03"), ("ㄷ", 1, 50.0, "C03")],
     [(1, "ㄱ", None, 0), (2, "ㄴ", None, 0), (3, "ㄱ,ㄷ", None, 1), (4, "ㄴ,ㄷ", None, 0), (5, "ㄱ,ㄴ,ㄷ", None, 0)]),
    ("t_2026_01_12", "뉴턴 법칙", "statements", 1,
     [("ㄱ", 1, 30.0, "C04"), ("ㄴ", 1, 40.0, "C05"), ("ㄷ", 0, 45.0, "C06")],
     [(1, "ㄱ,ㄴ", None, 1), (2, "ㄱ", None, 0), (3, "ㄷ", None, 0), (4, "ㄴ,ㄷ", None, 0), (5, "ㄱ,ㄴ,ㄷ", None, 0)]),
    ("t_2026_01_18", "뉴턴 법칙", "numeric", 2,
     [(db.ANSWER_LABEL, 1, 60.0, "C05,C03")],
     [(1, None, "2 kg", 0), (2, None, "4 kg", 1), (3, None, "6 kg", 0), (4, None, "8 kg", 0), (5, None, "10 kg", 0)]),
]


def _fake_physics(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE items (item_key TEXT PRIMARY KEY, subject TEXT, year INT, mon INT, number INT, cat_1 TEXT, leaf TEXT,
                            answer INT, correct_rate REAL, item_format TEXT, image_path TEXT, stem TEXT, diagram_desc TEXT);
        CREATE TABLE statements (item_key TEXT, label TEXT, text TEXT, is_true INT, error_rate REAL);
        CREATE TABLE choices (item_key TEXT, choice_no INT, picks TEXT, text TEXT, rate REAL, is_answer INT);
    """)
    for key, cat, fmt, ans, sts, chs in ITEMS:
        y, m, n = key.split("_")[1:]
        conn.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (key, "ph1", int(y), int(m), int(n), cat, None, ans, 55.0, fmt, None, "stem", None))
        for lab, t, er, _concept in sts:
            conn.execute("INSERT INTO statements VALUES (?,?,?,?,?)", (key, lab, None, t, er))
        for no, picks, text, isa in chs:
            conn.execute("INSERT INTO choices VALUES (?,?,?,?,?,?)", (key, no, picks, text, 20.0, isa))
    conn.commit(); conn.close()


def _fake_concept_map(path):
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE statement_concept (item_key TEXT, label TEXT, concept TEXT, note TEXT, PRIMARY KEY (item_key, label));")
    for key, _c, _f, _a, sts, _ch in ITEMS:
        for lab, _t, _e, concept in sts:
            conn.execute("INSERT INTO statement_concept VALUES (?,?,?,NULL)", (key, lab, concept))
    conn.commit(); conn.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    phys, qm = tmp_path / "physics.db", tmp_path / "concept_map.db"
    _fake_physics(phys); _fake_concept_map(qm)
    for mod in (student, teacher):
        monkeypatch.setattr(mod, "PHYSICS_DB", phys)
        monkeypatch.setattr(mod, "CONCEPT_MAP_DB", qm)
    monkeypatch.setattr(student, "_engine", None)
    monkeypatch.setattr(student, "regions_of", lambda key, subject="ph1": None)
    app = FastAPI()
    auth.install(app); student.install(app); teacher.install(app)
    acc = db.init_accounts_db(path=tmp_path / "accounts.db")
    rdb = db.init_responses_db(path=tmp_path / "responses.db")
    app.dependency_overrides[auth.accounts_conn] = lambda: (yield from auth.open_conn(acc))
    app.dependency_overrides[student.responses_conn] = lambda: (yield from auth.open_conn(rdb))
    return TestClient(app)


def _signup(c, email, org=None, invite=None):
    r = c.post("/api/auth/signup", json={"email": email, "password": "pw1234", "display_name": email.split("@")[0],
                                         "org_name": org, "invite": invite})
    assert r.status_code == 200, r.text
    return r.json()


def test_teacher_flow_end_to_end(client, tmp_path):
    c = client
    me = _signup(c, "owner@x.kr", org="테스트 학원")
    # 학원 승인은 운영자 명령 — 테스트는 직접
    conn = db.connect(tmp_path / "accounts.db"); conn.execute("UPDATE orgs SET status='active'"); conn.commit(); conn.close()

    home = c.get("/api/teacher/home").json()
    assert home["org"]["name"] == "테스트 학원" and home["org"]["role"] == "owner" and home["classes"] == []

    cid = c.post("/api/teacher/classes", json={"name": "화요일반"}).json()["class_id"]
    assert c.get("/api/teacher/home").json()["classes"][0]["todo"] == "명단을 올리세요"

    # 명단: 평문 pin 은 이 응답에만
    r = c.post(f"/api/teacher/classes/{cid}/students", json={"rows": [
        {"display_name": "김가", "school": "A고", "entry_year": 2025}, {"display_name": "이나"}, {"display_name": "박다", "phone": "010"}]})
    assert r.status_code == 200, r.text
    made = r.json()["students"]
    assert len(made) == 3 and all(len(s["login_key"]) == 6 and len(s["pin"]) == 4 for s in made)
    assert c.post(f"/api/teacher/classes/{cid}/students", json={"rows": [{"display_name": " "}]}).status_code == 400
    cls = c.get(f"/api/teacher/classes/{cid}").json()
    assert [m["display_name"] for m in cls["members"]] == ["김가", "박다", "이나"] and "pin" not in cls["members"][0]

    # 문항 은행
    bank = c.get("/api/teacher/bank").json()
    assert {it["item_key"] for it in bank["items"]} == {k for k, *_ in ITEMS} and bank["cats"] == ["뉴턴 법칙"]
    assert bank["items"][0]["concepts"] == ["C01", "C02", "C03"]

    # 시험지 (진단 모드) — 구성 중
    keys = [k for k, *_ in ITEMS]
    r = c.post(f"/api/teacher/classes/{cid}/exams", json={"title": "3월 1주 점검", "mode": "diagnostic", "item_keys": keys})
    assert r.status_code == 200, r.text
    eid = r.json()["exam_set_id"]
    ex = c.get(f"/api/teacher/exams/{eid}").json()
    assert ex["exam"]["status"] == "draft" and [i["input_format"] for i in ex["items"]] == ["per_statement", "per_statement", "short"]
    assert c.post(f"/api/teacher/classes/{cid}/exams", json={"title": "x", "mode": "diagnostic", "item_keys": []}).status_code == 400
    assert c.put(f"/api/teacher/exams/{eid}", json={"title": "3월 점검", "mode": "diagnostic", "item_keys": keys[:2]}).status_code == 200
    assert c.get(f"/api/teacher/exams/{eid}").json()["exam"]["n_items"] == 2
    assert c.put(f"/api/teacher/exams/{eid}", json={"title": "3월 점검", "mode": "diagnostic", "item_keys": keys}).status_code == 200

    # 학생 로그인 — 임시 비밀번호 → 바꿔야 함
    s = TestClient(c.app)
    st = made[0]
    r = s.post("/api/auth/login", json={"login_key": st["login_key"], "password": st["pin"]})
    assert r.status_code == 200 and r.json()["must_change"] is True
    assert s.get("/api/student/exams").status_code == 403                         # must_change 면 막힌다
    assert s.post("/api/auth/password", json={"old": st["pin"], "new": "mine1"}).status_code == 200
    assert s.get("/api/student/exams").json()["exams"] == []                       # 아직 구성 중 → 안 보임

    # 열기
    assert c.post(f"/api/teacher/exams/{eid}/open").json()["status"] == "open"
    assert c.put(f"/api/teacher/exams/{eid}", json={"title": "x", "mode": "diagnostic", "item_keys": keys}).status_code == 409
    assert c.delete(f"/api/teacher/exams/{eid}").status_code == 409
    exams = s.get("/api/student/exams").json()["exams"]
    assert len(exams) == 1 and exams[0]["submitted"] is False and exams[0]["n_items"] == 3

    # 문항 → 제출 (ㄱ 맞음, ㄴ 틀림, ㄷ 모르겠다 / 2번 전부 맞음 / 단답 정답)
    items = s.get(f"/api/student/exams/{eid}").json()["items"]
    assert [i["item_key"] for i in items] == keys and items[2]["format"] == "numeric" and items[2]["statements"] == []
    body = {"exam_set_id": eid, "answers": [
        {"item_key": keys[0], "label": "ㄱ", "answer": True}, {"item_key": keys[0], "label": "ㄴ", "answer": True},
        {"item_key": keys[0], "label": "ㄷ", "answer": None, "unsure": True},
        {"item_key": keys[1], "label": "ㄱ", "answer": True}, {"item_key": keys[1], "label": "ㄴ", "answer": True}, {"item_key": keys[1], "label": "ㄷ", "answer": False},
        {"item_key": keys[2], "answer_text": "4kg"}],
        "items": [{"item_key": k, "seq": i + 1, "elapsed_ms": 1000} for i, k in enumerate(keys)]}
    r = s.post("/api/student/submit", json=body)
    assert r.status_code == 200, r.text
    assert "sections" not in r.json() and r.json()["exam_set_id"] == eid        # 시험은 결과를 안 돌려준다
    assert s.post("/api/student/submit", json=body).status_code == 409           # 두 번 제출
    assert s.get(f"/api/student/exams/{eid}").status_code == 409
    assert s.get("/api/student/exams").json()["exams"][0]["submitted"] is True

    # 강사: 현황 · 결과 표
    ex = c.get(f"/api/teacher/exams/{eid}").json()
    assert sum(1 for x in ex["students"] if x["attempt_id"]) == 1
    res = c.get(f"/api/teacher/exams/{eid}/results").json()
    assert res["n_submitted"] == 1
    row = next(x for x in res["students"] if x["user_id"] == st["user_id"])
    cell0 = row["cells"][keys[0]]
    assert cell0["state"] == "wrong" and cell0["wrong"] == ["ㄴ"] and cell0["unsure"] == ["ㄷ"]
    assert row["cells"][keys[1]]["state"] == "ok" and row["cells"][keys[2]]["state"] == "ok"
    assert row["n_full"] == 2 and row["score"] == 67
    absent = next(x for x in res["students"] if x["user_id"] != st["user_id"])
    assert absent["cells"][keys[0]]["state"] == "absent" and absent["score"] is None
    col = next(i for i in res["items"] if i["item_key"] == keys[0])
    assert col["stmt_wrong_rate"] == {"ㄱ": 0, "ㄴ": 100, "ㄷ": None} and col["class_correct_rate"] == 0
    assert next(i for i in res["items"] if i["item_key"] == keys[2])["labels"] == [db.ANSWER_LABEL]

    # 학생 상세
    d = c.get(f"/api/teacher/exams/{eid}/students/{st['user_id']}").json()
    assert d["attempt"] and d["items"][0]["units"] == {"ㄱ": True, "ㄴ": False, "ㄷ": None}
    assert d["summary"]["answered"] == 6 and d["summary"]["correct"] == 5 and d["history"][0]["score"] == 67
    assert c.get(f"/api/teacher/exams/{eid}/students/{absent['user_id']}").json()["attempt"] is None

    # 닫기 → 학생에게 안 보임, 홈 카드 문구
    assert c.post(f"/api/teacher/exams/{eid}/close").json()["status"] == "closed"
    assert s.get("/api/student/exams").json()["exams"] == []
    assert "결과" in c.get("/api/teacher/home").json()["classes"][0]["todo"]

    # 원장 overview · 초대 → 강사 가입 → 그 강사는 담당 반만
    ov = c.get("/api/owner/overview").json()
    assert ov["n_students"] == 3 and len(ov["teachers"]) == 1 and ov["classes"][0]["last_exam"]["status"] == "closed"
    inv = c.post("/api/owner/invites", json={}).json()["invite"]
    t = TestClient(c.app)
    _signup(t, "t2@x.kr", invite=inv)
    assert t.get("/api/teacher/home").json()["classes"] == []
    assert t.get(f"/api/teacher/classes/{cid}").status_code == 403
    assert t.get("/api/owner/overview").status_code == 403


def test_realistic_mode_and_dev_fill(client, tmp_path, monkeypatch):
    c = client
    _signup(c, "owner@x.kr", org="테스트 학원")
    cid = c.post("/api/teacher/classes", json={"name": "반"}).json()["class_id"]
    c.post(f"/api/teacher/classes/{cid}/students", json={"rows": [{"display_name": f"학생{i}"} for i in range(5)]})
    keys = [k for k, *_ in ITEMS]
    eid = c.post(f"/api/teacher/classes/{cid}/exams", json={"title": "실전", "mode": "realistic", "item_keys": keys}).json()["exam_set_id"]
    assert all(i["input_format"] == "choice" for i in c.get(f"/api/teacher/exams/{eid}").json()["items"])
    c.post(f"/api/teacher/exams/{eid}/open")

    # dev.fill 은 PL_DEV 가 켜져 있고 개발 학원의 반일 때만 — 여기선 개발 학원이 아니므로 403
    monkeypatch.setenv("PL_DEV", "1")
    dev.install(c.app)
    assert c.post("/api/dev/fill", json={"exam_set_id": eid}).status_code == 403
    d = TestClient(c.app)                                       # 쿠키 없음 → 개발자 계정(운영자)으로
    seed = d.post("/api/dev/seed").json()
    dcid = seed["class_id"]
    deid = d.post(f"/api/teacher/classes/{dcid}/exams", json={"title": "개발", "mode": "diagnostic", "item_keys": keys}).json()["exam_set_id"]
    assert d.post("/api/dev/fill", json={"exam_set_id": deid}).status_code == 200          # 안 열어도 채울 수 있다 (개발용)
    r = d.post("/api/dev/fill", json={"exam_set_id": deid}).json()
    assert r["filled"] == 0 and r["skipped"] == 5
    res = d.get(f"/api/teacher/exams/{deid}/results").json()
    assert res["n_submitted"] == 5 and all(s["score"] is not None for s in res["students"])
    assert all(i["class_correct_rate"] is not None for i in res["items"])
