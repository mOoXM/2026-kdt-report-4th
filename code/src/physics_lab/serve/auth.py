r"""
auth.py — 로그인 · 세션 쿠키 · "누가 부르나" 판단. accounts.py 의 HTTP 층

    /api/auth/signup     강사 가입 → 바로 로그인 (쿠키)
    /api/auth/login      키(학생·게스트) 또는 이메일(강사) + 비밀번호 → 쿠키
    /api/auth/logout     쿠키 지우고 세션 행 삭제
    /api/auth/me         내가 누구인가 (화면이 첫 로드에 부른다)
    /api/auth/password   임시 → 새 비밀번호. must_change=1 상태에서 열려 있는 유일한 경로

api.py 는 `auth.install(app)` 한 줄로 이 라우터와 오류 매핑을 단다.

두 층의 경계
---------------------------------------------
accounts.py 는 표만 안다 — 쿠키·401·403 을 모른다. 이 파일이 그 반대쪽이다:
쿠키/헤더에서 세션 원문을 꺼내 accounts.get_session_user 에 넘기고, 권한 재료
(is_owner · is_class_teacher)로 403 을 내고, AccountsError 를 HTTP 코드로 바꾼다.
의존 방향은 serve → accounts → db 한쪽뿐이다.

다른 라우터가 가져다 쓰는 것
---------------------------
    conn = Depends(accounts_conn)      요청마다 accounts.db 연결 하나. 끝나면 commit / rollback + close
    me   = Depends(current_user)       로그인 안 됐으면 401. must_change=1 이어도 통과 (비밀번호 변경 화면용)
    me   = Depends(require_user)       + must_change=1 이면 403 {"code": "must_change"}
    me   = Depends(require_admin)      + is_admin 아니면 403
    me   = Depends(require_active_member)   + 승인된(active) 학원 소속이 아니면 403 — /images · /api/items 용 (⑤에서 붙인다)
    ensure_owner(conn, me, org_id)             아니면 403. 엔드포인트 안에서 부른다 (경로 변수를 받아야 해서)
    ensure_class_teacher(conn, me, class_id)   담당 강사 또는 그 학원 원장. 아니면 403

★ 트랜잭션과 HTTPException
--------------------------
accounts_conn 은 요청이 **HTTPException 으로 끝나도 commit** 한다. 401·403·404 는 오류가 아니라
정상 응답의 하나이고, 그 전에 쓴 것(로그인 실패 횟수!)은 남아야 한다. 예외로 rollback 하면
잠금이 영원히 안 걸린다 — accounts.login 이 실패를 None 으로 돌려주는 것과 같은 이유.
그 밖의 예외(AccountsError 포함 — 가입 도중 Duplicate 등, 그리고 버그)는 rollback.

쿠키
----
`pl_session`, HttpOnly(JS 가 못 읽음), SameSite=Lax(다른 사이트에서 오는 POST 에 안 실림 — CSRF 대부분 차단),
secure=False 인 이유 — 사설 VPN 주소가 http 다. 리버스 프록시 로 https 를 붙이면 True.
앱(Flutter)은 쿠키 대신 헤더 `X-Session` 으로 같은 원문을 보낸다. 표에는 원문이 없다 (sha256).

개발자 모드
------------------
`.env` 에 `PL_DEV=1` 이면 **세션이 없는 요청**을 개발자 계정(dev@local — 강사+운영자, "개발 학원" 승인됨)으로 본다.
쿠키가 있으면 평소대로 (역할 바꿔 보기는 `/api/dev/login-as` 가 진짜 세션을 만든다 — serve/dev.py).
`.env` 는 git 밖이라 기계마다 따로다. 켜지면 시작 로그에 경고, `/me` 가 `dev: true` 를 줘 화면이 빨간 띠를 단다.
자동 로그인·지우기·사용자 바꾸기는 전부 dev_enabled() 뒤에만 있다 — 꺼져 있으면 라우터 자체가 안 붙는다.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator

from dotenv import load_dotenv

from fastapi import APIRouter, Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import accounts as A
from ..db import accounts_db, connect, init_accounts_db

load_dotenv()                                   # PL_DEV

DEV_EMAIL = "dev@local"
DEV_ORG = "개발 학원"


def dev_enabled() -> bool:
    """개발자 모드인가. 환경 변수 하나 — 테스트가 monkeypatch 로 켠다."""
    return os.getenv("PL_DEV", "") == "1"


COOKIE = "pl_session"
HEADER = "X-Session"
SECURE = False                      # https 가 되면 True
COOKIE_MAX_AGE = 60 * 60 * 24 * A.SESSION_DAYS

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ============================================================ 연결
def open_conn(path) -> Iterator[sqlite3.Connection]:
    """
    accounts_conn 의 본체. 테스트는 `yield from auth.open_conn(tmp_path / "accounts.db")` 로
    임시 DB 를 끼운다 (app.dependency_overrides). 규칙은 머리말 ★ 절.
    """
    conn = connect(path)
    try:
        yield conn
    except HTTPException:
        conn.commit()               # 401·403·404 는 정상 응답 — 그 전에 쓴 것(실패 횟수)을 남긴다
        raise
    except BaseException:
        conn.rollback()             # 반쪽 가입 · 버그
        raise
    else:
        conn.commit()
    finally:
        conn.close()


def accounts_conn() -> Iterator[sqlite3.Connection]:
    """요청마다 하나. data/accounts.db 가 없으면 만든다 (스키마에 DROP 이 없어 안전)."""
    path = accounts_db()
    if not path.is_file():
        init_accounts_db(path=path)
    yield from open_conn(path)


# ============================================================ 누구인가
def session_token(pl_session: str | None = Cookie(None, alias=COOKIE),
                  x_session: str | None = Header(None, alias=HEADER)) -> str | None:
    """헤더가 있으면 헤더, 없으면 쿠키. 둘 다 없으면 None (여기서는 401 을 내지 않는다 — logout 도 이걸 쓴다)."""
    return x_session or pl_session


def current_user(conn: sqlite3.Connection = Depends(accounts_conn),
                 token: str | None = Depends(session_token)) -> dict:
    """로그인된 사람. 없거나 만료·비활성이면 401. must_change=1 이어도 통과한다 — /password 가 이걸 쓴다."""
    me = A.get_session_user(conn, token) if token else None
    if me is None and dev_enabled():
        return ensure_dev_user(conn)              # 개발자 모드: 쿠키가 없거나 죽은 세션이면 개발자 계정
    if not token:
        raise HTTPException(401, "로그인이 필요합니다")
    if me is None:
        raise HTTPException(401, "세션이 만료됐습니다. 다시 로그인하세요")
    return me


def ensure_dev_user(conn: sqlite3.Connection) -> dict:
    """개발자 계정. 없으면 만든다: 강사 가입(학원 '개발 학원' → 원장) + 학원 승인 + 운영자 플래그. 비밀번호는 무작위 — 쓸 일이 없다."""
    u = A.find_user(conn, email=DEV_EMAIL)
    if u is None:
        r = A.create_teacher(conn, email=DEV_EMAIL, password=A.new_token(), display_name="개발자", org_name=DEV_ORG)
        A.approve_org(conn, r["org_id"])
        A.set_admin(conn, r["user_id"], True)
        return A.load_user(conn, r["user_id"])
    return A.load_user(conn, u["user_id"])


def require_user(me: dict = Depends(current_user)) -> dict:
    """대부분의 API 가 쓰는 것. 임시 비밀번호 상태면 비밀번호부터 바꾸게 막는다."""
    if me["must_change"]:
        raise HTTPException(403, {"code": "must_change", "message": "임시 비밀번호를 먼저 바꿔야 합니다"})
    return me


def require_admin(me: dict = Depends(require_user)) -> dict:
    """운영자. 역할이 아니라 users.is_admin 플래그."""
    if not me["is_admin"]:
        raise HTTPException(403, "운영자만 할 수 있습니다")
    return me


def in_active_org(conn: sqlite3.Connection, user_id: str) -> bool:
    """
    승인된(active) 학원에 속해 있나. 강사는 org_members 로, 학생은 반(class_members → classes)으로.
    문항 이미지는 승인 뒤에만.
    """
    row = conn.execute(
        "SELECT 1 FROM org_members m JOIN orgs o USING (org_id) "
        "WHERE m.user_id = ? AND m.left_at IS NULL AND o.status = 'active' "
        "UNION ALL "
        "SELECT 1 FROM class_members cm JOIN classes c USING (class_id) JOIN orgs o USING (org_id) "
        "WHERE cm.user_id = ? AND cm.left_at IS NULL AND o.status = 'active' "
        "LIMIT 1",
        (user_id, user_id)).fetchone()
    return row is not None


def require_active_member(conn: sqlite3.Connection = Depends(accounts_conn),
                          me: dict = Depends(require_user)) -> dict:
    """로그인 + 승인된 학원 소속. 운영자는 통과. /images · /api/items 에 붙일 것 (⑤)."""
    if me["is_admin"] or in_active_org(conn, me["user_id"]):
        return me
    raise HTTPException(403, {"code": "org_pending", "message": "학원 승인 대기 중입니다"})


# ============================================================ 권한 판단 (재료는 accounts.py)
def ensure_owner(conn: sqlite3.Connection, me: dict, org_id: str) -> None:
    """이 학원의 원장이 아니면 403. 운영자는 통과."""
    if me["is_admin"] or A.is_owner(conn, me["user_id"], org_id):
        return
    raise HTTPException(403, "이 학원의 원장만 할 수 있습니다")


def ensure_class_teacher(conn: sqlite3.Connection, me: dict, class_id: str) -> None:
    """
    이 반의 담당 강사, 또는 이 반이 속한 학원의 원장이 아니면 403 (권한 표: 원장은 모든 반).
    반이 없으면 404 — 권한 검사 전에 존재부터 (없는 반에 403 을 내면 화면이 헷갈린다).
    """
    cls = conn.execute("SELECT org_id FROM classes WHERE class_id = ?", (class_id,)).fetchone()
    if cls is None:
        raise HTTPException(404, "반이 없습니다")          # 운영자도 없는 반은 404 (전엔 admin 이 먼저 통과해 dict(None) 500)
    if me["is_admin"] or A.is_class_teacher(conn, me["user_id"], class_id):
        return
    if A.is_owner(conn, me["user_id"], cls["org_id"]):
        return
    raise HTTPException(403, "이 반의 담당 강사나 원장만 할 수 있습니다")


# ============================================================ 쿠키
def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=SECURE,
                    max_age=COOKIE_MAX_AGE, path="/")


def _clear_cookie(resp: Response) -> None:
    resp.delete_cookie(COOKIE, path="/")


# ============================================================ 요청 모양
class SignupIn(BaseModel):
    email: str
    password: str
    display_name: str
    org_name: str | None = None
    invite: str | None = None


class LoginIn(BaseModel):
    login_key: str | None = None    # 학생 · 게스트
    email: str | None = None        # 강사
    password: str | None = None     # 게스트는 없음


class PasswordIn(BaseModel):
    old: str
    new: str


# ============================================================ 엔드포인트
@router.post("/signup")
def signup(body: SignupIn, resp: Response, request: Request,
           conn: sqlite3.Connection = Depends(accounts_conn)):
    """강사 가입 → 세션까지 만들어 쿠키를 심는다 (가입 뒤 다시 로그인시키지 않는다)."""
    try:
        r = A.create_teacher(conn, email=body.email, password=body.password,
                             display_name=body.display_name,
                             org_name=body.org_name, invite_token=body.invite)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    token = A.create_session(conn, r["user_id"], user_agent=request.headers.get("user-agent"))
    _set_cookie(resp, token)
    return {"user_id": r["user_id"], "org_id": r["org_id"], "role": r["role"]}


@router.post("/login")
def login(body: LoginIn, resp: Response, request: Request,
          conn: sqlite3.Connection = Depends(accounts_conn)):
    """
    성공 → 쿠키 + {"user", "must_change"}. must_change 가 True 면 화면은 비밀번호 변경으로 보낸다.
    실패 → 401. 키가 없는 건지 비밀번호가 틀린 건지 말하지 않는다.
    잠김 → 423 (AccountsError 핸들러). 실패 횟수는 HTTPException 이어도 commit 되어 남는다 (머리말 ★).
    """
    if (body.login_key is None) == (body.email is None):
        raise HTTPException(400, "login_key 또는 email 중 하나만 보내세요")
    me = A.login(conn, login_key=body.login_key, email=body.email, password=body.password)
    if me is None:
        raise HTTPException(401, "키(이메일) 또는 비밀번호가 맞지 않습니다")
    token = A.create_session(conn, me["user_id"], user_agent=request.headers.get("user-agent"))
    _set_cookie(resp, token)
    return {"user": me, "must_change": bool(me["must_change"])}


@router.post("/logout")
def logout(resp: Response, conn: sqlite3.Connection = Depends(accounts_conn),
           token: str | None = Depends(session_token)):
    """세션이 없어도 200 — 이미 나간 상태에서 또 눌러도 화면이 깨지지 않게."""
    if token:
        A.delete_session(conn, token)
    _clear_cookie(resp)
    return {"ok": True}


@router.get("/me")
def me(me: dict = Depends(current_user)):
    """must_change=1 이어도 답한다 — 화면이 "비밀번호부터 바꾸세요" 로 보낼 수 있게. dev 는 개발자 모드 띠용."""
    return {"user": me, "dev": dev_enabled()}


@router.post("/password")
def password(body: PasswordIn, conn: sqlite3.Connection = Depends(accounts_conn),
             me: dict = Depends(current_user), token: str | None = Depends(session_token)):
    """
    본인 비밀번호 변경. 지금 세션(keep_session)은 남기고 다른 기기는 로그아웃.
    옛 비밀번호가 틀리면 401 — 로그인과 같은 잠금 카운트가 올라간다.
    """
    try:
        ok = A.change_password(conn, me["user_id"], body.old, body.new, keep_session=token)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    if not ok:
        raise HTTPException(401, "현재 비밀번호가 맞지 않습니다")
    return {"ok": True}


# ============================================================ 오류 매핑 · 설치
_STATUS = {A.Duplicate: 409, A.NotFound: 404, A.InvalidInvite: 400}


def _accounts_error(request: Request, exc: A.AccountsError) -> JSONResponse:
    """AccountsError → HTTP 코드 한 곳. 라우터마다 try/except 를 안 쓴다."""
    if isinstance(exc, A.Locked):
        return JSONResponse(status_code=423,
                            content={"detail": str(exc), "code": "locked", "locked_until": exc.locked_until})
    return JSONResponse(status_code=_STATUS.get(type(exc), 400), content={"detail": str(exc)})


def install(app: FastAPI) -> None:
    """api.py 가 부른다. 라우터 + AccountsError 핸들러."""
    app.include_router(router)
    app.add_exception_handler(A.AccountsError, _accounts_error)
