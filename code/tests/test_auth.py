"""
serve/auth.py — 쿠키·401·403·423 이 accounts.py 위에서 설계대로 도는지.

api.py 전체를 띄우지 않고 auth 만 단 작은 FastAPI 앱을 쓴다 — physics.db 등 data/ 가 없어도 돈다.
accounts_conn 을 tmp_path 의 DB 로 바꿔 끼운다 (dependency_overrides).
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from physics_lab import accounts as A
from physics_lab import db
from physics_lab.serve import auth

OWNER = {"email": "o@x.kr", "password": "pw-owner", "display_name": "원장", "org_name": "물리학원"}


def _make_app() -> FastAPI:
    app = FastAPI()
    auth.install(app)

    # 의존성·판단 함수를 실제로 물리는 검증용 엔드포인트 (실제 앱엔 없다)
    @app.get("/t/user")
    def t_user(me: dict = Depends(auth.require_user)):
        return {"user_id": me["user_id"]}

    @app.get("/t/admin")
    def t_admin(me: dict = Depends(auth.require_admin)):
        return {"ok": True}

    @app.get("/t/active")
    def t_active(me: dict = Depends(auth.require_active_member)):
        return {"ok": True}

    @app.get("/t/org/{org_id}")
    def t_org(org_id: str, conn: sqlite3.Connection = Depends(auth.accounts_conn),
              me: dict = Depends(auth.require_user)):
        auth.ensure_owner(conn, me, org_id)
        return {"ok": True}

    @app.get("/t/class/{class_id}")
    def t_class(class_id: str, conn: sqlite3.Connection = Depends(auth.accounts_conn),
                me: dict = Depends(auth.require_user)):
        auth.ensure_class_teacher(conn, me, class_id)
        return {"ok": True}

    return app


@pytest.fixture
def env(tmp_path):
    """(client, conn) — conn 은 테스트가 직접 표를 들여다보거나 학생을 심을 때."""
    path = db.init_accounts_db(path=tmp_path / "accounts.db")
    app = _make_app()

    def override():
        yield from auth.open_conn(path)

    app.dependency_overrides[auth.accounts_conn] = override
    client = TestClient(app)
    conn = db.connect(path)
    yield client, conn
    conn.close()
    app.dependency_overrides.clear()


def _signup(client, **kw):
    r = client.post("/api/auth/signup", json={**OWNER, **kw})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- 가입 · me · 로그아웃
def test_signup_sets_cookie_and_me_works(env):
    client, conn = env
    r = client.post("/api/auth/signup", json=OWNER)
    assert r.status_code == 200 and r.json()["role"] == "owner"
    assert auth.COOKIE in r.cookies                                  # 가입 즉시 로그인
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie   # http 인 동안
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "o@x.kr"
    assert "password_hash" not in me.json()["user"]
    n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert n == 1 and conn.execute("SELECT session_hash FROM sessions").fetchone()[0] != r.cookies[auth.COOKIE]


def test_signup_errors_map_to_http(env):
    client, conn = env
    _signup(client)
    assert client.post("/api/auth/signup", json=OWNER).status_code == 409                 # Duplicate
    assert client.post("/api/auth/signup", json={**OWNER, "email": "a@x.kr", "invite": "bad"}).status_code == 400   # InvalidInvite
    both = {**OWNER, "email": "b@x.kr", "invite": "t"}                                   # 학원명 + 초대 → ValueError
    assert client.post("/api/auth/signup", json=both).status_code == 400
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1                 # 반쪽 가입은 rollback


def test_me_requires_login_and_logout_ends_session(env):
    client, conn = env
    assert client.get("/api/auth/me").status_code == 401
    _signup(client)
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert client.post("/api/auth/logout").status_code == 200                            # 또 눌러도 200


def test_header_instead_of_cookie(env):
    client, conn = env
    _signup(client)
    token = client.cookies[auth.COOKIE]
    bare = TestClient(client.app)                                                       # 쿠키 없는 새 클라이언트
    assert bare.get("/api/auth/me").status_code == 401
    assert bare.get("/api/auth/me", headers={auth.HEADER: token}).status_code == 200
    assert bare.get("/api/auth/me", headers={auth.HEADER: "no-such-session"}).status_code == 401   # 헤더는 ascii 만


# ---------------------------------------------------------------- 로그인 · 잠금
def _failed(conn, user_id):
    """그 학생의 실패 횟수. 표에 원장 행도 있으니 WHERE 를 꼭 건다."""
    return conn.execute("SELECT failed_count FROM credentials WHERE user_id=?", (user_id,)).fetchone()[0]


def _student(conn):
    """원장 + 반 + 학생 하나를 accounts 함수로 직접 심는다 (강사 화면은 아직 없다)."""
    with conn:
        o = A.create_teacher(conn, **OWNER)
        A.approve_org(conn, o["org_id"])
        cid = A.create_class(conn, org_id=o["org_id"], name="개념반", teacher_id=o["user_id"])
        s = A.enroll_students(conn, cid, [{"display_name": "이하은"}])[0]
    return o, cid, s


def test_login_student_then_must_change_flow(env):
    client, conn = env
    o, cid, s = _student(conn)
    r = client.post("/api/auth/login", json={"login_key": s["login_key"].lower(), "password": s["pin"]})
    assert r.status_code == 200 and r.json()["must_change"] is True
    assert client.get("/api/auth/me").status_code == 200                                 # me 는 열려 있다
    r = client.get("/t/user")                                                            # 다른 건 막힌다
    assert r.status_code == 403 and r.json()["detail"]["code"] == "must_change"
    wrong = "0000" if s["pin"] != "0000" else "0001"
    assert client.post("/api/auth/password", json={"old": wrong, "new": "1357"}).status_code == 401
    assert _failed(conn, s["user_id"]) == 1                                              # 틀린 옛 비밀번호도 카운트
    assert client.post("/api/auth/password", json={"old": s["pin"], "new": "12"}).status_code == 400   # 너무 짧다
    r = client.post("/api/auth/password", json={"old": s["pin"], "new": "1357"})
    assert r.status_code == 200
    assert client.get("/t/user").status_code == 200                                      # 이제 열린다. 세션도 그대로
    assert client.get("/api/auth/me").json()["user"]["must_change"] == 0


def test_login_failures_and_lock(env):
    client, conn = env
    o, cid, s = _student(conn)
    bad = {"login_key": s["login_key"], "password": "9999"}
    for _ in range(4):
        assert client.post("/api/auth/login", json=bad).status_code == 401
    assert _failed(conn, s["user_id"]) == 4                                              # 401 이어도 commit 됐다
    assert client.post("/api/auth/login", json=bad).status_code == 401                   # 5번째 → 잠금
    r = client.post("/api/auth/login", json={"login_key": s["login_key"], "password": s["pin"]})
    assert r.status_code == 423 and r.json()["code"] == "locked" and r.json()["locked_until"]
    assert client.post("/api/auth/login", json={"login_key": "ZZZZZZ", "password": "1"}).status_code == 401   # 없는 키도 401
    assert client.post("/api/auth/login", json={"password": "1"}).status_code == 400                        # 둘 다 없음
    assert client.post("/api/auth/login", json={"login_key": "A", "email": "b", "password": "1"}).status_code == 400


def test_login_teacher_and_guest(env):
    client, conn = env
    o, cid, s = _student(conn)
    with conn:
        g = A.issue_guest(conn, org_id=o["org_id"])
    r = client.post("/api/auth/login", json={"email": "O@X.KR", "password": "pw-owner"})
    assert r.status_code == 200 and r.json()["must_change"] is False
    assert client.get("/t/user").status_code == 200
    r = client.post("/api/auth/login", json={"login_key": g["login_key"]})               # 게스트: 비밀번호 없이
    assert r.status_code == 200 and r.json()["user"]["kind"] == "guest"
    assert client.post("/api/auth/password", json={"old": "x", "new": "1234"}).status_code == 404   # 게스트는 비밀번호가 없다


# ---------------------------------------------------------------- 권한
def test_admin_owner_class_checks(env):
    client, conn = env
    o, cid, s = _student(conn)
    with conn:
        token = A.create_invite(conn, org_id=o["org_id"], created_by=o["user_id"])
        t = A.create_teacher(conn, email="t@x.kr", password="p", display_name="강사", invite_token=token)
        c2 = A.create_class(conn, org_id=o["org_id"], name="문제풀이반", teacher_id=t["user_id"])
        other = A.create_teacher(conn, email="z@x.kr", password="p", display_name="남", org_name="옆학원")

    def as_(email, pw="p"):
        c = TestClient(client.app)
        assert c.post("/api/auth/login", json={"email": email, "password": pw}).status_code == 200
        return c

    owner, teacher, stranger = as_("o@x.kr", "pw-owner"), as_("t@x.kr"), as_("z@x.kr")
    assert owner.get("/t/admin").status_code == 403                                      # 원장이어도 운영자는 아니다
    assert owner.get(f"/t/org/{o['org_id']}").status_code == 200
    assert teacher.get(f"/t/org/{o['org_id']}").status_code == 403
    assert stranger.get(f"/t/org/{o['org_id']}").status_code == 403
    assert teacher.get(f"/t/class/{c2}").status_code == 200                             # 담당
    assert owner.get(f"/t/class/{c2}").status_code == 200                               # 원장은 모든 반
    assert teacher.get(f"/t/class/{cid}").status_code == 403                            # 남의 반
    assert stranger.get(f"/t/class/{cid}").status_code == 403
    assert owner.get("/t/class/c_none").status_code == 404                              # 없는 반은 404 가 먼저
    conn.execute("UPDATE users SET is_admin=1 WHERE user_id=?", (other["user_id"],))
    conn.commit()
    assert stranger.get("/t/admin").status_code == 200                                  # 운영자는 전부 통과
    assert stranger.get(f"/t/org/{o['org_id']}").status_code == 200
    assert stranger.get(f"/t/class/{cid}").status_code == 200


def test_active_member_gate(env):
    client, conn = env
    with conn:
        o = A.create_teacher(conn, **OWNER)                                              # pending 학원
        cid = A.create_class(conn, org_id=o["org_id"], name="개념반", teacher_id=o["user_id"])
        s = A.enroll_students(conn, cid, [{"display_name": "이하은"}])[0]
        A.change_password(conn, s["user_id"], s["pin"], "1357")                          # must_change 해제
    teacher, student = TestClient(client.app), TestClient(client.app)
    assert teacher.post("/api/auth/login", json={"email": "o@x.kr", "password": "pw-owner"}).status_code == 200
    assert student.post("/api/auth/login", json={"login_key": s["login_key"], "password": "1357"}).status_code == 200
    for c in (teacher, student):
        r = c.get("/t/active")
        assert r.status_code == 403 and r.json()["detail"]["code"] == "org_pending"
    with conn:
        A.approve_org(conn, o["org_id"])
    for c in (teacher, student):
        assert c.get("/t/active").status_code == 200
    with conn:
        A.withdraw_student(conn, cid, s["user_id"])
    assert student.get("/t/active").status_code == 403                                  # 퇴원하면 다시 막힌다


def test_expired_session_is_401(env):
    client, conn = env
    _signup(client)
    conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00Z'")
    conn.commit()
    assert client.get("/api/auth/me").status_code == 401
