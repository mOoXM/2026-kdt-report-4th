"""
accounts.py — 함수가 설계대로 만들고·거부하고·되돌리는지.
tmp_path 에 새 DB. data/ 불필요. 시각은 T 로 고정해서 만료 계산을 정확히 잰다.
"""
import re

import pytest

from physics_lab import accounts as A
from physics_lab import db

T = "2026-09-28T04:00:00Z"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(db.init_accounts_db(path=tmp_path / "accounts.db"))
    yield c
    c.close()


def _owner(conn, email="o@x.kr", org="물리학원"):
    with conn:
        return A.create_teacher(conn, email=email, password="pw-owner", display_name="원장", org_name=org, now=T)


# ---------------------------------------------------------------- 값 만들기
def test_generators_shape():
    assert re.fullmatch(r"[23456789A-HJ-NP-Z]{6}", A.new_key())
    assert re.fullmatch(r"u_[23456789A-HJ-NP-Z]{12}", A.new_user_id())
    assert re.fullmatch(r"o_[23456789A-HJ-NP-Z]{10}", A.new_org_id())
    assert re.fullmatch(r"c_[23456789A-HJ-NP-Z]{10}", A.new_class_id())
    assert re.fullmatch(r"[0-9]{4}", A.new_pin()) and isinstance(A.new_pin(), str)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", A.utcnow())
    assert A.plus(T, days=7) == "2026-10-05T04:00:00Z"
    assert A.plus(T, minutes=90) == "2026-09-28T05:30:00Z"
    assert len(A.token_hash("x")) == 64


def test_password_hash_roundtrip():
    h = A.hash_password("4821")
    assert h.startswith("$argon2id$") and "4821" not in h
    assert A.verify_hash(h, "4821") is True
    assert A.verify_hash(h, "4822") is False
    assert A.verify_hash("깨진 해시", "4821") is False


# ---------------------------------------------------------------- create_teacher
def test_create_teacher_with_org_name(conn):
    r = _owner(conn)
    assert r["role"] == "owner" and r["user_id"].startswith("u_") and r["org_id"].startswith("o_")
    org = conn.execute("SELECT name, status FROM orgs WHERE org_id=?", (r["org_id"],)).fetchone()
    assert (org["name"], org["status"]) == ("물리학원", "pending")
    mem = conn.execute("SELECT role FROM org_members WHERE org_id=? AND user_id=?",
                       (r["org_id"], r["user_id"])).fetchone()
    assert mem["role"] == "owner"
    cred = conn.execute("SELECT must_change FROM credentials WHERE user_id=?", (r["user_id"],)).fetchone()
    assert cred["must_change"] == 0                     # 강사는 자기가 정한 비밀번호라 변경 강제 없음
    assert A.verify_password(conn, r["user_id"], "pw-owner")
    assert not A.verify_password(conn, r["user_id"], "wrong")


def test_create_teacher_solo_makes_own_org(conn):
    with conn:
        r = A.create_teacher(conn, email="solo@x.kr", password="p", display_name=" 김지수 ", now=T)
    name = conn.execute("SELECT name FROM orgs WHERE org_id=?", (r["org_id"],)).fetchone()["name"]
    assert name == "김지수 선생님" and r["role"] == "owner"


def test_email_is_normalized_and_unique(conn):
    _owner(conn, email="Owner@X.kr")
    assert A.find_user(conn, email="owner@x.kr") is not None
    assert A.find_user(conn, email="OWNER@x.KR") is not None
    with pytest.raises(A.Duplicate):
        with conn:
            A.create_teacher(conn, email="owner@x.kr", password="p", display_name="b", org_name="다른학원", now=T)


def test_org_name_and_invite_together_is_error(conn):
    with pytest.raises(ValueError):
        A.create_teacher(conn, email="a@x.kr", password="p", display_name="a", org_name="x", invite_token="t")


def test_empty_fields_rejected(conn):
    with pytest.raises(ValueError):
        A.create_teacher(conn, email=" ", password="p", display_name="a")
    with pytest.raises(ValueError):
        A.create_teacher(conn, email="a@x.kr", password="", display_name="a")


