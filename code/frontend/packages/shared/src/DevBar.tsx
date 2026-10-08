/**
 * DevBar.tsx — 개발자 모드 띠. 서버가 PL_DEV=1 일 때만 (useAuth().dev) 화면 맨 아래에 빨갛게 뜬다.
 *
 *   누구로 보고 있나 · 개발 학원 사람들로 바꾸기(진짜 세션) · seed / reset · 마지막 제출(요청·응답·DB 에 들어간 행)
 *
 * 앱 둘(학생·강사)이 같이 쓴다. 역할을 바꾸면 그 사람의 앱으로 통째로 이동한다 — 강사로 바꾸면 강사 앱,
 * 학생·게스트로 바꾸면 학생 앱. 운영자(개발자 계정)는 어느 앱이든 그대로 (belongsHere).
 * 서버에 개발자 모드가 없으면 이 컴포넌트는 아무것도 그리지 않는다.
 */
import { useEffect, useState } from "react";
import { dev, lastCall, onCall, type DevState, type DevUser } from "./api";
import { useAuth } from "./auth";

const KIND = { teacher: "강사", student: "학생", guest: "게스트" } as const;

function pretty(v: unknown) { return JSON.stringify(v, null, 1); }

export default function DevBar() {
  const { dev: on, user, app, refresh } = useAuth();
  const [st, setSt] = useState<DevState | null>(null);
  const [open, setOpen] = useState(false);
  const [showLast, setShowLast] = useState(false);
  const [saved, setSaved] = useState<unknown>(null);
  const [msg, setMsg] = useState("");
  const [, bump] = useState(0);

  useEffect(() => { if (on) dev.state().then(setSt).catch(() => setSt(null)); }, [on, user?.user_id]);
  useEffect(() => onCall(() => { bump(n => n + 1); setSaved(null); }), []);

  if (!on || !user) return null;

  async function become(u: DevUser) {
    const r = await dev.loginAs(u.user_id);
    const home = r.user.kind === "teacher" ? "teacher" : "student";
    if (home !== app && !r.user.is_admin) window.location.href = `/app/${home}/`;
    else await refresh();
  }
  async function seed() { const r = await dev.seed(); setSt(r); setMsg(r.made.length ? `만듦: ${r.made.join(", ")}` : "이미 다 있음"); }
  async function reset() { const r = await dev.reset(); setMsg(`응답 ${r.deleted}건 지움`); }
  async function loadSaved() {
    const id = (lastCall.result as { attempt_id?: string } | undefined)?.attempt_id;
    if (!id) { setMsg("마지막 제출에 attempt_id 가 없다"); return; }
    setSaved(await dev.attempt(id));
  }

  const who = user.display_name ?? user.login_key ?? user.email ?? user.user_id;
  return (
    <div className="devbar">
      <div className="devrow">
        <b>DEV</b>
        <span>{who} <span className="dim">· {KIND[user.kind]}{user.is_admin ? " · 운영자" : ""} · {app} 앱</span></span>
        <button onClick={() => setOpen(o => !o)}>{open ? "접기" : "사용자 바꾸기"}</button>
        <button onClick={seed}>seed</button>
        <button onClick={reset}>reset</button>
        <button onClick={() => setShowLast(s => !s)} disabled={!lastCall.path}>마지막 제출{lastCall.path ? ` (${lastCall.status})` : ""}</button>
        {msg && <span className="dim">{msg}</span>}
      </div>
      {open && st && (
        <div className="devrow wrap">
          {st.users.map(u => (
            <button key={u.user_id} className={u.user_id === user.user_id ? "cur" : ""} onClick={() => become(u)} title={u.user_id}>
              {u.display_name ?? u.email ?? u.login_key} <span className="dim">{KIND[u.kind]}{u.login_key ? ` ${u.login_key}` : ""}</span>
            </button>
          ))}
          <span className="dim">학생 비밀번호 {st.password} · 반 "{st.class}"</span>
        </div>
      )}
      {showLast && lastCall.path && (
        <div className="devpanel">
          <div><b>{lastCall.method} {lastCall.path}</b> <span className="dim">{lastCall.at}</span> <button onClick={loadSaved}>DB 에 들어간 행</button></div>
          <div className="devcols">
            <pre><u>요청</u>{"\n"}{pretty(lastCall.body)}</pre>
            <pre><u>응답 {lastCall.status}</u>{"\n"}{pretty(lastCall.result)}</pre>
            {saved !== null && <pre><u>responses.db</u>{"\n"}{pretty(saved)}</pre>}
          </div>
        </div>
      )}
    </div>
  );
}
