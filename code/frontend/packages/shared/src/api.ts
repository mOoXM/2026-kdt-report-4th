/**
 * api.ts — 서버(FastAPI)와의 계약. 화면은 전부 이 파일을 통해서만 서버를 부른다.
 *
 * 타입은 서버가 실제로 돌려주는 모양이다 (accounts._user_dict · auth.py · api.py).
 * 서버 쪽 계약이 바뀌면 여기가 먼저 깨져야 한다 — 그래서 any 를 쓰지 않는다.
 * 쿠키(pl_session)는 브라우저가 자동으로 붙인다. credentials: "same-origin" 이 기본.
 */

export type User = {
  user_id: string;
  kind: "student" | "teacher" | "guest";
  login_key: string | null;
  email: string | null;
  display_name: string | null;
  is_admin: number;
  must_change: number;          // 1 이면 임시 비밀번호 — 비밀번호 변경 화면 밖은 403
  session_expires_at?: string;
};

export class ApiError extends Error {
  status: number;
  code?: string;
  lockedUntil?: string;
  constructor(status: number, message: string, code?: string, lockedUntil?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.lockedUntil = lockedUntil;
  }
}

/** 개발자 모드 디버그용: 마지막 POST 의 요청·응답을 기억해 둔다 (DevBar 가 보여 준다). 화면 로직은 안 쓴다. */
export const lastCall: { method?: string; path?: string; body?: unknown; status?: number; result?: unknown; at?: string } = {};
const listeners = new Set<() => void>();
export const onCall = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };

/** fetch 한 겹. 2xx 가 아니면 ApiError — detail 이 문자열이든 {code,message} 든 한 모양으로 편다. */
async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.ok) {
    const out = (res.status === 204 ? undefined : await res.json()) as T;
    if (method !== "GET") { Object.assign(lastCall, { method, path, body, status: res.status, result: out, at: new Date().toISOString() }); listeners.forEach(f => f()); }
    return out;
  }
  let message = `${res.status}`;
  let code: string | undefined;
  let lockedUntil: string | undefined;
  try {
    const j = await res.json();
    const d = j.detail;
    if (typeof d === "string") message = d;
    else if (d && typeof d === "object") { message = d.message ?? message; code = d.code; }
    if (j.code) code = j.code;                // Locked: {"detail", "code": "locked", "locked_until"}
    if (j.locked_until) lockedUntil = j.locked_until;
  } catch { /* 본문이 JSON 이 아니면 상태 코드만 */ }
  throw new ApiError(res.status, message, code, lockedUntil);
}

// ---------------------------------------------------------------- auth
export const auth = {
  me: () => call<{ user: User; dev?: boolean }>("GET", "/api/auth/me"),
  login: (id: string, password: string | null) => {
    // 칸 하나로 받는다: '@' 가 있으면 강사(email), 없으면 학생·게스트(login_key)
    const body = id.includes("@") ? { email: id, password } : { login_key: id, password };
    return call<{ user: User; must_change: boolean }>("POST", "/api/auth/login", body);
  },
  signup: (p: { email: string; password: string; display_name: string; org_name?: string; invite?: string }) =>
    call<{ user_id: string; org_id: string; role: string }>("POST", "/api/auth/signup", p),
  logout: () => call<{ ok: true }>("POST", "/api/auth/logout"),
  changePassword: (old: string, next: string) => call<{ ok: true }>("POST", "/api/auth/password", { old, new: next }),
};

// ---------------------------------------------------------------- 개발자 모드 (/api/dev — PL_DEV=1 일 때만 있다)
export type DevUser = { user_id: string; kind: User["kind"]; login_key: string | null; email: string | null; is_admin: number;
                        display_name: string | null; class_name: string | null; expires_at: string | null };
export type DevState = { me: User; org_id: string; users: DevUser[]; password: string; class: string };
export const dev = {
  state: () => call<DevState>("GET", "/api/dev/state"),
  loginAs: (user_id: string) => call<{ user: User }>("POST", "/api/dev/login-as", { user_id }),
  seed: () => call<DevState & { made: string[] }>("POST", "/api/dev/seed"),
  reset: () => call<{ deleted: number }>("POST", "/api/dev/reset"),
  attempt: (id: string) => call<Record<string, unknown>>("GET", `/api/dev/attempt/${id}`),
};

