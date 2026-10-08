/**
 * Exam.tsx — 시험 길. /exam/:eid
 * 강사가 낸 시험지를 시험지 순서대로 <Solve> 에 넘기고, 제출하면 "제출됐습니다" 만.
 * 결과(진단)는 돌려받지 않는다 — 강사가 공개할 때. 연습 길(Practice)과 Solve 는 같고 출처·제출 뒤만 다르다.
 */
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { exams, useAction, useLoad, type SubmitBody } from "@pl/shared";
import Solve from "../solve/Solve";

export default function Exam() {
  const { eid = "" } = useParams();
  const { data, err, loading } = useLoad(() => exams.items(eid), [eid]);
  const [done, setDone] = useState<{ attempt_id: string; answered: number } | null>(null);
  const act = useAction();

  async function onSubmit(body: SubmitBody) {
    const r = await act.run(() => exams.submit(eid, body));
    if (r) setDone({ attempt_id: r.attempt_id, answered: r.summary.answered });
  }

  if (loading) return <div className="loading">시험지를 받는 중</div>;
  if (err || !data) return (
    <main className="card"><h1>시험</h1><p className="err">{err}</p><p><Link to="/">← 홈</Link></p></main>);
  if (done) return (
    <main className="card done-screen">
      <div className="mark">✓</div>
      <h1>제출됐습니다</h1>
      <p className="soft">{data.title} · {data.n}문항</p>
      <p className="soft tiny">결과는 선생님이 확인한 뒤 알려 줍니다.</p>
      <p><Link to="/"><button className="ghost">홈으로</button></Link></p>
    </main>);
  return (
    <>
      {act.err && <p className="err bar">{act.err}</p>}
      <Solve items={data.items} mode={data.mode} onSubmit={onSubmit} busy={act.busy} />
    </>
  );
}