# ---------------------------------------------------------------- 초대
def test_invite_flow(conn):
    o = _owner(conn)
    with conn:
        token = A.create_invite(conn, org_id=o["org_id"], created_by=o["user_id"], email="T@x.kr", now=T)
    assert len(token) >= 40
    row = conn.execute("SELECT * FROM invites").fetchone()
    assert row["token_hash"] == A.token_hash(token) and token not in row["token_hash"]
    assert row["email"] == "t@x.kr" and row["expires_at"] == A.plus(T, days=7) and row["used_by"] is None

    with conn:
        t = A.create_teacher(conn, email="t@x.kr", password="p", display_name="강사",
                             invite_token=token, now=A.plus(T, days=1))
    assert t["org_id"] == o["org_id"] and t["role"] == "teacher"
    row = conn.execute("SELECT used_by, used_at FROM invites").fetchone()
    assert row["used_by"] == t["user_id"] and row["used_at"] == A.plus(T, days=1)
    assert conn.execute("SELECT COUNT(*) FROM orgs").fetchone()[0] == 1     # 학원이 늘지 않았다

    # 한 번 쓴 초대는 끝
    with pytest.raises(A.InvalidInvite):
        with conn:
            A.create_teacher(conn, email="t2@x.kr", password="p", display_name="x", invite_token=token, now=T)


def test_invite_expired_or_unknown(conn):
    o = _owner(conn)
    with conn:
        token = A.create_invite(conn, org_id=o["org_id"], created_by=o["user_id"], days=7, now=T)
    with pytest.raises(A.InvalidInvite):
        with conn:
            A.create_teacher(conn, email="late@x.kr", password="p", display_name="x",
                             invite_token=token, now=A.plus(T, days=7))      # 정확히 만료 시각 = 무효
    with pytest.raises(A.InvalidInvite):
        with conn:
            A.create_teacher(conn, email="x@x.kr", password="p", display_name="x", invite_token="없는토큰", now=T)


def test_invite_requires_existing_org_and_user(conn):
    o = _owner(conn)
    with pytest.raises(A.NotFound):
        A.create_invite(conn, org_id="o_none", created_by=o["user_id"])
    with pytest.raises(A.NotFound):
        A.create_invite(conn, org_id=o["org_id"], created_by="u_none")


# ---------------------------------------------------------------- 트랜잭션 (지키는 것 1)
def test_failed_signup_leaves_nothing(conn):
    """초대가 무효라 InvalidInvite 가 나면, 그 전에 넣은 users·credentials 도 rollback 으로 사라져야 한다."""
    _owner(conn)
    with pytest.raises(A.InvalidInvite):
        with conn:
            A.create_teacher(conn, email="half@x.kr", password="p", display_name="반쪽", invite_token="bad", now=T)
    assert A.find_user(conn, email="half@x.kr") is None
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0] == 1


# ---------------------------------------------------------------- approve_org
def test_approve_org(conn):
    o = _owner(conn)
    with conn:
        A.approve_org(conn, o["org_id"])
    assert conn.execute("SELECT status FROM orgs WHERE org_id=?", (o["org_id"],)).fetchone()["status"] == "active"
    with conn:
        A.approve_org(conn, o["org_id"])                # 두 번 해도 조용히
    with pytest.raises(A.NotFound):
        A.approve_org(conn, "o_none")


# ---------------------------------------------------------------- find_user
def test_find_user_argument_rules(conn):
    with pytest.raises(ValueError):
        A.find_user(conn)
    with pytest.raises(ValueError):
        A.find_user(conn, login_key="A", email="b")
    assert A.find_user(conn, login_key="nope") is None


# ================================================================ 덩어리 2 — 반 · 명단
def _org_with_class(conn):
    o = _owner(conn)
    with conn:
        A.approve_org(conn, o["org_id"])
        cid = A.create_class(conn, org_id=o["org_id"], name="물리 개념반", teacher_id=o["user_id"], now=T)
    return o, cid


ROWS = [
    {"display_name": "이하은", "school": "부산고", "entry_year": 2025, "phone": "010-1"},
    {"display_name": " 김민준 ", "school": "", "entry_year": "2024"},        # 공백·문자열 연도도 받는다
    {"display_name": "박서연"},
]


