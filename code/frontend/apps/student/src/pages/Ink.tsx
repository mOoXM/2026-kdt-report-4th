/**
 * Ink.tsx — 필기 시험대. "브라우저 필기로 충분한가" 를 아이패드 + Apple Pencil 로 직접 재는 화면.
 *
 * 그리기는 solve/InkPad.tsx 가 한다 (풀이 화면과 같은 부품). 여기는 문항 이미지 위에 얹고,
 * 하단 숫자판(초당 입력 점 수 · 묶인 점 비율 · 압력 범위 · 도구)과 JSON 저장만 더한다.
 *
 * 저장 형식 { item_key, w, h, dpr, ua, saved_at, strokes: [{ t0, tool, points: [[x/W, y/H, p, dt], ...] }] }
 *   — 나중에 responses.db 의 item_ink 표에 그대로 넣을 후보.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { items as fetchItems, type Item } from "@pl/shared";
import InkPad, { toInkJson, type InkStats, type Stroke } from "../solve/InkPad";

export default function Ink() {
  const [list, setList] = useState<Item[]>([]);
  const [item, setItem] = useState<Item | null>(null);
  const [penOnly, setPenOnly] = useState(true);
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [stats, setStats] = useState<InkStats>({ events: 0, coalesced: 0, pMin: 1, pMax: 0, tool: "-", hz: 0 });
  const [loadErr, setLoadErr] = useState<string | null>(null);

  useEffect(() => {
    fetchItems("image", 30).then(r => { setList(r.items); setItem(r.items[0] ?? null); })
      .catch(e => setLoadErr(String(e?.message ?? e)));
  }, []);

  const nPoints = useMemo(() => strokes.reduce((n, s) => n + s.points.length, 0), [strokes]);

  function download() {
    if (!item) return;
    const el = document.querySelector<HTMLElement>(".ink .inkpad");
    const w = el?.clientWidth ?? 0, h = el?.clientHeight ?? 0;
    const out = { item_key: item.item_key, w, h, dpr: window.devicePixelRatio, ua: navigator.userAgent,
                  saved_at: new Date().toISOString(), strokes: toInkJson(strokes) };
    const blob = new Blob([JSON.stringify(out)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `ink_${item.item_key}.json`; a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <main className="ink">
      <header className="bar">
        <Link to="/">← 홈</Link>
        <select value={item?.item_key ?? ""} onChange={e => { setStrokes([]); setItem(list.find(i => i.item_key === e.target.value) ?? null); }}>
          {list.map(i => <option key={i.item_key} value={i.item_key}>{i.title}</option>)}
        </select>
        <label className="chk"><input type="checkbox" checked={penOnly} onChange={e => setPenOnly(e.target.checked)} /> 펜만</label>
        <button className="ghost" onClick={() => setStrokes(s => s.slice(0, -1))} disabled={!strokes.length}>되돌리기</button>
        <button className="ghost" onClick={() => setStrokes([])} disabled={!strokes.length}>지우기</button>
        <button onClick={download} disabled={!strokes.length}>JSON 저장</button>
      </header>

      {loadErr && <p className="err">{loadErr} — 로그인이 필요하면 <Link to="/login?next=/ink">로그인</Link></p>}

      <div className="sheet">
        {item?.image && <InkPad image={item.image} strokes={strokes} onChange={setStrokes} penOnly={penOnly} onStats={setStats} />}
      </div>

      <footer className="stats mono">
        획 {strokes.length} · 점 {nPoints} · 입력 {stats.hz}/s · 묶인 점 {stats.events ? Math.round(100 * stats.coalesced / stats.events) : 0}%
        · 압력 {stats.pMax ? `${stats.pMin.toFixed(2)}–${stats.pMax.toFixed(2)}` : "-"} · 도구 {stats.tool}
        · coalesced {"getCoalescedEvents" in PointerEvent.prototype ? "○" : "×"}
        · predicted {"getPredictedEvents" in PointerEvent.prototype ? "○" : "×"}
      </footer>
    </main>
  );
}