// ---------------------------------------------------------------- 앱 나누기
/** 앱 이름 = FastAPI 가 서빙하는 경로(/app/<name>/) = apps/<name>/. serve/api.py 의 APPS 와 같은 목록. */
export type AppName = "student" | "teacher";
/** 각 앱에 들어올 수 있는 계정 종류. 서버가 최종 판단하지만 화면에서도 먼저 거른다. */
export const APP_KINDS: Record<AppName, User["kind"][]> = {
  student: ["student", "guest"],
  teacher: ["teacher"],
};
/** 이 사용자의 집 — 강사는 강사 앱, 나머지는 학생 앱. 앱을 넘어갈 때는 새로고침(window.location) 이 필요하다. */
export const homeOf = (u: User): string => (u.kind === "teacher" ? "/app/teacher/" : "/app/student/");

// ---------------------------------------------------------------- 문항 · 제출 (학생 라우터 /api/student)
export type Statement = { label: string; text: string | null; error_rate: number | null };
export type ItemFormat = "statements" | "numeric";               // ㄱㄴㄷ 보기형 | 계산형 (단답 또는 ①~⑤)
/** 이미지 안의 구역 — [ymin, xmin, ymax, xmax], 0~1000 (이미지 크기 무관. 화면에선 /10 해서 % 로 쓴다). 서버 regions.py 와 같은 모양 */
export type Box = [number, number, number, number];
export type Regions = {
  options: Box | null;                                   // 선지 묶음 — 진단 모드가 가린다
  figures: { tag: string | null; box: Box }[];           // 그림 (가)(나)…
  statements: { tag: string | null; box: Box }[];        // 보기 ㄱㄴㄷ
  texts: Box[];
};
export type Item = {
  item_key: string; title: string; format: ItemFormat; correct_rate: number | null;
  image?: string; stem?: string; diagram?: string; statements: Statement[];   // 계산형은 statements 가 빈다 ('답' 은 안 온다)
  regions?: Regions | null;                                // 이미지 모드에서만. 레이아웃이 없는 문항은 null
  input_format?: "per_statement" | "choice" | "short";   // 시험 길에서 서버가 정한 답 모양 (exam_items). 없으면 모드 × 형식으로
};

export const items = (mode: "image" | "text" = "image", limit = 0) =>
  call<{ cat: string; mode: string; n: number; items: Item[] }>("GET", `/api/student/items?mode=${mode}&limit=${limit}`);

/** 시험 모드 (exam_sets.mode). diagnostic = 선지 가림(ㄱㄴㄷ O/X/? · 단답), realistic = 학교 시험처럼 ①~⑤ */
export type Mode = "diagnostic" | "realistic";

/** 응답 하나 — 세 모양 (responses.py 머리 주석과 같다). 문항마다 한 모양. */
export type Answer =
  | { item_key: string; label: string; answer: boolean | null; unsure?: boolean; answered_at?: string; changed_cnt?: number }  // 보기별
  | { item_key: string; choice_no: number; answered_at?: string }                                                            // ①~⑤
  | { item_key: string; answer_text: string; answered_at?: string };                                                         // 단답
export type ItemTiming = { item_key: string; seq?: number; elapsed_ms?: number; focus_lost_ms?: number; scroll_px?: number; shown_at?: string; answered_at?: string };
export type SubmitBody = {
  answers: Answer[];
  items?: ItemTiming[];
  client?: { device?: string; viewport?: string; orientation?: string; started_at?: string };
  source?: "self_selected" | "recommended";   // 연습 길: 추천으로 받은 문항은 recommended (집단 통계에서 뺀다)
  exam_set_id?: string;
  assigned_at?: string;                        // 과제 묶음 — 서버가 source='assigned' + 풀고 나면 done
};
/** 과제 (assignments). 한 번에 낸 것 = assigned_at 이 같은 묶음 */
export type AssignmentBatch = { assigned_at: string; due_at: string | null; target_concept: string | null; target_label?: string | null;
                                n: number; n_done: number; items: (Item & { status: "assigned" | "done" | "skipped" })[] };
export const assignments = {
  list: () => call<{ batches: AssignmentBatch[] }>("GET", "/api/student/assignments"),
};
/** 유사 문항 (/api/student/similar). items 는 /items 와 같은 모양 + score. concepts 는 이웃의 개념 투표 — 개념 없는 단원은 빈 목록 */
export type SimilarConcept = { code: string; label: string; group: string; weight: number };
export const similar = (item_key: string, k = 3, exclude: string[] = []) =>
  call<{ based_on: string; items: (Item & { score: number })[]; concepts: SimilarConcept[] }>(
    "GET", `/api/student/similar?item_key=${encodeURIComponent(item_key)}&k=${k}&exclude=${encodeURIComponent(exclude.join(","))}`);
