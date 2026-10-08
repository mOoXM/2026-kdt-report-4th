r"""
student.py — 학생용 API. /api/student/… 와 /images/{key}

    GET  /api/student/items?mode=image|text   연결표이 붙은 문항 (지금은 뉴턴 법칙 단원만)
    POST /api/student/submit                  보기별 판단 → 채점·진단 + responses.db 저장 (로그인 필수)
    GET  /api/student/concepts                     개념 목록 (학생용 문구만)
    GET  /images/{item_key}                   문항 이미지 (주소는 문항 데이터에 박혀 있어 prefix 없이 둔다)

왜 파일이 따로인가 — 사용자 축으로 모듈을 나눈다. 학생 API 를 고칠 때 강사 코드가 화면에 없고,
나중에 학생 서버만 따로 띄우게 되면 `install(app)` 한 줄로 조립한다. api.py 는 조립과 HTML 서빙만 한다.
도메인은 responses.py(저장)·diagnosis.py(진단)·concept_display.py(문구) — 이 파일은 HTTP 층이다.

두 가지 표시 방식
-----------------
    items?mode=image   문항 이미지 (실제 시험지) — 저작권 노출 지점
    items?mode=text    stem + 도표 서술 + 보기 텍스트 (VLM 이 뽑은 것)

응답을 저장한다
----------------------
/submit 은 로그인 필수 (auth.require_user). 채점·진단은 전과 같이 돌려주고, 풀이는 responses.py 로
responses.db 에 쓴다 (purpose='practice'; 시험지가 생기면 exam). 익명 채점 경로는 없다 — 무료 이용자도
게스트 키로 들어온다. "모르겠다"(unsure)·시간 필드도 받는다. 저장은 하되 채점·진단에서는 뺀다.

저작권: /images 는 로컬 파일을 그대로 낸다. 승인된 학원 소속만(require_active_member) 붙이는 것은 ⑤ 에서.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import responses as R
from ..db import ANSWER_LABEL, DEFAULT_SUBJECT, PHYSICS_DB, CONCEPT_MAP_DB, CM, ROOT, connect, init_responses_db, responses_db
from ..offline.regions import regions_of
from . import auth
from ..engine.concept_display import (also as concept_also, as_sections, catalog, group as concept_group,
                         label as concept_label, tiers as concept_tiers)
from ..engine.diagnosis import DIAGNOSIS_THRESHOLD, BasicDiagnosis, Response as Resp

UNIT = "뉴턴 법칙"          # M1 은 이 단원만

router = APIRouter(prefix="/api/student", tags=["student"])
images = APIRouter(tags=["student"])          # /images/{key} — prefix 없음


def install(app: FastAPI) -> None:
    """api.py 가 부른다. 학생 서버만 따로 띄울 때도 이 한 줄."""
    app.include_router(router)
    app.include_router(images)


_engine: BasicDiagnosis | None = None
_engine_stamp: tuple[float, float] | None = None


def _db_stamp() -> tuple[float, float]:
    """두 DB 파일의 mtime. 둘 중 하나라도 바뀌면 다시 읽는다."""
    return (os.stat(PHYSICS_DB).st_mtime, os.stat(CONCEPT_MAP_DB).st_mtime)


def engine() -> BasicDiagnosis:
    """
    프로세스 수명 동안 캐시하되, DB 파일이 바뀌었으면 다시 적재한다.

    예전에는 한 번 읽으면 끝이라 "검수했는데 진단이 그대로" 가 반복됐다.
    폰 검수가 concept_map.db 를 고치면 그 다음 요청부터 반영된다.
    mtime 비교는 stat() 두 번이라 요청마다 해도 비용이 없다.
    """
    global _engine, _engine_stamp
    stamp = _db_stamp()
    if _engine is None or stamp != _engine_stamp:
        _engine = BasicDiagnosis.from_db(PHYSICS_DB, CONCEPT_MAP_DB, cat=UNIT)
        _engine_stamp = stamp
    return _engine


# ------------------------------------------------------------ 스키마
class Answer(BaseModel):
    """
    응답 하나. 세 모양 중 하나 (responses.py 머리 주석):
      보기별  label + answer   True/False = 판단, None = 무응답, None + unsure = "모르겠다"   (진단 모드, ㄱㄴㄷ 문항)
      단답    answer_text       계산형 문항을 진단 모드로 — 선지를 안 보고 값을 적는다
      선지    choice_no 1~5     실전 모드 — 어느 문항이든 ①~⑤
    """
    item_key: str
    label: str | None = None
    answer: bool | None = None
    unsure: bool = False
    choice_no: int | None = None
    answer_text: str | None = None
    answered_at: str | None = None
    changed_cnt: int = 0


class ItemTiming(BaseModel):
    """문항 단위 시간·UI 부하 (전부 선택. 화면이 재서 보내면 저장된다)."""
    item_key: str
    seq: int | None = None
    elapsed_ms: int | None = None
    focus_lost_ms: int | None = None
    scroll_px: int | None = None
    shown_at: str | None = None
    answered_at: str | None = None


class ClientInfo(BaseModel):
    device: str | None = None
    viewport: str | None = None
    orientation: str | None = None
    started_at: str | None = None


class SubmitRequest(BaseModel):
    answers: list[Answer] = Field(default_factory=list)
    items: list[ItemTiming] = Field(default_factory=list)
    client: ClientInfo | None = None
    exam_set_id: str | None = None            # 있으면 시험 길 (purpose='exam'). 열린 시험 + 내 반 + 아직 제출 안 함 이어야 한다
    source: str | None = None                 # 연습 길만: self_selected(기본) | recommended
    assigned_at: str | None = None            # 과제 묶음(assignments.assigned_at). 있으면 source='assigned' 로 저장하고 그 문항들을 done 으로


# ------------------------------------------------------------ 응답 DB 연결
_migrated: set[Path] = set()


def responses_conn():
    """
    요청마다 responses.db 연결 하나. 규칙은 auth.open_conn 과 같다 (HTTPException 이어도 commit).
    없으면 만들고, 있으면 프로세스당 한 번 스키마를 맞춘다 (v6 열 추가 — db.migrate_responses_db).
    """
    path = responses_db()
    if path not in _migrated:
        init_responses_db(path=path)              # 없으면 생성, 있으면 migrate
        _migrated.add(path)
    yield from auth.open_conn(path)


def load_item_facts(keys: list[str]) -> dict:
    """
    physics.db 에서 문항들의 형식·보기 목록·선지 구성·선지 값을 읽는다.
    {"format":  {item_key: "statements" | "numeric"},
     "labels":  {item_key: {"ㄱ","ㄴ","ㄷ"}},                      '답' 은 안 들어간다 (화면이 보내는 보기가 아니다)
     "choices": {item_key: [(choice_no, {"ㄱ","ㄴ"}), ...]},      보기 조합형 — 파생 선지 계산용
     "texts":   {item_key: {choice_no: "4 kg", ...}},             계산형 — 단답 → 선지 대조용
     "answer":  {item_key: choice_no}}                            정답 선지 — 계산형 채점용
    보기 목록은 "없는 보기" 를 400 으로 막는 데 쓴다.
    """
    facts = {"format": {}, "labels": {}, "choices": {}, "texts": {}, "answer": {}}
    if not keys:
        return facts
    qs = ",".join("?" * len(keys))
    conn = connect(PHYSICS_DB)
    for r in conn.execute(f"SELECT item_key, item_format FROM items WHERE item_key IN ({qs})", keys):
        facts["format"][r["item_key"]] = r["item_format"]
    for r in conn.execute(f"SELECT item_key, label FROM statements WHERE item_key IN ({qs})", keys):
        if r["label"] != ANSWER_LABEL:
            facts["labels"].setdefault(r["item_key"], set()).add(r["label"])
    for r in conn.execute(f"SELECT item_key, choice_no, picks, text, is_answer FROM choices WHERE item_key IN ({qs})", keys):
        if r["is_answer"]:
            facts["answer"][r["item_key"]] = r["choice_no"]
        if r["picks"]:                                  # 보기 조합형
            facts["choices"].setdefault(r["item_key"], []).append(
                (r["choice_no"], {p.strip() for p in r["picks"].split(",")}))
        elif r["text"]:                                 # 계산형 — 값·수식 (pl-load-db 가 VLM 전사에서 넣는다)
            facts["texts"].setdefault(r["item_key"], {})[r["choice_no"]] = r["text"]
    conn.close()
    return facts


def derived_units(answers: list[Answer], facts: dict) -> list[Resp]:
    """
    보기별이 아닌 응답을 진단이 먹는 판단 단위로 바꾼다. 저장(responses.db)과는 무관 — 원본은 그대로 남는다.
      계산형 + 단답     → ('답', 맞았나). 입력값을 선지 값과 맞춰 정답 선지면 참. 어느 선지와도 안 맞으면 거짓
      계산형 + ①~⑤     → ('답', 고른 번호 == 정답 번호)
      보기형 + ①~⑤     → 그 선지가 참이라고 보는 보기 집합에서 ㄱㄴㄷ 각각을 역산 (실전 모드. 선지가 보였던 조건의 약한 자료)
    무응답(빈 단답)은 뺀다. 정답·선지 정보가 없는 문항도 뺀다.
    """
    out: list[Resp] = []
    for a in answers:
        if a.label:
            continue
        fmt, key = facts["format"].get(a.item_key), a.item_key
        if fmt == "numeric":
            ans = facts["answer"].get(key)
            if ans is None:
                continue
            if a.choice_no is not None:
                out.append(Resp(key, ANSWER_LABEL, a.choice_no == ans))
            elif a.answer_text and a.answer_text.strip():
                no, _ = R.derive_short(facts["texts"].get(key), a.answer_text)
                out.append(Resp(key, ANSWER_LABEL, no == ans))
        elif a.choice_no is not None:
            picks = dict(facts["choices"].get(key, []))
            if a.choice_no in picks:
                for label in sorted(facts["labels"].get(key, ())):
                    out.append(Resp(key, label, label in picks[a.choice_no]))
    return out


def _as_answer(a: Answer) -> dict:
    """Answer → responses.save_attempt 가 받는 dict (세 모양 중 하나)."""
    if a.label:
        return {"item_key": a.item_key, "label": a.label, "judged_true": a.answer, "unsure": a.unsure,
                "answered_at": a.answered_at, "changed_cnt": a.changed_cnt}
    if a.choice_no is not None:
        return {"item_key": a.item_key, "choice_no": a.choice_no, "answered_at": a.answered_at}
    return {"item_key": a.item_key, "answer_text": a.answer_text or "", "answered_at": a.answered_at}


def _save(rconn, me: dict, req: SubmitRequest, facts: dict) -> str:
    """풀이를 responses.db 에. exam_set_id 가 있으면 시험(exam, 진단 갱신 트랙), 없으면 연습(practice)."""
    R.ensure_student(rconn, me["user_id"])
    try:
        return R.save_attempt(
            rconn, student_id=me["user_id"], purpose="exam" if req.exam_set_id else "practice",
            exam_set_id=req.exam_set_id,
            source=None if req.exam_set_id else ("assigned" if req.assigned_at else req.source),
            answers=[_as_answer(a) for a in req.answers],
            items={t.item_key: t.model_dump(exclude={"item_key"}, exclude_none=True) for t in req.items},
            choices=facts["choices"], choice_texts=facts["texts"],
            client=req.client.model_dump(exclude={"started_at"}) if req.client else None,
            started_at=req.client.started_at if req.client else None)
    except R.BadAnswer as e:
        raise HTTPException(400, str(e)) from None
    except sqlite3.IntegrityError as e:
        if "ux_attempts_exam_student" in str(e):        # 동시에 두 번 제출 — 인덱스가 막았다 (db.migrate_responses_db)
            rconn.rollback()
            raise HTTPException(409, "이미 제출한 시험입니다") from None
        raise


def _mark_assigned_done(rconn, me: dict, req: SubmitRequest) -> None:
    """과제 묶음으로 푼 것은 assignments.status='done'. 묶음에 없는 문항은 그냥 연습으로 남는다."""
    if not req.assigned_at:
        return
    keys = sorted({a.item_key for a in req.answers})
    if keys:
        rconn.execute(f"UPDATE assignments SET status = 'done' WHERE student_id = ? AND assigned_at = ? AND status = 'assigned' "
                      f"AND item_key IN ({','.join('?' * len(keys))})", (me["user_id"], req.assigned_at, *keys))


# ------------------------------------------------------------ 문항
def load_items(mode: str, keys: list[str] | None = None) -> list[dict]:
    """
    연습 길(cat): 연결표이 붙은 문항만 — 개념 가 없으면 진단에 쓸 수 없다.
    시험 길(keys): 개념 없어도 내보낸다 — 상대성·전자기·파동처럼 개념 정의 전인 단원도 강사가 시험지에 담는다.
      보기(ㄱㄴㄷ, is_true)는 해설 통계에서 왔으므로 채점은 되고, 진단(개념 층)만 빠진다.

    정답(is_true)은 여기서 빼지 않는다 — 로컬 테스트용이고, 채점을 서버가
    하므로 굳이 숨길 필요가 없다. 외부 배포 시에는 빼야 한다.
    """
    conn = connect(PHYSICS_DB, [(CONCEPT_MAP_DB, CM)])
    if keys:
        cond, params = f"i.item_key IN ({','.join('?' * len(keys))})", tuple(keys)
        need_concept = ""
    else:
        cond, params = "i.cat_1 = ?", (UNIT,)
        need_concept = "AND k.concept != ''"
    rows = conn.execute(f"""
        SELECT i.item_key, i.year, i.mon, i.number, i.stem, i.diagram_desc,
               i.image_path, i.correct_rate, i.item_format,
               s.label, s.text, s.error_rate, k.concept
        FROM statements s
        JOIN items i ON i.item_key = s.item_key
        LEFT JOIN {CM}.statement_concept k
          ON k.item_key = s.item_key AND k.label = s.label
        WHERE {cond} {need_concept} AND s.is_true IS NOT NULL
        ORDER BY i.item_key, s.label
    """, params).fetchall()
    conn.close()

    items: dict[str, dict] = {}
    for r in rows:
        it = items.setdefault(r["item_key"], {
            "item_key": r["item_key"],
            "title": f"{r['year']}년 {r['mon']}월 {r['number']}번",
            "format": r["item_format"],                    # "statements" (ㄱㄴㄷ) | "numeric" (계산형: 단답 또는 ①~⑤)
            "correct_rate": r["correct_rate"],
            "statements": [],
        })
        if mode == "text":
            it["stem"] = r["stem"]
            it["diagram"] = r["diagram_desc"]
        else:
            it["image"] = f"/images/{r['item_key']}"
            it["regions"] = regions_of(r["item_key"])     # 구역 박스 (0~1000). 진단 모드가 options 를 가린다. 없으면 None
        if r["label"] == ANSWER_LABEL:                     # 계산형의 판단 단위 — 보기가 아니다. 정답 값은 내보내지 않는다
            continue
        it["statements"].append({
            "label": r["label"],
            "text": r["text"] if mode == "text" else None,
            "error_rate": r["error_rate"],
        })
    return list(items.values())


@router.get("/items")
def api_items(mode: str = Query("image", pattern="^(image|text)$"),
              limit: int = 0):
    items = load_items(mode)
    if limit:
        items = items[:limit]
    return {"cat": UNIT, "mode": mode, "n": len(items), "items": items}


@images.get("/images/{item_key}")
def api_image(item_key: str):
    """
    문항 이미지. **로컬 테스트용이다** — 외부 배포 시 저작권 재검토 필요.
    """
    conn = connect(PHYSICS_DB)
    row = conn.execute("SELECT image_path FROM items WHERE item_key = ?",
                       (item_key,)).fetchone()
    conn.close()
    if not row or not row[0]:
        raise HTTPException(404, "이미지 경로 없음")
    # physics.db 의 image_path 는 상대경로다. 프로젝트 루트 기준으로 푼다
    path = Path(row[0])
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise HTTPException(404, f"파일 없음: {path}")
    return FileResponse(path)


# ------------------------------------------------------------ 시험 길 (강사가 낸 시험)
def _my_class_ids(conn, user_id: str) -> list[str]:
    return [r["class_id"] for r in conn.execute(
        "SELECT class_id FROM class_members WHERE user_id = ? AND left_at IS NULL", (user_id,))]


def _open_exam_for(conn, rconn, me: dict, exam_set_id: str):
    """내 반의 진행 중(opened, not closed) 시험이어야 한다. 아니면 404/409."""
    e = rconn.execute("SELECT * FROM exam_sets WHERE exam_set_id = ?", (exam_set_id,)).fetchone()
    if e is None or e["class_id"] not in _my_class_ids(conn, me["user_id"]):
        raise HTTPException(404, "시험이 없습니다")
    if not e["opened_at"]:
        raise HTTPException(409, "아직 열리지 않은 시험입니다")
    if e["closed_at"]:
        raise HTTPException(409, "끝난 시험입니다")
    return e


@router.get("/exams")
def api_exams(me: dict = Depends(auth.require_user), conn=Depends(auth.accounts_conn), rconn=Depends(responses_conn)):
    """내 반에 열린 시험 (+ 이미 제출했는지). 홈의 '열린 시험' 목록. 끝난 시험은 결과를 강사가 공개할 때 — 지금은 안 보인다."""
    cids = _my_class_ids(conn, me["user_id"])
    if not cids:
        return {"exams": []}
    qs = ",".join("?" * len(cids))
    names = {r["class_id"]: r["name"] for r in conn.execute(f"SELECT class_id, name FROM classes WHERE class_id IN ({qs})", cids)}
    out = []
    for e in rconn.execute(f"SELECT * FROM exam_sets WHERE class_id IN ({qs}) AND opened_at IS NOT NULL AND closed_at IS NULL "
                           "ORDER BY opened_at DESC", cids):
        n = rconn.execute("SELECT COUNT(*) FROM exam_items WHERE exam_set_id = ?", (e["exam_set_id"],)).fetchone()[0]
        done = rconn.execute("SELECT attempt_id FROM attempts WHERE exam_set_id = ? AND student_id = ? LIMIT 1",
                             (e["exam_set_id"], me["user_id"])).fetchone()
        out.append({"exam_set_id": e["exam_set_id"], "title": e["title"], "mode": e["mode"], "round_no": e["round_no"],
                    "class_name": names.get(e["class_id"]), "n_items": n, "opened_at": e["opened_at"],
                    "submitted": done is not None})
    return {"exams": out}


@router.get("/exams/{exam_set_id}")
def api_exam_items(exam_set_id: str, me: dict = Depends(auth.require_user), conn=Depends(auth.accounts_conn),
                   rconn=Depends(responses_conn)):
    """시험 문항을 시험지 순서대로 (Solve 가 먹는 모양 = /items 와 같다). 이미 제출했으면 409."""
    e = _open_exam_for(conn, rconn, me, exam_set_id)
    if rconn.execute("SELECT 1 FROM attempts WHERE exam_set_id = ? AND student_id = ?", (exam_set_id, me["user_id"])).fetchone():
        raise HTTPException(409, "이미 제출한 시험입니다")
    rows = rconn.execute("SELECT item_key, input_format FROM exam_items WHERE exam_set_id = ? ORDER BY seq", (exam_set_id,)).fetchall()
    keys = [r["item_key"] for r in rows]
    by_key = {it["item_key"]: it for it in load_items("image", keys=keys)}
    items = []
    for r in rows:
        it = by_key.get(r["item_key"])
        if it is None:
            continue
        it["input_format"] = r["input_format"]          # 서버가 정한 답 모양. 전사 없는 계산형은 진단 모드여도 choice
        items.append(it)
    return {"exam_set_id": exam_set_id, "title": e["title"], "mode": e["mode"], "n": len(items), "items": items}


# ------------------------------------------------------------ 채점·진단
@router.post("/submit")
def api_submit(req: SubmitRequest, me: dict = Depends(auth.require_user), rconn=Depends(responses_conn),
               conn=Depends(auth.accounts_conn)):
    """
    로그인 필수. 없는 보기·모양 오류는 400. 채점·진단 결과에 attempt_id 를 얹어 돌려준다.
    "모르겠다"·무응답은 저장은 되지만 채점·진단에서는 뺀다 (판단하지 않은 것을 틀린 것으로 세지 않는다).
    exam_set_id 가 있으면: 내 반의 열린 시험이어야 하고, 두 번 제출은 409. 결과는 저장되지만 학생에게 진단을 돌려주지 않는다
    결과는 강사가 공개할 때 본다. 응답엔 attempt_id 와 summary 만.
    """
    if req.exam_set_id:
        _open_exam_for(conn, rconn, me, req.exam_set_id)
        if rconn.execute("SELECT 1 FROM attempts WHERE exam_set_id = ? AND student_id = ?",
                         (req.exam_set_id, me["user_id"])).fetchone():
            raise HTTPException(409, "이미 제출한 시험입니다")
        # 시험지에 있는 문항만. 아니면 아무 문항이나 보내거나 빠뜨려도 들어가고, 결과 표에선 "미응시" 로 보인다
        exam_keys = {r["item_key"] for r in rconn.execute("SELECT item_key FROM exam_items WHERE exam_set_id = ?", (req.exam_set_id,))}
        extra = sorted({a.item_key for a in req.answers} - exam_keys)
        if extra:
            raise HTTPException(400, f"시험지에 없는 문항: {', '.join(extra[:5])}")
    facts = load_item_facts(sorted({a.item_key for a in req.answers}))
    unknown = [a.item_key for a in req.answers if a.item_key not in facts["format"]]
    if unknown:
        raise HTTPException(400, f"없는 문항: {', '.join(sorted(set(unknown))[:5])}")
    bad_label = [f"{a.item_key} {a.label}" for a in req.answers
                 if a.label and a.label not in facts["labels"].get(a.item_key, ())]
    if bad_label:
        raise HTTPException(400, f"없는 보기: {', '.join(bad_label[:5])}")
    bad_short = [a.item_key for a in req.answers
                 if a.label is None and a.choice_no is None and facts["format"].get(a.item_key) != "numeric"]
    if bad_short:
        raise HTTPException(400, f"단답은 계산형 문항만: {', '.join(sorted(set(bad_short))[:5])}")
    est = engine()
    responses = [Resp(a.item_key, a.label, a.answer) for a in req.answers if a.label and a.answer is not None]
    responses += derived_units(req.answers, facts)
    diag = est.estimate(responses)
    seen = {(r.item_key, r.label) for r in responses}
    weak = {k.code for k in diag.weak()}

    # 틀린 보기 하나는 점수가 가장 낮은 개념 한 곳에만 보여 준다 (섹션마다 되풀이되지 않게).
    home: dict[tuple[str, str], str] = {}
    for k in sorted((x for x in diag.concepts if x.code in weak),
                    key=lambda x: x.score if x.score is not None else 9):
        for item_key, lab, _err in k.wrong:
            home.setdefault((item_key, lab), k.code)

    def wrongs(k):
        """이 개념에 배정된 틀린 보기들."""
        out = []
        for item_key, lab, err in k.wrong:
            if home.get((item_key, lab)) != k.code:
                continue
            u = est.units.get((item_key, lab)) or {}
            out.append({"item_key": item_key, "label": lab,
                        "error_rate": err,
                        "also": concept_also(u.get("concept", []), weak, k.code)})
        return out[:5]

    attempt_id = _save(rconn, me, req, facts)
    _mark_assigned_done(rconn, me, req)
    if req.exam_set_id:
        return {"attempt_id": attempt_id, "exam_set_id": req.exam_set_id,
                "summary": {"answered": diag.n_answered, "correct": None, "threshold": DIAGNOSIS_THRESHOLD}}
    return {
        "attempt_id": attempt_id,
        "summary": {
            "answered": diag.n_answered,
            "correct": diag.n_correct,
            "threshold": DIAGNOSIS_THRESHOLD,
        },
        # 심한 순으로 세 덩어리. 화면 맨 위에서 "무엇부터" 를 답한다.
        "tiers": concept_tiers([{"code": k.code, "score": k.score,
                            "status": k.status} for k in diag.concepts]),
        # concept_display 가 그룹으로 접고 학생용 문구를 붙인다.
        # 라벨러용 name(축약어)·desc(판정 규칙)는 내보내지 않는다.
        "sections": as_sections([
            {
                "code": k.code,
                "score": k.score, "status": k.status,
                "n_units": k.n_units, "n_correct": k.n_correct,
                "wrong": wrongs(k),
            }
            for k in diag.concepts if k.n_units > 0
        ]),
        # 코드 목록을 내보내지 않는다. 화면은 개수만 쓴다.
        "weak_count": len(diag.weak()),
        "recommend": enrich(est.recommend(diag, seen=seen, limit=5)),
    }


def enrich(recs: list[dict]) -> list[dict]:
    """추천 문항에 제목을 붙인다. 코드만 있으면 화면에 못 쓴다."""
    if not recs:
        return []
    conn = connect(PHYSICS_DB)
    keys = [r["item_key"] for r in recs]
    rows = {
        r["item_key"]: r for r in conn.execute(
            "SELECT item_key, year, mon, number, correct_rate FROM items "
            f"WHERE item_key IN ({','.join('?' * len(keys))})", keys)
    }
    conn.close()
    for r in recs:
        m = rows.get(r["item_key"])
        if m:
            r["title"] = f"{m['year']}년 {m['mon']}월 {m['number']}번"
            r["correct_rate"] = m["correct_rate"]
        # 겨냥한 개념 를 코드가 아니라 학생용 문구로 내보낸다.
        # 추천 근거는 남기되 체계는 안 드러낸다.
        r["labels"] = [concept_label(c) for c in r.pop("concepts", [])]
        r.pop("score", None)            # 내부 점수. 화면에 쓸 일이 없다
    return recs


# ------------------------------------------------------------ 과제 (강사가 낸 것 — teacher.api_assign)
@router.get("/assignments")
def api_assignments(me: dict = Depends(auth.require_user), rconn=Depends(responses_conn)):
    """내 과제를 묶음(assigned_at)별로. items 는 Solve 가 먹는 모양. 다 푼 묶음도 준다 (done 표시)."""
    rows = rconn.execute("SELECT item_key, target_concept, assigned_at, due_at, status FROM assignments WHERE student_id = ? "
                         "ORDER BY assigned_at DESC", (me["user_id"],)).fetchall()
    by_key = {it["item_key"]: it for it in load_items("image", keys=sorted({r["item_key"] for r in rows}))} if rows else {}
    out: dict[str, dict] = {}
    for r in rows:
        b = out.setdefault(r["assigned_at"], {"assigned_at": r["assigned_at"], "due_at": r["due_at"], "target_concept": r["target_concept"],
                                              "target_label": concept_label(r["target_concept"]) if r["target_concept"] else None,
                                              "items": [], "n": 0, "n_done": 0})
        it = by_key.get(r["item_key"])
        if it:
            b["items"].append({**it, "status": r["status"]})
        b["n"] += 1
        b["n_done"] += r["status"] == "done"
    return {"batches": list(out.values())}


# ------------------------------------------------------------ 유사 문항
SIMILAR_ALPHA = 0.5
_similar = None


def similar_index():
    """build/ph1/embed/ 를 프로세스당 한 번 적재. 없으면 None (pl-embed 전)."""
    global _similar
    if _similar is None:
        from ..similar.index import SimilarIndex, embed_dir
        if not (embed_dir() / "figures.npy").is_file():
            return None
        _similar = SimilarIndex.load()
    return _similar


@router.get("/similar")
def api_similar(item_key: str, k: int = Query(3, ge=1, le=10), exclude: str = "",
                me: dict = Depends(auth.require_user)):
    """
    이 문항과 비슷한 문항 k 개 + 이웃의 개념 투표("필요한 개념"). 글 벡터 + 그림 벡터(alpha 0.5).
    exclude: 이미 푼 문항 (쉼표). 추천 풀은 색인된 문항 전부 — 개념 없는 단원도 "비슷한 문제" 로는 나온다.
    concepts 는 라벨 확정된 이웃에서만 모이므로 개념 없는 단원은 빈 목록.
    """
    idx = similar_index()
    if idx is None:
        raise HTTPException(503, "유사 문항 색인이 없습니다 (pl-embed)")
    if item_key not in idx._item_no:
        raise HTTPException(404, "이 문항은 색인에 없습니다")
    skip = {item_key} | {x.strip() for x in exclude.split(",") if x.strip()}
    nb = [(key, sc) for key, sc in idx.neighbors(item_key, k=k + len(skip), alpha=SIMILAR_ALPHA) if key not in skip][:k]
    by_key = {it["item_key"]: it for it in load_items("image", keys=[key for key, _ in nb])}
    items = []
    for key, sc in nb:
        it = by_key.get(key)
        if it:
            it["score"] = round(sc, 3)
            items.append(it)
    from ..similar.evaluate import load_labels
    votes = idx.vote_concept(nb, load_labels(DEFAULT_SUBJECT))
    concepts = [{"code": c, "label": concept_label(c), "group": concept_group(c), "weight": round(w, 3)}
           for c, w in sorted(votes.items(), key=lambda x: -x[1])[:5]]
    return {"based_on": item_key, "items": items, "concepts": concepts}


@router.get("/concepts")
def api_concepts():
    """개념 목록. 화면에서 쓸 문구만 — 단축키와 라벨링 판정 규칙은 뺀다."""
    return {"sections": catalog()}

