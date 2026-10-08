/**
 * ExamPage.tsx — 화면 4번 "시험 진행". 상태에 따라 보이는 것이 다르다.
 *   구성 중   문항 목록 · 고치기 · 지우기 · [확정하고 열기]
 *   진행 중   응시 현황(제출 n/m, 학생 칩) · [닫기] · 결과 미리 보기 링크 · (개발자 모드) 가짜 응답 채우기
 *   끝남      결과 화면으로
 * 시험지 PDF · 답안지 PDF · 스캔 판독은 종이 경로(파이썬 일) — 자리만 둔다.
 */
import { Link, useNavigate, useParams } from "react-router-dom";
import { Empty, PageHead, Pill, devFill, shortDate, teacher, useAction, useAuth, useLoad } from "@pl/shared";
import { STATUS } from "./Home";

export default function ExamPage() {
  const { eid = "" } = useParams();
  const nav = useNavigate();
  const { dev } = useAuth();
  const { data, err, loading, reload } = useLoad(() => teacher.exam(eid), [eid]);
  const act = useAction();

  async function open() {
    if (!confirm("확정하고 학생에게 열까요? 연 뒤에는 문항을 바꿀 수 없습니다.")) return;
    if (await act.run(() => teacher.openExam(eid))) reload();
  }
  async function close() {
    if (!confirm("시험을 닫을까요? 아직 제출하지 않은 학생은 더 풀 수 없습니다.")) return;
    if (await act.run(() => teacher.closeExam(eid))) nav(`/exams/${eid}/results`);
  }
  async function del() {
    if (!confirm("이 시험지를 지울까요?")) return;
    if (await act.run(() => teacher.deleteExam(eid))) nav(`/classes/${data?.exam.class_id}`);
  }
  async function fill() {
    if (await act.run(() => devFill(eid))) reload();
  }

  if (loading) return <div className="loading">불러오는 중</div>;
  if (err || !data) return <Empty>{err}</Empty>;
  const { exam, items, students } = data;
  const done = students.filter(s => s.attempt_id);
  const st = STATUS[exam.status];

  return (
    <>
      <PageHead crumbs={[{ to: "/", label: "내 반" }, { to: `/classes/${exam.class_id}`, label: data.class_name ?? "반" }]}
        title={<>{exam.title} <Pill tone={st.tone}>{st.label}</Pill></>}
        sub={<>{exam.round_no}회 · {exam.mode === "diagnostic" ? "진단 모드 (선지 가림)" : "실전 모드 (①~⑤)"} · {items.length}문항
             {exam.opened_at && ` · 열림 ${shortDate(exam.opened_at)}`}{exam.closed_at && ` · 닫힘 ${shortDate(exam.closed_at)}`}</>}
        actions={<>
          {exam.status === "draft" && <>
            <button className="ghost" onClick={del} disabled={act.busy}>지우기</button>
            <Link to={`/exams/${eid}/edit`}><button className="ghost">문항 고치기</button></Link>
            <button onClick={open} disabled={act.busy || items.length === 0}>확정하고 열기</button></>}
          {exam.status === "open" && <>
            <Link to={`/exams/${eid}/results`}><button className="ghost">결과 미리 보기</button></Link>
            <button onClick={close} disabled={act.busy}>시험 닫기</button></>}
          {exam.status === "closed" && <Link to={`/exams/${eid}/results`}><button>결과 보기</button></Link>}
        </>} />
      {act.err && <p className="err">{act.err}</p>}

      <div className="two">
        <section className="panel">
          <h2>응시 현황 <span className="soft">{done.length} / {students.length} 제출</span><span className="spacer" />
            {dev && exam.status !== "draft" && <button className="ghost tiny" onClick={fill} disabled={act.busy}>DEV · 가짜 응답 채우기</button>}</h2>
          {exam.status === "draft" ? (
            <p className="soft" style={{ fontSize: 14 }}>아직 열지 않았습니다. "확정하고 열기"를 누르면 학생 앱의 <b>열린 시험</b>에 나타납니다.
              학생은 {location.origin}/app/student/ 에서 키로 로그인해 풉니다.</p>
          ) : (
            <>
              <div className="progress" style={{ marginBottom: 12 }}><i style={{ width: `${students.length ? 100 * done.length / students.length : 0}%` }} /></div>
              <div className="chips">
                {students.map(s => <span key={s.user_id} className={`chip ${s.attempt_id ? "done" : ""}`} title={s.finished_at ?? ""}>{s.display_name}</span>)}
              </div>
            </>)}
          <h2 style={{ marginTop: 20 }}>종이로 치기 <span className="soft">준비 중</span></h2>
          <div className="actions">
            <button className="ghost" disabled>시험지 PDF</button>
            <button className="ghost" disabled>답안지 PDF (이름·키·QR)</button>
            <button className="ghost" disabled>스캔 올리기</button>
          </div>
        </section>

        <section className="panel">
          <h2>문항 <span className="soft">{items.length}</span></h2>
          <div className="rows">
            {items.map(it => (
              <div key={it.item_key} className="row">
                <span className="num soft">{it.seq}</span>
                <img src={it.image} alt="" style={{ width: 56, height: 56, objectFit: "cover", objectPosition: "top", border: "1px solid var(--grid)", borderRadius: 6 }} />
                <span className="t"><b>{it.title}</b>
                  <span>{it.cat} · {it.format === "numeric" ? "계산형" : "보기형"} · {
                    { per_statement: "ㄱㄴㄷ 판단", short: "단답", choice: "①~⑤" }[it.input_format]}
                    {it.correct_rate != null && ` · 전국 ${Math.round(it.correct_rate)}%`}</span></span>
              </div>))}
          </div>
        </section>
      </div>
    </>
  );
}
