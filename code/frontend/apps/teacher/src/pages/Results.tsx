/**
 * Results.tsx — 화면 5번 "결과". 세 층으로 본다.
 *   ① 표     행 = 학생, 열 = 문항 (손 채점지와 같은 칸 수). 칸 색 = 그 문항에서 틀린 보기 수
 *            (다 맞음 흰색 / 하나 틀림 연한 빨강 / 둘 이상 진한 빨강 / 모르겠다 포함 = 연한 회색 채움(5절 미확정 → 회색으로) / 미응시 진한 회색).
 *            열 머리 = 번호 + 반 정답률 + ㄱ·ㄴ·ㄷ 반 오답률 막대 셋. 행 끝 점수, 열 끝(아래) 정답률.
 *   ② 열 펼침  열 머리 클릭 → 그 문항만 학생 × ㄱㄴㄷ 세 열로. 나머지는 한 칸 그대로.
 *   ③ 학생    이름 클릭 → 오른쪽 서랍: 이 시험의 문항별 O/X + 개념 진단 + 회차 추이. (과제 내기는 자리만)
 *   칸 클릭 → 팝오버: 그 학생의 보기별 답.
 *   개념 토글   표 위 "문항 / 개념". 같은 행, 열만 개념 로 — 학생별 개념 상태는 학생 상세(③)를 학생 수만큼 불러 모은다 (반 25명이면 25번. 목업이라 그대로).
 * 정렬: 이름순 / 점수순.
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Empty, PageHead, Pill, shortDate, similar, teacher, useAction, useLoad, type Cell, type ConceptResult, type ResultItem, type ResultRow, type StudentDetail } from "@pl/shared";
import { STATUS } from "./Home";

const CONCEPT_TONE: Record<string, string> = { "숙달": "u-t", "경계": "w1", "미숙달": "u-f", "판단 불가": "u-n" };

function cellClass(c: Cell | undefined): string {
  if (!c || c.state === "absent") return "absent";
  if (c.state === "blank") return "blank";
  if (c.unsure && c.unsure.length) return c.wrong && c.wrong.length ? (c.wrong.length >= 2 ? "w2" : "w1") : "unsure";
  if (c.state === "ok") return "ok";
  return (c.wrong?.length ?? 0) >= 2 ? "w2" : "w1";
}

export default function Results() {
  const { eid = "" } = useParams();
  const { data, err, loading } = useLoad(() => teacher.results(eid), [eid]);
  const [openCol, setOpenCol] = useState<string | null>(null);            // ② 펼친 문항
  const [sort, setSort] = useState<"name" | "score">("name");
  const [view, setView] = useState<"items" | "concept">("items");
  const [pop, setPop] = useState<{ x: number; y: number; row: ResultRow; item: ResultItem } | null>(null);
  const [drawer, setDrawer] = useState<string | null>(null);              // ③ 학생 user_id
  const [conceptRows, setConceptRows] = useState<Record<string, StudentDetail> | null>(null);

  useEffect(() => { const f = () => setPop(null); window.addEventListener("scroll", f, true); return () => window.removeEventListener("scroll", f, true); }, []);

  // 개념 토글: 학생 상세를 모아 온다 (제출한 학생만)
  useEffect(() => {
    if (view !== "concept" || conceptRows || !data) return;
    Promise.all(data.students.filter(s => s.attempt_id).map(s => teacher.studentResult(eid, s.user_id).then(d => [s.user_id, d] as const)))
      .then(rows => setConceptRows(Object.fromEntries(rows))).catch(() => setConceptRows({}));
  }, [view, conceptRows, data, eid]);

  const rows = useMemo(() => {
    if (!data) return [];
    const r = [...data.students];
    if (sort === "score") r.sort((a, b) => (b.score ?? -1) - (a.score ?? -1) || a.display_name.localeCompare(b.display_name));
    else r.sort((a, b) => a.display_name.localeCompare(b.display_name));
    return r;
  }, [data, sort]);

  if (loading) return <div className="loading">채점하는 중</div>;
  if (err || !data) return <Empty>{err}</Empty>;
  const { exam, items } = data;
  const st = STATUS[exam.status];
  const nSub = data.n_submitted;
  const avg = nSub ? Math.round(rows.reduce((a, r) => a + (r.score ?? 0), 0) / nSub) : null;

  // 개념 열: 모은 학생 상세의 개념 합집합 (그룹 순서대로)
  const conceptCols: { code: string; label: string; group: string }[] = [];
  if (conceptRows) {
    const seen = new Set<string>();
    for (const d of Object.values(conceptRows)) for (const sec of d.sections ?? []) for (const k of sec.concepts)
      if (!seen.has(k.code)) { seen.add(k.code); conceptCols.push({ code: k.code, label: k.label, group: sec.group }); }
  }
  const conceptOf = (uid: string, code: string): ConceptResult | undefined =>
    conceptRows?.[uid]?.sections?.flatMap(s => s.concepts).find(k => k.code === code);

  return (
    <>
      <PageHead crumbs={[{ to: "/", label: "내 반" }, { to: `/classes/${exam.class_id}`, label: data.class_name ?? "반" }, { to: `/exams/${eid}`, label: exam.title }]}
        title={<>{exam.title} <Pill tone={st.tone}>{st.label}</Pill></>}
        sub={<>{exam.round_no}회 · {items.length}문항 · 제출 {nSub}/{data.students.length}{avg != null && <> · 반 평균 <b className="num">{avg}</b>점</>}
             {exam.closed_at && ` · ${shortDate(exam.closed_at)}`}</>}
        actions={<>
          <span className="seg">
            <button className={view === "items" ? "on" : "ghost"} onClick={() => setView("items")}>문항</button>
            <button className={view === "concept" ? "on" : "ghost"} onClick={() => setView("concept")}>개념</button>
          </span>
          <span className="seg">
            <button className={sort === "name" ? "on" : "ghost"} onClick={() => setSort("name")}>이름순</button>
            <button className={sort === "score" ? "on" : "ghost"} onClick={() => setSort("score")}>점수순</button>
          </span>
        </>} />

      {nSub === 0 && <Empty>아직 제출한 학생이 없습니다.</Empty>}

      {view === "items" ? (
        <div className="rwrap">
          <table className="rt">
            <thead>
              <tr>
                <th className="name">학생</th>
                {items.map(it => {
                  const isOpen = openCol === it.item_key;
                  const head = (
                    <th key={it.item_key} className={`col ${isOpen ? "open" : ""}`} onClick={() => setOpenCol(isOpen ? null : it.item_key)}
                        title={`${it.title}\n반 정답률 ${it.class_correct_rate ?? "—"}% · 전국 ${it.national_correct_rate != null ? Math.round(it.national_correct_rate) : "—"}%\n${
                          it.labels.map(l => `${l} 오답률 ${it.stmt_wrong_rate[l] ?? "—"}%`).join(" · ")}`}>
                      <div className="h">
                        <span className="n">{it.seq}</span>
                        <span className="bars">{it.labels.map(l => { const v = it.stmt_wrong_rate[l]; return <i key={l} className={v == null ? "none" : ""} style={{ height: `${v == null ? 10 : Math.max(4, v * 0.22)}px` }} />; })}</span>
                        <span className="pct">{it.class_correct_rate ?? "—"}%</span>
                      </div>
                    </th>);
                  if (!isOpen) return head;
                  return [head, ...it.labels.map(l => <th key={`${it.item_key}:${l}`} className="sub">{l}<br /><span className="num">{it.stmt_wrong_rate[l] ?? "—"}%</span></th>)];
                })}
                <th className="score">점수</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.user_id}>
                  <td className="name"><a onClick={() => setDrawer(r.user_id)}>{r.display_name}</a></td>
                  {items.map(it => {
                    const c = r.cells[it.item_key];
                    const isOpen = openCol === it.item_key;
                    const main = (
                      <td key={it.item_key} className={`c ${cellClass(c)} ${pop?.row.user_id === r.user_id && pop.item.item_key === it.item_key ? "sel" : ""}`}
                          onClick={e => c && c.state !== "absent" && setPop({ x: e.clientX, y: e.clientY, row: r, item: it })}>
                        <i title={c?.wrong?.length ? `틀림: ${c.wrong.join(" ")}` : c?.state === "absent" ? "미응시" : ""} /></td>);
                    if (!isOpen) return main;
                    return [main, ...it.labels.map(l => {
                      const u = c?.units?.[l];
                      const cls = c?.state === "absent" ? "absent" : u === true ? "u-t" : u === false ? "u-f" : "u-n";
                      return <td key={`${it.item_key}:${l}`} className={`c sub ${cls}`}><i /></td>;
                    })];
                  })}
                  <td className="score">{r.score == null ? <span className="soft">—</span> : <>{r.score}<span className="soft tiny"> ({r.n_full}/{items.length})</span></>}</td>
                </tr>))}
            </tbody>
            <tfoot>
              <tr>
                <td className="name soft tiny">반 정답률</td>
                {items.map(it => {
                  const isOpen = openCol === it.item_key;
                  const main = <td key={it.item_key}>{it.class_correct_rate ?? "—"}</td>;
                  if (!isOpen) return main;
                  return [main, ...it.labels.map(l => <td key={`${it.item_key}:${l}`}>{it.stmt_wrong_rate[l] == null ? "—" : 100 - (it.stmt_wrong_rate[l] as number)}</td>)];
                })}
                <td className="score">{avg ?? "—"}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      ) : (
        <div className="rwrap">
          {!conceptRows ? <div className="loading">학생별 개념를 모으는 중</div> : conceptCols.length === 0 ? <Empty>진단할 개념가 없습니다 (개념가 붙은 단원의 문항이어야 합니다)</Empty> : (
            <table className="rt">
              <thead>
                <tr><th className="name">학생</th>
                  {conceptCols.map(k => <th key={k.code} className="col" title={`${k.label}\n${k.group}`}><div className="h"><span className="n">{k.code}</span>
                    <span className="pct">{(() => { const vals = rows.map(r => conceptOf(r.user_id, k.code)).filter((x): x is ConceptResult => !!x && x.score != null); return vals.length ? Math.round(100 * vals.filter(x => x.status === "숙달").length / vals.length) + "%" : "—"; })()}</span></div></th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.user_id}>
                    <td className="name"><a onClick={() => setDrawer(r.user_id)}>{r.display_name}</a></td>
                    {conceptCols.map(k => { const x = conceptOf(r.user_id, k.code); return <td key={k.code} className={`c ${x ? CONCEPT_TONE[x.status] ?? "u-n" : r.attempt_id ? "u-n" : "absent"}`}><i title={x ? `${x.label}: ${x.status} (${x.n_correct}/${x.n_units})` : ""} /></td>; })}
                  </tr>))}
              </tbody>
            </table>)}
        </div>)}

      <div className="legend">
        {view === "items" ? <>
          <span><i style={{ background: "#fff" }} />다 맞음</span><span><i style={{ background: "#F3D9D6" }} />하나 틀림</span>
          <span><i style={{ background: "#E3A7A2" }} />둘 이상 틀림</span><span><i style={{ background: "#EEF0EE" }} />모르겠다 · 무응답</span>
          <span><i style={{ background: "var(--grid)" }} />미응시</span>
          <span className="soft">열 머리의 막대 = ㄱ·ㄴ·ㄷ 반 오답률. 열 머리를 누르면 그 문항만 보기별로 펼칩니다. 이름을 누르면 학생 상세.</span>
        </> : <>
          <span><i style={{ background: "#fff" }} />숙달</span><span><i style={{ background: "#F3D9D6" }} />경계</span>
          <span><i style={{ background: "#E3A7A2" }} />미숙달</span><span><i style={{ background: "#EEF0EE" }} />판단 불가</span>
          <span className="soft">열 머리 % = 반에서 숙달한 비율 (반 응답 직접 집계). 전국 비교는 시험 당일 자료라 단서가 다릅니다.</span>
        </>}
      </div>

      {pop && (() => {
        const c = pop.row.cells[pop.item.item_key];
        const left = Math.min(pop.x + 8, window.innerWidth - 310), top = Math.min(pop.y + 8, window.innerHeight - 200);
        return (
          <>
            <div className="drawer-bg" style={{ background: "transparent" }} onClick={() => setPop(null)} />
            <div className="pop" style={{ left, top }}>
              <b>{pop.row.display_name}</b> · {pop.item.seq}번 <span className="soft">{pop.item.title}</span>
              <div style={{ marginTop: 6 }}>
                {pop.item.labels.map(l => { const u = c?.units?.[l]; const un = c?.unsure?.includes(l);
                  return <div key={l} className="u"><b>{l}</b><span className={u === true ? "st ok" : u === false ? "st false" : "st soft"}>{un ? "모르겠다" : u === true ? "맞음" : u === false ? "틀림" : "무응답"}</span>
                    <span className="soft tiny">반 오답률 {pop.item.stmt_wrong_rate[l] ?? "—"}%</span></div>; })}
                {c?.answer_text != null && <div className="u"><b>답</b><span className="mono">{c.answer_text}</span></div>}
                {c?.choice_no != null && pop.item.input_format === "choice" && <div className="u"><b>선지</b><span>{["①", "②", "③", "④", "⑤"][c.choice_no - 1]}</span></div>}
              </div>
              <p className="soft tiny" style={{ margin: "8px 0 0" }}>{pop.item.cat} · <a onClick={() => { setPop(null); setDrawer(pop.row.user_id); }}>학생 상세 →</a></p>
            </div>
          </>);
      })()}

      {drawer && <StudentDrawer eid={eid} cid={data.exam.class_id} uid={drawer} onClose={() => setDrawer(null)} />}
    </>
  );
}

/** ③ 학생 한 명 — 이 시험의 문항별 O/X + 개념 진단 + 회차 추이 + 과제 내기(자리) */
function StudentDrawer({ eid, cid, uid, onClose }: { eid: string; cid: string; uid: string; onClose: () => void }) {
  const { data, err, loading } = useLoad(() => teacher.studentResult(eid, uid), [eid, uid]);
  const TONE: Record<string, string> = { "숙달": "ok", "경계": "weak", "미숙달": "false", "판단 불가": "soft" };
  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <aside className="drawer">
        {loading ? <div className="loading">불러오는 중</div> : err || !data ? <Empty>{err}</Empty> : (
          <>
            <h2>{data.student.display_name}</h2>
            {!data.attempt ? <p className="soft">이 시험을 치르지 않았습니다.</p> : (
              <>
                <p className="soft tiny">제출 {shortDate(data.attempt.finished_at ?? data.attempt.started_at)} · 판단 단위 {data.summary?.correct}/{data.summary?.answered}</p>
                {data.history && data.history.length > 1 && (
                  <>
                    <h3 style={{ fontSize: 13, margin: "14px 0 0", color: "var(--soft)" }}>회차 추이</h3>
                    <div className="hist">
                      {data.history.map(h => <div key={h.exam_set_id} className={h.exam_set_id === eid ? "cur" : ""}>
                        <i style={{ height: `${Math.max(2, (h.score ?? 0) * 0.4)}px` }} title={h.title} /><span>{h.round_no}회 {h.score ?? "—"}</span></div>)}
                    </div>
                  </>)}
                {data.tiers && data.tiers.length > 0 && <div className="tiers">{data.tiers.map(t => <p key={t.title}><b>{t.title}</b> {t.text}</p>)}</div>}
                {data.sections?.map(sec => (
                  <section key={sec.group} className="conceptgroup">
                    <h2 style={{ fontSize: 13 }}>{sec.group}</h2>
                    {sec.concepts.map(k => <div key={k.code} className="concept"><div className="concepthead"><span className="mono soft tiny">{k.code}</span><b>{k.label}</b>
                      <span className={`st ${TONE[k.status] ?? "soft"}`}>{k.status}</span><span className="soft tiny">{k.n_correct}/{k.n_units}</span></div></div>)}
                  </section>))}
                <h3 style={{ fontSize: 13, margin: "16px 0 6px", color: "var(--soft)" }}>문항별</h3>
                <div className="ox">
                  {data.items?.map(it => (
                    <div key={it.item_key}><b>{it.seq}번 <span className="soft">{it.elapsed_ms != null ? `${Math.round(it.elapsed_ms / 1000)}초` : ""}</span></b>
                      {Object.entries(it.units).map(([l, u]) => <span key={l} className={u === true ? "t" : u === false ? "f" : "n"}>{l}{u === true ? "○" : u === false ? "✕" : it.unsure.includes(l) ? "?" : "–"} </span>)}
                    </div>))}
                </div>
                <AssignPanel cid={cid} uid={uid} detail={data} />
              </>)}
            <p className="soft tiny" style={{ marginTop: 20 }}><Link to={`/exams/${eid}`}>시험으로</Link> · <a onClick={onClose}>닫기</a></p>
          </>)}
      </aside>
    </>
  );
}


