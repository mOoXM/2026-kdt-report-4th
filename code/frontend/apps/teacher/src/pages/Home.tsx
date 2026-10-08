/**
 * Home.tsx — 화면 1번 "내 반 목록". 반 카드(이름 · 학생 수 · 마지막 시험 · "다음에 할 일" 한 줄) + 반 만들기.
 * 원장이면 "학원 전체" 탭이 붙는다.
 * 학원이 승인 대기(pending)면 머리에 알린다 — 문항 이미지는 승인 뒤에만.
 */
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Empty, PageHead, Pill, owner, shortDate, teacher, useAction, useAuth, useLoad, type ClassCard, type ExamSummary } from "@pl/shared";

export const STATUS: Record<ExamSummary["status"], { label: string; tone: "soft" | "true" | "ok" }> = {
  draft: { label: "구성 중", tone: "soft" }, open: { label: "진행 중", tone: "true" }, closed: { label: "끝남", tone: "ok" },
};

export default function Home() {
  const { user } = useAuth();
  const { data, err, loading, reload } = useLoad(() => teacher.home(), [user?.user_id]);
  const [tab, setTab] = useState<"mine" | "org">("mine");
  const [creating, setCreating] = useState(false);
  const act = useAction();
  const nav = useNavigate();

  async function create(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const name = String(new FormData(ev.currentTarget).get("name") ?? "").trim();
    if (!name) return;
    const r = await act.run(() => teacher.createClass(name));
    if (r) nav(`/classes/${r.class_id}`);
  }

  if (loading) return <div className="loading">불러오는 중</div>;
  if (err || !data) return <Empty>{err ?? "학원 정보가 없습니다"}</Empty>;
  const isOwner = data.org.role === "owner" || !!user?.is_admin;

  return (
    <>
      <PageHead title={data.org.name}
        sub={<>{data.org.status === "pending" ? <Pill tone="weak">승인 대기</Pill> : <Pill tone="ok">승인됨</Pill>}
             {" "}{data.org.role === "owner" ? "원장" : "강사"} · {data.me.display_name}</>}
        actions={isOwner && (
          <span className="seg">
            <button className={tab === "mine" ? "on" : "ghost"} onClick={() => setTab("mine")}>내 반</button>
            <button className={tab === "org" ? "on" : "ghost"} onClick={() => setTab("org")}>학원 전체</button>
          </span>)} />

      {data.org.status === "pending" && (
        <p className="panel" style={{ marginBottom: 16, fontSize: 14 }}>
          학원이 아직 승인 전입니다. 반·명단·시험지는 지금 만들 수 있고, 문항 이미지는 승인 뒤부터 보입니다.
        </p>)}

      {tab === "org" ? <OrgTab /> : (
        <div className="grid">
          {data.classes.map(c => <ClassTile key={c.class_id} c={c} />)}
          {creating
            ? <form className="tile" onSubmit={create}>
                <h3>새 반</h3>
                <div className="form">
                  <input name="name" placeholder="예: 물리Ⅰ 화요일반" autoFocus />
                  {act.err && <p className="err">{act.err}</p>}
                  <div className="actions"><button disabled={act.busy}>만들기</button>
                    <button type="button" className="ghost" onClick={() => setCreating(false)}>취소</button></div>
                </div>
              </form>
            : <a className="tile new" onClick={() => setCreating(true)}>＋ 반 만들기</a>}
        </div>)}
      {data.classes.length === 0 && !creating && tab === "mine" && (
        <p className="soft tiny" style={{ marginTop: 12 }}>첫 반을 만들고 명단을 붙여 넣으면 학생 키가 나옵니다.</p>)}
      <span hidden onClick={reload} />
    </>
  );
}

function ClassTile({ c }: { c: ClassCard }) {
  const last = c.last_exam;
  return (
    <Link to={`/classes/${c.class_id}`} className="tile">
      <h3>{c.name}</h3>
      <div className="meta">
        <span>학생 <b className="num">{c.n_students}</b></span>
        <span>시험 <b className="num">{c.n_exams}</b></span>
        {c.teacher_name && <span>{c.teacher_name}</span>}
      </div>
      {last && (
        <p style={{ margin: "0 0 8px", fontSize: 13 }}>
          <Pill tone={STATUS[last.status].tone}>{STATUS[last.status].label}</Pill> {last.title}
          <span className="soft"> · {shortDate(last.closed_at ?? last.opened_at ?? last.created_at)}</span>
        </p>)}
      <div className="todo">→ {c.todo}</div>
    </Link>
  );
}

/** 원장 탭 — 학원 전체: 강사 · 모든 반 · 초대 */
function OrgTab() {
  const { data, err, loading } = useLoad(() => owner.overview(), []);
  const act = useAction();
  const [invite, setInvite] = useState<string | null>(null);
  if (loading) return <div className="loading">불러오는 중</div>;
  if (err || !data) return <Empty>{err}</Empty>;
  return (
    <div className="two">
      <section className="panel">
        <h2>반 전체 <span className="soft">{data.classes.length}개 · 학생 {data.n_students}명</span></h2>
        <table className="tbl">
          <thead><tr><th>반</th><th>담당</th><th className="r">학생</th><th>마지막 시험</th></tr></thead>
          <tbody>
            {data.classes.map(c => (
              <tr key={c.class_id}>
                <td><Link to={`/classes/${c.class_id}`}>{c.name}</Link></td>
                <td>{c.teacher_name ?? <span className="soft">없음</span>}</td>
                <td className="r num">{c.n_students}</td>
                <td>{c.last_exam ? <><Pill tone={STATUS[c.last_exam.status].tone}>{STATUS[c.last_exam.status].label}</Pill> {c.last_exam.title}</> : <span className="soft">—</span>}</td>
              </tr>))}
          </tbody>
        </table>
      </section>
      <section className="panel">
        <h2>강사 <span className="soft">{data.teachers.length}명</span></h2>
        <table className="tbl">
          <tbody>
            {data.teachers.map(t => (
              <tr key={t.user_id}><td>{t.display_name}<br /><span className="soft tiny">{t.email}</span></td>
                <td className="r">{t.role === "owner" ? <Pill tone="true">원장</Pill> : <Pill tone="soft">강사</Pill>}</td></tr>))}
          </tbody>
        </table>
        <p style={{ marginTop: 12 }}>
          <button className="ghost" disabled={act.busy} onClick={async () => { const r = await act.run(() => owner.invite()); if (r) setInvite(r.invite); }}>
            강사 초대 코드 만들기</button>
        </p>
        {invite && (
          <div className="keys">
            <p className="warn">이 코드는 지금 한 번만 보입니다. 가입 화면의 "초대 코드" 칸에 넣으면 이 학원의 강사가 됩니다 (7일).</p>
            <code className="mono" style={{ wordBreak: "break-all", fontSize: 13 }}>{invite}</code>
          </div>)}
        {act.err && <p className="err">{act.err}</p>}
      </section>
    </div>
  );
}