export type Wrong = { item_key: string; label: string; error_rate: number | null; also: string[] };
export type ConceptResult = { code: string; label: string; group: string; score: number | null; status: string; n_units: number; n_correct: number; wrong: Wrong[] };
export type SubmitResult = {
  attempt_id: string;
  summary: { answered: number; correct: number; threshold: number };
  tiers: { title: string; text: string; codes: string[] }[];           // 심한 순 "무엇부터" 문장
  sections: { group: string; concepts: ConceptResult[] }[];                       // 그룹별 개념
} & Record<string, unknown>;
export const submit = (body: SubmitBody) => call<SubmitResult>("POST", "/api/student/submit", body);

// ---------------------------------------------------------------- 시험 길 (학생) — /api/student/exams
export type OpenExam = { exam_set_id: string; title: string; mode: Mode; round_no: number | null; class_name: string | null;
                         n_items: number; opened_at: string; submitted: boolean };
export const exams = {
  list: () => call<{ exams: OpenExam[] }>("GET", "/api/student/exams"),
  items: (id: string) => call<{ exam_set_id: string; title: string; mode: Mode; n: number; items: Item[] }>("GET", `/api/student/exams/${id}`),
  /** 시험 제출. 응답은 attempt_id 와 summary 뿐 — 진단은 강사가 공개할 때 */
  submit: (id: string, body: SubmitBody) =>
    call<{ attempt_id: string; exam_set_id: string; summary: { answered: number } }>("POST", "/api/student/submit", { ...body, exam_set_id: id }),
};

// ---------------------------------------------------------------- 강사 (/api/teacher) · 원장 (/api/owner)
export type ExamStatus = "draft" | "open" | "closed";
export type ExamSummary = { exam_set_id: string; class_id: string; title: string; round_no: number | null; mode: Mode; status: ExamStatus;
                            n_items: number; n_submitted: number; created_at: string; opened_at: string | null; closed_at: string | null };
export type Org = { org_id: string; name: string; status: "pending" | "active" | "disabled"; role: "owner" | "teacher" };
export type ClassCard = { class_id: string; name: string; teacher_id: string | null; teacher_name: string | null;
                          n_students: number; n_exams: number; last_exam: ExamSummary | null; todo: string };
export type Member = { user_id: string; display_name: string; school: string | null; entry_year: number | null; phone: string | null;
                       login_key: string; joined_at: string; left_at: string | null };
export type NewStudent = { user_id: string; login_key: string; pin: string | null; display_name: string };   // pin 은 이 응답에만 (한 번 전달)
export type BankItem = { item_key: string; title: string; year: number; mon: number; number: number; cat: string | null; leaf: string | null;
                         format: ItemFormat; correct_rate: number | null; image: string; labels: string[]; concepts: string[];
                         units: { label: string; concepts: string[]; error_rate: number | null }[] };   // 보기별 개념 (자동 담기가 단독 보기를 센다)
/** 자동으로 담기 (exam_pick). 저장 안 함 — 제안만 */
export type PickIn = { concepts: string[]; n_statements: number; n_numeric: number; exclude_seen: boolean; keep: string[] };
export type PickOut = { item_keys: string[]; coverage: Record<string, number>; short: string[]; pool: Record<string, number>; n_excluded: number };
export type ConceptInfo = { code: string; label: string; group: string };
export type ExamItem = { item_key: string; seq: number; title: string; cat: string | null; format: ItemFormat; correct_rate: number | null;
                         image: string; labels: string[]; input_format: "per_statement" | "choice" | "short" };
export type ExamStudent = { user_id: string; display_name: string; login_key: string; attempt_id: string | null; finished_at: string | null };
/** 결과 표의 칸. absent 미응시 / blank 응시했지만 판단 없음 / ok 다 맞음 / wrong 틀린 보기 있음 */
export type Cell = { state: "absent" | "blank" | "ok" | "wrong"; wrong?: string[]; unsure?: string[];
                     units?: Record<string, boolean | null>; choice_no?: number | null; answer_text?: string | null };
export type ResultItem = { item_key: string; seq: number; title: string; format: ItemFormat | null; cat: string | null; image: string;
                           input_format: string; national_correct_rate: number | null; class_correct_rate: number | null;
                           labels: string[]; stmt_wrong_rate: Record<string, number | null> };
export type ResultRow = { user_id: string; display_name: string; attempt_id: string | null; n_full: number; score: number | null;
                          cells: Record<string, Cell> };