def test_create_class(conn):
    o, cid = _org_with_class(conn)
    assert cid.startswith("c_")
    row = conn.execute("SELECT * FROM classes WHERE class_id=?", (cid,)).fetchone()
    assert (row["org_id"], row["teacher_id"], row["name"], row["subject"]) == (o["org_id"], o["user_id"], "물리 개념반", "ph1")
    with conn:                                                               # 담당 없이도 만들 수 있다
        c2 = A.create_class(conn, org_id=o["org_id"], name="문제풀이반", now=T)
    assert conn.execute("SELECT teacher_id FROM classes WHERE class_id=?", (c2,)).fetchone()["teacher_id"] is None


def test_create_class_rejects(conn):
    o = _owner(conn)
    with pytest.raises(A.NotFound):
        A.create_class(conn, org_id="o_none", name="x")
    with pytest.raises(ValueError):
        A.create_class(conn, org_id=o["org_id"], name="  ")
    with conn:                                                               # 다른 학원의 강사는 담당이 될 수 없다
        other = A.create_teacher(conn, email="other@x.kr", password="p", display_name="남", org_name="옆학원", now=T)
    with pytest.raises(A.NotFound):
        A.create_class(conn, org_id=o["org_id"], name="x", teacher_id=other["user_id"])


def test_reassign_teacher(conn):
    o, cid = _org_with_class(conn)
    with conn:
        token = A.create_invite(conn, org_id=o["org_id"], created_by=o["user_id"], now=T)
        t = A.create_teacher(conn, email="t@x.kr", password="p", display_name="강사", invite_token=token, now=T)
        A.reassign_teacher(conn, cid, t["user_id"])
    assert conn.execute("SELECT teacher_id FROM classes WHERE class_id=?", (cid,)).fetchone()["teacher_id"] == t["user_id"]
    with conn:
        A.reassign_teacher(conn, cid, None)                                  # 강사 퇴사 → 담당 없음
    assert conn.execute("SELECT teacher_id FROM classes WHERE class_id=?", (cid,)).fetchone()["teacher_id"] is None
    with pytest.raises(A.NotFound):
        A.reassign_teacher(conn, "c_none", None)
    with pytest.raises(A.NotFound):
        A.reassign_teacher(conn, cid, "u_none")


def test_enroll_students_new(conn):
    o, cid = _org_with_class(conn)
    with conn:
        out = A.enroll_students(conn, cid, ROWS, now=T)
    assert [r["display_name"] for r in out] == ["이하은", "김민준", "박서연"]     # 입력 순서, 공백 제거
    keys = {r["login_key"] for r in out}
    assert len(keys) == 3 and all(re.fullmatch(r"[23456789A-HJ-NP-Z]{6}", k) for k in keys)
    for r in out:
        assert isinstance(r["pin"], str) and re.fullmatch(r"[0-9]{4}", r["pin"])
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (r["user_id"],)).fetchone()
        assert u["kind"] == "student" and u["login_key"] == r["login_key"] and u["email"] is None
        c = conn.execute("SELECT * FROM credentials WHERE user_id=?", (r["user_id"],)).fetchone()
        assert c["must_change"] == 1 and r["pin"] not in c["password_hash"]     # 평문은 표에 없다
        assert A.verify_password(conn, r["user_id"], r["pin"])                    # 반환된 pin 으로 들어갈 수 있다
    m = conn.execute("SELECT * FROM class_members WHERE class_id=? AND user_id=?", (cid, out[0]["user_id"])).fetchone()
    assert (m["display_name"], m["school"], m["entry_year"], m["phone"], m["joined_at"]) == ("이하은", "부산고", 2025, "010-1", T)
    m2 = conn.execute("SELECT school, entry_year, phone FROM class_members WHERE user_id=?", (out[1]["user_id"],)).fetchone()
    assert (m2["school"], m2["entry_year"], m2["phone"]) == (None, 2024, None)   # 빈 문자열은 NULL 로


def test_enroll_existing_student_into_second_class(conn):
    o, c1 = _org_with_class(conn)
    with conn:
        first = A.enroll_students(conn, c1, ROWS[:1], now=T)
        c2 = A.create_class(conn, org_id=o["org_id"], name="문제풀이반", now=T)
        again = A.enroll_students(conn, c2, [{"display_name": "이하은", "user_id": first[0]["user_id"]}], now=T)
    assert again[0]["pin"] is None and again[0]["login_key"] == first[0]["login_key"]
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2               # 원장 + 학생 1. 계정이 안 늘었다
    assert conn.execute("SELECT COUNT(*) FROM class_members WHERE user_id=?", (first[0]["user_id"],)).fetchone()[0] == 2
    with pytest.raises(A.Duplicate):                                                   # 같은 반에 두 번은 안 된다
        with conn:
            A.enroll_students(conn, c1, [{"display_name": "이하은", "user_id": first[0]["user_id"]}], now=T)
    with pytest.raises(A.NotFound):
        A.enroll_students(conn, c1, [{"display_name": "x", "user_id": "u_none"}], now=T)


