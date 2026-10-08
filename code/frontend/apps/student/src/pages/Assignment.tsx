/**
 * Assignment.tsx — 과제 길. /assignment/:at   (at = assignments.assigned_at, 한 묶음)
 * 아직 안 푼 문항만 <Solve> 에 넘기고, 제출은 assigned_at 을 붙여 source='assigned' 로. 결과는 연습처럼 바로 보여 준다.
 *
 */
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, assignments, submit, useLoad, type Item, type SubmitBody, type SubmitResult } from "@pl/shared";
import Solve from "../solve/Solve";
import Result from "../solve/Result";

export default function Assignment() {
  const { at = "" } = useParams();
  const { data, err, loading } = useLoad(() => assignments.list(), [at]);
  const [res, setRes] = useState<SubmitResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [sErr, setSErr] = useState<string | null>(null);

  const batch = data?.batches.find(b => b.assigned_at === at);
  const items: Item[] = (batch?.items ?? []).filter(i => i.status !== "done");

  async function onSubmit(body: SubmitBody) {
    setBusy(true); setSErr(null);
    try { setRes(await submit({ ...body, assigned_at: at })); }
    catch (e) { setSErr(e instanceof ApiError ? e.message : "제출에 실패했습니다"); }
    finally { setBusy(false); }
  }

  if (loading) return <div className="loading">과제를 받는 중</div>;
  if (err || !batch) return <main className="card"><h1>과제</h1><p className="err">{err ?? "과제가 없습니다"}</p><p><Link to="/">← 홈</Link></p></main>;
  if (res) return <Result res={res} items={items} onAgain={() => window.location.assign("/app/student/")} />;
  if (!items.length) return <main className="card"><h1>과제</h1><p className="soft">이 과제는 다 풀었습니다.</p><p><Link to="/">← 홈</Link></p></main>;
  return (
    <>
      {sErr && <p className="err bar">{sErr}</p>}
      <Solve items={items} mode="diagnostic" onSubmit={onSubmit} busy={busy} />
    </>
  );
}