export type StudentDetail = {
  student: { user_id: string; display_name: string };
  attempt: { attempt_id: string; started_at: string; finished_at: string | null } | null;
  items?: { item_key: string; seq: number; title: string; image: string | null; units: Record<string, boolean | null>; unsure: string[]; elapsed_ms: number | null }[];
  summary?: { answered: number; correct: number };
  tiers?: { title: string; text: string; codes: string[] }[];
  sections?: { group: string; concepts: ConceptResult[] }[];
  history?: { exam_set_id: string; title: string; round_no: number | null; score: number | null }[];
};

export const teacher = {
  home: () => call<{ org: Org; me: { user_id: string; display_name: string | null; role: string }; classes: ClassCard[] }>("GET", "/api/teacher/home"),
  createClass: (name: string) => call<{ class_id: string }>("POST", "/api/teacher/classes", { name }),
  klass: (cid: string) => call<{ class: { class_id: string; name: string; teacher_name: string | null; created_at: string }; members: Member[]; exams: ExamSummary[] }>("GET", `/api/teacher/classes/${cid}`),
  enroll: (cid: string, rows: { display_name: string; school?: string; entry_year?: number | null; phone?: string }[]) =>
    call<{ students: NewStudent[] }>("POST", `/api/teacher/classes/${cid}/students`, { rows }),
  resetPassword: (cid: string, uid: string) => call<{ user_id: string; pin: string }>("POST", `/api/teacher/classes/${cid}/students/${uid}/reset-password`),
  withdraw: (cid: string, uid: string) => call<{ ok: true }>("POST", `/api/teacher/classes/${cid}/students/${uid}/withdraw`),
  bank: () => call<{ items: BankItem[]; cats: string[]; concepts: Record<string, ConceptInfo[]> }>("GET", "/api/teacher/bank"),
  assign: (cid: string, uid: string, p: { item_keys: string[]; target_concept?: string | null; due_at?: string | null }) =>
    call<{ assigned_at: string; n: number }>("POST", `/api/teacher/classes/${cid}/students/${uid}/assignments`, p),
  assignments: (cid: string, uid: string) =>
    call<{ batches: { assigned_at: string; due_at: string | null; target_concept: string | null; n: number; n_done: number;
                      items: { item_key: string; title: string; status: string }[] }[] }>("GET", `/api/teacher/classes/${cid}/students/${uid}/assignments`),
  pickItems: (cid: string, p: PickIn) => call<PickOut>("POST", `/api/teacher/classes/${cid}/exams/pick`, p),
  createExam: (cid: string, p: { title: string; mode: Mode; item_keys: string[] }) => call<{ exam_set_id: string; round_no: number }>("POST", `/api/teacher/classes/${cid}/exams`, p),
  updateExam: (eid: string, p: { title: string; mode: Mode; item_keys: string[] }) => call<{ ok: true }>("PUT", `/api/teacher/exams/${eid}`, p),
  deleteExam: (eid: string) => call<{ ok: true }>("DELETE", `/api/teacher/exams/${eid}`),
  openExam: (eid: string) => call<{ status: ExamStatus }>("POST", `/api/teacher/exams/${eid}/open`),
  closeExam: (eid: string) => call<{ status: ExamStatus }>("POST", `/api/teacher/exams/${eid}/close`),
  exam: (eid: string) => call<{ exam: ExamSummary; class_name: string | null; items: ExamItem[]; students: ExamStudent[] }>("GET", `/api/teacher/exams/${eid}`),
  results: (eid: string) => call<{ exam: ExamSummary; class_name: string | null; items: ResultItem[]; students: ResultRow[]; n_submitted: number }>("GET", `/api/teacher/exams/${eid}/results`),
  studentResult: (eid: string, uid: string) => call<StudentDetail>("GET", `/api/teacher/exams/${eid}/students/${uid}`),
};
export const owner = {
  overview: () => call<{ org: Org; teachers: { user_id: string; display_name: string | null; email: string | null; role: string; joined_at: string }[];
                         classes: (Omit<ClassCard, "todo" | "n_exams">)[]; n_students: number }>("GET", "/api/owner/overview"),
  invite: (email?: string) => call<{ invite: string; days: number }>("POST", "/api/owner/invites", { email: email || null }),
};
/** 개발자 모드: 시험에 그 반 전원의 가짜 응답을 넣는다 (dev.py fill) */
export const devFill = (exam_set_id: string) => call<{ filled: number; skipped: number }>("POST", "/api/dev/fill", { exam_set_id });

/** 서버 규약의 시각 문자열 '2026-09-29T04:10:00Z' (초까지, UTC). accounts.utcnow() 와 같은 모양. */
export const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