def test_enroll_all_or_nothing(conn):
    """3명 중 셋째가 잘못되면 앞의 둘도 안 들어간다 (부르는 쪽 rollback)."""
    o, cid = _org_with_class(conn)
    bad = ROWS[:2] + [{"display_name": "정우", "entry_year": 1999}]
    with pytest.raises(ValueError, match="3번째 행"):
        with conn:
            A.enroll_students(conn, cid, bad, now=T)
    assert conn.execute("SELECT COUNT(*) FROM users WHERE kind='student'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM class_members").fetchone()[0] == 0


def test_enroll_rejects(conn):
    o, cid = _org_with_class(conn)
    with pytest.raises(ValueError, match="이름"):
        A.enroll_students(conn, cid, [{"display_name": " "}], now=T)
    with pytest.raises(ValueError, match="숫자"):
        A.enroll_students(conn, cid, [{"display_name": "a", "entry_year": "이천"}], now=T)
    with pytest.raises(A.NotFound):
        A.enroll_students(conn, "c_none", ROWS, now=T)
    conn.execute("UPDATE classes SET archived_at=? WHERE class_id=?", (T, cid))
    with pytest.raises(ValueError, match="닫힌"):
        A.enroll_students(conn, cid, ROWS, now=T)


def test_withdraw_student(conn):
    o, cid = _org_with_class(conn)
    with conn:
        out = A.enroll_students(conn, cid, ROWS[:1], now=T)
        A.withdraw_student(conn, cid, out[0]["user_id"], now=A.plus(T, days=30))
    row = conn.execute("SELECT left_at FROM class_members WHERE user_id=?", (out[0]["user_id"],)).fetchone()
    assert row["left_at"] == A.plus(T, days=30)
    with conn:
        A.withdraw_student(conn, cid, out[0]["user_id"], now=A.plus(T, days=60))   # 두 번째는 조용히, 날짜 안 바뀜
    row = conn.execute("SELECT left_at FROM class_members WHERE user_id=?", (out[0]["user_id"],)).fetchone()
    assert row["left_at"] == A.plus(T, days=30)
    n = conn.execute("SELECT COUNT(*) FROM users WHERE user_id=?", (out[0]["user_id"],)).fetchone()[0]
    assert n == 1                                                                  # 계정은 남는다
    with pytest.raises(A.NotFound):
        A.withdraw_student(conn, cid, "u_none")


# ================================================================ 덩어리 3 — 로그인 · 비밀번호 · 세션 · 권한 재료
def _student(conn):
    """원장 + 반 + 학생 1명. (owner dict, class_id, student dict with pin)"""
    o, cid = _org_with_class(conn)
    with conn:
        s = A.enroll_students(conn, cid, ROWS[:1], now=T)[0]
    return o, cid, s


def _cred(conn, user_id):
    return conn.execute("SELECT failed_count, locked_until, must_change FROM credentials WHERE user_id=?",
                        (user_id,)).fetchone()


def test_login_student_and_teacher(conn):
    o, cid, s = _student(conn)
    with conn:
        r = A.login(conn, login_key=s["login_key"].lower(), password=s["pin"], now=T)   # 소문자로 쳐도 된다
    assert r is not None and r["user_id"] == s["user_id"] and r["kind"] == "student" and r["must_change"] == 1
    assert "password_hash" not in r
    with conn:
        t = A.login(conn, email="O@X.KR", password="pw-owner", now=T)
    assert t["user_id"] == o["user_id"] and t["must_change"] == 0
    assert A.login(conn, login_key="ZZZZZZ", password="0000", now=T) is None              # 없는 키
    assert A.login(conn, login_key=s["login_key"], password=None, now=T) is None          # 비밀번호 없이


