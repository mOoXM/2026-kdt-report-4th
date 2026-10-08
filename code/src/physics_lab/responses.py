r"""
responses.py — 학생 응답을 `data/{과목}/responses.db` 에 쓰는 유일한 창구 (accounts.py 와 같은 모양)

    from physics_lab import responses as R
    with conn:                                         # 부르는 쪽이 묶는다
        R.ensure_student(conn, user_id)
        attempt_id = R.save_attempt(conn, student_id=user_id, purpose="practice", answers=[...])

무엇을 쓰나 — 풀이 한 번 = 세 표
------------------------------
    attempts              세션 하나 (누가 · 왜(purpose) · 어느 시험지 · 기기 · 시각)
    responses             문항 단위 맥락 (몇 번째로 나왔나 · 왜 나왔나(source) · 형식 · 파생 선지 · 시간)
    statement_responses   보기 단위 판단  ★ 원본 (judged_true 0/1 · 모르겠다 · 무응답)

세 표는 한 트랜잭션에 들어간다. 보기 하나가 틀리면(없는 문항 등) 전부 안 들어간다.

세 상태 (responses_schema.sql statement_responses)
    judged_true = 0/1, unsure = 0    판단함
    judged_true = NULL, unsure = 1   "모르겠다"
    judged_true = NULL, unsure = 0   무응답

파생 선지 (responses.choice_no · choice_source)
    보기별 O/X 조합이 어느 선지에 해당하나를 계산한다 — physics.db 의 choices.picks("ㄱ,ㄴ") 와 대조.
      choice_source='derived', choice_no=3      계산해서 3번
      choice_source='derived', choice_no=NULL   계산했으나 대응 선지 없음  ← 설계가 재려는 값 ("선지 5개가 조합 8개를 얼마나 못 덮나")
      choice_source=NULL,      choice_no=NULL   계산 안 함 (보기 하나라도 NULL/모르겠다, 또는 choices 를 안 줌)
    이 파일은 physics.db 를 열지 않는다. 부르는 쪽(api.py)이 choices 를 읽어 넘긴다 — 여기는 responses.db 만 안다.

세 입력 형식 (v5, responses.input_format) — answers 원소의 모양으로 가린다
    per_statement   {"item_key", "label", "judged_true", "unsure", ...}   보기별 O/X/모르겠다. 원본은 statement_responses
    choice          {"item_key", "choice_no": 3}                           ①~⑤ 고름. 원본은 responses.choice_no (given)
    short           {"item_key", "answer_text": "4 kg"}                     단답. 원본은 responses.answer_text.
                                                                           choice_texts 를 주면 선지와 맞춰 파생 (derived)
    한 문항에는 한 형식만. 보기형 문항(ㄱㄴㄷ)은 per_statement 또는 choice, 계산형(numeric)은 short 또는 choice.
    모드(exam_sets.mode): diagnostic = per_statement·short (선지 가림) / realistic = 전부 choice.

purpose 가 트랙을 가른다 (스키마 attempts 주석)
    exam · pilot   진단 갱신 O. exam_set_id 필수
    homework · practice   기록만. 진단은 안 바꾼다
진단 저장(diagnoses)은 exam 에서만 — 이 파일엔 아직 없다 (시험지 구성 뒤에).

시각은 accounts.utcnow() 와 같은 규약 ('2026-09-29T04:10:00Z'). 부르는 쪽이 now 를 고정할 수 있다.
"""

from __future__ import annotations

import secrets
import sqlite3

from .accounts import KEY_ALPHABET, utcnow

PURPOSES = ("exam", "homework", "practice", "pilot")
SOURCES = ("exam_set", "assigned", "recommended", "self_selected")
DEFAULT_SOURCE = {"exam": "exam_set", "pilot": "exam_set", "homework": "assigned", "practice": "self_selected"}


class ResponsesError(Exception):
    """이 모듈이 내는 오류의 부모."""


class BadAnswer(ResponsesError):
    """응답 모양이 틀렸다 — 같은 보기 두 번, 판단과 모르겠다를 동시에, 시험지 없는 exam 등."""


