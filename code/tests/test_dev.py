"""
개발자 모드 (serve/dev.py + auth.dev_enabled). 작은 FastAPI 앱에 auth + dev 만 달고 tmp DB 로.
가장 중요한 검사: PL_DEV 가 없으면 /api/dev/* 가 붙지 않고 자동 로그인도 없다.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from physics_lab import db
from physics_lab.serve import auth, dev
from physics_lab.serve.student import responses_conn


def _app(tmp_path):
    app = FastAPI()
    auth.install(app)
    dev.install(app)
    acc = db.init_accounts_db(path=tmp_path / "accounts.db")
    rdb = db.init_responses_db(path=tmp_path / "responses.db")
    app.dependency_overrides[auth.accounts_conn] = lambda: (yield from auth.open_conn(acc))
    app.dependency_overrides[responses_conn] = lambda: (yield from auth.open_conn(rdb))
    return TestClient(app)


def test_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PL_DEV", raising=False)
    c = _app(tmp_path)
    assert c.get("/api/auth/me").status_code == 401                 # 자동 로그인 없음
    assert c.get("/api/dev/state").status_code == 404               # 라우터 자체가 없음
    assert c.post("/api/dev/seed").status_code == 404


def test_dev_mode_auto_login_seed_switch_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("PL_DEV", "1")
    c = _app(tmp_path)

    me = c.get("/api/auth/me").json()
    assert me["dev"] is True
    assert me["user"]["email"] == auth.DEV_EMAIL and me["user"]["is_admin"] == 1 and me["user"]["kind"] == "teacher"

    s = c.post("/api/dev/seed").json()
    kinds = sorted(u["kind"] for u in s["users"])
    assert kinds == ["guest"] + ["student"] * 5 + ["teacher"]
    assert c.post("/api/dev/seed").json()["made"] == []            # 두 번 눌러도 안 불어남

    student = next(u for u in s["users"] if u["kind"] == "student")
    r = c.post("/api/dev/login-as", json={"user_id": student["user_id"]})
    assert r.status_code == 200 and auth.COOKIE in r.cookies
    me2 = c.get("/api/auth/me").json()["user"]
    assert me2["user_id"] == student["user_id"] and me2["kind"] == "student" and me2["must_change"] == 0

    # 학생 비밀번호가 정해진 값으로 — 보통 로그인도 된다
    bare = TestClient(c.app)
    ok = bare.post("/api/auth/login", json={"login_key": student["login_key"], "password": s["password"]})
    assert ok.status_code == 200, ok.text

    assert c.post("/api/dev/login-as", json={"user_id": "u_nobody"}).status_code == 403
    assert c.post("/api/dev/reset").json() == {"deleted": 0}
    assert c.get("/api/dev/attempt/a_none").status_code == 404