/**
 * 과제 내기. 두 가지로 문항을 모은다:
 *   유사 — 이 시험에서 틀린 문항마다 비슷한 문항 2개
 *   개념   — 미숙달·경계 개념 로 자동 담기 (/exams/pick — 개념 당 2문항)
 * 모은 목록은 강사가 빼고 나서 "과제 내기". 한 번에 낸 것이 한 묶음(assigned_at). 아래에 지금까지 낸 묶음과 푼 수.
 */
function AssignPanel({ cid, uid, detail }: { cid: string; uid: string; detail: StudentDetail }) {
  const [picked, setPicked] = useState<{ item_key: string; title: string }[]>([]);
  const [targetConcept, setTargetConcept] = useState<string | null>(null);
  const nConcept = 4;                                           // 개념 당 자동 담기 문항 수 (강사가 고르게 하려면 상태로)
  const act = useAction();
  const sent = useAction();
  const list = useLoad(() => teacher.assignments(cid, uid), [cid, uid, sent.busy]);

  const wrongKeys = [...new Set((detail.items ?? []).filter(it => Object.values(it.units).some(u => u === false)).map(it => it.item_key))];
  const weakConcepts = (detail.sections ?? []).flatMap(sec => sec.concepts).filter(k => k.status === "미숙달" || k.status === "경계");
  const solved = new Set((detail.items ?? []).map(it => it.item_key));
  const add = (items: { item_key: string; title: string }[]) =>
    setPicked(p => { const have = new Set(p.map(x => x.item_key)); return [...p, ...items.filter(x => !have.has(x.item_key) && !solved.has(x.item_key))]; });

  async function bySimilar() {
    const got: { item_key: string; title: string }[] = [];
    for (const key of wrongKeys.slice(0, 5)) {
      const r = await act.run(() => similar(key, 2, [...solved]));
      if (r) got.push(...r.items.map(it => ({ item_key: it.item_key, title: it.title })));
    }
    if (got.length) { add(got); setTargetConcept(null); }
  }
  async function byConcept(code: string) {
    const r = await act.run(() => teacher.pickItems(cid, { concepts: [code], n_statements: nConcept, n_numeric: 0, exclude_seen: true, keep: [] }));
    if (r) {
      const bank = await act.run(() => teacher.bank());
      const title = Object.fromEntries((bank?.items ?? []).map(i => [i.item_key, i.title]));
      add(r.item_keys.map(k => ({ item_key: k, title: title[k] ?? k }))); setTargetConcept(code);
    }
  }
  async function send() {
    const r = await sent.run(() => teacher.assign(cid, uid, { item_keys: picked.map(x => x.item_key), target_concept: targetConcept }));
    if (r) setPicked([]);
  }

  return (
    <>
      <h3 style={{ fontSize: 13, margin: "16px 0 6px", color: "var(--soft)" }}>과제 내기</h3>
      <div className="seg">
        <button className="ghost tiny" onClick={bySimilar} disabled={!wrongKeys.length || act.busy}>틀린 {wrongKeys.length}문항의 유사 문항</button>
        {weakConcepts.map(k => <button key={k.code} className="ghost tiny" onClick={() => byConcept(k.code)} disabled={act.busy} title={k.label}>{k.code} {nConcept}문항</button>)}
      </div>
      {act.err && <p className="err tiny">{act.err}</p>}
      {picked.length > 0 && (
        <div className="picked" style={{ marginTop: 8 }}>
          {picked.map((x, i) => <div key={x.item_key}><span className="num">{i + 1}</span><span style={{ flex: 1 }}>{x.title}</span>
            <button className="ghost" onClick={() => setPicked(p => p.filter(y => y.item_key !== x.item_key))}>×</button></div>)}
          <p style={{ marginTop: 8 }}><button onClick={send} disabled={sent.busy}>{sent.busy ? "…" : `${picked.length}문항 과제 내기${targetConcept ? ` (${targetConcept})` : ""}`}</button></p>
          {sent.err && <p className="err tiny">{sent.err}</p>}
        </div>)}
      {list.data && list.data.batches.length > 0 && (
        <div style={{ marginTop: 10 }}>
          {list.data.batches.map(b => (
            <p key={b.assigned_at} className="soft tiny">{shortDate(b.assigned_at)} · {b.n}문항{b.target_concept ? ` · ${b.target_concept}` : ""} · 푼 것 {b.n_done}/{b.n}</p>))}
        </div>)}
    </>
  );
}