def new_attempt_id() -> str:
    return "a_" + "".join(secrets.choice(KEY_ALPHABET) for _ in range(12))


# ---------------------------------------------------------------- 학생
def ensure_student(conn: sqlite3.Connection, user_id: str, *, consent: int = 0,
                   now: str | None = None) -> None:
    """
    students 에 없으면 한 줄. attempts.student_id 의 FK 가 요구한다.
    student_id = accounts.users.user_id (파일이 달라 FK 는 못 건다 → check_all 8번이 교차 검사).
    """
    conn.execute("INSERT OR IGNORE INTO students (student_id, consent, created_at) VALUES (?, ?, ?)",
                 (user_id, int(consent), now or utcnow()))


# ---------------------------------------------------------------- 파생 선지
def derive_choice(choices: list[tuple[int, set[str]]] | None,
                  judged: dict[str, bool | None]) -> tuple[int | None, str | None]:
    """
    보기별 판단 → (choice_no, choice_source).
        choices  [(1, {"ㄱ"}), (3, {"ㄱ","ㄴ"}), ...]   그 선지가 참이라고 보는 보기 집합 (physics.db choices.picks)
        judged   {"ㄱ": True, "ㄴ": True, "ㄷ": False}  NULL 이면 판단 안 한 것
    보기 하나라도 None 이거나 choices 가 없으면 (None, None) — 계산 안 함.
    다 판단했으면 참인 보기 집합과 같은 선지를 찾는다. 없으면 (None, 'derived') — 계산했으나 없음.
    """
    if not choices or not judged or any(v is None for v in judged.values()):
        return None, None
    picked = {label for label, v in judged.items() if v}
    for no, picks in choices:
        if picks == picked:
            return no, "derived"
    return None, "derived"


def normalize_answer(s: str | None) -> str:
    """
    단답 비교용 1차 정리: 공백 제거 · 괄호 제거 · 소문자 · ×·· → * · 전각 숫자/기호 → 반각.
    "(5/2)L" 과 "5/2 L" 이 같아진다. 동치 변형(2.5L ↔ 5/2 L, 단위 생략)은 여기서 안 다룬다 —
    맞는 선지가 없으면 choice_no=NULL 로 남고, 그런 응답을 모아 보고 규칙을 늘린다.
    """
    if not s:
        return ""
    t = s.strip().lower()
    t = t.translate(str.maketrans("０１２３４５６７８９（）／", "0123456789()/"))
    t = t.replace("×", "*").replace("·", "*").replace("−", "-")
    return "".join(ch for ch in t if not ch.isspace() and ch not in "()")


def derive_short(choice_texts: dict[int, str] | None, answer_text: str | None) -> tuple[int | None, str | None]:
    """
    단답 → (choice_no, choice_source). choice_texts = {1: "2 kg", 2: "4 kg", ...} (physics.db choices.text)
    입력이 비었거나 선지 텍스트가 없으면 (None, None). 정리한 문자열이 같은 선지가 있으면 그 번호, 없으면 (None, 'derived').
    """
    if not answer_text or not choice_texts:
        return None, None
    want = normalize_answer(answer_text)
    if not want:
        return None, None
    for no, text in choice_texts.items():
        if normalize_answer(text) == want:
            return int(no), "derived"
    return None, "derived"


