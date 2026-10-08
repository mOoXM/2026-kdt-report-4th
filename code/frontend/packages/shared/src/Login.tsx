/**
 * Login.tsx — 화면 하나에 세 상태. ?mode=login|signup|password, ?next=돌아갈곳, ?invite=초대토큰
 * 학생 앱·강사 앱이 같은 파일을 쓴다. 어느 앱인지는 useAuth().app 으로 안다.
 *
 *   login     키 또는 이메일 + 비밀번호. 게스트는 비밀번호를 비운다.
 *   signup    강사 가입 — 강사 앱에서만. 학원명을 적으면 원장, 초대 코드가 있으면 그 학원의 강사, 둘 다 없으면 1인 학원.
 *             학생 앱에서 "강사이신가요?" 를 누르면 강사 앱의 가입 화면으로 넘어간다.
 *   password  임시 비밀번호 → 새 비밀번호. 로그인 응답의 must_change 가 true 면 여기로 온다.
 *
 * 로그인이 끝나면: 이 앱 사람이면 next 로, 아니면(학생 앱에 강사가 로그인) 그 사람의 앱으로 통째로 이동.
 * 오류 문장은 서버 것을 그대로 보여 준다 (서버가 이미 사람 말로 낸다). 423(잠금)만 "몇 분 뒤" 로 계산.
 */
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, auth, type User } from "./api";
import { belongsHere, leaveTo, useAuth } from "./auth";

type Mode = "login" | "signup" | "password";

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 423 && e.lockedUntil) {
      const min = Math.max(1, Math.ceil((Date.parse(e.lockedUntil) - Date.now()) / 60000));
      return `여러 번 틀려서 잠겼습니다. ${min}분 뒤에 다시 하세요.`;
    }
    return e.message;
  }
  return "서버에 연결할 수 없습니다";
}

export default function Login() {
  const [sp, setSp] = useSearchParams();
  const { app, setUser } = useAuth();
  const canSignup = app === "teacher";
  const asked = (sp.get("mode") as Mode) || "login";
  const mode: Mode = asked === "signup" && !canSignup ? "login" : asked;     // 학생 앱엔 가입 화면이 없다
  const next = sp.get("next") || "/";
  const nav = useNavigate();
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const go = (m: Mode) => { setErr(null); setSp({ mode: m, next }); };

  async function run(fn: () => Promise<void>) {
    setErr(null); setBusy(true);
    try { await fn(); } catch (e) { setErr(errorText(e)); } finally { setBusy(false); }
  }

  /** 로그인·가입·비밀번호 변경이 끝난 뒤 갈 곳. */
  function arrive(u: User, mustChange = false) {
    setUser(u);
    if (!belongsHere(app, u)) { leaveTo(u); return; }
    if (mustChange) go("password");
    else nav(next, { replace: true });
  }

  // ---- 로그인
  async function onLogin(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const f = new FormData(ev.currentTarget);
    const id = String(f.get("id") || "").trim();
    const pw = String(f.get("password") || "");
    await run(async () => {
      const r = await auth.login(id, pw === "" ? null : pw);
      arrive(r.user, r.must_change);
    });
  }

  // ---- 가입 (강사 앱)
  async function onSignup(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const f = new FormData(ev.currentTarget);
    const p = {
      email: String(f.get("email") || "").trim(),
      password: String(f.get("password") || ""),
      display_name: String(f.get("display_name") || "").trim(),
      org_name: String(f.get("org_name") || "").trim() || undefined,
      invite: String(f.get("invite") || "").trim() || undefined,
    };
    await run(async () => {
      await auth.signup(p);
      const me = await auth.me();
      arrive(me.user);
    });
  }

  // ---- 비밀번호 변경 (임시 → 새)
  async function onPassword(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const f = new FormData(ev.currentTarget);
    const old = String(f.get("old") || "");
    const a = String(f.get("new") || "");
    const b = String(f.get("confirm") || "");
    if (a !== b) { setErr("새 비밀번호 두 칸이 다릅니다"); return; }
    if (a.length < 4) { setErr("새 비밀번호는 4자 이상"); return; }
    await run(async () => {
      await auth.changePassword(old, a);
      const me = await auth.me();
      arrive(me.user);
    });
  }

  return (
    <main className="card">
      <h1>물리학Ⅰ 인지 진단 <span className="soft">· {app === "teacher" ? "강사" : "학생"}</span></h1>

      {mode === "login" && (
        <form onSubmit={onLogin} className="form">
          <label>키 또는 이메일
            <input name="id" autoComplete="username" autoCapitalize="characters" autoFocus required
                   placeholder={app === "teacher" ? "name@school.kr" : "K7M3PX 또는 name@school.kr"} />
          </label>
          <label>비밀번호 {app === "student" && <span className="soft">(게스트 키는 비워 두세요)</span>}
            <input name="password" type="password" autoComplete="current-password" inputMode={app === "student" ? "numeric" : undefined} />
          </label>
          <button disabled={busy}>{busy ? "…" : "들어가기"}</button>
          {canSignup
            ? <p className="soft">처음이신가요? <a onClick={() => go("signup")}>학원 계정 만들기</a></p>
            : <p className="soft">강사이신가요? <a href="/app/teacher/login?mode=signup">강사 앱에서 학원 계정 만들기</a></p>}
        </form>
      )}

      {mode === "signup" && (
        <form onSubmit={onSignup} className="form">
          <label>이메일 <input name="email" type="email" autoComplete="email" required /></label>
          <label>비밀번호 <input name="password" type="password" autoComplete="new-password" required minLength={4} /></label>
          <label>이름 <input name="display_name" required placeholder="학생에게 보이는 이름" /></label>
          <label>학원 이름 <span className="soft">(비우면 "○○ 선생님" 학원)</span>
            <input name="org_name" placeholder="예: 물리학원" />
          </label>
          <label>초대 코드 <span className="soft">(원장에게 받았으면)</span>
            <input name="invite" defaultValue={sp.get("invite") ?? ""} autoCapitalize="none" />
          </label>
          <button disabled={busy}>{busy ? "…" : "가입"}</button>
          <p className="soft"><a onClick={() => go("login")}>← 로그인으로</a></p>
        </form>
      )}

      {mode === "password" && (
        <form onSubmit={onPassword} className="form">
          <p>임시 비밀번호를 받았으면 <b>내 것으로 바꿔야</b> 계속할 수 있습니다. 바꾸고 나면 선생님도 모릅니다.</p>
          <label>지금 비밀번호 <input name="old" type="password" autoComplete="current-password" required autoFocus /></label>
          <label>새 비밀번호 <span className="soft">(4자 이상)</span>
            <input name="new" type="password" autoComplete="new-password" required minLength={4} />
          </label>
          <label>새 비밀번호 확인 <input name="confirm" type="password" autoComplete="new-password" required /></label>
          <button disabled={busy}>{busy ? "…" : "바꾸기"}</button>
        </form>
      )}

      {err && <p className="err" role="alert">{err}</p>}
    </main>
  );
}
