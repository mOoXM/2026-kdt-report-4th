r"""
db.py — 이 프로젝트에서 SQLite 를 여는 유일한 문

왜 있는가
---------
이 프로젝트는 DB 가 네 개이고 서로를 ATTACH 로 조인한다. 그런데 여는 방식이
파일마다 달랐고, 경로 상수도 여러 파일에 **각각** 정의되어 있었다. 폴더 구조를 바꾸면 한쪽만 따라오고 다른 쪽은 조용히 어긋난다.

여기가 경로의 유일한 출처다. serve/ 의 코드는
전부 이 파일의 `connect()` 로 연다.

    engine/diagnosis.py  connect(physics, [(concept_map, CM)])   physics 가 main
    serve/api.py       connect(physics, [(concept_map, CM)])   physics 가 main

아직 직접 여는 곳 — similar/evaluate.py 의 `?mode=ro` 읽기 전용 URI. FK 가 없는 DB 라 해롭지는
않지만 다음 정리 때 여기로 모은다.

★ foreign_keys 를 여기서 켠다
-----------------------------
`PRAGMA foreign_keys` 는 DB 파일이 아니라 **연결(connection)** 단위 설정이고
SQLite 기본값이 OFF 다. `responses_schema.sql` 맨 위에 써 둔 것은 그 파일을
실행하는 순간에만 유효하다.

즉 `sqlite3.connect()` 를 직접 부르면 스키마의 REFERENCES 가 전부 장식이 되고,
없는 student_id 로 attempt 가 조용히 들어간다. **그래서 여는 문을 하나로 좁힌다.**

★ 파일이 없으면 만들지 않고 실패한다
------------------------------------
SQLite 는 없는 경로를 열면 **빈 DB 를 새로 만든다.** ATTACH 도 마찬가지다.
오타 한 글자에 `data/ph1/qmatrx.db` 가 생기고, 조회는 "no such table" 이 아니라
그냥 빈 결과를 낸다. 원본 DB 를 다루는 코드에서 이건 조용한 사고다.
그래서 기본은 "없으면 FileNotFoundError", 만들 때만 create=True 를 준다.

ATTACH alias 를 상수로 고정한다
-------------------------------
뷰를 쓰지 않는 이유가 "다른 스크립트가 다른 alias 로 붙이면 깨진다"
였다. alias 를 P/CM/R 상수로 두면 그 전제가 사라진다.

쓰는 법
-------
    from .db import connect, physics_db, concept_map_db, responses_db, P, CM

    conn = connect(responses_db(), [(physics_db(), P), (concept_map_db(), CM)])
    conn.execute("SELECT ... FROM statement_responses sr "
                 "JOIN p.statements s USING (item_key, label) "
                 "JOIN q.statement_concept k USING (item_key, label)")
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

# src/physics_lab/db.py → parents[2] 가 프로젝트 루트. 하위 패키지로 옮기면 숫자가 바뀐다.
ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"
DATA = ROOT / "data"

DEFAULT_SUBJECT = "ph1"

# ATTACH alias. 문자열을 직접 쓰지 말고 이것을 쓴다.
P = "p"        # physics.db  — items · statements · choices

# 계산형(items.item_format='numeric') 문항의 판단 단위 라벨.
# ㄱㄴㄷ 가 없는 문항은 "답을 맞혔나" 하나가 판단 단위다. statements 에 label='답' 행 하나로 두면
# (is_true=1, error_rate = 100 - 정답률) 개념 라벨링 · 진단(diagnosis) · 연결표가
# (item_key, label) 그대로 돌아간다. 화면에는 보기로 내보내지 않는다 — 단답 또는 ①~⑤ 로 받는다.
ANSWER_LABEL = "답"


def item_error_rate(correct_rate) -> float | None:
    """계산형 문항의 '오판율' = 100 - 정답률 (무응답 포함). 정답률이 없으면 None."""
    return None if correct_rate is None else round(100.0 - float(correct_rate), 1)
CM = "q"        # concept_map.db  — statement_concept · item_flags
A = "a"        # accounts.db — users · classes · class_members. 강사 화면만 붙인다 (개인정보)
R = "r"        # roster.db 는 accounts.class_members 로 흡수됐다. 남은 참조가 지워지면 삭제


# ---------------------------------------------------------------- 경로
# build/ 는 파생물(매번 DROP -> CREATE), data/ 는 원본(다시 못 만든다).
# 이 구분이 폴더로 드러나 있으므로 함수도 그대로 나눠 둔다.

def physics_db(subject: str = DEFAULT_SUBJECT) -> Path:
    """파생물. load_db.py 가 매번 다시 만든다."""
    return BUILD / subject / "physics.db"


def concept_map_db(subject: str = DEFAULT_SUBJECT) -> Path:
    """원본. 손으로 붙인 연결표."""
    return DATA / subject / "concept_map.db"


def responses_db(subject: str = DEFAULT_SUBJECT) -> Path:
    """원본. 학생 응답 — 연결표보다 더 못 되살린다."""
    return DATA / subject / "responses.db"


def accounts_db() -> Path:
    """
    원본. 사용자·학원·반·명단·세션. 과목과 무관하므로 과목 폴더 밖이다.
    .gitignore. 서버만 쓴다.
    """
    return DATA / "accounts.db"


def roster_db(subject: str = DEFAULT_SUBJECT) -> Path:
    """ 실명은 accounts.class_members.display_name. 남은 참조를 지운 뒤 삭제."""
    return DATA / subject / "roster.db"


# 라우터들이 쓰는 이름. 같은 함수에서 나온다.
PHYSICS_DB = physics_db()
CONCEPT_MAP_DB = concept_map_db()
RESPONSES_DB = responses_db()
ACCOUNTS_DB = accounts_db()
ROSTER_DB = roster_db()


# ---------------------------------------------------------------- 연결
def connect(main: Path | str,
            attach: Sequence[tuple[Path | str, str]] = (),
            *,
            create: bool = False,
            busy_ms: int = 3000) -> sqlite3.Connection:
    """
    main 을 열고 attach 를 [(경로, alias), ...] 로 붙인다.

    항상 하는 것
        PRAGMA foreign_keys = ON     연결 단위라 매번 켜야 한다
        PRAGMA busy_timeout          concept_labeler 가 concept_map 에 쓰는 중에도 기다린다
        row_factory = Row            r["item_key"] 로 읽는다

    create=True 는 **새로 만들 때만** 준다. 기본은 없으면 실패한다.
    """
    main = Path(main)
    if not create and not main.is_file():
        raise FileNotFoundError(
            f"DB 가 없다: {main}\n"
            f"  경로 오타이거나 아직 안 만들어진 것이다. "
            f"새로 만들 의도라면 create=True 를 준다.")
    if create:
        main.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False: FastAPI 는 sync 의존성(yield 연결)과 엔드포인트를 **다른 스레드풀 스레드**에서 돌릴 수 있다.
    # 기본값(True)이면 "SQLite objects created in a thread can only be used in that same thread" 가 **가끔** 난다
    # (스레드가 우연히 같으면 통과해서 테스트에선 안 잡힌다). 연결은 요청마다 하나이고 한 요청 안에서 순서대로만 쓰므로 안전하다.
    conn = sqlite3.connect(main, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # busy_timeout 이 먼저다. 이게 없으면 아래 PRAGMA 부터 locked 로 튄다.
    conn.execute(f"PRAGMA busy_timeout = {int(busy_ms)}")

    conn.execute("PRAGMA foreign_keys = ON")
    # 트랜잭션 안에서는 이 PRAGMA 가 조용히 무시된다. 켜졌는지 확인한다 —
    # 안 켜진 채로 쓰면 REFERENCES 가 전부 장식이 되고, 그 사실을
    # 한참 뒤에 고아 행으로 발견하게 된다.
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        conn.close()
        raise RuntimeError(f"foreign_keys 를 켜지 못했다: {main}")

    for path, alias in attach:
        path = Path(path)
        if not path.is_file():
            conn.close()
            raise FileNotFoundError(
                f"ATTACH 대상이 없다: {path} (as {alias})\n"
                f"  SQLite 는 없는 경로를 붙이면 빈 DB 를 만들어 버린다. "
                f"그러면 조회가 오류 없이 빈 결과를 낸다.")
        # alias 는 파라미터로 못 넘긴다. P/CM/R 상수만 쓰므로 그대로 넣는다.
        conn.execute(f'ATTACH ? AS "{alias}"', (str(path),))

    return conn


# ---------------------------------------------------------------- 응답 DB 초기화
def init_responses_db(subject: str = DEFAULT_SUBJECT, *,
                      path: Path | None = None) -> Path:
    """
    responses_schema.sql 로 학생 응답 DB 를 만든다. 이미 있으면 그대로 둔다.

    새 PC 에서
    `python -c "from physics_lab.db import init_responses_db; init_responses_db()"`.
    스키마에 DROP 이 없으므로 있는 DB 에 다시 돌려도 데이터가 안 날아간다
    (CREATE TABLE IF NOT EXISTS 가 아니면 에러가 난다 — 그래서 미리 막는다).
    """
    path = path or responses_db(subject)
    if path.is_file():
        migrate_responses_db(path)
        return path
    sql = (Path(__file__).parent / "responses_schema.sql").read_text(encoding="utf-8")
    conn = connect(path, create=True)
    try:
        conn.executescript(sql)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    return path


# 있는 DB 에 ALTER 로 더한 열. {표: [(열, 선언)]}. 새 DB 는 responses_schema.sql 이 처음부터 갖는다.
#   v5: exam_sets.mode · responses.answer_text   v6: exam_sets.opened_at · closed_at
_RESPONSES_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "exam_sets": [("mode", "TEXT NOT NULL DEFAULT 'diagnostic'"), ("opened_at", "TEXT"), ("closed_at", "TEXT")],
    "responses": [("answer_text", "TEXT")],
}
_RESPONSES_VERSION = "6"
_RESPONSES_REBUILD_BELOW = 5        # 이 버전 미만은 CHECK('short' 등)가 달라 ALTER 로는 못 맞춘다 → 응답 0행이면 파일을 다시 만든다
_migrate_lock = __import__("threading").Lock()


def _responses_version(conn: sqlite3.Connection) -> int:
    try:
        r = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return int(r[0]) if r else 0
    except sqlite3.OperationalError:
        return 0


def migrate_responses_db(path: Path) -> list[str]:
    """
    있는 responses.db 를 지금 스키마에 맞춘다. 멱등 — 매 기동 때 불러도 된다. 반환: 이번에 더한 "표.열" (로그용).
      1. schema_version < 5 (서버의 v3 처럼): CHECK 가 달라 ALTER 로 못 맞춘다. 응답(attempts)이 0행이면
         옛 파일을 .bak-v{N} 으로 옮기고 responses_schema.sql 로 새로 만든다. 응답이 있으면 **멈춘다** — 사람이 옮겨야 한다
      2. 그 위에서 PRAGMA table_info 로 없는 열만 ALTER TABLE ADD COLUMN (v5·v6 열)
    전엔 opened_at/closed_at 만 더하고 '6' 을 찍어서, v3 DB 에서 첫 시험 만들기가 `no column named mode` 로 죽었다.
    두 요청이 동시에 처음 들어와도 한 번만 돌게 Lock.
    """
    with _migrate_lock:
        return _migrate_responses_db(path)


def _migrate_responses_db(path: Path) -> list[str]:
    conn = connect(path)
    try:
        ver = _responses_version(conn)
        if 0 < ver < _RESPONSES_REBUILD_BELOW or (ver == 0 and conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='attempts'").fetchone()):
            n = conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            if n:
                raise RuntimeError(f"{path}: schema_version {ver} 인데 응답이 {n}건 있다. 자동으로 못 올린다 — "
                                   f"파일을 옮기고(백업) 새로 만들 것")
            conn.close()
            bak = path.with_name(f"{path.name}.bak-v{ver}")
            path.replace(bak)
            for side in ("-wal", "-shm"):
                sp = path.with_name(path.name + side)
                if sp.exists():
                    sp.unlink()
            init_responses_db(path=path)
            return [f"rebuilt (v{ver} → v{_RESPONSES_VERSION}, 옛 파일 {bak.name})"]
    finally:
        try:
            conn.close()
        except sqlite3.ProgrammingError:
            pass

    conn = connect(path)
    added: list[str] = []
    try:
        for table, cols in _RESPONSES_MIGRATIONS.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols:
                if col not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                    added.append(f"{table}.{col}")
        # 같은 시험을 두 번 제출 못 하게 — 코드의 SELECT 검사는 동시 요청을 못 막는다. 새 DB 도 여기서 받는다
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_attempts_exam_student "
                     "ON attempts (exam_set_id, student_id) WHERE purpose = 'exam'")
        if added:
            from .accounts import utcnow
            conn.execute("INSERT OR REPLACE INTO meta (key, value, updated_at) VALUES ('schema_version', ?, ?)",
                         (_RESPONSES_VERSION, utcnow()))
        conn.commit()
    finally:
        conn.close()
    return added


# ---------------------------------------------------------------- 계정 DB 초기화
def init_accounts_db(*, path: Path | None = None) -> Path:
    """
    accounts_schema.sql 로 계정 DB 를 만든다. 이미 있으면 그대로 둔다.
    init_responses_db 와 같은 규약 — 스키마에 DROP 이 없어 있는 DB 에 다시 돌려도 안전.
    """
    path = path or accounts_db()
    if path.is_file():
        return path
    sql = (Path(__file__).parent / "accounts_schema.sql").read_text(encoding="utf-8")
    conn = connect(path, create=True)
    try:
        conn.executescript(sql)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    return path
