r"""
teacher.py — 강사·원장용 API. /api/teacher/… 와 /api/owner/…

강사가 시험 한 번 치르기까지 누르는 것만:
    GET  /api/teacher/home                          내 학원 · 내 반 카드 (학생 수 · 마지막 시험 · 다음 할 일)
    POST /api/teacher/classes                       반 만들기 {name}
    GET  /api/teacher/classes/{cid}                 반 = 명단 + 시험 목록
    POST /api/teacher/classes/{cid}/students        명단 붙여 넣기 → 키·임시 비밀번호 (★ 평문 pin 은 이 응답에만)
    POST /api/teacher/classes/{cid}/students/{uid}/reset-password   임시 비밀번호 다시
    POST /api/teacher/classes/{cid}/students/{uid}/withdraw         퇴원
    GET  /api/teacher/bank?cat=                     문항 은행 (개념 가 붙은 문항만) + 단원 목록 + 그 단원의 개념
    POST /api/teacher/classes/{cid}/exams           시험지 만들기 {title, mode, item_keys}
    PUT  /api/teacher/exams/{eid}                   구성 중일 때만 고침
    DELETE /api/teacher/exams/{eid}                 구성 중일 때만
    POST /api/teacher/exams/{eid}/open · /close     진행 중 ↔ 끝 (opened_at · closed_at, v6)
    GET  /api/teacher/exams/{eid}                   시험지 + 응시 현황
    GET  /api/teacher/exams/{eid}/results           결과 표 ① (학생 × 문항, 칸 = 틀린 보기 수) + 열 머리(보기별 반 오답률)
    GET  /api/teacher/exams/{eid}/students/{uid}    학생 한 명: 문항별 O/X + 개념 진단 (③)
    GET  /api/owner/overview                        학원 전체: 강사 · 모든 반 · 승인 상태 (원장만)
    POST /api/owner/invites                         강사 초대 토큰 (원장만)

두 DB 를 한 요청에서 쓴다 — 반·명단은 accounts.db(conn), 시험지·응답은 responses.db(rconn).
exam_sets.class_id 가 두 파일을 잇는다 (파일이 달라 FK 는 없다 — check_all 8번이 검사).

권한: 서버가 최종 판단. 반 단위는 auth.ensure_class_teacher(담당 강사 또는 그 학원 원장, 운영자 통과),
학원 단위는 auth.ensure_owner. 시험지는 그 반의 권한을 따른다 (exam → class_id → ensure_class_teacher).

시험 상태 (v6): opened_at NULL = 구성 중(문항 바꿀 수 있음) / opened_at 만 = 진행 중(학생 앱에 보임) / closed_at = 끝(결과).
확정 뒤 문항 변경 불가 — 응시한 학생과 아닌 학생의 시험지가 달라지면 반 집계가 깨진다.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .. import accounts as A
from .. import responses as R
from ..db import ANSWER_LABEL, PHYSICS_DB, CONCEPT_MAP_DB, CM, connect
from ..concept.defs import CONCEPTS_BY_UNIT, sort_concept
from . import auth
from ..engine.concept_display import as_sections, group as concept_group, label as concept_label, tiers as concept_tiers
from ..engine.diagnosis import Response as Resp
from .student import derived_units, engine, load_item_facts, responses_conn, Answer as StudentAnswer

router = APIRouter(prefix="/api/teacher", tags=["teacher"])
owner = APIRouter(prefix="/api/owner", tags=["owner"])


def install(app: FastAPI) -> None:
    """api.py 가 부른다."""
    app.include_router(router)
    app.include_router(owner)


# ============================================================ 누구인가
def require_teacher(me: dict = Depends(auth.require_user)) -> dict:
    """강사 앱 API 는 강사만 (운영자는 통과 — belongsHere 와 같은 규칙)."""
    if me["is_admin"] or me["kind"] == "teacher":
        return me
    raise HTTPException(403, "강사만 할 수 있습니다")


def my_org(conn: sqlite3.Connection, me: dict) -> dict:
    """내가 속한 학원 (강사는 하나). 운영자가 학원이 없으면 404 — 화면은 '학원 없음' 으로."""
    row = conn.execute(
        "SELECT o.org_id, o.name, o.status, m.role FROM org_members m JOIN orgs o USING (org_id) "
        "WHERE m.user_id = ? AND m.left_at IS NULL ORDER BY m.joined_at LIMIT 1", (me["user_id"],)).fetchone()
    if row is None:
        raise HTTPException(404, "속한 학원이 없습니다")
    return dict(row)


# ============================================================ 모양
class ClassIn(BaseModel):
    name: str


class StudentRow(BaseModel):
    display_name: str
    school: str | None = None
    entry_year: int | None = None
    phone: str | None = None


class StudentsIn(BaseModel):
    rows: list[StudentRow] = Field(default_factory=list)


class ExamIn(BaseModel):
    title: str
    mode: str = "diagnostic"                  # diagnostic | realistic (exam_sets.mode)
    item_keys: list[str] = Field(default_factory=list)


class AssignIn(BaseModel):
    item_keys: list[str] = Field(default_factory=list)
    target_concept: str | None = None              # 이 과제가 겨냥한 개념 (약한 개념 자동 담기일 때)
    due_at: str | None = None


class InviteIn(BaseModel):
    email: str | None = None
    days: int = 7


# ============================================================ 시험 상태 · 공통 조회
def exam_status(e: sqlite3.Row | dict) -> str:
    """'draft' 구성 중 / 'open' 진행 중 / 'closed' 끝. 화면이 세 상태로 다른 것을 보여 준다."""
    if e["closed_at"]:
        return "closed"
    if e["opened_at"]:
        return "open"
    return "draft"


def _exam_row(rconn: sqlite3.Connection, exam_set_id: str) -> sqlite3.Row:
    e = rconn.execute("SELECT * FROM exam_sets WHERE exam_set_id = ?", (exam_set_id,)).fetchone()
    if e is None:
        raise HTTPException(404, "시험이 없습니다")
    return e


def _exam_items(rconn: sqlite3.Connection, exam_set_id: str) -> list[sqlite3.Row]:
    return rconn.execute("SELECT item_key, seq, input_format FROM exam_items WHERE exam_set_id = ? ORDER BY seq",
                         (exam_set_id,)).fetchall()


def _members(conn: sqlite3.Connection, class_id: str, *, active_only: bool = True) -> list[dict]:
    rows = conn.execute(
        "SELECT cm.user_id, cm.display_name, cm.school, cm.entry_year, cm.phone, cm.joined_at, cm.left_at, u.login_key "
        "FROM class_members cm JOIN users u USING (user_id) WHERE cm.class_id = ? "
        + ("AND cm.left_at IS NULL " if active_only else "") + "ORDER BY cm.display_name", (class_id,)).fetchall()
    return [dict(r) for r in rows]


def _attempts_by_student(rconn: sqlite3.Connection, exam_set_id: str) -> dict[str, dict]:
    """학생마다 마지막 풀이 하나 (같은 시험을 두 번 제출하면 나중 것)."""
    out: dict[str, dict] = {}
    for a in rconn.execute("SELECT attempt_id, student_id, started_at, finished_at FROM attempts "
                           "WHERE exam_set_id = ? AND purpose = 'exam' ORDER BY started_at", (exam_set_id,)):
        out[a["student_id"]] = dict(a)
    return out


def _exam_summary(rconn: sqlite3.Connection, e: sqlite3.Row) -> dict:
    n_items = rconn.execute("SELECT COUNT(*) FROM exam_items WHERE exam_set_id = ?", (e["exam_set_id"],)).fetchone()[0]
    n_sub = rconn.execute("SELECT COUNT(DISTINCT student_id) FROM attempts WHERE exam_set_id = ? AND purpose = 'exam'",
                          (e["exam_set_id"],)).fetchone()[0]
    return {"exam_set_id": e["exam_set_id"], "class_id": e["class_id"], "title": e["title"], "round_no": e["round_no"],
            "mode": e["mode"], "status": exam_status(e), "n_items": n_items, "n_submitted": n_sub,
            "created_at": e["created_at"], "opened_at": e["opened_at"], "closed_at": e["closed_at"]}


# ============================================================ 홈 · 반
@router.get("/home")
def api_home(me: dict = Depends(require_teacher), conn: sqlite3.Connection = Depends(auth.accounts_conn),
             rconn: sqlite3.Connection = Depends(responses_conn)):
    """
    내 반 카드. 원장은 학원의 모든 반, 강사는 담당 반. 카드마다 "다음에 할 일" 한 줄 — 화면 1번.
    """
    org = my_org(conn, me)
    if org["role"] == "owner" or me["is_admin"]:
        rows = conn.execute("SELECT c.*, u.display_name AS teacher_name FROM classes c LEFT JOIN users u ON u.user_id = c.teacher_id "
                            "WHERE c.org_id = ? AND c.archived_at IS NULL ORDER BY c.created_at", (org["org_id"],)).fetchall()
    else:
        rows = conn.execute("SELECT c.*, u.display_name AS teacher_name FROM classes c LEFT JOIN users u ON u.user_id = c.teacher_id "
                            "WHERE c.org_id = ? AND c.teacher_id = ? AND c.archived_at IS NULL ORDER BY c.created_at",
                            (org["org_id"], me["user_id"])).fetchall()
    classes = []
    for c in rows:
        n = conn.execute("SELECT COUNT(*) FROM class_members WHERE class_id = ? AND left_at IS NULL", (c["class_id"],)).fetchone()[0]
        exams = [_exam_summary(rconn, e) for e in rconn.execute(
            "SELECT * FROM exam_sets WHERE class_id = ? ORDER BY created_at DESC", (c["class_id"],))]
        last = exams[0] if exams else None
        if n == 0:
            todo = "명단을 올리세요"
        elif last is None:
            todo = "첫 시험지를 만드세요"
        elif last["status"] == "draft":
            todo = f"'{last['title']}' 구성 중 — 확정하고 여세요"
        elif last["status"] == "open":
            todo = f"'{last['title']}' 진행 중 — {last['n_submitted']}/{n} 제출"
        else:
            todo = f"'{last['title']}' 결과를 보세요"
        classes.append({"class_id": c["class_id"], "name": c["name"], "teacher_id": c["teacher_id"],
                        "teacher_name": c["teacher_name"], "n_students": n, "n_exams": len(exams),
                        "last_exam": last, "todo": todo})
    return {"org": org, "me": {"user_id": me["user_id"], "display_name": me["display_name"], "role": org["role"]},
            "classes": classes}


@router.post("/classes")
def api_create_class(body: ClassIn, me: dict = Depends(require_teacher),
                     conn: sqlite3.Connection = Depends(auth.accounts_conn)):
    org = my_org(conn, me)
    try:
        class_id = A.create_class(conn, org_id=org["org_id"], name=body.name, teacher_id=me["user_id"])
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"class_id": class_id}


@router.get("/classes/{class_id}")
def api_class(class_id: str, me: dict = Depends(require_teacher), conn: sqlite3.Connection = Depends(auth.accounts_conn),
              rconn: sqlite3.Connection = Depends(responses_conn)):
    """반 = 명단 + 시험 목록 (화면 2번). 퇴원생은 left_at 과 함께 뒤에."""
    auth.ensure_class_teacher(conn, me, class_id)
    c = conn.execute("SELECT c.*, u.display_name AS teacher_name FROM classes c LEFT JOIN users u ON u.user_id = c.teacher_id "
                     "WHERE c.class_id = ?", (class_id,)).fetchone()
    exams = [_exam_summary(rconn, e) for e in rconn.execute(
        "SELECT * FROM exam_sets WHERE class_id = ? ORDER BY round_no DESC, created_at DESC", (class_id,))]
    return {"class": dict(c), "members": _members(conn, class_id, active_only=False), "exams": exams}


@router.post("/classes/{class_id}/students")
def api_enroll(class_id: str, body: StudentsIn, me: dict = Depends(require_teacher),
               conn: sqlite3.Connection = Depends(auth.accounts_conn)):
    """
    명단 등록. 한 행이라도 틀리면 400 — 전부 안 들어간다 (accounts.enroll_students 규칙).
    ★ 반환의 pin 은 평문 임시 비밀번호. 이 응답에만 있다. 화면은 안내문 인쇄에 쓰고 보관하지 않는다.
    """
    auth.ensure_class_teacher(conn, me, class_id)
    if not body.rows:
        raise HTTPException(400, "명단이 비었습니다")
    try:
        made = A.enroll_students(conn, class_id, [r.model_dump() for r in body.rows])
    except (ValueError, A.AccountsError) as e:
        conn.rollback()                 # open_conn 은 HTTPException 에도 commit 한다 — 앞 줄들이 반쪽으로 남지 않게
        raise HTTPException(400, str(e)) from None
    return {"students": made}


@router.post("/classes/{class_id}/students/{user_id}/reset-password")
def api_reset_pw(class_id: str, user_id: str, me: dict = Depends(require_teacher),
                 conn: sqlite3.Connection = Depends(auth.accounts_conn)):
    auth.ensure_class_teacher(conn, me, class_id)
    _require_member_of(conn, class_id, user_id)
    pin = A.reset_password(conn, user_id)
    return {"user_id": user_id, "pin": pin}


@router.post("/classes/{class_id}/students/{user_id}/withdraw")
def api_withdraw(class_id: str, user_id: str, me: dict = Depends(require_teacher),
                 conn: sqlite3.Connection = Depends(auth.accounts_conn)):
    auth.ensure_class_teacher(conn, me, class_id)
    _require_member_of(conn, class_id, user_id)
    A.withdraw_student(conn, class_id, user_id)
    return {"ok": True}


# ============================================================ 과제 (assignments — 처방 트랙)
def _assignment_batches(rconn: sqlite3.Connection, user_id: str) -> list[dict]:
    """학생 한 명의 과제를 assigned_at 으로 묶어서 (한 번에 낸 것 = 한 묶음). 최근 것 먼저."""
    rows = rconn.execute("SELECT assignment_id, item_key, target_concept, assigned_at, due_at, status FROM assignments "
                         "WHERE student_id = ? ORDER BY assigned_at DESC, assignment_id", (user_id,)).fetchall()
    meta = _item_meta([r["item_key"] for r in rows])
    out: dict[str, dict] = {}
    for r in rows:
        b = out.setdefault(r["assigned_at"], {"assigned_at": r["assigned_at"], "due_at": r["due_at"], "target_concept": r["target_concept"],
                                              "items": [], "n": 0, "n_done": 0})
        m = meta.get(r["item_key"], {})
        b["items"].append({"item_key": r["item_key"], "title": m.get("title", r["item_key"]), "status": r["status"]})
        b["n"] += 1
        b["n_done"] += r["status"] == "done"
    return list(out.values())


@router.post("/classes/{class_id}/students/{user_id}/assignments")
def api_assign(class_id: str, user_id: str, body: AssignIn, me: dict = Depends(require_teacher),
               conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    """
    과제 내기. 문항 n 개를 한 묶음(assigned_at 같음)으로. 학생 홈에 뜨고, 풀면 source='assigned' 로 저장되고 status 가 done 이 된다.
    from_diagnosis_id 는 아직 비워 둔다 — diagnoses 저장이 붙으면 그때 연결.
    """
    auth.ensure_class_teacher(conn, me, class_id)
    _require_member_of(conn, class_id, user_id)
    keys = list(dict.fromkeys(k for k in body.item_keys if k))
    if not keys:
        raise HTTPException(400, "문항이 없습니다")
    _check_items(keys)
    R.ensure_student(rconn, user_id)
    now = A.utcnow()
    for k in keys:
        rconn.execute("INSERT INTO assignments (assignment_id, student_id, item_key, target_concept, from_diagnosis_id, assigned_by, assigned_at, due_at, status) "
                      "VALUES (?, ?, ?, ?, NULL, 'teacher', ?, ?, 'assigned')",
                      ("as_" + A._rand(A.SHORT_ID_LEN), user_id, k, body.target_concept, now, body.due_at))
    return {"assigned_at": now, "n": len(keys)}


@router.get("/classes/{class_id}/students/{user_id}/assignments")
def api_assignments(class_id: str, user_id: str, me: dict = Depends(require_teacher),
                    conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    auth.ensure_class_teacher(conn, me, class_id)
    _require_member_of(conn, class_id, user_id)
    return {"batches": _assignment_batches(rconn, user_id)}


def _require_member_of(conn: sqlite3.Connection, class_id: str, user_id: str) -> None:
    if conn.execute("SELECT 1 FROM class_members WHERE class_id = ? AND user_id = ?", (class_id, user_id)).fetchone() is None:
        raise HTTPException(404, "이 반의 학생이 아닙니다")


# ============================================================ 문항 은행
def load_bank() -> list[dict]:
    """
    is_true 가 있는 보기(또는 계산형 '답')를 가진 문항 전부 — 개념 없어도. 시험지 구성 화면의 재료.
    개념 없는 문항은 concepts 가 비어 있고, 자동 담기는 그것을 안 고른다 (진단 층이 없으니까). 채점은 된다.
    문항마다 concepts(정렬된 코드) · labels(ㄱㄴㄷ 또는 '답') · format · correct_rate. 보기 원문은 안 내보낸다 (저작권 — 이미지로 본다).
    """
    conn = connect(PHYSICS_DB, [(CONCEPT_MAP_DB, CM)])
    rows = conn.execute(f"""
        SELECT i.item_key, i.year, i.mon, i.number, i.cat_1, i.leaf, i.correct_rate, i.item_format,
               s.label, s.error_rate, k.concept
        FROM items i
        JOIN statements s ON s.item_key = i.item_key
        LEFT JOIN {CM}.statement_concept k ON k.item_key = s.item_key AND k.label = s.label
        WHERE s.is_true IS NOT NULL
        ORDER BY i.year, i.mon, i.number, s.label
    """).fetchall()
    conn.close()
    items: dict[str, dict] = {}
    for r in rows:
        it = items.setdefault(r["item_key"], {
            "item_key": r["item_key"], "title": f"{r['year']}년 {r['mon']}월 {r['number']}번",
            "year": r["year"], "mon": r["mon"], "number": r["number"],
            "cat": r["cat_1"], "leaf": r["leaf"], "format": r["item_format"], "correct_rate": r["correct_rate"],
            "image": f"/images/{r['item_key']}", "labels": [], "concepts": set(), "units": []})
        it["labels"].append(r["label"])
        codes = [c.strip() for c in (r["concept"] or "").split(",") if c.strip()]
        it["concepts"].update(codes)
        it["units"].append({"label": r["label"], "concepts": sort_concept(set(codes)), "error_rate": r["error_rate"]})   # 보기별 — exam_pick 이 단독 보기를 센다
    out = []
    for it in items.values():
        it["concepts"] = sort_concept(it["concepts"])
        out.append(it)
    return out


@router.get("/bank")
def api_bank(me: dict = Depends(require_teacher)):
    """문항 은행 + 단원 목록 + 단원별 개념(이름 포함). 커버리지(\"C03·C05 가 안 재짐\")는 화면이 센다."""
    items = load_bank()
    cats = sorted({it["cat"] for it in items if it["cat"]}, key=lambda c: list(CONCEPTS_BY_UNIT).index(c) if c in CONCEPTS_BY_UNIT else 99)
    concepts = {cat: [{"code": c, "label": concept_label(c), "group": concept_group(c)} for c in CONCEPTS_BY_UNIT.get(cat, [])] for cat in cats}
    return {"items": items, "cats": cats, "concepts": concepts}


class PickIn(BaseModel):
    concepts: list[str] = Field(default_factory=list)      # 진단할 개념
    n_statements: int = 6                             # 보기형 수
    n_numeric: int = 2                                # 계산형 수
    exclude_seen: bool = False                        # 이 반이 이미 본 문항 제외
    keep: list[str] = Field(default_factory=list)     # 이미 담긴 문항 (커버리지에 세고, 뒤에 덧붙인다)


@router.post("/classes/{class_id}/exams/pick")
def api_pick_items(class_id: str, body: PickIn, me: dict = Depends(require_teacher),
                   conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    """
    개념 + 문항 수 → 시험 문항 제안 (exam_pick.pick). 저장하지 않는다 — 화면이 담긴 목록에 넣고 강사가 고친 뒤 저장한다.
    exclude_seen: 이 반의 어느 시험에든 들어갔던 문항은 뺀다 (구성 중인 것 포함).
    """
    from ..engine.exam_pick import pick
    auth.ensure_class_teacher(conn, me, class_id)
    if not body.concepts:
        raise HTTPException(400, "진단할 개념 를 하나 이상 고르세요")
    if body.n_statements + body.n_numeric <= 0:
        raise HTTPException(400, "문항 수가 0 입니다")
    seen: set[str] = set()
    if body.exclude_seen:
        seen = {r["item_key"] for r in rconn.execute(
            "SELECT DISTINCT ei.item_key FROM exam_items ei JOIN exam_sets e ON e.exam_set_id = ei.exam_set_id WHERE e.class_id = ?",
            (class_id,))}
    r = pick(load_bank(), body.concepts, body.n_statements, body.n_numeric, exclude=seen, keep=body.keep)
    r["n_excluded"] = len(seen)
    return r


# ============================================================ 시험지
def _ensure_exam_access(conn: sqlite3.Connection, rconn: sqlite3.Connection, me: dict, exam_set_id: str) -> sqlite3.Row:
    e = _exam_row(rconn, exam_set_id)
    auth.ensure_class_teacher(conn, me, e["class_id"])
    return e


def _check_items(keys: list[str]) -> dict:
    if not keys:
        raise HTTPException(400, "문항을 하나 이상 담으세요")
    if len(set(keys)) != len(keys):
        raise HTTPException(400, "같은 문항이 두 번 들어 있습니다")
    facts = load_item_facts(keys)
    missing = [k for k in keys if k not in facts["format"]]
    if missing:
        raise HTTPException(400, f"없는 문항: {', '.join(missing[:5])}")
    return facts


def _write_items(rconn: sqlite3.Connection, exam_set_id: str, keys: list[str], mode: str, facts: dict) -> None:
    """exam_items 를 통째로 다시 쓴다. input_format 은 모드 × 형식 (스키마 v5 주석)."""
    rconn.execute("DELETE FROM exam_items WHERE exam_set_id = ?", (exam_set_id,))
    for i, k in enumerate(keys, 1):
        if mode == "realistic":
            fmt = "choice"
        elif facts["format"][k] == "numeric":
            fmt = "short" if facts["texts"].get(k) else "choice"     # 선지 값(전사)이 없으면 단답을 대조할 수 없다 → ①~⑤
        else:
            fmt = "per_statement"
        rconn.execute("INSERT INTO exam_items (exam_set_id, item_key, seq, input_format) VALUES (?, ?, ?, ?)",
                      (exam_set_id, k, i, fmt))


@router.post("/classes/{class_id}/exams")
def api_create_exam(class_id: str, body: ExamIn, me: dict = Depends(require_teacher),
                    conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    auth.ensure_class_teacher(conn, me, class_id)
    if body.mode not in ("diagnostic", "realistic"):
        raise HTTPException(400, "mode 는 diagnostic 또는 realistic")
    title = body.title.strip()
    if not title:
        raise HTTPException(400, "제목을 적으세요")
    facts = _check_items(body.item_keys)
    round_no = rconn.execute("SELECT COALESCE(MAX(round_no), 0) + 1 FROM exam_sets WHERE class_id = ?", (class_id,)).fetchone()[0]
    exam_set_id = "e_" + A._rand(A.SHORT_ID_LEN)
    rconn.execute("INSERT INTO exam_sets (exam_set_id, class_id, title, round_no, mode, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (exam_set_id, class_id, title, round_no, body.mode, me["user_id"], A.utcnow()))
    _write_items(rconn, exam_set_id, body.item_keys, body.mode, facts)
    return {"exam_set_id": exam_set_id, "round_no": round_no}


@router.put("/exams/{exam_set_id}")
def api_update_exam(exam_set_id: str, body: ExamIn, me: dict = Depends(require_teacher),
                    conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    e = _ensure_exam_access(conn, rconn, me, exam_set_id)
    if exam_status(e) != "draft":
        raise HTTPException(409, "확정된 시험은 문항을 바꿀 수 없습니다 (응시한 학생과 시험지가 달라집니다)")
    if body.mode not in ("diagnostic", "realistic"):
        raise HTTPException(400, "mode 는 diagnostic 또는 realistic")
    facts = _check_items(body.item_keys)
    rconn.execute("UPDATE exam_sets SET title = ?, mode = ? WHERE exam_set_id = ?", (body.title.strip() or e["title"], body.mode, exam_set_id))
    _write_items(rconn, exam_set_id, body.item_keys, body.mode, facts)
    return {"ok": True}


@router.delete("/exams/{exam_set_id}")
def api_delete_exam(exam_set_id: str, me: dict = Depends(require_teacher),
                    conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    e = _ensure_exam_access(conn, rconn, me, exam_set_id)
    if exam_status(e) != "draft":
        raise HTTPException(409, "확정된 시험은 지울 수 없습니다")
    if rconn.execute("SELECT 1 FROM attempts WHERE exam_set_id = ? LIMIT 1", (exam_set_id,)).fetchone():
        raise HTTPException(409, "응답이 있는 시험은 지울 수 없습니다")      # FK 로 500 나던 것 (dev/fill 뒤)
    rconn.execute("DELETE FROM exam_items WHERE exam_set_id = ?", (exam_set_id,))
    rconn.execute("DELETE FROM exam_sets WHERE exam_set_id = ?", (exam_set_id,))
    return {"ok": True}


@router.post("/exams/{exam_set_id}/open")
def api_open_exam(exam_set_id: str, me: dict = Depends(require_teacher),
                  conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    """확정 + 열기. 이 순간부터 학생 앱 '열린 시험' 에 보인다. 문항은 더 못 바꾼다."""
    e = _ensure_exam_access(conn, rconn, me, exam_set_id)
    if exam_status(e) == "closed":
        raise HTTPException(409, "끝난 시험입니다")
    if not _exam_items(rconn, exam_set_id):
        raise HTTPException(400, "문항이 없는 시험은 열 수 없습니다")
    if not e["opened_at"]:
        rconn.execute("UPDATE exam_sets SET opened_at = ? WHERE exam_set_id = ?", (A.utcnow(), exam_set_id))
    return {"status": "open"}


@router.post("/exams/{exam_set_id}/close")
def api_close_exam(exam_set_id: str, me: dict = Depends(require_teacher),
                   conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    e = _ensure_exam_access(conn, rconn, me, exam_set_id)
    if exam_status(e) != "open":
        raise HTTPException(409, "진행 중인 시험만 닫을 수 있습니다")
    rconn.execute("UPDATE exam_sets SET closed_at = ? WHERE exam_set_id = ?", (A.utcnow(), exam_set_id))
    return {"status": "closed"}


def _item_meta(keys: list[str]) -> dict[str, dict]:
    """제목·형식·정답률·보기 참/거짓 (is_true). 결과 채점과 시험지 화면이 쓴다."""
    if not keys:
        return {}
    qs = ",".join("?" * len(keys))
    conn = connect(PHYSICS_DB)
    meta = {r["item_key"]: {"item_key": r["item_key"], "title": f"{r['year']}년 {r['mon']}월 {r['number']}번",
                            "cat": r["cat_1"], "format": r["item_format"], "correct_rate": r["correct_rate"],
                            "image": f"/images/{r['item_key']}", "labels": [], "truth": {}}
            for r in conn.execute(f"SELECT item_key, year, mon, number, cat_1, item_format, correct_rate FROM items WHERE item_key IN ({qs})", keys)}
    for r in conn.execute(f"SELECT item_key, label, is_true, error_rate FROM statements WHERE item_key IN ({qs}) ORDER BY label", keys):
        m = meta.get(r["item_key"])
        if m is None:
            continue
        m["labels"].append(r["label"])
        m["truth"][r["label"]] = r["is_true"]
    conn.close()
    return meta


@router.get("/exams/{exam_set_id}")
def api_exam(exam_set_id: str, me: dict = Depends(require_teacher),
             conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    """시험지 + 응시 현황 (화면 3·4번). 학생마다 제출 여부."""
    e = _ensure_exam_access(conn, rconn, me, exam_set_id)
    rows = _exam_items(rconn, exam_set_id)
    meta = _item_meta([r["item_key"] for r in rows])
    items = [{**meta.get(r["item_key"], {"item_key": r["item_key"], "title": r["item_key"], "labels": [], "truth": {}}),
              "seq": r["seq"], "input_format": r["input_format"]} for r in rows]
    for it in items:
        it.pop("truth", None)
    members = _members(conn, e["class_id"])
    att = _attempts_by_student(rconn, exam_set_id)
    students = [{"user_id": m["user_id"], "display_name": m["display_name"], "login_key": m["login_key"],
                 "attempt_id": att.get(m["user_id"], {}).get("attempt_id"),
                 "finished_at": att.get(m["user_id"], {}).get("finished_at")} for m in members]
    cls = conn.execute("SELECT name FROM classes WHERE class_id = ?", (e["class_id"],)).fetchone()
    return {"exam": _exam_summary(rconn, e), "class_name": cls["name"] if cls else None, "items": items, "students": students}


# ============================================================ 결과
def _units_of(attempt_items: list[dict], meta: dict, facts: dict) -> dict[str, dict]:
    """
    한 풀이를 문항별 판단 단위로. {item_key: {"units": {label: bool|None}, "unsure": {label}, "answered": bool, "choice_no", "answer_text"}}
    보기별(per_statement)은 statement_responses 그대로 정답(is_true)과 비교.
    선지·단답은 student.derived_units 와 같은 규칙으로 ㄱㄴㄷ 역산 / '답' 판정.
    None = 판단 안 함(무응답·모르겠다) — 틀린 것으로 세지 않는다.
    """
    out: dict[str, dict] = {}
    for r in attempt_items:
        key = r["item_key"]
        m = meta.get(key)
        if m is None:
            continue
        cell = {"units": {}, "unsure": [], "answered": False, "choice_no": r.get("choice_no"), "answer_text": r.get("answer_text"),
                "input_format": r.get("input_format")}
        if r.get("input_format") == "per_statement":
            for s in r.get("statements", []):
                truth = m["truth"].get(s["label"])
                if s["unsure"]:
                    cell["unsure"].append(s["label"])
                if s["judged_true"] is None or truth is None:
                    cell["units"][s["label"]] = None
                else:
                    cell["units"][s["label"]] = bool(s["judged_true"]) == bool(truth)
                    cell["answered"] = True
        else:
            a = StudentAnswer(item_key=key, choice_no=r.get("choice_no") if r.get("input_format") == "choice" else None,
                              answer_text=r.get("answer_text"))
            derived = derived_units([a], facts)
            if derived:
                cell["answered"] = True
            for d in derived:
                cell["units"][d.label] = bool(d.answer == facts_truth(d, m))
        out[key] = cell
    return out


def facts_truth(d: Resp, m: dict) -> bool:
    """derived_units 의 Resp.answer 는 '학생이 참이라 봤나'. 보기형은 is_true 와, '답' 은 True 와 비교한다."""
    if d.label == ANSWER_LABEL:
        return True
    return bool(m["truth"].get(d.label))


@router.get("/exams/{exam_set_id}/results")
def api_results(exam_set_id: str, me: dict = Depends(require_teacher),
                conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    """
    결과 표 ①. 행 = 학생, 열 = 문항. 칸 = 그 문항에서 틀린 보기 수 + 모르겠다 포함 + 미응시.
    열 머리 = 문항 정답률(반) + 보기별 반 오답률 (ㄱ·ㄴ·ㄷ 막대 셋). 계산형은 '답' 하나.
    """
    e = _ensure_exam_access(conn, rconn, me, exam_set_id)
    rows = _exam_items(rconn, exam_set_id)
    keys = [r["item_key"] for r in rows]
    meta = _item_meta(keys)
    facts = load_item_facts(keys)
    members = _members(conn, e["class_id"])
    att = _attempts_by_student(rconn, exam_set_id)

    # 열 머리 집계: 보기마다 [판단한 수, 틀린 수]
    col: dict[str, dict[str, list[int]]] = {k: {} for k in keys}
    item_ok: dict[str, list[int]] = {k: [0, 0] for k in keys}          # [응시, 다 맞음]
    students = []
    for m in members:
        a = att.get(m["user_id"])
        cells: dict[str, dict] = {k: {"state": "absent"} for k in keys}     # 미응시 = 전부 회색
        n_full = 0
        if a:
            got = R.load_attempt(rconn, a["attempt_id"]) or {"items": []}
            units = _units_of(got["items"], meta, facts)
            for k in keys:
                u = units.get(k)
                if u is None:
                    cells[k] = {"state": "absent"}
                    continue
                wrong = [lab for lab, ok in u["units"].items() if ok is False]
                judged = [lab for lab, ok in u["units"].items() if ok is not None]
                for lab, ok in u["units"].items():
                    if ok is not None:
                        c = col[k].setdefault(lab, [0, 0]); c[0] += 1; c[1] += (0 if ok else 1)
                item_ok[k][0] += 1
                full = bool(judged) and not wrong and len(judged) == len(u["units"])
                if full:
                    item_ok[k][1] += 1; n_full += 1
                cells[k] = {"state": "ok" if full else ("wrong" if wrong else "blank"), "wrong": wrong, "unsure": u["unsure"],
                            "units": u["units"], "choice_no": u["choice_no"], "answer_text": u["answer_text"]}
        students.append({"user_id": m["user_id"], "display_name": m["display_name"], "attempt_id": a["attempt_id"] if a else None,
                         "n_full": n_full, "score": round(100 * n_full / len(keys)) if keys and a else None, "cells": cells})

    items = []
    for r in rows:
        k = r["item_key"]
        mt = meta.get(k, {"title": k, "labels": [], "format": None, "correct_rate": None, "cat": None, "image": f"/images/{k}"})
        labels = [ANSWER_LABEL] if mt.get("format") == "numeric" else [lab for lab in mt["labels"] if lab != ANSWER_LABEL]
        items.append({"item_key": k, "seq": r["seq"], "title": mt["title"], "format": mt.get("format"), "cat": mt.get("cat"),
                      "image": mt.get("image"), "input_format": r["input_format"], "national_correct_rate": mt.get("correct_rate"),
                      "class_correct_rate": round(100 * item_ok[k][1] / item_ok[k][0]) if item_ok[k][0] else None,
                      "labels": labels,
                      "stmt_wrong_rate": {lab: (round(100 * c[1] / c[0]) if c[0] else None) for lab, c in
                                          ((lab, col[k].get(lab, [0, 0])) for lab in labels)}})
    cls = conn.execute("SELECT name FROM classes WHERE class_id = ?", (e["class_id"],)).fetchone()
    return {"exam": _exam_summary(rconn, e), "class_name": cls["name"] if cls else None, "items": items, "students": students,
            "n_submitted": sum(1 for s in students if s["attempt_id"])}


@router.get("/exams/{exam_set_id}/students/{user_id}")
def api_student_result(exam_set_id: str, user_id: str, me: dict = Depends(require_teacher),
                       conn: sqlite3.Connection = Depends(auth.accounts_conn), rconn: sqlite3.Connection = Depends(responses_conn)):
    """학생 한 명 (③). 이 시험의 문항별 판단 + 개념 진단 (학생 앱 결과와 같은 sections/tiers) + 이 반 회차 추이."""
    e = _ensure_exam_access(conn, rconn, me, exam_set_id)
    _require_member_of(conn, e["class_id"], user_id)
    name = conn.execute("SELECT display_name FROM class_members WHERE class_id = ? AND user_id = ?", (e["class_id"], user_id)).fetchone()
    a = _attempts_by_student(rconn, exam_set_id).get(user_id)
    if a is None:
        return {"student": {"user_id": user_id, "display_name": name["display_name"]}, "attempt": None}
    rows = _exam_items(rconn, exam_set_id)
    keys = [r["item_key"] for r in rows]
    meta = _item_meta(keys)
    facts = load_item_facts(keys)
    got = R.load_attempt(rconn, a["attempt_id"]) or {"items": []}
    units = _units_of(got["items"], meta, facts)
    items = []
    resps: list[Resp] = []
    for r in rows:
        k = r["item_key"]
        u = units.get(k)
        mt = meta.get(k, {})
        items.append({"item_key": k, "seq": r["seq"], "title": mt.get("title", k), "image": mt.get("image"),
                      "units": u["units"] if u else {}, "unsure": u["unsure"] if u else [],
                      "elapsed_ms": next((x.get("elapsed_ms") for x in got["items"] if x["item_key"] == k), None)})
        if u:
            for lab, ok in u["units"].items():
                if ok is not None:
                    truth = True if lab == ANSWER_LABEL else bool(mt["truth"].get(lab))
                    resps.append(Resp(k, lab, truth if ok else (not truth)))
    diag = engine().estimate(resps)
    sections = as_sections([{"code": x.code, "score": x.score, "status": x.status, "n_units": x.n_units, "n_correct": x.n_correct, "wrong": []}
                            for x in diag.concepts if x.n_units > 0])
    tiers = concept_tiers([{"code": x.code, "score": x.score, "status": x.status} for x in diag.concepts])
    # 회차 추이: 이 반의 끝난·진행 중 시험에서 이 학생의 다 맞은 문항 비율
    history = []
    for ex in rconn.execute("SELECT * FROM exam_sets WHERE class_id = ? AND opened_at IS NOT NULL ORDER BY round_no", (e["class_id"],)):
        ha = _attempts_by_student(rconn, ex["exam_set_id"]).get(user_id)
        hk = [x["item_key"] for x in _exam_items(rconn, ex["exam_set_id"])]
        score = None
        if ha and hk:
            hg = R.load_attempt(rconn, ha["attempt_id"]) or {"items": []}
            hu = _units_of(hg["items"], _item_meta(hk), load_item_facts(hk))
            full = sum(1 for k in hk if (u := hu.get(k)) and u["units"] and all(v is True for v in u["units"].values()))
            score = round(100 * full / len(hk))
        history.append({"exam_set_id": ex["exam_set_id"], "title": ex["title"], "round_no": ex["round_no"], "score": score})
    return {"student": {"user_id": user_id, "display_name": name["display_name"]},
            "attempt": {"attempt_id": a["attempt_id"], "started_at": a["started_at"], "finished_at": a["finished_at"]},
            "items": items, "summary": {"answered": diag.n_answered, "correct": diag.n_correct},
            "tiers": tiers, "sections": sections, "history": history}


# ============================================================ 원장
@owner.get("/overview")
def api_overview(me: dict = Depends(require_teacher), conn: sqlite3.Connection = Depends(auth.accounts_conn),
                 rconn: sqlite3.Connection = Depends(responses_conn)):
    """학원 전체 (화면 1번 '학원 전체' 탭). 원장만. 강사 목록 · 모든 반 · 승인 상태."""
    org = my_org(conn, me)
    auth.ensure_owner(conn, me, org["org_id"])
    teachers = [dict(r) for r in conn.execute(
        "SELECT u.user_id, u.display_name, u.email, m.role, m.joined_at FROM org_members m JOIN users u USING (user_id) "
        "WHERE m.org_id = ? AND m.left_at IS NULL ORDER BY m.role DESC, m.joined_at", (org["org_id"],))]
    classes = []
    for c in conn.execute("SELECT c.*, u.display_name AS teacher_name FROM classes c LEFT JOIN users u ON u.user_id = c.teacher_id "
                          "WHERE c.org_id = ? AND c.archived_at IS NULL ORDER BY c.created_at", (org["org_id"],)):
        n = conn.execute("SELECT COUNT(*) FROM class_members WHERE class_id = ? AND left_at IS NULL", (c["class_id"],)).fetchone()[0]
        last = rconn.execute("SELECT * FROM exam_sets WHERE class_id = ? ORDER BY created_at DESC LIMIT 1", (c["class_id"],)).fetchone()
        classes.append({"class_id": c["class_id"], "name": c["name"], "teacher_name": c["teacher_name"], "teacher_id": c["teacher_id"],
                        "n_students": n, "last_exam": _exam_summary(rconn, last) if last else None})
    n_students = conn.execute("SELECT COUNT(DISTINCT cm.user_id) FROM class_members cm JOIN classes c USING (class_id) "
                              "WHERE c.org_id = ? AND cm.left_at IS NULL", (org["org_id"],)).fetchone()[0]
    return {"org": org, "teachers": teachers, "classes": classes, "n_students": n_students}


@owner.post("/invites")
def api_invite(body: InviteIn, me: dict = Depends(require_teacher), conn: sqlite3.Connection = Depends(auth.accounts_conn)):
    """강사 초대 토큰. 가입 화면의 '초대 코드' 칸에 넣는다. 원문은 이 응답에만."""
    org = my_org(conn, me)
    auth.ensure_owner(conn, me, org["org_id"])
    token = A.create_invite(conn, org_id=org["org_id"], created_by=me["user_id"], email=body.email, days=body.days)
    return {"invite": token, "days": body.days}