# ---------------------------------------------------------------- 풀이 저장
def save_attempt(conn: sqlite3.Connection, *, student_id: str, purpose: str, answers: list[dict],
                 exam_set_id: str | None = None, source: str | None = None,
                 items: dict[str, dict] | None = None, choices: dict[str, list] | None = None,
                 choice_texts: dict[str, dict[int, str]] | None = None,
                 client: dict | None = None, capture_method: str = "app",
                 started_at: str | None = None, now: str | None = None) -> str:
    """
    풀이 한 번을 세 표에 쓴다. 반환 attempt_id.

    answers  세 모양이 섞여 올 수 있다 (문항마다 한 모양):
               보기별  {"item_key", "label", "judged_true": bool|None, "unsure": bool, "answered_at"?, "changed_cnt"?}
               선지    {"item_key", "choice_no": 1~5, "answered_at"?}
               단답    {"item_key", "answer_text": str, "answered_at"?}
             문항 순서(responses.seq)는 answers 에 처음 나온 순서. items[key]["seq"] 가 있으면 그것.
    items    문항 단위 선택 정보. {item_key: {"seq", "elapsed_ms", "focus_lost_ms", "scroll_px", "shown_at", "answered_at", "target_concept"}}
    choices  {item_key: [(choice_no, {"ㄱ","ㄴ"}), ...]}  보기별 → 파생 선지 계산용. 없으면 계산 안 함
    choice_texts  {item_key: {choice_no: "4 kg", ...}}    단답 → 파생 선지 계산용. 없으면 계산 안 함
    client   {"device", "viewport", "orientation"}
    source   없으면 purpose 로 정한다 (exam→exam_set, practice→self_selected …)

    막는 것 (BadAnswer): exam/pilot 인데 exam_set_id 없음 · 같은 보기 두 번 · judged_true 와 unsure 동시 ·
    한 문항에 두 형식 · 선지 번호 범위 밖 · 종이(capture_method≠app)인데 elapsed_ms 있음.
    스키마 CHECK 와 같은 규칙을 먼저 걸러 메시지를 붙인다.
    """
    if purpose not in PURPOSES:
        raise BadAnswer(f"purpose 가 아니다: {purpose}")
    if purpose in ("exam", "pilot") and not exam_set_id:
        raise BadAnswer(f"{purpose} 는 exam_set_id 가 있어야 한다 (반 집계의 단위)")
    source = source or DEFAULT_SOURCE[purpose]
    if source not in SOURCES:
        raise BadAnswer(f"source 가 아니다: {source}")
    if not answers:
        raise BadAnswer("응답이 비었다")
    now = now or utcnow()
    items = items or {}
    choices = choices or {}
    choice_texts = choice_texts or {}
    client = client or {}

    # 응답 → 문항으로 묶기 (처음 나온 순서 유지). 문항마다 {"format", "labels", "choice_no", "answer_text", "answered_at"}
    by_item: dict[str, dict] = {}

    def slot(key: str, fmt: str, i: int) -> dict:
        it = by_item.setdefault(key, {"format": fmt, "labels": {}, "choice_no": None, "answer_text": None, "answered_at": None})
        if it["format"] != fmt:
            raise BadAnswer(f"{i}번째 응답 ({key}): 한 문항에 두 형식 ({it['format']} 과 {fmt})")
        return it

    for i, a in enumerate(answers, 1):
        key = a.get("item_key")
        if not key:
            raise BadAnswer(f"{i}번째 응답: item_key 가 비었다")
        if a.get("label"):                                             # 보기별
            label = a["label"]
            jt, unsure = a.get("judged_true"), bool(a.get("unsure", False))
            if unsure and jt is not None:
                raise BadAnswer(f"{i}번째 응답 ({key} {label}): 판단과 '모르겠다' 를 동시에 보낼 수 없다")
            it = slot(key, "per_statement", i)
            if label in it["labels"]:
                raise BadAnswer(f"{i}번째 응답 ({key} {label}): 같은 보기가 두 번")
            it["labels"][label] = {"judged_true": None if jt is None else int(bool(jt)), "unsure": int(unsure),
                                   "answered_at": a.get("answered_at"), "changed_cnt": int(a.get("changed_cnt") or 0)}
        elif a.get("choice_no") is not None:                           # 선지
            no = a["choice_no"]
            if not isinstance(no, int) or isinstance(no, bool) or not 1 <= no <= 5:
                raise BadAnswer(f"{i}번째 응답 ({key}): 선지 번호는 1~5 ({no!r})")
            it = slot(key, "choice", i)
            if it["choice_no"] is not None:
                raise BadAnswer(f"{i}번째 응답 ({key}): 같은 문항의 선지가 두 번")
            it["choice_no"], it["answered_at"] = no, a.get("answered_at")
        elif "answer_text" in a:                                       # 단답 ("" 은 무응답으로 둔다)
            it = slot(key, "short", i)
            if it["answer_text"] is not None:
                raise BadAnswer(f"{i}번째 응답 ({key}): 같은 문항의 단답이 두 번")
            it["answer_text"], it["answered_at"] = (str(a["answer_text"]).strip() or None), a.get("answered_at")
        else:
            raise BadAnswer(f"{i}번째 응답 ({key}): label · choice_no · answer_text 중 하나는 있어야 한다")

    attempt_id = new_attempt_id()
    conn.execute(
        "INSERT INTO attempts (attempt_id, student_id, purpose, exam_set_id, device, viewport, orientation, "
        "started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (attempt_id, student_id, purpose, exam_set_id, client.get("device"), client.get("viewport"),
         client.get("orientation"), started_at or now, now))

    for default_seq, (key, it) in enumerate(by_item.items(), 1):
        meta = items.get(key, {})
        if capture_method != "app" and meta.get("elapsed_ms") is not None:
            raise BadAnswer(f"{key}: 종이 응답에 반응시간이 있다")
        fmt, labels = it["format"], it["labels"]
        if fmt == "per_statement":
            judged = {label: (None if v["judged_true"] is None else bool(v["judged_true"])) for label, v in labels.items()}
            choice_no, choice_source = derive_choice(choices.get(key), judged)
        elif fmt == "choice":
            choice_no, choice_source = it["choice_no"], "given"
        else:                                                          # short
            choice_no, choice_source = derive_short(choice_texts.get(key), it["answer_text"])
        conn.execute(
            "INSERT INTO responses (attempt_id, item_key, seq, source, target_concept, input_format, capture_method, "
            "choice_no, choice_source, answer_text, elapsed_ms, focus_lost_ms, scroll_px, shown_at, answered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (attempt_id, key, meta.get("seq", default_seq), source, meta.get("target_concept"), fmt, capture_method,
             choice_no, choice_source, it["answer_text"] if fmt == "short" else None,
             meta.get("elapsed_ms"), meta.get("focus_lost_ms"), meta.get("scroll_px"),
             meta.get("shown_at"), meta.get("answered_at") or it["answered_at"]))
        for label, v in labels.items():
            conn.execute(
                "INSERT INTO statement_responses (attempt_id, item_key, label, judged_true, unsure, answered_at, changed_cnt) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (attempt_id, key, label, v["judged_true"], v["unsure"], v["answered_at"], v["changed_cnt"]))
    return attempt_id


# ---------------------------------------------------------------- 조회
def load_attempt(conn: sqlite3.Connection, attempt_id: str) -> dict | None:
    """풀이 하나를 통째로. {"attempt": {...}, "items": [{"item_key", "seq", ..., "statements": [...]}]}. 없으면 None."""
    a = conn.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
    if a is None:
        return None
    items = []
    for r in conn.execute("SELECT * FROM responses WHERE attempt_id = ? ORDER BY seq", (attempt_id,)):
        sts = conn.execute(
            "SELECT label, judged_true, unsure, answered_at, changed_cnt FROM statement_responses "
            "WHERE attempt_id = ? AND item_key = ? ORDER BY label", (attempt_id, r["item_key"])).fetchall()
        items.append({**dict(r), "statements": [dict(s) for s in sts]})
    return {"attempt": dict(a), "items": items}


def list_attempts(conn: sqlite3.Connection, student_id: str, *, limit: int = 50) -> list[dict]:
    """한 학생의 풀이 목록, 최근 것부터. 학생 '내 결과' 화면과 강사 화면이 쓴다."""
    rows = conn.execute(
        "SELECT a.attempt_id, a.purpose, a.exam_set_id, a.started_at, a.finished_at, "
        "COUNT(DISTINCT r.item_key) AS n_items "
        "FROM attempts a LEFT JOIN responses r USING (attempt_id) "
        "WHERE a.student_id = ? GROUP BY a.attempt_id ORDER BY a.started_at DESC LIMIT ?",
        (student_id, limit)).fetchall()
    return [dict(r) for r in rows]
