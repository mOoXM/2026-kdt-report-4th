/**
 * ClassPage.tsx — 화면 2번 "반 = 명단 + 시험 목록".
 *   왼쪽 명단: 표에 붙여 넣기(이름·학교·입학연도·전화번호, 탭/쉼표 구분) → 저장 → 키·임시 비밀번호 → 안내문 인쇄
 *   오른쪽 시험 회차: 상태(구성 중 / 진행 중 / 끝남) · 제출 수 · 새 시험지
 * ★ 임시 비밀번호(pin)는 저장 응답에만 있다. 화면 상태에만 두고 새로고침하면 사라진다 — 쪽지로 전달하고 보관하지 않는다.
 */
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Empty, PageHead, Pill, shortDate, teacher, useAction, useLoad, type Member, type NewStudent } from "@pl/shared";
import { STATUS } from "./Home";

/** 붙여 넣은 글을 행으로. 한 줄 = 학생 하나. 칸은 탭·쉼표·두 칸 이상 공백. 머리줄("이름 학교 …")은 건너뛴다. */
function parseRows(text: string) {
  const rows: { display_name: string; school?: string; entry_year?: number | null; phone?: string }[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const cells = line.split(/\t|,|\s{2,}/).map(s => s.trim());
    if (/^(이름|성명|name)$/i.test(cells[0])) continue;
    const [display_name, school, year, phone] = cells;
    const entry_year = year && /^\d{4}$/.test(year) ? Number(year) : year && /^\d{2}$/.test(year) ? 2000 + Number(year) : null;
    rows.push({ display_name, school: school || undefined, entry_year, phone: phone || undefined });
  }
  return rows;
}

const gradeOf = (entry_year: number | null) => {
  if (!entry_year) return "";
  const g = new Date().getFullYear() - entry_year + 1;
  return g >= 1 && g <= 3 ? `고${g}` : `${entry_year}입학`;
};

