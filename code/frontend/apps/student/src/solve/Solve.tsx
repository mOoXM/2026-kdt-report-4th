/**
 * Solve.tsx — 풀이 부품. 문항을 하나씩 보여 주고 답을 받아 제출 페이로드를 만든다.
 *
 * 문항이 어디서 왔는지(시험지 / 연습 / 추천) 모른다. items 를 받고 onSubmit(payload) 로 넘길 뿐 —
 * 시험 길·연습 길이 이 부품을 감싸고 "문항 출처" 와 "제출 뒤" 만 다르게 한다.
 *
 * 화면 삼분할: 왼쪽 문항 이미지 · 오른쪽 위 판정 · 오른쪽 아래 필기(연습장). 좁으면 세로로 쌓인다.
 *
 * 판정 칸은 모드 × 문항 형식으로 정해진다 (responses.input_format):
 *   diagnostic + statements  ㄱㄴㄷ 각각 O / X / ?        → per_statement
 *   diagnostic + numeric     단답 입력                    → short
 *   realistic  + 아무거나     ①~⑤                        → choice
 *
 * 시간: shown_at(처음 본 때) · elapsed_ms(그 문항을 보고 있던 시간 — 돌아오면 누적) · focus_lost_ms(앱 밖에 있던 시간)
 *       · changed_cnt(판단을 바꾼 횟수). 서버 responses / statement_responses 의 그 칸들.
 * 필기: 문항 이미지 위(qStrokes — 그림에 힘 화살표 등)와 연습장(padStrokes)을 따로. 문항마다 들고 있어 돌아와도 남는다.
 *       지금은 제출 페이로드에 넣지 않는다 (item_ink 표가 생기면 둘 다, 구분해서).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { nowIso, type Answer, type Item, type ItemTiming, type Mode, type SubmitBody } from "@pl/shared";
import InkPad, { type InkTool, type Stroke } from "./InkPad";
import ZoomPane, { type Frame } from "./ZoomPane";

type StmtAns = { answer: boolean | null; unsure: boolean; changed_cnt: number; answered_at?: string };
type ItemState = {
  stmts: Record<string, StmtAns>;
  choice?: number;                      // realistic
  text?: string;                        // diagnostic + numeric
  changed_cnt: number;                  // 문항 단위 답(선지·단답)을 바꾼 횟수
  answered_at?: string;
  shown_at?: string;
  elapsed: number;                      // ms, 누적
  focus_lost: number;                   // ms, 누적
  qStrokes: Stroke[];                   // 문항 이미지 위
  padStrokes: Stroke[];                 // 연습장
};

const CIRCLED = ["①", "②", "③", "④", "⑤"];

function fresh(it: Item): ItemState {
  return { stmts: Object.fromEntries(it.statements.map(s => [s.label, { answer: null, unsure: false, changed_cnt: 0 }])),
           changed_cnt: 0, elapsed: 0, focus_lost: 0, qStrokes: [], padStrokes: [] };
}

/** 답 모양. 서버가 exam_items.input_format 으로 정해 줬으면 그것(전사 없는 계산형은 진단 모드여도 ①~⑤), 아니면 모드 × 형식 */
type Kind = "per_statement" | "choice" | "short";
const kindOf = (it: Item, mode: Mode): Kind =>
  it.input_format ?? (mode === "realistic" ? "choice" : it.format === "numeric" ? "short" : "per_statement");

/** 이 문항에 답이 (일부라도) 있나 — 진행 점 표시용 */
function answered(st: ItemState, it: Item, mode: Mode): boolean {
  const k = kindOf(it, mode);
  if (k === "choice") return st.choice !== undefined;
  if (k === "short") return !!st.text?.trim();
  return Object.values(st.stmts).some(a => a.answer !== null || a.unsure);
}

type Props = {
  items: Item[];
  mode: Mode;
  onSubmit: (body: SubmitBody) => void | Promise<void>;
  busy?: boolean;
};

