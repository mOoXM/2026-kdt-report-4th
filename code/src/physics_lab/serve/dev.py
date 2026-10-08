r"""
dev.py — 개발자 모드 라우터. `.env` 에 `PL_DEV=1` 일 때만 api.py 가 조립한다 (아니면 /api/dev/* 는 404).

    /api/dev/state                 지금 누구인가 + 바꿔 볼 수 있는 사용자 목록 (개발 학원 안)
    /api/dev/login-as {user_id}    그 사용자의 진짜 세션을 만들어 쿠키로 — 학생·게스트 역할을 실제 kind 로 본다
    /api/dev/seed                  개발 학원에 반 1 · 학생 5(비밀번호 1234, 변경 강제 없음) · 게스트 1. 두 번 눌러도 안 불어남
    /api/dev/reset                 개발 학원 사용자들의 응답(attempts·responses·statement_responses)만 지움. 계정은 남긴다
    /api/dev/attempt/{id}          방금 저장된 풀이를 responses.db 행 그대로 (input_format · choice_source · elapsed …)

자동 로그인 자체는 auth.current_user 에 있다 (세션 없는 요청 → 개발자 계정). 여기는 그 위의 도구들.
안전장치: 켜지면 시작 로그에 경고(install), 화면에 빨간 띠(/me 의 dev), login-as 는 개발 학원 사람만.
배포 때 지우지 않는다 — 스위치가 .env 에 없으면 아무것도 안 붙는다. 테스트 tests/test_dev.py 가 그걸 지킨다.
"""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel

from .. import accounts as A
from .. import responses as R
from . import auth
from .student import load_item_facts, responses_conn

log = logging.getLogger("physics_lab.dev")
router = APIRouter(prefix="/api/dev")

DEV_CLASS = "개발반"
DEV_PASSWORD = "1234"
N_STUDENTS = 5


# ------------------------------------------------------------ 개발 학원 안 사람들
def dev_org_id(conn: sqlite3.Connection) -> str:
    """개발자 계정이 원장인 학원. 없으면 ensure_dev_user 가 만든다."""
    me = auth.ensure_dev_user(conn)
    row = conn.execute(
        "SELECT org_id FROM org_members WHERE user_id = ? AND role = 'owner' AND left_at IS NULL", (me["user_id"],)).fetchone()
    if row is None:
        raise HTTPException(500, "개발자 계정에 학원이 없다")
    return row["org_id"]


def dev_users(conn: sqlite3.Connection, org_id: str) -> list[dict]:
    """개발 학원에 딸린 사용자: 강사(구성원) · 반 명단 학생 · 이 학원이 발급한 게스트."""
    rows = conn.execute(
        """
        SELECT u.user_id, u.kind, u.login_key, u.email, u.is_admin, u.expires_at,
               COALESCE(cm.display_name, u.display_name) AS display_name, c.name AS class_name
        FROM users u
        LEFT JOIN org_members om ON om.user_id = u.user_id AND om.org_id = ? AND om.left_at IS NULL
        LEFT JOIN class_members cm ON cm.user_id = u.user_id AND cm.left_at IS NULL
        LEFT JOIN classes c ON c.class_id = cm.class_id AND c.org_id = ?
        WHERE om.user_id IS NOT NULL OR c.class_id IS NOT NULL OR u.issued_by_org = ?
        ORDER BY CASE u.kind WHEN 'teacher' THEN 0 WHEN 'student' THEN 1 ELSE 2 END, display_name
        """, (org_id, org_id, org_id)).fetchall()
    return [dict(r) for r in rows]


def _state(conn: sqlite3.Connection, me: dict) -> dict:
    org_id = dev_org_id(conn)
    return {"me": me, "org_id": org_id, "users": dev_users(conn, org_id),
            "password": DEV_PASSWORD, "class": DEV_CLASS}


@router.get("/state")
def api_state(me: dict = Depends(auth.current_user), conn: sqlite3.Connection = Depends(auth.accounts_conn)):
    return _state(conn, me)


# ------------------------------------------------------------ 역할 바꿔 보기
class LoginAs(BaseModel):
    user_id: str