def test_login_lockout_doubles_and_resets(conn):
    o, cid, s = _student(conn)
    key, uid = s["login_key"], s["user_id"]
    for i in range(1, 5):                                                                 # 1~4번 실패: 카운트만
        with conn:
            assert A.login(conn, login_key=key, password="9999", now=T) is None
        assert (_cred(conn, uid)["failed_count"], _cred(conn, uid)["locked_until"]) == (i, None)
    with conn:                                                                            # 5번째: 1분 잠금
        assert A.login(conn, login_key=key, password="9999", now=T) is None
    assert _cred(conn, uid)["locked_until"] == A.plus(T, minutes=1)
    with pytest.raises(A.Locked) as e:                                                    # 잠금 중엔 맞는 비밀번호도 거부
        A.login(conn, login_key=key, password=s["pin"], now=A.plus(T, minutes=0))
    assert e.value.locked_until == A.plus(T, minutes=1)
    t6 = A.plus(T, minutes=1)                                                             # 풀린 직후 또 틀림: 2분
    with conn:
        assert A.login(conn, login_key=key, password="9999", now=t6) is None
    assert _cred(conn, uid)["locked_until"] == A.plus(t6, minutes=2)
    t7 = A.plus(t6, minutes=2)                                                            # 또: 4분
    with conn:
        assert A.login(conn, login_key=key, password="9999", now=t7) is None
    assert _cred(conn, uid)["locked_until"] == A.plus(t7, minutes=4)
    t8 = A.plus(t7, minutes=4)
    with conn:                                                                            # 맞으면 전부 초기화
        assert A.login(conn, login_key=key, password=s["pin"], now=t8) is not None
    assert (_cred(conn, uid)["failed_count"], _cred(conn, uid)["locked_until"]) == (0, None)


def test_login_lock_caps_at_60_minutes(conn):
    o, cid, s = _student(conn)
    conn.execute("UPDATE credentials SET failed_count=20 WHERE user_id=?", (s["user_id"],))
    with conn:
        A.login(conn, login_key=s["login_key"], password="9999", now=T)
    assert _cred(conn, s["user_id"])["locked_until"] == A.plus(T, minutes=60)


def test_login_failure_survives_commit_pattern(conn):
    """4번 ①의 함정: 실패가 None 이라 with conn: 이 commit 하고, 카운트가 남는다."""
    o, cid, s = _student(conn)
    with conn:
        r = A.login(conn, login_key=s["login_key"], password="0000", now=T)
    assert r is None
    path = conn.execute("PRAGMA database_list").fetchone()[2]          # 이 연결이 연 파일
    other = db.connect(path)                                             # 다른 연결에서 보여야 commit 된 것
    assert other.execute("SELECT failed_count FROM credentials WHERE user_id=?", (s["user_id"],)).fetchone()[0] == 1
    other.close()


def test_login_disabled_user(conn):
    o, cid, s = _student(conn)
    conn.execute("UPDATE users SET status='disabled' WHERE user_id=?", (s["user_id"],))
    assert A.login(conn, login_key=s["login_key"], password=s["pin"], now=T) is None


def test_login_guest_key_only_until_expiry(conn):
    o = _owner(conn)
    conn.execute("INSERT INTO users (user_id, kind, login_key, expires_at, issued_by_org, created_at) "
                 "VALUES ('u_g','guest','GUEST1',?,?,?)", (A.plus(T, days=14), o["org_id"], T))
    r = A.login(conn, login_key="guest1", now=T)                                          # 비밀번호 없이
    assert r["kind"] == "guest" and r["must_change"] == 0
    assert A.login(conn, login_key="GUEST1", now=A.plus(T, days=14)) is None              # 만료 시각 = 끝


def test_change_password(conn):
    o, cid, s = _student(conn)
    uid = s["user_id"]
    with conn:
        s1 = A.create_session(conn, uid, now=T)
        s2 = A.create_session(conn, uid, now=T)                                           # 다른 기기
    with conn:
        assert A.change_password(conn, uid, "wrong", "1357", now=T) is False               # 옛 것 틀림 → False + 카운트
    assert _cred(conn, uid)["failed_count"] == 1
    with conn:
        assert A.change_password(conn, uid, s["pin"], "1357", keep_session=s1, now=T) is True
    c = _cred(conn, uid)
    assert (c["must_change"], c["failed_count"]) == (0, 0)
    assert A.verify_password(conn, uid, "1357") and not A.verify_password(conn, uid, s["pin"])
    assert A.get_session_user(conn, s1, now=T) is not None                                 # 지금 기기는 유지
    assert A.get_session_user(conn, s2, now=T) is None                                     # 다른 기기는 로그아웃
    with pytest.raises(ValueError):
        A.change_password(conn, uid, "1357", "12", now=T)
    with pytest.raises(A.NotFound):
        A.change_password(conn, "u_none", "a", "bcde", now=T)


