/**
 * Practice.tsx — 연습 길. 문항을 받아 <Solve> 에 넘기고, 제출하면 즉시 결과.
 *
 * 세 화면이 차례로: 시작(모드·문항 수 고르기) → 풀기(Solve) → 결과.
 * 시험 길(/exam/:id)은 나중에 같은 Solve 를 감싸되 "제출됐습니다" 만 보여 준다.
 * 아직 /api/student/items 는 단원 하나(뉴턴 법칙)만 준다 — 단원 고르기는 서버가 cat 을 받을 때.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, items as fetchItems, similar, submit, type Item, type Mode, type SubmitBody, type SubmitResult } from "@pl/shared";
import Solve from "../solve/Solve";
import Result from "../solve/Result";

type Source = "self_selected" | "recommended";
type Phase = { kind: "start" } | { kind: "solve"; items: Item[]; source: Source } | { kind: "result"; res: SubmitResult; items: Item[]; source: Source };

export default function Practice() {
  const [all, setAll] = useState<Item[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("diagnostic");
  const [n, setN] = useState(5);
  const [phase, setPhase] = useState<Phase>({ kind: "start" });
  const [busy, setBusy] = useState(false);
  const [solved, setSolved] = useState<string[]>([]);      // 이번 자리에서 푼 문항 — 추천에서 뺀다

  useEffect(() => {
    fetchItems("image").then(r => setAll(r.items)).catch(e => setErr(e instanceof ApiError ? e.message : "서버에 연결할 수 없습니다"));
  }, []);

  function start() {
    if (!all) return;
    const pick = [...all].sort(() => Math.random() - 0.5).slice(0, n);      // 무작위 n 개. 추천이 붙으면 여기가 바뀐다
    setPhase({ kind: "solve", items: pick, source: "self_selected" });
  }

  /** 틀린 문항마다 비슷한 문항을 받아 이어서 푼다. source=recommended 로 제출된다 */
  async function more() {
    if (phase.kind !== "result") return;
    const wrong = [...new Set(phase.res.sections.flatMap(sec => sec.concepts.flatMap(k => k.wrong.map(w => w.item_key))))];
    const base = wrong.length ? wrong : phase.items.map(i => i.item_key);      // 다 맞았으면 푼 문항 기준으로
    setBusy(true); setErr(null);
    try {
      const got: Item[] = [];
      const seen = new Set(solved);
      for (const key of base.slice(0, 4)) {
        const r = await similar(key, 2, [...seen]);
        for (const it of r.items) if (!seen.has(it.item_key)) { seen.add(it.item_key); got.push(it); }
        if (got.length >= n) break;
      }
      if (!got.length) { setErr("비슷한 문항을 더 찾지 못했습니다"); return; }
      setPhase({ kind: "solve", items: got.slice(0, n), source: "recommended" });
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "추천을 받지 못했습니다");
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(body: SubmitBody) {
    if (phase.kind !== "solve") return;
    setBusy(true); setErr(null);
    try {
      const res = await submit({ ...body, source: phase.source });
      setSolved(s => [...s, ...phase.items.map(i => i.item_key)]);
      setPhase({ kind: "result", res, items: phase.items, source: phase.source });
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "제출에 실패했습니다");
    } finally {
      setBusy(false);
    }
  }

  if (phase.kind === "solve") {
    return (
      <>
        {err && <p className="err bar">{err}</p>}
        <Solve items={phase.items} mode={mode} onSubmit={onSubmit} busy={busy} />
      </>
    );
  }
  if (phase.kind === "result") {
    return <Result res={phase.res} items={phase.items} onAgain={() => setPhase({ kind: "start" })} onMore={more} busy={busy}
                   recommended={phase.source === "recommended"} />;
  }

  const nNum = all?.filter(i => i.format === "numeric").length ?? 0;
  return (
    <main className="card">
      <h1>연습</h1>
      <p className="soft">뉴턴 법칙 {all ? `${all.length}문항 (계산형 ${nNum})` : "불러오는 중"}</p>
      {err && <p className="err">{err} — <Link to="/login?next=/practice">로그인</Link></p>}
      <div className="form">
        <label>모드
          <span className="seg">
            <button className={mode === "diagnostic" ? "on" : "ghost"} onClick={() => setMode("diagnostic")}>진단 — ㄱㄴㄷ 판단 · 단답</button>
            <button className={mode === "realistic" ? "on" : "ghost"} onClick={() => setMode("realistic")}>실전 — ①~⑤</button>
          </span>
        </label>
        <label>문항 수
          <input type="number" min={1} max={all?.length ?? 30} value={n} onChange={e => setN(Math.max(1, +e.target.value || 1))} />
        </label>
        <button onClick={start} disabled={!all || !all.length}>시작</button>
      </div>
      <p className="soft tiny"><Link to="/">← 홈</Link></p>
    </main>
  );
}
