/**
 * ExamBuilder.tsx — 화면 3번 "시험지 구성". 필터(단원·연도·형식) + 미리보기 + 담기. 담긴 목록 옆에 개념 커버리지("C03·C05 가 안 재짐").
 * 새로 만들 때(/classes/:cid/exams/new)와 구성 중인 시험을 고칠 때(/exams/:eid/edit) 같은 화면.
 * 모드(진단/실전)는 시험지 단위 — 문항별 input_format 은 서버가 모드 × 형식으로 정한다.
 * 확정(열기)은 ExamPage 에서 — 여기서는 저장만. 저장 뒤 ExamPage 로 간다.
 */
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Empty, PageHead, teacher, useAction, useLoad, type BankItem, type Mode, type PickOut } from "@pl/shared";

export default function ExamBuilder() {
  const { cid, eid } = useParams();
  const nav = useNavigate();
  const bank = useLoad(() => teacher.bank(), []);
  const existing = useLoad(async () => (eid ? teacher.exam(eid) : null), [eid]);
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<Mode>("diagnostic");
  const [picked, setPicked] = useState<string[]>([]);
  const [cat, setCat] = useState<string>("");
  const [year, setYear] = useState<string>("");
  const [fmt, setFmt] = useState<string>("");
  const [preview, setPreview] = useState<BankItem | null>(null);
  const [seeded, setSeeded] = useState(false);
  const act = useAction();
  // 자동으로 담기: 진단할 개념 + 보기형/계산형 수 → 서버(exam_pick)가 골라 담긴 목록에 덧붙인다. 제안일 뿐 — 강사가 빼고 더한다
  const [autoConcepts, setAutoConcepts] = useState<Set<string>>(new Set());
  const [nStmt, setNStmt] = useState(6);
  const [nNum, setNNum] = useState(2);
  const [exclSeen, setExclSeen] = useState(false);
  const [pickInfo, setPickInfo] = useState<PickOut | null>(null);
  const pickAct = useAction();

  // 고치기: 서버 것으로 한 번 채운다
  if (existing.data && !seeded) {
    setTitle(existing.data.exam.title); setMode(existing.data.exam.mode);
    setPicked(existing.data.items.map(i => i.item_key)); setSeeded(true);
  }

  const items = bank.data?.items ?? [];
  const byKey = useMemo(() => Object.fromEntries(items.map(i => [i.item_key, i])), [items]);
  const years = useMemo(() => [...new Set(items.map(i => i.year))].sort((a, b) => b - a), [items]);
  const shown = items.filter(i => (!cat || i.cat === cat) && (!year || String(i.year) === year) && (!fmt || i.format === fmt));

  // 커버리지: 담긴 문항의 개념 합집합 vs 고른 단원(없으면 담긴 문항 단원들)의 개념
  const pickedConcepts = new Set(picked.flatMap(k => byKey[k]?.concepts ?? []));
  const coverCats = cat ? [cat] : [...new Set(picked.map(k => byKey[k]?.cat).filter((c): c is string => !!c))];
  const coverList = coverCats.flatMap(c => bank.data?.concepts[c] ?? []);
  const missing = coverList.filter(k => !pickedConcepts.has(k.code));

  const toggle = (key: string) => setPicked(p => (p.includes(key) ? p.filter(k => k !== key) : [...p, key]));
  const move = (i: number, d: -1 | 1) => setPicked(p => { const q = [...p]; const j = i + d; if (j < 0 || j >= q.length) return p; [q[i], q[j]] = [q[j], q[i]]; return q; });

  async function save() {
    const t = title.trim() || `${new Date().getMonth() + 1}월 점검`;
    if (eid) {
      if (await act.run(() => teacher.updateExam(eid, { title: t, mode, item_keys: picked }))) nav(`/exams/${eid}`);
    } else if (cid) {
      const r = await act.run(() => teacher.createExam(cid, { title: t, mode, item_keys: picked }));
      if (r) nav(`/exams/${r.exam_set_id}`, { replace: true });
    }
  }

  const classId = cid ?? existing.data?.exam.class_id;
  const autoCats = cat ? [cat] : (bank.data?.cats ?? []);                       // 개념 격자: 고른 단원, 없으면 전부
  const toggleConcept = (code: string) => setAutoConcepts(p => { const q = new Set(p); q.has(code) ? q.delete(code) : q.add(code); return q; });
  async function autoPick() {
    if (!classId) return;
    const r = await pickAct.run(() => teacher.pickItems(classId, {
      concepts: [...autoConcepts], n_statements: nStmt, n_numeric: nNum, exclude_seen: exclSeen, keep: picked }));
    if (!r) return;
    setPicked(r.item_keys);
    setPickInfo(r);
  }

  if (bank.loading || existing.loading) return <div className="loading">문항 은행을 불러오는 중</div>;
  if (bank.err || !bank.data) return <Empty>{bank.err}</Empty>;
  const backTo = eid ? `/exams/${eid}` : `/classes/${cid}`;

  return (
    <>
      <PageHead crumbs={[{ to: "/", label: "내 반" }, { to: backTo, label: eid ? existing.data?.exam.title ?? "시험" : "반" }]}
        title={eid ? "시험지 고치기" : "새 시험지"}
        sub={<>문항 {items.length}개 (개념 붙은 것 {items.filter(i => i.concepts.length > 0).length}) 중에서 담습니다. 개념 없는 단원은 채점만 되고 진단 층은 빠집니다. 확정(열기) 뒤에는 문항을 바꿀 수 없습니다.</>} />

      <div className="builder">
        <section>
          <div className="filters">
            <select value={cat} onChange={e => setCat(e.target.value)}>
              <option value="">단원 전체</option>{bank.data.cats.map(c => <option key={c} value={c}>{c}</option>)}</select>
            <select value={year} onChange={e => setYear(e.target.value)}>
              <option value="">연도 전체</option>{years.map(y => <option key={y} value={y}>{y}</option>)}</select>
            <select value={fmt} onChange={e => setFmt(e.target.value)}>
              <option value="">형식 전체</option><option value="statements">보기형 (ㄱㄴㄷ)</option><option value="numeric">계산형</option></select>
            <span className="soft tiny">{shown.length}문항 · 누르면 담김, 돋보기는 크게 보기</span>
          </div>
          {shown.length === 0 ? <Empty>조건에 맞는 문항이 없습니다</Empty> : (
            <div className="bank">
              {shown.map(it => {
                const idx = picked.indexOf(it.item_key);
                return (
                  <div key={it.item_key} className={`bitem ${idx >= 0 ? "in" : ""}`} onClick={() => toggle(it.item_key)}>
                    {idx >= 0 && <span className="badge">{idx + 1}</span>}
                    <img src={it.image} alt={it.title} loading="lazy" />
                    <div className="cap"><span>{it.title}</span>
                      <a onClick={e => { e.stopPropagation(); setPreview(it); }} title="크게 보기">🔍</a></div>
                    <div className="concepts">{it.format === "numeric" ? "계산 · " : ""}{it.concepts.join(" ")}
                      {it.correct_rate != null && <span className="soft"> · {Math.round(it.correct_rate)}%</span>}</div>
                  </div>);
              })}
            </div>)}
        </section>

        <aside className="side panel">
          <div className="form">
            <label>제목<input value={title} onChange={e => setTitle(e.target.value)} placeholder="예: 10월 1주 역학 점검" /></label>
            <label>모드
              <span className="seg">
                <button type="button" className={mode === "diagnostic" ? "on" : "ghost"} onClick={() => setMode("diagnostic")}>진단</button>
                <button type="button" className={mode === "realistic" ? "on" : "ghost"} onClick={() => setMode("realistic")}>실전</button>
              </span>
              <span className="soft tiny">{mode === "diagnostic" ? "선지를 가립니다 — ㄱㄴㄷ 판단 · 계산형은 단답" : "학교 시험처럼 ①~⑤"}</span>
            </label>
          </div>
          <h2 style={{ marginTop: 16 }}>자동으로 담기</h2>
          <p className="soft tiny">진단할 개념 를 고르고 문항 수를 정하면 개념 당 2문항 이상이 되게 골라 담습니다. 담긴 것은 그대로 두고 덧붙입니다.</p>
          {autoCats.map(c => (
            <div key={c} style={{ marginTop: 6 }}>
              {autoCats.length > 1 && <div className="soft tiny">{c}</div>}
              <div className="cover">{(bank.data?.concepts[c] ?? []).map(k => (
                <span key={k.code} className={autoConcepts.has(k.code) ? "hit" : ""} title={k.label} style={{ cursor: "pointer" }}
                      onClick={() => toggleConcept(k.code)}>{k.code}</span>))}</div>
            </div>))}
          <div className="form" style={{ marginTop: 8 }}>
            <div style={{ display: "flex", gap: 8 }}>
              <label style={{ flex: 1 }}>보기형<input type="number" min={0} max={30} value={nStmt} onChange={e => setNStmt(+e.target.value || 0)} /></label>
              <label style={{ flex: 1 }}>계산형<input type="number" min={0} max={30} value={nNum} onChange={e => setNNum(+e.target.value || 0)} /></label>
            </div>
            <label className="chk" style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <input type="checkbox" checked={exclSeen} onChange={e => setExclSeen(e.target.checked)} /> 이 반이 이미 본 문항 제외</label>
          </div>
          <p style={{ marginTop: 8 }}><button className="ghost" onClick={autoPick} disabled={autoConcepts.size === 0 || nStmt + nNum === 0 || pickAct.busy || !classId} style={{ width: "100%" }}>
            {pickAct.busy ? "…" : `${autoConcepts.size}개 개념 로 ${nStmt + nNum}문항 담기`}</button></p>
          {pickAct.err && <p className="err">{pickAct.err}</p>}
          {pickInfo && (
            <p className="soft tiny">
              {pickInfo.short.length === 0
                ? "모든 개념 가 2문항 이상입니다."
                : `2문항이 안 됨: ${pickInfo.short.map(k => `${k} ${pickInfo.coverage[k] ?? 0}`).join(" · ")} — 은행에 문항이 모자랍니다`}
              {pickInfo.n_excluded > 0 && ` (이미 본 ${pickInfo.n_excluded}문항 제외)`}
            </p>)}

          <h2 style={{ marginTop: 16 }}>담긴 문항 <span className="soft">{picked.length}</span></h2>
          {picked.length === 0 ? <p className="soft tiny">왼쪽에서 문항을 누르세요.</p> : (
            <div className="picked">
              {picked.map((k, i) => (
                <div key={k}><span className="num">{i + 1}</span><span style={{ flex: 1 }}>{byKey[k]?.title ?? k}</span>
                  <button className="ghost" onClick={() => move(i, -1)} disabled={i === 0}>↑</button>
                  <button className="ghost" onClick={() => move(i, 1)} disabled={i === picked.length - 1}>↓</button>
                  <button className="ghost" onClick={() => toggle(k)}>×</button></div>))}
            </div>)}
          {coverList.length > 0 && (
            <>
              <h2 style={{ marginTop: 16 }}>개념 커버리지 <span className="soft">{coverList.length - missing.length}/{coverList.length}</span></h2>
              <div className="cover">{coverList.map(k => <span key={k.code} className={pickedConcepts.has(k.code) ? "hit" : ""} title={k.label}>{k.code}</span>)}</div>
              {missing.length > 0 && <p className="soft tiny" style={{ marginTop: 6 }}>안 재짐: {missing.map(k => `${k.code} ${k.label}`).join(" · ")}</p>}
            </>)}
          {act.err && <p className="err">{act.err}</p>}
          <p style={{ marginTop: 16 }}><button onClick={save} disabled={picked.length === 0 || act.busy} style={{ width: "100%" }}>
            {act.busy ? "…" : eid ? "저장" : "시험지 만들기"}</button></p>
        </aside>
      </div>

      {preview && (
        <div className="preview" onClick={() => setPreview(null)}>
          <img src={preview.image} alt={preview.title} />
        </div>)}
    </>
  );
}