def test_reset_password(conn):
    o, cid, s = _student(conn)
    uid = s["user_id"]
    conn.execute("UPDATE credentials SET failed_count=7, locked_until=?, must_change=0 WHERE user_id=?",
                 (A.plus(T, minutes=30), uid))
    with conn:
        tok = A.create_session(conn, uid, now=T)
        pin = A.reset_password(conn, uid, now=T)
    assert re.fullmatch(r"[0-9]{4}", pin) and isinstance(pin, str)
    c = _cred(conn, uid)
    assert (c["must_change"], c["failed_count"], c["locked_until"]) == (1, 0, None)       # 잠금도 풀린다
    assert A.verify_password(conn, uid, pin) and not A.verify_password(conn, uid, s["pin"])
    assert A.get_session_user(conn, tok, now=T) is None                                    # 전부 로그아웃
    with pytest.raises(A.NotFound):
        A.reset_password(conn, "u_none")


def test_session_roundtrip_and_hash(conn):
    o, cid, s = _student(conn)
    with conn:
        tok = A.create_session(conn, s["user_id"], user_agent="ipad", now=T)
    assert len(tok) >= 40
    row = conn.execute("SELECT * FROM sessions").fetchone()
    assert row["session_hash"] == A.token_hash(tok) and tok not in row["session_hash"]    # 원문은 표에 없다
    assert row["expires_at"] == A.plus(T, days=30) and row["user_agent"] == "ipad"
    u = A.get_session_user(conn, tok, now=A.plus(T, days=29))
    assert u["user_id"] == s["user_id"] and u["must_change"] == 1 and u["session_expires_at"] == A.plus(T, days=30)
    assert A.get_session_user(conn, tok, now=A.plus(T, days=30)) is None                   # 만료 시각 = 끝
    assert A.get_session_user(conn, "없는세션", now=T) is None
    conn.execute("UPDATE users SET status='disabled' WHERE user_id=?", (s["user_id"],))
    assert A.get_session_user(conn, tok, now=T) is None                                    # 계정을 끄면 세션도 죽는다
    with pytest.raises(A.AccountsError):
        A.create_session(conn, s["user_id"], now=T)
    with pytest.raises(A.NotFound):
        A.create_session(conn, "u_none", now=T)


def test_guest_session_ends_with_account(conn):
    o = _owner(conn)
    conn.execute("INSERT INTO users (user_id, kind, login_key, expires_at, issued_by_org, created_at) "
                 "VALUES ('u_g','guest','GUEST1',?,?,?)", (A.plus(T, days=3), o["org_id"], T))
    with conn:
        tok = A.create_session(conn, "u_g", now=T)                                        # 세션 30일 > 계정 3일
    assert conn.execute("SELECT expires_at FROM sessions").fetchone()["expires_at"] == A.plus(T, days=3)
    assert A.get_session_user(conn, tok, now=A.plus(T, days=2)) is not None
    assert A.get_session_user(conn, tok, now=A.plus(T, days=3)) is None


def test_logout_and_purge(conn):
    o, cid, s = _student(conn)
    with conn:
        a = A.create_session(conn, s["user_id"], now=T)
        b = A.create_session(conn, s["user_id"], now=T)
        A.create_session(conn, o["user_id"], days=1, now=T)                                 # 원장, 1일짜리
        A.delete_session(conn, a)                                                          # 로그아웃 하나
    assert A.get_session_user(conn, a, now=T) is None and A.get_session_user(conn, b, now=T) is not None
    with conn:
        assert A.delete_sessions(conn, s["user_id"]) == 1
    with conn:
        assert A.purge_expired_sessions(conn, now=A.plus(T, days=1)) == 1                  # c 만 만료
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_is_owner_and_is_class_teacher(conn):
    o, cid = _org_with_class(conn)
    with conn:
        token = A.create_invite(conn, org_id=o["org_id"], created_by=o["user_id"], now=T)
        t = A.create_teacher(conn, email="t@x.kr", password="p", display_name="강사", invite_token=token, now=T)
        c2 = A.create_class(conn, org_id=o["org_id"], name="문제풀이반", teacher_id=t["user_id"], now=T)
    assert A.is_owner(conn, o["user_id"], o["org_id"]) and not A.is_owner(conn, t["user_id"], o["org_id"])
    assert A.is_class_teacher(conn, o["user_id"], cid) and not A.is_class_teacher(conn, t["user_id"], cid)
    assert A.is_class_teacher(conn, t["user_id"], c2) and not A.is_class_teacher(conn, o["user_id"], c2)
    assert not A.is_owner(conn, "u_none", o["org_id"]) and not A.is_class_teacher(conn, t["user_id"], "c_none")
    conn.execute("UPDATE org_members SET left_at=? WHERE user_id=?", (T, o["user_id"]))
    assert not A.is_owner(conn, o["user_id"], o["org_id"])                                  # 나간 원장은 아니다