@router.post("/login-as")
def api_login_as(body: LoginAs, resp: Response, conn: sqlite3.Connection = Depends(auth.accounts_conn)):
    """개발 학원 사람에 한해 그 사용자의 세션을 만들어 쿠키로. 게스트는 만료 전이어야 한다 (create_session 이 막는다)."""
    org_id = dev_org_id(conn)
    if body.user_id not in {u["user_id"] for u in dev_users(conn, org_id)}:
        raise HTTPException(403, "개발 학원 사람만 바꿔 볼 수 있다")
    token = A.create_session(conn, body.user_id, user_agent="dev")
    auth._set_cookie(resp, token)
    return {"user": A.load_user(conn, body.user_id)}


# ------------------------------------------------------------ 테스트 데이터
@router.post("/seed")
def api_seed(conn: sqlite3.Connection = Depends(auth.accounts_conn)):
    """반 하나 · 학생 N · 게스트 하나. 이미 있으면 그대로 두고 모자란 것만 채운다."""
    me = auth.ensure_dev_user(conn)
    org_id = dev_org_id(conn)
    cls = conn.execute("SELECT class_id FROM classes WHERE org_id = ? AND name = ? AND archived_at IS NULL",
                       (org_id, DEV_CLASS)).fetchone()
    class_id = cls["class_id"] if cls else A.create_class(conn, org_id=org_id, name=DEV_CLASS, teacher_id=me["user_id"])
    n_have = conn.execute("SELECT COUNT(*) FROM class_members WHERE class_id = ? AND left_at IS NULL", (class_id,)).fetchone()[0]
    made = []
    if n_have < N_STUDENTS:
        rows = [{"display_name": f"학생{i}", "school": "개발고", "entry_year": 2025} for i in range(n_have + 1, N_STUDENTS + 1)]
        for r in A.enroll_students(conn, class_id, rows, must_change=0):
            A.set_password(conn, r["user_id"], DEV_PASSWORD, must_change=0)      # 정해진 비밀번호, 변경 강제 없음
            made.append(r["login_key"])
    guest = conn.execute(
        "SELECT user_id FROM users WHERE kind = 'guest' AND issued_by_org = ? AND status = 'active' AND expires_at > ?",
        (org_id, A.utcnow())).fetchone()
    if guest is None:
        made.append("guest:" + A.issue_guest(conn, org_id=org_id)["login_key"])
    return {"class_id": class_id, "made": made, **_state(conn, me)}


