"""
accounts_schema.sql · responses_schema.sql v4 가 설계 판단을 실제로 막는지.
원본 DB 를 안 건드린다 — tmp_path 에 새로 만든다. 어디서나 돈다 (data/ 불필요).
"""
import sqlite3

import pytest

from physics_lab import db

T = "2026-09-28T00:00:00Z"


@pytest.fixture
def acc(tmp_path):
    p = db.init_accounts_db(path=tmp_path / "accounts.db")
    conn = db.connect(p)
    yield conn
    conn.close()


def _seed(c):
    # 컬럼 이름을 적는다 — 칸이 늘어도 테스트가 안 깨지게.
    c.execute("INSERT INTO users (user_id, kind, email, display_name, created_at) "
              "VALUES ('u_o','teacher','o@x.kr','원장',?)", (T,))
    c.execute("INSERT INTO orgs (org_id, name, status, created_at) VALUES ('o1','학원','pending',?)", (T,))
    c.execute("INSERT INTO org_members (org_id, user_id, role, joined_at) VALUES ('o1','u_o','owner',?)", (T,))
    c.execute("INSERT INTO classes (class_id, org_id, teacher_id, name, subject, created_at) "
              "VALUES ('c1','o1','u_o','물리 개념반','ph1',?)", (T,))
    c.execute("INSERT INTO classes (class_id, org_id, teacher_id, name, subject, created_at) "
              "VALUES ('c2','o1','u_o','물리 문제풀이반','ph1',?)", (T,))
    c.execute("INSERT INTO users (user_id, kind, login_key, created_at) "
              "VALUES ('u_s','student','K7M3PX',?)", (T,))
    c.execute("INSERT INTO credentials (user_id, password_hash, must_change, updated_at) "
              "VALUES ('u_s','$argon2id$x',0,?)", (T,))


def test_tables_and_pragmas(acc):
    names = {r[0] for r in acc.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "credentials", "sessions", "orgs", "org_members", "invites",
            "classes", "class_members", "meta"} <= names
    assert acc.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert acc.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "1"


def test_v1_afternoon_columns(acc):
    """잠금 두 칸, 세션·초대는 해시 컬럼."""
    cred = [r[1] for r in acc.execute("PRAGMA table_info(credentials)")]
    assert "failed_count" in cred and "locked_until" in cred
    assert [r[1] for r in acc.execute("PRAGMA table_info(sessions)")][0] == "session_hash"
    assert [r[1] for r in acc.execute("PRAGMA table_info(invites)")][0] == "token_hash"
    _seed(acc)
    row = acc.execute("SELECT failed_count, locked_until FROM credentials WHERE user_id='u_s'").fetchone()
    assert (row[0], row[1]) == (0, None)          # 기본값


def test_student_in_many_classes(acc):
    """개념반 + 문제풀이반 — 반 소속은 class_members 한 곳, M:N."""
    _seed(acc)
    for cid in ("c1", "c2"):
        acc.execute("INSERT INTO class_members VALUES (?, 'u_s','이하은','부산고',2025,NULL,?,NULL,NULL)", (cid, T))
    n = acc.execute("SELECT COUNT(*) FROM class_members WHERE user_id='u_s'").fetchone()[0]
    assert n == 2


@pytest.mark.parametrize("why,sql", [
    ("강사인데 email 없음", "INSERT INTO users VALUES ('x','teacher',NULL,NULL,0,'a',0,'active',NULL,NULL,'t')"),
    ("학생인데 login_key 없음", "INSERT INTO users VALUES ('x','student',NULL,NULL,0,NULL,0,'active',NULL,NULL,'t')"),
    ("게스트 아닌데 만료일", "INSERT INTO users VALUES ('x','student','ABCDEF',NULL,0,NULL,0,'active','2026-10-01T00:00:00Z',NULL,'t')"),
    ("login_key 중복", "INSERT INTO users VALUES ('x','student','K7M3PX',NULL,0,NULL,0,'active',NULL,NULL,'t')"),
    ("없는 학원의 반", "INSERT INTO classes VALUES ('cx','o_none',NULL,'x','ph1','t',NULL)"),
    ("org_members 에 student 역할", "INSERT INTO org_members VALUES ('o1','u_s','student','t',NULL)"),
    ("입학연도 범위 밖", "INSERT INTO class_members VALUES ('c1','u_s','x',NULL,1999,NULL,'t',NULL,NULL)"),
    ("없는 사용자의 세션", "INSERT INTO sessions (session_hash, user_id, created_at, expires_at) VALUES ('s1','u_none','t','t')"),
    ("없는 학원의 초대", "INSERT INTO invites (token_hash, org_id, created_by, created_at, expires_at) "
                  "VALUES ('i1','o_none','u_o','t','t')"),
])
def test_rejects(acc, why, sql):
    _seed(acc)
    with pytest.raises(sqlite3.IntegrityError):
        acc.execute(sql)


def test_guest_has_no_password_and_expires(acc):
    _seed(acc)
    acc.execute("INSERT INTO users (user_id, kind, login_key, expires_at, issued_by_org, created_at) "
                "VALUES ('u_g','guest','QW3RTY','2026-10-05T00:00:00Z','o1',?)", (T,))
    assert acc.execute("SELECT COUNT(*) FROM credentials WHERE user_id='u_g'").fetchone()[0] == 0


def test_responses_schema_is_current_and_has_no_class_on_students(tmp_path):
    p = db.init_responses_db(path=tmp_path / "responses.db")
    c = db.connect(p)
    cols = [r[1] for r in c.execute("PRAGMA table_info(students)")]
    assert "class_id" not in cols and "cohort" not in cols
    assert c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "6"      # v6: opened_at·closed_at
    # student_id 는 accounts.users.user_id 를 그대로 받는다 (파일이 달라 FK 는 없다)
    c.execute("INSERT INTO students (student_id, consent, created_at) VALUES ('u_s', 1, ?)", (T,))
    c.execute("INSERT INTO exam_sets (exam_set_id, class_id, title, round_no, created_by, created_at) "
              "VALUES ('e1', 'c1', '9월 2차', 2, 'u_o', ?)", (T,))                                   # mode 는 기본값 diagnostic
    c.execute("INSERT INTO attempts (attempt_id, student_id, purpose, exam_set_id, started_at) "
              "VALUES ('a1', 'u_s', 'exam', 'e1', ?)", (T,))
    c.close()