# ================================================================ 덩어리 4 — 게스트 · 키 재발급 · CLI
def test_issue_guest(conn):
    o = _owner(conn)
    with conn:
        g = A.issue_guest(conn, org_id=o["org_id"], now=T)
        free = A.issue_guest(conn, days=3, now=T)                                         # 블로그: 학원 없음
    u = conn.execute("SELECT * FROM users WHERE user_id=?", (g["user_id"],)).fetchone()
    assert (u["kind"], u["login_key"], u["expires_at"], u["issued_by_org"]) == ("guest", g["login_key"], A.plus(T, days=14), o["org_id"])
    assert conn.execute("SELECT COUNT(*) FROM credentials WHERE user_id=?", (g["user_id"],)).fetchone()[0] == 0
    assert A.login(conn, login_key=g["login_key"], now=A.plus(T, days=13)) is not None    # 키만으로
    assert A.login(conn, login_key=g["login_key"], now=A.plus(T, days=14)) is None
    assert free["expires_at"] == A.plus(T, days=3)
    assert conn.execute("SELECT issued_by_org FROM users WHERE user_id=?", (free["user_id"],)).fetchone()[0] is None
    with pytest.raises(A.NotFound):
        A.issue_guest(conn, org_id="o_none", now=T)


def test_promote_guest_keeps_user_id(conn):
    o, cid = _org_with_class(conn)
    with conn:
        g = A.issue_guest(conn, org_id=o["org_id"], now=T)
        sess = A.create_session(conn, g["user_id"], now=T)                                # 게스트로 로그인해 둔 상태
    with conn:
        out = A.promote_guest(conn, g["user_id"], cid, "이하은", school="부산고", entry_year=2025, now=A.plus(T, days=2))
    assert out["user_id"] == g["user_id"] and out["login_key"] == g["login_key"]          # 같은 사람, 같은 키
    assert re.fullmatch(r"[0-9]{4}", out["pin"])
    u = conn.execute("SELECT kind, expires_at, issued_by_org FROM users WHERE user_id=?", (g["user_id"],)).fetchone()
    assert (u["kind"], u["expires_at"], u["issued_by_org"]) == ("student", None, o["org_id"])   # 이력은 남는다
    assert _cred(conn, g["user_id"])["must_change"] == 1
    m = conn.execute("SELECT display_name, school, entry_year FROM class_members WHERE user_id=?", (g["user_id"],)).fetchone()
    assert (m["display_name"], m["school"], m["entry_year"]) == ("이하은", "부산고", 2025)
    assert A.get_session_user(conn, sess, now=A.plus(T, days=2)) is None                  # 게스트 세션은 끝
    with conn:                                                                            # 이제 학생으로 로그인 — 만료 지나도 된다
        assert A.login(conn, login_key=g["login_key"], password=out["pin"], now=A.plus(T, days=30)) is not None
    with pytest.raises(ValueError, match="게스트가 아니다"):
        A.promote_guest(conn, g["user_id"], cid, "x", now=T)                              # 두 번은 안 된다
    with pytest.raises(ValueError, match="게스트가 아니다"):
        A.promote_guest(conn, o["user_id"], cid, "x", now=T)


