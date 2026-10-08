r"""
accounts.py — 사용자 · 학원 · 반 · 명단 · 세션. `data/accounts.db` 에 쓰는 유일한 창구

사용 (프로젝트 루트에서, 운영자 명령):
    uv run pl-accounts add-teacher --email o@x.kr --name 원장 --org 물리학원
    uv run pl-accounts approve-org o_XXXXXXXXXX
    uv run pl-accounts invite o_XXXXXXXXXX --by u_XXXXXXXXXXXX
    (반 · 명단 · 로그인 · 게스트 명령은 뒤 덩어리에서)

코드에서:
    from physics_lab import accounts, db
    conn = db.connect(db.accounts_db())
    with conn:                                        # ← 부르는 쪽이 묶는다. 성공 commit / 예외 rollback
        r = accounts.create_teacher(conn, email=..., password=..., display_name=..., org_name=...)


지키는 것 넷
-----------
1. 함수는 `conn` 을 받고 **commit 하지 않는다.** 가입 하나가 users·credentials·orgs·org_members
   네 표에 쓰는데, 셋째에서 실패하면 앞의 둘도 취소돼야 한다. 그 묶음(트랜잭션)은 부르는 쪽
   — API 요청 하나, CLI 명령 하나, 테스트 하나 — 이 `with conn:` 으로 만든다.
2. SQLite 의 오류는 **우리 이름**으로 바꿔 낸다: AccountsError 아래 Duplicate · NotFound ·
   InvalidInvite · Locked. 잘못된 인자는 ValueError. 그 밖(디스크 꽉 참 등)은 잡지 않는다.
3. **누가 부르는지는 보지 않는다.** "이 강사가 이 반 담당인가" 는 serve/auth.py 가 판단한다.
   여기는 그 재료(is_owner · is_class_teacher)만 둔다. CLI 는 운영자라 검사가 없어야 한다.
4. pin · 비밀번호 · 세션 원문 · 초대 토큰 원문은 **로그·오류 메시지·print 에 안 나온다.**
   평문 pin 은 만든 함수의 반환값에만 존재한다 — 강사가 학생에게 한 번 전달하고 끝.

왜 이런 값들인가
---------------
- login_key: 사람이 손으로 치는 6자. 0/O/1/I 를 뺀 32자 집합. 키는 ID 이지 비밀이 아니다.
- user_id 'u_'+12자 · org_id 'o_'+10자 · class_id 'c_'+10자: 접두사로 어느 표 ID 인지 보이게.
- 임시 pin: 숫자 4자리 **문자열** ("0937"). int() 하면 앞자리 0 이 사라진다. 겹쳐도 된다
  (누구인지는 키가 가리고 pin 은 그 키의 짝일 뿐).
- 세션·초대 원문: secrets.token_urlsafe(32). 표에는 sha256 만 — DB 파일이 새도 못 쓴다.
- 해시: argon2id, OWASP 최소 권장(19MiB·t=2·p=1). 기본값 64MiB 는 동시 로그인 40개면 2.5GB.
- 시각: utcnow() 한 함수로만. '2026-09-28T04:10:00Z' 자릿수 고정 → 문자열 비교가 시간 비교.
  모든 쓰기 함수가 now=None 을 받아 테스트가 시각을 고정할 수 있다.
- random 이 아니라 secrets: random 은 예측 가능해서 키·토큰에 못 쓴다.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from .db import accounts_db, connect, init_accounts_db

# ---------------------------------------------------------------- 상수
KEY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"   # 32자. 0/O/1/I 없음
KEY_LEN = 6
USER_ID_LEN = 12
SHORT_ID_LEN = 10
KEY_RETRIES = 5                                     # UNIQUE 충돌 시 다시 만드는 횟수

SESSION_DAYS = 30
GUEST_DAYS = 14
INVITE_DAYS = 7

LOCK_AFTER = 5                                      # 연속 실패 n회부터 잠금
LOCK_BASE_MINUTES = 1                               # 첫 잠금 1분, 실패마다 두 배
LOCK_MAX_MINUTES = 60

TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"

# argon2id. 서버 메모리를 아끼려고 OWASP 최소 권장으로.
_hasher = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)


# ---------------------------------------------------------------- 예외
class AccountsError(Exception):
    """이 모듈이 내는 오류의 부모. API 는 이것 하나로 받아 '사용자 잘못' 으로 처리한다."""


class Duplicate(AccountsError):
    """이미 있다 — 이메일, (5번 다시 만들어도) 키."""


class NotFound(AccountsError):
    """그런 사용자·학원·반이 없다."""


class InvalidInvite(AccountsError):
    """초대가 없거나 · 만료됐거나 · 이미 썼다. 셋을 구분하지 않는다 (링크 가진 쪽에 정보를 안 준다)."""


class Locked(AccountsError):
    """로그인 잠금 중. locked_until 에 풀리는 시각."""

    def __init__(self, locked_until: str):
        super().__init__(f"잠금 중: {locked_until} 까지")
        self.locked_until = locked_until


# ---------------------------------------------------------------- 시각
def utcnow() -> str:
    """'2026-09-28T04:10:00Z'. 시각을 만드는 유일한 함수 — 자릿수가 흐트러지면 문자열 비교가 깨진다."""
    return datetime.now(timezone.utc).strftime(TIME_FMT)


def _parse(t: str) -> datetime:
    return datetime.strptime(t, TIME_FMT).replace(tzinfo=timezone.utc)


def plus(now: str, *, days: int = 0, minutes: int = 0) -> str:
    """now 에서 days·minutes 뒤. 만료 시각 계산용."""
    return (_parse(now) + timedelta(days=days, minutes=minutes)).strftime(TIME_FMT)


# ---------------------------------------------------------------- 값 만들기
def _rand(n: int) -> str:
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(n))


def new_key() -> str:
    return _rand(KEY_LEN)


def new_user_id() -> str:
    return "u_" + _rand(USER_ID_LEN)


def new_org_id() -> str:
    return "o_" + _rand(SHORT_ID_LEN)


def new_class_id() -> str:
    return "c_" + _rand(SHORT_ID_LEN)


def new_pin() -> str:
    """숫자 4자리 문자열. '0937' 처럼 0 으로 시작할 수 있다 — 절대 int 로 다루지 말 것."""
    return f"{secrets.randbelow(10000):04d}"


def new_token() -> str:
    """세션·초대 원문. 43자. 표에는 token_hash() 만 넣는다."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_hash(password_hash: str, password: str) -> bool:
    """
    argon2 는 안 맞으면 예외를 내는데, 여기서는 True/False 로 바꾼다. 로그인 함수가 쓴다.
    깨진 해시(표가 손상됐거나 ascii 가 아닌 것)는 InvalidHashError 나 UnicodeEncodeError 로
    오는데 둘 다 ValueError 다 — 로그인이 500 으로 죽는 대신 "안 맞음" 이어야 한다.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, ValueError):
        return False


def norm_email(email: str) -> str:
    """SQLite UNIQUE 는 대소문자를 구분한다. 넣을 때·찾을 때 같은 함수로 맞춘다."""
    return email.strip().lower()


def norm_key(key: str) -> str:
    return key.strip().upper()


# ---------------------------------------------------------------- 내부
def _insert_user_with_key(conn: sqlite3.Connection, *, kind: str, created_at: str,
                          expires_at: str | None = None,
                          issued_by_org: str | None = None) -> tuple[str, str]:
    """
    login_key 가 있는 사용자(student · guest)를 넣는다. 키가 겹치면(UNIQUE) 다시 만들어 최대 5번.
    32^6 ≈ 10억 중이라 실제로는 한 번에 들어간다. 실패 INSERT 는 문장 하나만 취소되고
    트랜잭션은 살아 있어서 그냥 다시 INSERT 하면 된다.
    반환 (user_id, login_key).
    """
    user_id = new_user_id()
    for _ in range(KEY_RETRIES):
        key = new_key()
        try:
            conn.execute(
                "INSERT INTO users (user_id, kind, login_key, expires_at, issued_by_org, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, kind, key, expires_at, issued_by_org, created_at))
            return user_id, key
        except sqlite3.IntegrityError as e:
            if "users.login_key" not in str(e):
                raise
    raise Duplicate("login_key 를 5번 만들어도 겹쳤다 — 있을 수 없는 일이라 확인이 필요하다")


def _require(conn: sqlite3.Connection, table: str, id_col: str, id_val: str, what: str) -> sqlite3.Row:
    row = conn.execute(f"SELECT * FROM {table} WHERE {id_col} = ?", (id_val,)).fetchone()
    if row is None:
        raise NotFound(f"{what} 없음: {id_val}")
    return row


# ================================================================ 강사 · 학원
def create_teacher(conn: sqlite3.Connection, *, email: str, password: str, display_name: str,
                   org_name: str | None = None, invite_token: str | None = None,
                   now: str | None = None) -> dict:
    """
    강사 가입. 가입 화면과 운영자 명령이 같은 이 함수를 부른다.

        org_name 있음      → 새 학원(pending) 을 만들고 본인이 owner  (첫 가입자가 원장)
        invite_token 있음  → 그 학원의 teacher. 초대는 사용 처리
        둘 다 없음         → "{display_name} 선생님" 학원 + owner     (1인 강사도 학원이다)
        둘 다 있음         → ValueError (화면이 막아야 할 조합)

    반환 {"user_id", "org_id", "role"}.
    이메일이 이미 있으면 Duplicate. 초대가 없거나·만료·사용됨이면 InvalidInvite —
    이 경우 앞서 넣은 users·credentials 행은 부르는 쪽의 rollback 으로 같이 사라진다.
    """
    if org_name and invite_token:
        raise ValueError("학원명과 초대 링크는 같이 쓸 수 없다")
    email = norm_email(email)
    display_name = display_name.strip()
    if not email or not password or not display_name:
        raise ValueError("이메일 · 비밀번호 · 이름은 비울 수 없다")
    now = now or utcnow()

    user_id = new_user_id()
    try:
        conn.execute(
            "INSERT INTO users (user_id, kind, email, display_name, created_at) "
            "VALUES (?, 'teacher', ?, ?, ?)",
            (user_id, email, display_name, now))
    except sqlite3.IntegrityError as e:
        if "users.email" in str(e):
            raise Duplicate(f"이미 가입된 이메일: {email}") from None
        raise
    conn.execute(
        "INSERT INTO credentials (user_id, password_hash, must_change, updated_at) VALUES (?, ?, 0, ?)",
        (user_id, hash_password(password), now))

    if invite_token:
        inv = conn.execute(
            "SELECT org_id, used_by, expires_at FROM invites WHERE token_hash = ?",
            (token_hash(invite_token),)).fetchone()
        if inv is None or inv["used_by"] is not None or inv["expires_at"] <= now:
            raise InvalidInvite("초대 링크가 유효하지 않다")
        org_id, role = inv["org_id"], "teacher"
        conn.execute(
            "UPDATE invites SET used_by = ?, used_at = ? WHERE token_hash = ?",
            (user_id, now, token_hash(invite_token)))
    else:
        org_id, role = new_org_id(), "owner"
        name = org_name.strip() if org_name and org_name.strip() else f"{display_name} 선생님"
        conn.execute(
            "INSERT INTO orgs (org_id, name, status, created_at) VALUES (?, ?, 'pending', ?)",
            (org_id, name, now))

    conn.execute(
        "INSERT INTO org_members (org_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
        (org_id, user_id, role, now))
    return {"user_id": user_id, "org_id": org_id, "role": role}


def approve_org(conn: sqlite3.Connection, org_id: str) -> None:
    """
    학원 승인 pending → active. 운영자 명령 한 줄.
    가입은 아무나 되지만 문항 이미지는 active 뒤에만.
    이미 active 면 아무 일도 안 한다. 없으면 NotFound.
    """
    _require(conn, "orgs", "org_id", org_id, "학원")
    conn.execute("UPDATE orgs SET status = 'active' WHERE org_id = ? AND status = 'pending'", (org_id,))


def create_invite(conn: sqlite3.Connection, *, org_id: str, created_by: str,
                  email: str | None = None, days: int = INVITE_DAYS,
                  now: str | None = None) -> str:
    """
    강사 초대. 원장이 만들어 링크를 복사해 보낸다 (메일 발송은 아직 없다).
    반환은 **토큰 원문** — 링크에 실을 것. 표에는 sha256 만 들어가므로 이 반환값을 잃으면 다시 만든다.
    created_by 가 owner 인지는 부르는 쪽(auth.py) 이 본다.
    """
    _require(conn, "orgs", "org_id", org_id, "학원")
    _require(conn, "users", "user_id", created_by, "사용자")
    now = now or utcnow()
    token = new_token()
    conn.execute(
        "INSERT INTO invites (token_hash, org_id, email, created_by, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (token_hash(token), org_id, norm_email(email) if email else None,
         created_by, now, plus(now, days=days)))
    return token


# ================================================================ 반 · 명단
def _require_member(conn: sqlite3.Connection, org_id: str, user_id: str) -> None:
    """강사가 그 학원의 (나가지 않은) 구성원인지. 담당 배정은 학원 안에서만 — 데이터 정합성이지 권한 검사가 아니다."""
    _require(conn, "users", "user_id", user_id, "사용자")
    row = conn.execute(
        "SELECT 1 FROM org_members WHERE org_id = ? AND user_id = ? AND left_at IS NULL",
        (org_id, user_id)).fetchone()
    if row is None:
        raise NotFound(f"학원 {org_id} 의 구성원이 아님: {user_id}")


def create_class(conn: sqlite3.Connection, *, org_id: str, name: str,
                 teacher_id: str | None = None, subject: str = "ph1",
                 now: str | None = None) -> str:
    """
    반 하나. 시험과 집계의 단위. 반환 class_id.
    teacher_id 는 비워 둘 수 있다 (원장이 나중에 배정). 있으면 그 학원 구성원이어야 한다.
    subject('ph1'…) 가 이 반이 보는 과목 DB 를 정한다.
    """
    _require(conn, "orgs", "org_id", org_id, "학원")
    name = name.strip()
    if not name:
        raise ValueError("반 이름은 비울 수 없다")
    if teacher_id is not None:
        _require_member(conn, org_id, teacher_id)
    now = now or utcnow()
    class_id = new_class_id()
    conn.execute(
        "INSERT INTO classes (class_id, org_id, teacher_id, name, subject, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (class_id, org_id, teacher_id, name, subject, now))
    return class_id


def reassign_teacher(conn: sqlite3.Connection, class_id: str, teacher_id: str | None) -> None:
    """담당 강사 바꾸기. None 이면 담당 없음(강사 퇴사 → 원장만 보는 상태). 응답은 반에 붙어 있어 안 사라진다."""
    cls = _require(conn, "classes", "class_id", class_id, "반")
    if teacher_id is not None:
        _require_member(conn, cls["org_id"], teacher_id)
    conn.execute("UPDATE classes SET teacher_id = ? WHERE class_id = ?", (teacher_id, class_id))


def enroll_students(conn: sqlite3.Connection, class_id: str, rows: list[dict], *,
                    must_change: int = 1, now: str | None = None) -> list[dict]:
    """
    명단 등록. rows = [{"display_name", "school"?, "entry_year"?, "phone"?, "user_id"?}, ...]

    행마다
      user_id 없음 → 새 학생: users(student, 키 6자) + credentials(임시 4자리, must_change) + class_members
      user_id 있음 → 이미 있는 학생을 이 반에도 (개념반 학생을 문제풀이반에). 계정·비밀번호는 안 건드린다
    반환 [{"user_id", "login_key", "pin", "display_name"}, ...] 입력 순서대로.
      ★ 평문 pin 은 여기에만 있다. 새 학생만 pin 이 있고, 기존 학생은 None.
        부르는 쪽은 이걸 학생에게 한 번 전달(쪽지)하고 보관하지 않는다. 로그에 찍지 않는다.
      must_change=1 이면 학생이 첫 로그인에 자기 것으로 바꾼다 → 그 뒤로는 강사도 모른다.

    한 행이라도 잘못되면(이름 비움, 입학연도 범위 밖, 같은 반 중복) 예외 → 부르는 쪽 rollback 으로
    **전부 안 들어간다.** 명단 반쪽만 들어가는 것보다 강사가 고쳐서 다시 올리는 게 낫다.
    """
    cls = _require(conn, "classes", "class_id", class_id, "반")
    if cls["archived_at"] is not None:
        raise ValueError(f"닫힌 반에는 등록할 수 없다: {class_id}")
    now = now or utcnow()
    out = []
    for i, row in enumerate(rows, 1):
        display_name = (row.get("display_name") or "").strip()
        if not display_name:
            raise ValueError(f"{i}번째 행: 이름이 비었다")
        school = (row.get("school") or "").strip() or None
        phone = (row.get("phone") or "").strip() or None
        entry_year = row.get("entry_year")
        if entry_year is not None:
            try:
                entry_year = int(entry_year)
            except (TypeError, ValueError):
                raise ValueError(f"{i}번째 행 ({display_name}): 입학연도가 숫자가 아니다: {entry_year!r}") from None
            # 스키마의 CHECK 와 같은 범위. 여기서 먼저 걸러야 메시지에 행 번호를 실을 수 있다
            # (SQLite 의 CHECK 오류 문장은 버전마다 달라 파싱할 수 없다)
            if not 2000 <= entry_year <= 2100:
                raise ValueError(f"{i}번째 행 ({display_name}): 입학연도 범위 밖: {entry_year}")

        user_id, key, pin = row.get("user_id"), None, None
        if user_id:
            u = _require(conn, "users", "user_id", user_id, "사용자")
            if u["kind"] != "student":
                raise ValueError(f"{i}번째 행 ({display_name}): 학생 계정이 아니다 ({u['kind']}). "
                                 f"게스트는 promote_guest 로")
            key = u["login_key"]
        else:
            user_id, key = _insert_user_with_key(conn, kind="student", created_at=now)
            pin = new_pin()
            conn.execute(
                "INSERT INTO credentials (user_id, password_hash, must_change, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, hash_password(pin), must_change, now))
        try:
            conn.execute(
                "INSERT INTO class_members (class_id, user_id, display_name, school, entry_year, phone, joined_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (class_id, user_id, display_name, school, entry_year, phone, now))
        except sqlite3.IntegrityError as e:
            # 이 INSERT 의 UNIQUE 는 PK(class_id, user_id) 하나뿐이다
            if "UNIQUE" in str(e):
                raise Duplicate(f"{i}번째 행 ({display_name}): 이미 이 반에 있다") from None
            raise
        out.append({"user_id": user_id, "login_key": key, "pin": pin, "display_name": display_name})
    return out


def withdraw_student(conn: sqlite3.Connection, class_id: str, user_id: str, *,
                     now: str | None = None) -> None:
    """퇴원 — class_members.left_at 을 채운다. 행은 남긴다(응답 이력). 이미 나갔으면 조용히. 소속이 없으면 NotFound."""
    row = conn.execute(
        "SELECT left_at FROM class_members WHERE class_id = ? AND user_id = ?",
        (class_id, user_id)).fetchone()
    if row is None:
        raise NotFound(f"반 {class_id} 에 없는 학생: {user_id}")
    if row["left_at"] is None:
        conn.execute("UPDATE class_members SET left_at = ? WHERE class_id = ? AND user_id = ?",
                     (now or utcnow(), class_id, user_id))


# ================================================================ 로그인 · 비밀번호
def _user_dict(u: sqlite3.Row, must_change: int = 0) -> dict:
    """login · get_session_user 가 돌려주는 모양. 비밀번호 해시는 절대 안 싣는다."""
    return {"user_id": u["user_id"], "kind": u["kind"], "login_key": u["login_key"],
            "email": u["email"], "display_name": u["display_name"], "is_admin": u["is_admin"],
            "must_change": int(must_change or 0)}


def _record_failure(conn: sqlite3.Connection, user_id: str, failed_count: int, now: str) -> None:
    """
    연속 실패 +1. LOCK_AFTER 회부터 잠근다: 1분, 그 뒤 실패마다 두 배, 최대 60분.
    4자리는 경우의 수가 만 개라 로그인 창에서 두드리는 걸 이걸로 막는다 (해시는 파일이 샜을 때의 방어).
    """
    failed_count += 1
    locked_until = None
    if failed_count >= LOCK_AFTER:
        minutes = min(LOCK_BASE_MINUTES * 2 ** (failed_count - LOCK_AFTER), LOCK_MAX_MINUTES)
        locked_until = plus(now, minutes=minutes)
    conn.execute("UPDATE credentials SET failed_count = ?, locked_until = ? WHERE user_id = ?",
                 (failed_count, locked_until, user_id))


def _check_lock(cred: sqlite3.Row, now: str) -> None:
    if cred["locked_until"] is not None and cred["locked_until"] > now:
        raise Locked(cred["locked_until"])


def login(conn: sqlite3.Connection, *, password: str | None = None,
          login_key: str | None = None, email: str | None = None,
          now: str | None = None) -> dict | None:
    """
    로그인. 학생·게스트는 login_key 로, 강사는 email 로.

        맞음     → 사용자 dict (must_change 포함). failed_count 는 0 으로
        틀림     → **None** — 예외가 아니다. failed_count 를 올려 저장해야 하는데,
                   예외로 나가면 부르는 쪽의 with conn: 이 rollback 해서 잠금이 영원히 안 걸린다
        잠금 중  → Locked (아무것도 안 쓰니 rollback 돼도 잃을 게 없다)
        없는 키 · 비활성 계정 · 만료된 게스트 → None. 어느 경우인지 말하지 않는다

    게스트는 비밀번호가 없다 — 키만 맞고 expires_at 이 안 지났으면 통과.
    세션은 여기서 안 만든다. 부르는 쪽(auth.py)이 성공 뒤 create_session 을 부른다.
    """
    now = now or utcnow()
    u = find_user(conn, login_key=login_key, email=email)
    if u is None or u["status"] != "active":
        return None
    if u["kind"] == "guest":
        if u["expires_at"] is not None and u["expires_at"] <= now:
            return None
        return _user_dict(u)
    cred = conn.execute("SELECT * FROM credentials WHERE user_id = ?", (u["user_id"],)).fetchone()
    if cred is None or password is None:
        return None
    _check_lock(cred, now)
    if not verify_hash(cred["password_hash"], password):
        _record_failure(conn, u["user_id"], cred["failed_count"], now)
        return None
    if cred["failed_count"] or cred["locked_until"]:
        conn.execute("UPDATE credentials SET failed_count = 0, locked_until = NULL WHERE user_id = ?",
                     (u["user_id"],))
    return _user_dict(u, cred["must_change"])


def change_password(conn: sqlite3.Connection, user_id: str, old: str, new: str, *,
                    keep_session: str | None = None, now: str | None = None) -> bool:
    """
    본인이 비밀번호를 바꾼다 (임시 4자리 → 자기 것). 성공하면 must_change=0.

        맞음 → True. 다른 기기의 세션은 전부 삭제, keep_session(지금 쿠키의 원문)만 남긴다
        옛 비밀번호 틀림 → **False** (login 과 같은 잠금 카운트 — 로그인된 상태에서도 만 번 두드릴 수 있다)
        잠금 중 → Locked
    new 는 4자 이상. 뻔한 값(0000·1234) 거부는 화면 몫.
    """
    if not new or len(new) < 4:
        raise ValueError("새 비밀번호는 4자 이상")
    now = now or utcnow()
    cred = conn.execute("SELECT * FROM credentials WHERE user_id = ?", (user_id,)).fetchone()
    if cred is None:
        raise NotFound(f"비밀번호가 없는 계정: {user_id}")
    _check_lock(cred, now)
    if not verify_hash(cred["password_hash"], old):
        _record_failure(conn, user_id, cred["failed_count"], now)
        return False
    conn.execute(
        "UPDATE credentials SET password_hash = ?, must_change = 0, failed_count = 0, locked_until = NULL, "
        "updated_at = ? WHERE user_id = ?",
        (hash_password(new), now, user_id))
    delete_sessions(conn, user_id, keep=keep_session)
    return True


def reset_password(conn: sqlite3.Connection, user_id: str, *, now: str | None = None) -> str:
    """
    강사(또는 운영자)가 학생 비밀번호를 재설정. 새 임시 4자리, must_change=1, 잠금 해제, 세션 전부 삭제.
    반환은 **평문 pin** — 학생에게 한 번 전달하고 끝. 로그에 찍지 않는다.
    "이 강사가 이 학생 반의 담당인가" 는 부르는 쪽(auth.py) 이 본다.
    """
    _require(conn, "credentials", "user_id", user_id, "비밀번호가 있는 계정")
    now = now or utcnow()
    pin = new_pin()
    conn.execute(
        "UPDATE credentials SET password_hash = ?, must_change = 1, failed_count = 0, locked_until = NULL, "
        "updated_at = ? WHERE user_id = ?",
        (hash_password(pin), now, user_id))
    delete_sessions(conn, user_id)
    return pin


def set_password(conn: sqlite3.Connection, user_id: str, password: str, *, must_change: int = 0,
                 now: str | None = None) -> None:
    """
    운영자용: 비밀번호를 정해진 값으로. reset_password 와 달리 값을 부르는 쪽이 정하고 must_change 도 고른다.
    쓰는 곳은 개발자 모드 seed(학생 비밀번호 1234) 와 CLI — 서비스 화면에서는 쓰지 않는다 (강사는 reset_password).
    잠금 해제 + 세션 전부 삭제는 같다. 4자 미만은 ValueError.
    """
    if len(password) < 4:
        raise ValueError("비밀번호는 4자 이상")
    _require(conn, "credentials", "user_id", user_id, "비밀번호가 있는 계정")
    conn.execute(
        "UPDATE credentials SET password_hash = ?, must_change = ?, failed_count = 0, locked_until = NULL, "
        "updated_at = ? WHERE user_id = ?",
        (hash_password(password), int(bool(must_change)), now or utcnow(), user_id))
    delete_sessions(conn, user_id)


def set_admin(conn: sqlite3.Connection, user_id: str, on: bool = True) -> None:
    """운영자 플래그 (users.is_admin). 역할이 아니라 플래그 하나 — 서버 권한 검사가 전부 통과한다. 운영자 명령으로만."""
    _require(conn, "users", "user_id", user_id, "사용자")
    conn.execute("UPDATE users SET is_admin = ? WHERE user_id = ?", (1 if on else 0, user_id))


# ================================================================ 세션 (표 층. 쿠키는 serve/auth.py)
def create_session(conn: sqlite3.Connection, user_id: str, *, days: int = SESSION_DAYS,
                   user_agent: str | None = None, now: str | None = None) -> str:
    """
    로그인 성공 뒤. 반환은 **세션 원문**(쿠키에 실을 것). 표에는 sha256 만 — 파일이 새도 세션을 못 쓴다.
    만료 = min(days 뒤, users.expires_at) — 14일짜리 게스트가 13일째 로그인해도 세션이 14일에 끝난다.
    """
    u = _require(conn, "users", "user_id", user_id, "사용자")
    if u["status"] != "active":
        raise AccountsError(f"비활성 계정: {user_id}")
    now = now or utcnow()
    expires = plus(now, days=days)
    if u["expires_at"] is not None and u["expires_at"] < expires:
        expires = u["expires_at"]
    token = new_token()
    conn.execute(
        "INSERT INTO sessions (session_hash, user_id, created_at, expires_at, user_agent) VALUES (?, ?, ?, ?, ?)",
        (token_hash(token), user_id, now, expires, user_agent))
    return token


def get_session_user(conn: sqlite3.Connection, session: str, *, now: str | None = None) -> dict | None:
    """
    쿠키의 원문 → 누구인가. 읽기만 한다 (요청마다 불리므로 쓰지 않는다).
    세션 만료 · 계정 비활성 · 게스트 만료면 None. dict 에 must_change 와 session_expires_at 을 싣는다 —
    must_change=1 인 사람을 비밀번호 변경 화면 밖으로 못 나가게 막는 건 auth.py 가 한다.
    """
    now = now or utcnow()
    row = conn.execute(
        "SELECT s.expires_at AS session_expires_at, u.*, c.must_change "
        "FROM sessions s JOIN users u ON u.user_id = s.user_id "
        "LEFT JOIN credentials c ON c.user_id = u.user_id "
        "WHERE s.session_hash = ?",
        (token_hash(session),)).fetchone()
    if row is None or row["session_expires_at"] <= now or row["status"] != "active":
        return None
    if row["kind"] == "guest" and row["expires_at"] is not None and row["expires_at"] <= now:
        return None
    out = _user_dict(row, row["must_change"])
    out["session_expires_at"] = row["session_expires_at"]
    return out


def delete_session(conn: sqlite3.Connection, session: str) -> None:
    """로그아웃 — 이 세션 하나."""
    conn.execute("DELETE FROM sessions WHERE session_hash = ?", (token_hash(session),))


def delete_sessions(conn: sqlite3.Connection, user_id: str, *, keep: str | None = None) -> int:
    """이 사용자의 세션 전부 (keep 원문 하나만 남기고). 강제 로그아웃. 반환 지운 수."""
    if keep is None:
        cur = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    else:
        cur = conn.execute("DELETE FROM sessions WHERE user_id = ? AND session_hash != ?",
                           (user_id, token_hash(keep)))
    return cur.rowcount


def purge_expired_sessions(conn: sqlite3.Connection, *, now: str | None = None) -> int:
    """만료된 세션 행 정리. 가끔 돌리는 유지보수 (CLI). 안 돌려도 동작엔 영향 없다 — 조회가 만료를 본다."""
    return conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now or utcnow(),)).rowcount


# ================================================================ 게스트 · 키 재발급
def issue_guest(conn: sqlite3.Connection, *, org_id: str | None = None, days: int = GUEST_DAYS,
                now: str | None = None) -> dict:
    """
    임시 키 발급. 비밀번호 없음, expires_at 로 막는다.
        org_id 있음 → 입회 테스트 (학원이 발급). issued_by_org 에 남는다
        org_id 없음 → 블로그 무료 테스트 (우리가 발급)
    반환 {"user_id", "login_key", "expires_at"}. 정식 등록은 promote_guest — 같은 user_id 라 응답이 이어진다.
    """
    if org_id is not None:
        _require(conn, "orgs", "org_id", org_id, "학원")
    now = now or utcnow()
    expires = plus(now, days=days)
    user_id, key = _insert_user_with_key(conn, kind="guest", created_at=now,
                                         expires_at=expires, issued_by_org=org_id)
    return {"user_id": user_id, "login_key": key, "expires_at": expires}


def promote_guest(conn: sqlite3.Connection, user_id: str, class_id: str, display_name: str, *,
                  school: str | None = None, entry_year: int | None = None, phone: str | None = None,
                  must_change: int = 1, now: str | None = None) -> dict:
    """
    게스트 → 학생 승격. **같은 user_id** 를 kind='student' 로 바꾸고 임시 4자리를 만들고 반에 넣는다.
    새 계정을 만들지 않으므로 입회 테스트 응답(responses.db 의 student_id = 이 user_id)이 첫 진단 회차가 된다.
    키는 그대로 (학생이 이미 외웠다). 게스트 세션은 지운다 — 비밀번호 없이 만든 세션이라 다시 로그인하게.
    반환은 enroll_students 와 같은 모양 {"user_id", "login_key", "pin", "display_name"}. 평문 pin 은 여기에만.
    """
    u = _require(conn, "users", "user_id", user_id, "사용자")
    if u["kind"] != "guest":
        raise ValueError(f"게스트가 아니다 ({u['kind']}): {user_id}")
    if u["status"] != "active":
        raise ValueError(f"비활성 계정: {user_id}")
    now = now or utcnow()
    # CHECK (kind = 'guest' OR expires_at IS NULL) — 만료를 지워야 학생이 될 수 있다. issued_by_org 는 이력으로 남긴다
    conn.execute("UPDATE users SET kind = 'student', expires_at = NULL WHERE user_id = ?", (user_id,))
    pin = new_pin()
    conn.execute(
        "INSERT INTO credentials (user_id, password_hash, must_change, updated_at) VALUES (?, ?, ?, ?)",
        (user_id, hash_password(pin), must_change, now))
    delete_sessions(conn, user_id)
    row = {"display_name": display_name, "school": school, "entry_year": entry_year, "phone": phone,
           "user_id": user_id}
    out = enroll_students(conn, class_id, [row], now=now)[0]     # 반 검사·이름 정리·중복 검사를 재사용
    out["pin"] = pin
    return out


def reissue_key(conn: sqlite3.Connection, user_id: str) -> str:
    """
    학생·게스트의 login_key 를 새로. user_id 는 그대로라 응답·진단 이력이 안 끊긴다.
    쪽지를 잃었거나 남이 키로 장난칠 때. 세션은 안 지운다 — 키는 ID 이지 비밀이 아니다.
    강사는 email 로 들어오므로 대상이 아니다 (ValueError).
    ※ 답안지 QR 은 login_key 가 아니라 user_id 를 담아야 하는 이유가 이 함수다.
    """
    u = _require(conn, "users", "user_id", user_id, "사용자")
    if u["kind"] == "teacher":
        raise ValueError(f"강사는 키가 없다: {user_id}")
    for _ in range(KEY_RETRIES):
        key = new_key()
        try:
            conn.execute("UPDATE users SET login_key = ? WHERE user_id = ?", (key, user_id))
            return key
        except sqlite3.IntegrityError as e:
            if "users.login_key" not in str(e):
                raise
    raise Duplicate("login_key 를 5번 만들어도 겹쳤다 — 있을 수 없는 일이라 확인이 필요하다")


# ================================================================ 권한 재료 (판단은 serve/auth.py)
def is_owner(conn: sqlite3.Connection, user_id: str, org_id: str) -> bool:
    """이 학원의 원장인가. 나간 사람(left_at)은 아니다."""
    return conn.execute(
        "SELECT 1 FROM org_members WHERE org_id = ? AND user_id = ? AND role = 'owner' AND left_at IS NULL",
        (org_id, user_id)).fetchone() is not None


def is_class_teacher(conn: sqlite3.Connection, user_id: str, class_id: str) -> bool:
    """이 반의 담당 강사인가. 원장이 담당이면 원장도 True — 원장도 반을 맡을 수 있다."""
    return conn.execute(
        "SELECT 1 FROM classes WHERE class_id = ? AND teacher_id = ?",
        (class_id, user_id)).fetchone() is not None


# ================================================================ 조회
def load_user(conn: sqlite3.Connection, user_id: str) -> dict | None:
    """user_id 로 계약 모양 dict (login·get_session_user 와 같은 키). 세션 없이 사용자를 집는 운영자 경로용. 없으면 None."""
    row = conn.execute(
        "SELECT u.*, c.must_change FROM users u LEFT JOIN credentials c ON c.user_id = u.user_id WHERE u.user_id = ?",
        (user_id,)).fetchone()
    return None if row is None else _user_dict(row, row["must_change"])


def find_user(conn: sqlite3.Connection, *, login_key: str | None = None,
              email: str | None = None) -> sqlite3.Row | None:
    """키 또는 이메일로 users 행 하나. 둘 다 없거나 둘 다 있으면 ValueError."""
    if (login_key is None) == (email is None):
        raise ValueError("login_key 또는 email 중 하나만")
    if login_key is not None:
        return conn.execute("SELECT * FROM users WHERE login_key = ?", (norm_key(login_key),)).fetchone()
    return conn.execute("SELECT * FROM users WHERE email = ?", (norm_email(email),)).fetchone()


def verify_password(conn: sqlite3.Connection, user_id: str, password: str) -> bool:
    """비밀번호가 맞나. 잠금·실패 횟수는 안 건드린다 — 그건 login() 의 일."""
    row = conn.execute("SELECT password_hash FROM credentials WHERE user_id = ?", (user_id,)).fetchone()
    return row is not None and verify_hash(row["password_hash"], password)


# ================================================================ CLI — 운영자 명령 (권한 검사 없음)
def _open_db(path: Path | None) -> sqlite3.Connection:
    """--db 가 없으면 data/accounts.db. 없으면 만든다 (스키마에 DROP 이 없어 안전)."""
    p = path or accounts_db()
    if not p.is_file():
        init_accounts_db(path=p)
        print(f"새 DB 를 만들었다: {p}")
    return connect(p)


def _print_slips(rows: list[dict]) -> None:
    """키 + 임시 pin 표. 운영자에게 한 번 보여 주는 것 — 이 출력을 파일·로그에 남기지 말 것."""
    print(f"{'이름':10s} {'키':8s} {'임시 비밀번호':8s} user_id")
    for r in rows:
        print(f"{r['display_name']:10s} {r['login_key']:8s} {(r['pin'] or '(기존)'):8s} {r['user_id']}")
    print("※ 임시 비밀번호는 다시 볼 수 없다. 잃으면 reset-password.")


def _cmd_add_teacher(conn, a):
    pw = a.password or getpass.getpass("비밀번호: ")
    r = create_teacher(conn, email=a.email, password=pw, display_name=a.name,
                       org_name=a.org, invite_token=a.invite)
    print(f"user_id {r['user_id']}  org_id {r['org_id']}  role {r['role']}")


def _cmd_approve_org(conn, a):
    approve_org(conn, a.org_id)
    print(f"active: {a.org_id}")


def _cmd_invite(conn, a):
    token = create_invite(conn, org_id=a.org_id, created_by=a.by, email=a.email, days=a.days)
    print(f"초대 토큰 (링크에 붙일 것. 표엔 해시만 있어 다시 못 본다):\n{token}")


def _cmd_add_class(conn, a):
    cid = create_class(conn, org_id=a.org_id, name=a.name, teacher_id=a.teacher, subject=a.subject)
    print(f"class_id {cid}")


def _cmd_add_students(conn, a):
    with open(a.csv, encoding="utf-8-sig", newline="") as f:      # -sig: 엑셀이 붙이는 BOM 을 벗긴다
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"빈 CSV: {a.csv}")
    out = enroll_students(conn, a.class_id, rows)
    _print_slips(out)


def _cmd_withdraw(conn, a):
    withdraw_student(conn, a.class_id, a.user_id)
    print(f"퇴원 처리: {a.user_id} ← {a.class_id}")


def _cmd_reassign(conn, a):
    reassign_teacher(conn, a.class_id, a.teacher)
    print(f"담당: {a.teacher or '(없음)'} → {a.class_id}")


def _cmd_reset_password(conn, a):
    pin = reset_password(conn, a.user_id)
    print(f"임시 비밀번호 {pin}  (다시 볼 수 없다. 세션 전부 삭제됨)")


def _cmd_reissue_key(conn, a):
    print(f"새 키 {reissue_key(conn, a.user_id)}")


def _cmd_admin(conn, a):
    u = find_user(conn, email=a.who) if "@" in a.who else find_user(conn, login_key=a.who)
    if u is None:
        raise NotFound(f"없는 사용자: {a.who}")
    set_admin(conn, u["user_id"], not a.off)
    print(f"{u['user_id']} ({u['display_name']}) is_admin = {0 if a.off else 1}")


def _cmd_issue_guest(conn, a):
    r = issue_guest(conn, org_id=a.org, days=a.days)
    print(f"게스트 키 {r['login_key']}  만료 {r['expires_at']}  user_id {r['user_id']}")


def _cmd_promote_guest(conn, a):
    out = promote_guest(conn, a.user_id, a.class_id, a.name,
                        school=a.school, entry_year=a.year, phone=a.phone)
    _print_slips([out])


def _cmd_purge_sessions(conn, a):
    print(f"만료 세션 {purge_expired_sessions(conn)}건 삭제")


def _cmd_ls(conn, a):
    orgs = conn.execute("SELECT * FROM orgs ORDER BY created_at").fetchall()
    if not orgs:
        print("(학원 없음)")
    for o in orgs:
        members = conn.execute(
            "SELECT u.user_id, u.display_name, u.email, m.role FROM org_members m JOIN users u USING (user_id) "
            "WHERE m.org_id = ? AND m.left_at IS NULL ORDER BY m.role, m.joined_at", (o["org_id"],)).fetchall()
        print(f"{o['org_id']}  {o['name']}  [{o['status']}]")
        for m in members:
            print(f"    {m['role']:8s} {m['display_name']}  {m['email']}  {m['user_id']}")
        for c in conn.execute("SELECT * FROM classes WHERE org_id = ? ORDER BY created_at", (o["org_id"],)):
            n = conn.execute("SELECT COUNT(*) FROM class_members WHERE class_id = ? AND left_at IS NULL",
                             (c["class_id"],)).fetchone()[0]
            print(f"    반 {c['class_id']}  {c['name']}  ({c['subject']}, 학생 {n}, 담당 {c['teacher_id'] or '없음'})")
    n_guest = conn.execute("SELECT COUNT(*) FROM users WHERE kind = 'guest'").fetchone()[0]
    n_sess = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    print(f"게스트 {n_guest}  세션 {n_sess}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pl-accounts",
                                 description="계정·학원·반·명단 운영자 명령. 권한 검사 없음 — 서버 관리자만 쓴다.")
    ap.add_argument("--db", type=Path, default=None, help="기본 data/accounts.db. 없으면 만든다")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add-teacher", help="강사 가입 (학원명 → 원장 / 초대 → 강사 / 둘 다 없음 → 1인 학원)")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True, help="표시 이름")
    p.add_argument("--org", help="새 학원 이름")
    p.add_argument("--invite", help="초대 토큰")
    p.add_argument("--password", help="없으면 물어본다")
    p.set_defaults(func=_cmd_add_teacher)

    p = sub.add_parser("approve-org", help="학원 승인 pending → active")
    p.add_argument("org_id")
    p.set_defaults(func=_cmd_approve_org)

    p = sub.add_parser("invite", help="강사 초대 토큰")
    p.add_argument("org_id")
    p.add_argument("--by", required=True, help="만드는 사람 user_id (원장)")
    p.add_argument("--email")
    p.add_argument("--days", type=int, default=INVITE_DAYS)
    p.set_defaults(func=_cmd_invite)

    p = sub.add_parser("add-class", help="반 만들기")
    p.add_argument("org_id")
    p.add_argument("name")
    p.add_argument("--teacher", help="담당 강사 user_id")
    p.add_argument("--subject", default="ph1")
    p.set_defaults(func=_cmd_add_class)

    p = sub.add_parser("add-students", help="명단 CSV → 계정·키·임시 비밀번호")
    p.add_argument("class_id")
    p.add_argument("--csv", required=True, type=Path,
                   help="열: display_name, school, entry_year, phone (user_id 가 있으면 기존 학생을 이 반에도)")
    p.set_defaults(func=_cmd_add_students)

    p = sub.add_parser("withdraw", help="퇴원")
    p.add_argument("class_id")
    p.add_argument("user_id")
    p.set_defaults(func=_cmd_withdraw)

    p = sub.add_parser("reassign", help="담당 강사 변경 (--teacher 없으면 담당 없음)")
    p.add_argument("class_id")
    p.add_argument("--teacher")
    p.set_defaults(func=_cmd_reassign)

    p = sub.add_parser("reset-password", help="새 임시 4자리 + 강제 로그아웃")
    p.add_argument("user_id")
    p.set_defaults(func=_cmd_reset_password)

    p = sub.add_parser("admin", help="운영자 플래그 켜기 (--off 로 끄기). 이메일 또는 키로")
    p.add_argument("who", help="이메일(강사) 또는 로그인 키")
    p.add_argument("--off", action="store_true")
    p.set_defaults(func=_cmd_admin)

    p = sub.add_parser("reissue-key", help="새 로그인 키 (user_id 는 그대로)")
    p.add_argument("user_id")
    p.set_defaults(func=_cmd_reissue_key)

    p = sub.add_parser("issue-guest", help="임시 키 (입회 테스트는 --org, 블로그는 없이)")
    p.add_argument("--org")
    p.add_argument("--days", type=int, default=GUEST_DAYS)
    p.set_defaults(func=_cmd_issue_guest)

    p = sub.add_parser("promote-guest", help="게스트 → 학생 (같은 user_id)")
    p.add_argument("user_id")
    p.add_argument("class_id")
    p.add_argument("name")
    p.add_argument("--school")
    p.add_argument("--year", type=int, help="입학 연도")
    p.add_argument("--phone")
    p.set_defaults(func=_cmd_promote_guest)

    p = sub.add_parser("purge-sessions", help="만료 세션 정리")
    p.set_defaults(func=_cmd_purge_sessions)

    p = sub.add_parser("ls", help="학원·구성원·반 한눈에")
    p.set_defaults(func=_cmd_ls)

    a = ap.parse_args(argv)
    conn = _open_db(a.db)
    try:
        with conn:                          # 명령 하나 = 트랜잭션 하나
            a.func(conn, a)
        return 0
    except (AccountsError, ValueError, FileNotFoundError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