export default function Solve({ items, mode, onSubmit, busy }: Props) {
  const [idx, setIdx] = useState(0);
  const [frame, setFrame] = useState<Frame>({ x: 0, y: 0, w: 0, h: 0 });   // 이미지가 패널 안에 지금 놓인 자리 — 덮개 필기의 기준 틀
  const [state, setState] = useState<Record<string, ItemState>>(() => Object.fromEntries(items.map(it => [it.item_key, fresh(it)])));
  const [penOnly, setPenOnly] = useState(true);
  const [tool, setTool] = useState<InkTool>("pen");
  const [askClear, setAskClear] = useState(false);   // "전체 지우기" 확인 중
  const startedAt = useRef(nowIso());
  const enteredAt = useRef(performance.now());     // 지금 문항을 보기 시작한 때
  const hiddenAt = useRef<number | null>(null);

  const it = items[idx];
  const st = state[it.item_key];
  const patch = useCallback((key: string, f: (s: ItemState) => ItemState) =>
    setState(prev => ({ ...prev, [key]: f(prev[key]) })), []);

  // ---- 시간: 문항에 들어올 때 shown_at, 나갈 때 elapsed 누적
  useEffect(() => {
    const key = it.item_key;
    setAskClear(false);
    enteredAt.current = performance.now();
    patch(key, s => s.shown_at ? s : { ...s, shown_at: nowIso() });
    return () => {
      const dt = Math.round(performance.now() - enteredAt.current);
      patch(key, s => ({ ...s, elapsed: s.elapsed + dt }));
    };
  }, [it.item_key, patch]);

  // ---- 앱 밖에 있던 시간 (탭 전환·홈 버튼)
  useEffect(() => {
    const key = it.item_key;
    const onVis = () => {
      if (document.hidden) hiddenAt.current = performance.now();
      else if (hiddenAt.current !== null) {
        const dt = Math.round(performance.now() - hiddenAt.current);
        hiddenAt.current = null;
        patch(key, s => ({ ...s, focus_lost: s.focus_lost + dt }));
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [it.item_key, patch]);

  // ---- 판정
  function judge(label: string, v: boolean | null, unsure = false) {
    patch(it.item_key, s => {
      const a = s.stmts[label];
      const same = a.answer === v && a.unsure === unsure;
      const had = a.answer !== null || a.unsure;
      return { ...s, stmts: { ...s.stmts, [label]: {
        answer: same ? null : v, unsure: same ? false : unsure,           // 같은 걸 다시 누르면 지움
        changed_cnt: a.changed_cnt + (had && !same ? 1 : 0), answered_at: nowIso() } } };
    });
  }
  function pick(no: number) {
    patch(it.item_key, s => ({ ...s, choice: s.choice === no ? undefined : no,
      changed_cnt: s.changed_cnt + (s.choice !== undefined && s.choice !== no ? 1 : 0), answered_at: nowIso() }));
  }
  function type(text: string) {
    patch(it.item_key, s => ({ ...s, text, answered_at: nowIso() }));
  }

  // ---- 제출 페이로드
  function build(): SubmitBody {
    // 지금 문항의 시간은 effect 정리 전이라 직접 더한다
    const now = performance.now();
    const answers: Answer[] = [];
    const timing: ItemTiming[] = [];
    items.forEach((item, i) => {
      const s = state[item.item_key];
      const elapsed = s.elapsed + (item.item_key === it.item_key ? Math.round(now - enteredAt.current) : 0);
      const k = kindOf(item, mode);
      if (k === "choice") {
        if (s.choice !== undefined) answers.push({ item_key: item.item_key, choice_no: s.choice, answered_at: s.answered_at });
      } else if (k === "short") {
        answers.push({ item_key: item.item_key, answer_text: s.text ?? "", answered_at: s.answered_at });
      } else {
        for (const [label, a] of Object.entries(s.stmts))
          answers.push({ item_key: item.item_key, label, answer: a.answer, unsure: a.unsure, answered_at: a.answered_at, changed_cnt: a.changed_cnt });
      }
      timing.push({ item_key: item.item_key, seq: i + 1, elapsed_ms: elapsed, focus_lost_ms: s.focus_lost, scroll_px: 0,
                    shown_at: s.shown_at, answered_at: s.answered_at });
    });
    return { answers, items: timing, client: {
      device: navigator.userAgent.slice(0, 80), viewport: `${window.innerWidth}x${window.innerHeight}`,
      orientation: window.innerWidth >= window.innerHeight ? "landscape" : "portrait", started_at: startedAt.current } };
  }

  const nDone = useMemo(() => items.filter(x => answered(state[x.item_key], x, mode)).length, [items, state, mode]);
  const nInk = st.qStrokes.length + st.padStrokes.length;
  function undoInk() {                                   // 두 곳 중 가장 최근 획 하나
    patch(it.item_key, s => {
      const q = s.qStrokes.at(-1)?.t0 ?? -1, p = s.padStrokes.at(-1)?.t0 ?? -1;
      if (q < 0 && p < 0) return s;
      return q >= p ? { ...s, qStrokes: s.qStrokes.slice(0, -1) } : { ...s, padStrokes: s.padStrokes.slice(0, -1) };
    });
  }
  const clearInk = () => { patch(it.item_key, s => ({ ...s, qStrokes: [], padStrokes: [] })); setAskClear(false); };
  const last = idx === items.length - 1;

  return (
    <div className="solve">
      {/* 왼쪽: 문항 */}
      <section className="q">
        {it.image
          ? <ZoomPane resetKey={it.item_key} onFrame={setFrame}
                      overlay={<InkPad frame={frame} strokes={st.qStrokes} onChange={next => patch(it.item_key, s => ({ ...s, qStrokes: next }))} penOnly={penOnly} tool={tool} />}>
              <div className="qimg">
                <img src={it.image} alt={it.title} draggable={false} />
                {mode === "diagnostic" && it.regions?.options && (() => { const [y0, x0, y1, x1] = it.regions.options;   // 진단 모드: 선지 가림 (이미지에 붙는다)
                  return <div className="mask" style={{ top: `${y0 / 10}%`, left: `${x0 / 10}%`, height: `${(y1 - y0) / 10}%`, width: `${(x1 - x0) / 10}%` }} />; })()}
              </div>
            </ZoomPane>
          : <div className="qtext"><p>{it.stem}</p>{it.diagram && <p className="soft">{it.diagram}</p>}</div>}
      </section>

      {/* 오른쪽 위: 판정 */}
      <section className="judge">
        <header className="jbar">
          <span className="mono">{idx + 1} / {items.length}</span>
          <span className="soft tiny">{it.title} · {mode === "diagnostic" ? "진단" : "실전"}</span>
          <span className="dots">{items.map((x, i) =>
            <i key={x.item_key} className={`${i === idx ? "cur" : ""} ${answered(state[x.item_key], x, mode) ? "done" : ""}`} onClick={() => setIdx(i)} />)}</span>
        </header>

        {kindOf(it, mode) === "choice" ? (
          <div className="choices">
            {CIRCLED.map((c, i) => <button key={i} className={st.choice === i + 1 ? "on" : "ghost"} onClick={() => pick(i + 1)}>{c}</button>)}
          </div>
        ) : kindOf(it, mode) === "short" ? (
          <label className="short">
            <span className="soft tiny">답을 적으세요 (단위·기호 포함, 예: 4 kg · 3/5 mv0)</span>
            <input value={st.text ?? ""} onChange={e => type(e.target.value)} placeholder="답" autoCapitalize="none" autoCorrect="off" />
          </label>
        ) : (
          <div className="stmts">
            {it.statements.map(s => {
              const a = st.stmts[s.label];
              return (
                <div key={s.label} className="stmt">
                  <b>{s.label}</b>
                  {s.text && <span className="soft">{s.text}</span>}
                  <span className="oxq">
                    <button className={a.answer === true ? "on t" : "ghost"} onClick={() => judge(s.label, true)}>O</button>
                    <button className={a.answer === false ? "on f" : "ghost"} onClick={() => judge(s.label, false)}>X</button>
                    <button className={a.unsure ? "on u" : "ghost"} onClick={() => judge(s.label, null, true)}>?</button>
                  </span>
                </div>
              );
            })}
          </div>
        )}

        <nav className="jnav">
          <button className="ghost" onClick={() => setIdx(i => i - 1)} disabled={idx === 0}>← 이전</button>
          {last
            ? <button onClick={() => onSubmit(build())} disabled={busy}>{busy ? "…" : `제출 (${nDone}/${items.length})`}</button>
            : <button onClick={() => setIdx(i => i + 1)}>다음 →</button>}
        </nav>
      </section>

      {/* 오른쪽 아래: 연습장 */}
      <section className="pad">
        <div className="padbar">
          <span className="soft tiny">연습장 <span className="dim">(문항 위에도 써집니다)</span></span>
          <label className="chk tiny"><input type="checkbox" checked={penOnly} onChange={e => setPenOnly(e.target.checked)} /> 펜만</label>
          <span className="seg">
            <button className={tool === "pen" ? "on tiny" : "ghost tiny"} onClick={() => setTool("pen")}>펜</button>
            <button className={tool === "eraser" ? "on tiny" : "ghost tiny"} onClick={() => setTool("eraser")}>지우개</button>
          </span>
          <button className="ghost tiny" onClick={undoInk} disabled={!nInk}>되돌리기</button>
          {askClear
            ? <span className="confirm">문항 위·연습장 필기를 모두 지울까요?
                <button className="tiny danger" onClick={clearInk}>지우기</button>
                <button className="ghost tiny" onClick={() => setAskClear(false)}>취소</button></span>
            : <button className="ghost tiny" onClick={() => setAskClear(true)} disabled={!nInk}>전체 지우기</button>}
        </div>
        <InkPad strokes={st.padStrokes} onChange={next => patch(it.item_key, s => ({ ...s, padStrokes: next }))} penOnly={penOnly} tool={tool} />
      </section>
    </div>
  );
}