export default function ClassPage() {
  const { cid = "" } = useParams();
  const { data, err, loading, reload } = useLoad(() => teacher.klass(cid), [cid]);
  const [pasting, setPasting] = useState(false);
  const [text, setText] = useState("");
  const [made, setMade] = useState<NewStudent[]>([]);           // 이번에 만든 학생의 키·pin — 화면 상태에만
  const [pins, setPins] = useState<Record<string, string>>({});  // 재발급한 pin
  const act = useAction();
  const rows = useMemo(() => parseRows(text), [text]);

  async function save() {
    const r = await act.run(() => teacher.enroll(cid, rows));
    if (!r) return;
    setMade(r.students); setText(""); setPasting(false); reload();
  }
  async function resetPw(m: Member) {
    if (!confirm(`${m.display_name} 의 비밀번호를 임시 비밀번호로 바꿀까요? 다른 기기에서는 로그아웃됩니다.`)) return;
    const r = await act.run(() => teacher.resetPassword(cid, m.user_id));
    if (r) setPins(p => ({ ...p, [m.user_id]: r.pin }));
  }
  async function withdraw(m: Member) {
    if (!confirm(`${m.display_name} 을(를) 퇴원 처리할까요? 응답 기록은 남습니다.`)) return;
    if (await act.run(() => teacher.withdraw(cid, m.user_id))) reload();
  }

  if (loading) return <div className="loading">불러오는 중</div>;
  if (err || !data) return <Empty>{err}</Empty>;
  const active = data.members.filter(m => !m.left_at);
  const left = data.members.filter(m => m.left_at);
  const slips = made.length ? made : active.filter(m => pins[m.user_id]).map(m => ({ user_id: m.user_id, login_key: m.login_key, pin: pins[m.user_id], display_name: m.display_name }));

  return (
    <>
      <PageHead crumbs={[{ to: "/", label: "내 반" }]} title={data.class.name}
        sub={<>학생 {active.length}명 · 시험 {data.exams.length}회{data.class.teacher_name && ` · ${data.class.teacher_name}`}</>}
        actions={<>
          <button className="ghost" onClick={() => setPasting(true)}>명단 붙여 넣기</button>
          <Link to={`/classes/${cid}/exams/new`}><button disabled={active.length === 0}>새 시험지</button></Link>
        </>} />

      {slips.length > 0 && (
        <section className="panel keys" style={{ marginBottom: 16 }}>
          <h2>안내문 <span className="soft">학생 {slips.length}명 · 키와 임시 비밀번호</span><span className="spacer" />
            <button className="ghost tiny noprint" onClick={() => window.print()}>인쇄</button>
            <button className="ghost tiny noprint" onClick={() => { setMade([]); setPins({}); }}>닫기</button></h2>
          <p className="warn noprint">임시 비밀번호는 지금 이 화면에만 보입니다. 인쇄해서 학생에게 한 장씩 주세요. 학생이 첫 로그인 때 자기 비밀번호로 바꿉니다.</p>
          <div className="slips">
            {slips.map(s => (
              <div key={s.user_id} className="slip">
                <b>{s.display_name}</b> <span className="soft">· {data.class.name}</span>
                <div className="k">{s.login_key}</div>
                <div>임시 비밀번호 <b className="mono">{s.pin ?? "(기존 계정)"}</b></div>
                <div className="soft tiny">{location.origin}/app/student/ 에서 키로 로그인</div>
              </div>))}
          </div>
        </section>)}

      <div className="two">
        <section className="panel">
          <h2>명단 <span className="soft">{active.length}명</span></h2>
          {active.length === 0 ? <Empty>아직 학생이 없습니다. 위의 "명단 붙여 넣기"로 시작하세요.</Empty> : (
            <table className="tbl">
              <thead><tr><th>이름</th><th>학교</th><th>학년</th><th>키</th><th></th></tr></thead>
              <tbody>
                {active.map(m => (
                  <tr key={m.user_id}>
                    <td><b>{m.display_name}</b>{m.phone && <><br /><span className="soft tiny">{m.phone}</span></>}</td>
                    <td>{m.school ?? <span className="soft">—</span>}</td>
                    <td>{gradeOf(m.entry_year)}</td>
                    <td className="mono">{m.login_key}</td>
                    <td><div className="rowbtn">
                      <button className="ghost" onClick={() => resetPw(m)} title="임시 비밀번호 재발급">비번</button>
                      <button className="ghost" onClick={() => withdraw(m)} title="퇴원">퇴원</button></div></td>
                  </tr>))}
                {left.map(m => (
                  <tr key={m.user_id} className="dim">
                    <td>{m.display_name}</td><td colSpan={3}>퇴원 {shortDate(m.left_at)}</td><td></td>
                  </tr>))}
              </tbody>
            </table>)}
          {act.err && <p className="err">{act.err}</p>}
        </section>

        <section className="panel">
          <h2>시험 <span className="soft">{data.exams.length}회</span></h2>
          {data.exams.length === 0 ? <Empty>첫 시험지를 만드세요.</Empty> : (
            <div className="rows">
              {data.exams.map(e => (
                <Link key={e.exam_set_id} to={e.status === "closed" ? `/exams/${e.exam_set_id}/results` : `/exams/${e.exam_set_id}`} className="row">
                  <span className="num soft">{e.round_no}회</span>
                  <span className="t"><b>{e.title}</b>
                    <span>{e.mode === "diagnostic" ? "진단" : "실전"} · {e.n_items}문항 · 제출 {e.n_submitted}/{active.length} · {shortDate(e.closed_at ?? e.opened_at ?? e.created_at)}</span></span>
                  <Pill tone={STATUS[e.status].tone}>{STATUS[e.status].label}</Pill>
                </Link>))}
            </div>)}
        </section>
      </div>

      {pasting && (
        <div className="modal-bg" onClick={() => setPasting(false)}>
          <div className="modal paste" onClick={e => e.stopPropagation()}>
            <h2>명단 붙여 넣기</h2>
            <p className="hint">엑셀·시트에서 복사해 붙이세요. 한 줄에 학생 하나 — <b>이름</b> 학교 입학연도 전화번호 순서, 이름만 있어도 됩니다.</p>
            <textarea value={text} onChange={e => setText(e.target.value)} placeholder={"김민준\t한빛고\t2025\t010-1234-5678\n이서연\t한빛고\t2024"} autoFocus />
            {rows.length > 0 && (
              <table className="tbl" style={{ marginTop: 10 }}>
                <thead><tr><th>#</th><th>이름</th><th>학교</th><th>입학</th><th>전화</th></tr></thead>
                <tbody>{rows.slice(0, 50).map((r, i) => (
                  <tr key={i}><td className="num soft">{i + 1}</td><td>{r.display_name}</td><td>{r.school ?? ""}</td><td>{r.entry_year ?? ""}</td><td>{r.phone ?? ""}</td></tr>))}
                </tbody>
              </table>)}
            {act.err && <p className="err">{act.err}</p>}
            <div className="foot">
              <button className="ghost" onClick={() => setPasting(false)}>취소</button>
              <button onClick={save} disabled={rows.length === 0 || act.busy}>{act.busy ? "…" : `${rows.length}명 저장 → 키 발급`}</button>
            </div>
          </div>
        </div>)}
    </>
  );
}