@router.post("/reset")
def api_reset(conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    """개발 학원 사용자들의 응답만 지운다 (계정·반은 그대로). 다른 학원 응답은 건드리지 않는다."""
    org_id = dev_org_id(conn)
    ids = [u["user_id"] for u in dev_users(conn, org_id)]
    if not ids:
        return {"deleted": 0}
    qs = ",".join("?" * len(ids))
    attempts = [r[0] for r in rconn.execute(f"SELECT attempt_id FROM attempts WHERE student_id IN ({qs})", ids)]
    if attempts:
        aq = ",".join("?" * len(attempts))
        rconn.execute(f"DELETE FROM statement_responses WHERE attempt_id IN ({aq})", attempts)
        rconn.execute(f"DELETE FROM responses WHERE attempt_id IN ({aq})", attempts)
        rconn.execute(f"DELETE FROM attempts WHERE attempt_id IN ({aq})", attempts)
    return {"deleted": len(attempts)}


# ------------------------------------------------------------ 디버그
@router.get("/attempt/{attempt_id}")
def api_attempt(attempt_id: str, rconn: sqlite3.Connection = Depends(responses_conn)):
    """저장된 그대로. responses.load_attempt 와 같은 모양 (attempt + items[+statements])."""
    got = R.load_attempt(rconn, attempt_id)
    if got is None:
        raise HTTPException(404, "없는 attempt")
    return got


# ------------------------------------------------------------ 가짜 응답 (결과 표를 바로 보려고)
class FillIn(BaseModel):
    exam_set_id: str
    p_wrong: float = 0.3                   # 보기 하나를 틀릴 확률
    p_unsure: float = 0.08                  # "모르겠다" 확률 (진단 모드만)
    only_missing: bool = True               # 이미 제출한 학생은 건너뛴다


@router.post("/fill")
def api_fill(body: FillIn, conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    """
    열린(또는 끝난) 시험에 그 반 학생 전원의 무작위 응답을 넣는다. 모드에 맞는 형식으로 (진단: 보기별 O/X/? · 단답 / 실전: ①~⑤).
    학생마다 '실력' 을 하나 뽑아 틀릴 확률을 흔든다 — 표가 사람처럼 보이게. 개발 학원 밖 반은 건드리지 않는다.
    """
    import random
    e = rconn.execute("SELECT * FROM exam_sets WHERE exam_set_id = ?", (body.exam_set_id,)).fetchone()
    if e is None:
        raise HTTPException(404, "없는 시험")
    cls = conn.execute("SELECT org_id FROM classes WHERE class_id = ?", (e["class_id"],)).fetchone()
    if cls is None or cls["org_id"] != dev_org_id(conn):
        raise HTTPException(403, "개발 학원의 반만 채울 수 있습니다")
    keys = [r["item_key"] for r in rconn.execute("SELECT item_key FROM exam_items WHERE exam_set_id = ? ORDER BY seq", (body.exam_set_id,))]
    facts = load_item_facts(keys)
    truth = {}
    from ..db import ANSWER_LABEL, connect
    from . import student as _st
    pc = connect(_st.PHYSICS_DB)                            # student 모듈의 경로 (테스트가 가짜 DB 로 바꾸는 자리)
    for r in pc.execute(f"SELECT item_key, label, is_true FROM statements WHERE item_key IN ({','.join('?' * len(keys))})", keys):
        truth.setdefault(r["item_key"], {})[r["label"]] = r["is_true"]
    pc.close()
    members = [r["user_id"] for r in conn.execute("SELECT user_id FROM class_members WHERE class_id = ? AND left_at IS NULL", (e["class_id"],))]
    done = {r["student_id"] for r in rconn.execute("SELECT student_id FROM attempts WHERE exam_set_id = ?", (body.exam_set_id,))}
    made = []
    for uid in members:
        if body.only_missing and uid in done:
            continue
        skill = random.uniform(-0.2, 0.25)                      # 학생마다 흔들기
        pw = min(0.9, max(0.05, body.p_wrong + skill))
        answers, items = [], {}
        for i, k in enumerate(keys, 1):
            fmt = facts["format"].get(k)
            if e["mode"] == "realistic":
                ans = facts["answer"].get(k)
                no = ans if (ans and random.random() > pw) else random.randint(1, 5)
                answers.append({"item_key": k, "choice_no": no})
            elif fmt == "numeric":
                ans = facts["answer"].get(k); texts = facts["texts"].get(k, {})
                if ans and random.random() > pw and ans in texts:
                    txt = texts[ans]
                else:
                    others = [t for n, t in texts.items() if n != ans] or ["0"]
                    txt = random.choice(others)
                answers.append({"item_key": k, "answer_text": txt})
            else:
                for lab, t in sorted(truth.get(k, {}).items()):
                    if lab == ANSWER_LABEL:
                        continue
                    r = random.random()
                    if r < body.p_unsure:
                        answers.append({"item_key": k, "label": lab, "judged_true": None, "unsure": True})
                    else:
                        wrong = random.random() < pw
                        answers.append({"item_key": k, "label": lab, "judged_true": (not bool(t)) if wrong else bool(t), "unsure": False})
            items[k] = {"seq": i, "elapsed_ms": random.randint(20000, 150000), "focus_lost_ms": 0}
        R.ensure_student(rconn, uid)
        aid = R.save_attempt(rconn, student_id=uid, purpose="exam", exam_set_id=body.exam_set_id, answers=answers, items=items,
                             choices=facts["choices"], choice_texts=facts["texts"], client={"device": "dev-fill"})
        made.append(aid)
    return {"filled": len(made), "skipped": len(members) - len(made)}


def install(app: FastAPI) -> None:
    """api.py 가 부른다. PL_DEV=1 이 아니면 아무것도 안 한다."""
    if not auth.dev_enabled():
        return
    log.warning("★ 개발자 모드 (PL_DEV=1): 세션 없는 요청은 전부 %s 로 본다. 배포 기계의 .env 에는 PL_DEV 가 없어야 한다", auth.DEV_EMAIL)
    print("★ 개발자 모드 켜짐 (PL_DEV=1) — 자동 로그인 · /api/dev/* 활성. 배포 기계에선 .env 에서 뺄 것")
    app.include_router(router)