def test_promote_guest_all_or_nothing(conn):
    """반이 없으면 kind 변경·credentials 도 rollback 으로 사라진다 — 게스트로 남는다."""
    o = _owner(conn)
    with conn:
        g = A.issue_guest(conn, org_id=o["org_id"], now=T)
    with pytest.raises(A.NotFound):
        with conn:
            A.promote_guest(conn, g["user_id"], "c_none", "x", now=T)
    u = conn.execute("SELECT kind, expires_at FROM users WHERE user_id=?", (g["user_id"],)).fetchone()
    assert u["kind"] == "guest" and u["expires_at"] == A.plus(T, days=14)
    assert conn.execute("SELECT COUNT(*) FROM credentials WHERE user_id=?", (g["user_id"],)).fetchone()[0] == 0


def test_reissue_key(conn):
    o, cid, s = _student(conn)
    with conn:
        sess = A.create_session(conn, s["user_id"], now=T)
        new = A.reissue_key(conn, s["user_id"])
    assert new != s["login_key"] and re.fullmatch(r"[23456789A-HJ-NP-Z]{6}", new)
    assert A.find_user(conn, login_key=s["login_key"]) is None                             # 옛 키는 죽는다
    assert A.find_user(conn, login_key=new)["user_id"] == s["user_id"]                     # user_id 는 그대로
    assert A.get_session_user(conn, sess, now=T) is not None                               # 세션은 유지 (키는 비밀이 아니다)
    assert A.verify_password(conn, s["user_id"], s["pin"])                                 # 비밀번호도 그대로
    with pytest.raises(ValueError):
        A.reissue_key(conn, o["user_id"])                                                  # 강사는 키가 없다
    with pytest.raises(A.NotFound):
        A.reissue_key(conn, "u_none")


def test_cli_roundtrip(tmp_path, capsys):
    """운영자가 실제로 칠 순서대로. --db 로 임시 파일. 출력에서 ID·키·pin 을 읽어 다음 명령에 넘긴다."""
    dbp = str(tmp_path / "acc.db")

    def run(*args):
        return A.main(["--db", dbp, *args]), capsys.readouterr().out

    rc, out = run("add-teacher", "--email", "o@x.kr", "--name", "원장", "--org", "물리학원", "--password", "pw")
    assert rc == 0 and "새 DB" in out
    m = re.search(r"user_id (u_\w+)\s+org_id (o_\w+)\s+role owner", out)
    owner, org = m.group(1), m.group(2)

    rc, out = run("approve-org", org)
    assert rc == 0 and "active" in out
    rc, out = run("add-class", org, "개념반", "--teacher", owner)
    cid = re.search(r"class_id (c_\w+)", out).group(1)

    csv_path = tmp_path / "명단.csv"
    csv_path.write_text("﻿display_name,school,entry_year,phone\n이하은,부산고,2025,\n김민준,,2024,010-2\n", encoding="utf-8")
    rc, out = run("add-students", cid, "--csv", str(csv_path))
    assert rc == 0
    rows = re.findall(r"^(\S+)\s+([23456789A-HJ-NP-Z]{6})\s+([0-9]{4})\s+(u_\w+)", out, flags=re.M)
    assert [r[0] for r in rows] == ["이하은", "김민준"]
    name, key, pin, uid = rows[0]

    rc, out = run("reset-password", uid)
    new_pin = re.search(r"임시 비밀번호 ([0-9]{4})", out).group(1)
    rc, out = run("reissue-key", uid)
    new_key = re.search(r"새 키 ([23456789A-HJ-NP-Z]{6})", out).group(1)

    rc, out = run("issue-guest", "--org", org, "--days", "7")
    g = re.search(r"게스트 키 (\w{6}).*user_id (u_\w+)", out)
    rc, out = run("promote-guest", g.group(2), cid, "박서연", "--school", "해운대고", "--year", "2025")
    assert rc == 0 and "박서연" in out

    rc, out = run("ls")
    assert rc == 0 and "물리학원" in out and "학생 3" in out and "게스트 0" in out

    # 실제로 들어갈 수 있나 — CLI 가 만든 값으로 함수 직접 호출
    c = db.connect(tmp_path / "acc.db")
    assert A.login(c, login_key=new_key, password=new_pin)["user_id"] == uid
    c.close()

    # 오류는 1 로 끝나고 메시지는 stderr
    rc = A.main(["--db", dbp, "approve-org", "o_none"])
    assert rc == 1 and "학원 없음" in capsys.readouterr().err
    rc = A.main(["--db", dbp, "add-teacher", "--email", "o@x.kr", "--name", "x", "--org", "y", "--password", "p"])
    assert rc == 1
