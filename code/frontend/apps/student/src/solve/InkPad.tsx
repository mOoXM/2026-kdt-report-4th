/**
 * InkPad.tsx — 필기 부품. Ink.tsx(시험대)에서 캔버스 부분을 떼어낸 것.
 *
 * 쓰는 쪽이 획(strokes)을 들고 있고 이 부품은 그리기만 한다 — 그래서 문항을 넘겼다 돌아와도
 * 획이 남고, 제출 때 문항별 획을 그대로 보낼 수 있다 (나중 item_ink 표).
 *
 *   <InkPad strokes={s} onChange={setS} />                 빈 종이 (연습장)
 *   <InkPad strokes={s} onChange={setS} image={url} />     이미지 위에 (시험대)
 *
 * 지우개(tool="eraser", 또는 펜 뒷면 버튼 buttons&32)는 **획 단위** — 닿은 획이 통째로 사라진다. 픽셀을 긁지 않는다 (획 데이터가 깨진다).
 *
 * 캔버스 두 장: base(확정 획) · live(지금 긋는 획 + 예측 꼬리). 입력은 PointerEvents —
 * pointerType==="pen" 만 (penOnly), getCoalescedEvents 로 점을 다 받고, pressure 를 굵기로 (perfect-freehand).
 * 좌표는 **기준 틀(frame) 기준 0~1** — 틀은 보통 패드 자신이고, 풀이 화면에서는 ZoomPane 이 주는 "지금 이미지가 놓인 사각형".
 * 그러면 패드는 패널 전체를 덮고(축소해서 생긴 여백에도 써진다), 획은 이미지에 붙어 확대·이동을 따라간다.
 * 틀 밖의 획은 0 미만·1 초과 좌표로 그대로 남는다. 굵기는 틀 폭에 비례.
 */
import { type Box } from "@pl/shared";
import { useCallback, useEffect, useRef, useState } from "react";
import { getStroke } from "perfect-freehand";

export type Pt = [x: number, y: number, p: number, dt: number];     // x·y 는 틀 기준 비율 (틀 안이면 0~1, 밖이면 그 밖)
export type Frame = { x: number; y: number; w: number; h: number };  // 패드 안에서 기준 틀이 놓인 자리 (CSS px)
export type Stroke = { t0: number; tool: string; points: Pt[] };

const PEN = { size: 4, thinning: 0.6, smoothing: 0.5, streamline: 0.45 };
const BASE_W = 700;                      // 이 폭에서 굵기 4px. 넓거나 확대되면 비례

function toPath(pts: number[][]): string {
  if (pts.length < 2) return "";
  let d = `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)} Q`;
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[(i + 1) % pts.length];
    d += ` ${x0.toFixed(2)} ${y0.toFixed(2)} ${((x0 + x1) / 2).toFixed(2)} ${((y0 + y1) / 2).toFixed(2)}`;
  }
  return d + " Z";
}

export function drawStroke(ctx: CanvasRenderingContext2D, s: Stroke, color: string, f: Frame) {
  if (s.points.length === 0 || !f.w || !f.h) return;
  const size = Math.max(1.2, PEN.size * (f.w / BASE_W));
  const outline = getStroke(s.points.map(([x, y, p]) => [f.x + x * f.w, f.y + y * f.h, p]), { ...PEN, size, simulatePressure: s.tool !== "pen" });
  ctx.fillStyle = color;
  ctx.fill(new Path2D(toPath(outline)));
}

/** 저장용 (이미 0~1). 소수 자릿수만 줄인다. responses.db item_ink 후보 모양. */
export function toInkJson(strokes: Stroke[]) {
  return strokes.map(s => ({
    t0: Math.round(s.t0), tool: s.tool,
    points: s.points.map(([x, y, p, dt]) => [+x.toFixed(4), +y.toFixed(4), +p.toFixed(3), dt]),
  }));
}

export type InkTool = "pen" | "eraser";
const ERASE_R = 14;                      // 지우개 반지름 (CSS px)

export type InkStats = { events: number; coalesced: number; pMin: number; pMax: number; tool: string; hz: number };
const STATS0: InkStats = { events: 0, coalesced: 0, pMin: 1, pMax: 0, tool: "-", hz: 0 };

type Props = {
  strokes: Stroke[];
  onChange: (next: Stroke[]) => void;
  image?: string;                       // 있으면 이미지 크기에 맞춘다. 없으면 부모 박스 크기
  frame?: Frame;                        // 기준 틀 (패드 안 px). 주면 패드는 부모 박스를 덮고 좌표는 이 틀 기준 — ZoomPane 위 덮개용
  mask?: Box[];                         // 가릴 구역 (0~1000 좌표). 이미지와 캔버스 사이에 흰 판을 깐다 — 진단 모드의 선지
  sharp?: number;                       // 캔버스 해상도 배율 (ZoomPane 이 확대 끝에 준다). transform 으로 키워도 획이 뭉개지지 않게
  penOnly?: boolean;
  tool?: InkTool;
  onStats?: (s: InkStats) => void;      // 시험대용 숫자판
  className?: string;
};

const MAX_CANVAS_PX = 12_000_000;       // iPad 사파리는 캔버스 하나가 ~16M 픽셀을 넘으면 조용히 비워 버린다. 그 아래로

export default function InkPad({ strokes, onChange, image, frame, mask, sharp = 1, penOnly = true, tool = "pen", onStats, className }: Props) {
  const erasing = useRef(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const baseRef = useRef<HTMLCanvasElement>(null);
  const liveRef = useRef<HTMLCanvasElement>(null);
  const cur = useRef<Stroke | null>(null);
  const hzWin = useRef<number[]>([]);
  const stats = useRef<InkStats>({ ...STATS0 });
  const [size, setSize] = useState({ w: 0, h: 0 });

  // 캔버스를 이미지(또는 박스) 크기에 맞춘다. DPR 배율 포함
  const fit = useCallback(() => {
    const el = image ? imgRef.current : boxRef.current;
    if (!el) return;
    const w = el.clientWidth, h = el.clientHeight;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    const k = Math.min(dpr * Math.max(1, sharp), Math.sqrt(MAX_CANVAS_PX / (w * h)));   // 픽셀 수 상한 안에서 배율
    for (const c of [baseRef.current, liveRef.current]) {
      if (!c) continue;
      c.width = Math.round(w * k); c.height = Math.round(h * k);
      c.style.width = `${w}px`; c.style.height = `${h}px`;
      c.getContext("2d", { desynchronized: true })?.setTransform(k, 0, 0, k, 0, 0);
    }
    setSize({ w, h });
  }, [image, sharp]);

  useEffect(() => {
    fit();
    const ro = new ResizeObserver(fit);
    if (boxRef.current) ro.observe(boxRef.current);
    return () => ro.disconnect();
  }, [fit]);

  const fr: Frame = frame ?? { x: 0, y: 0, w: size.w, h: size.h };    // 기준 틀. 없으면 패드 자신

  // 확정 획 다시 그리기 (획·크기·틀이 바뀌면 — 틀은 확대·이동마다 바뀐다)
  useEffect(() => {
    const ctx = baseRef.current?.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, size.w, size.h);
    for (const s of strokes) drawStroke(ctx, s, "#16201C", fr);
  }, [strokes, size, fr.x, fr.y, fr.w, fr.h]);                            // eslint-disable-line react-hooks/exhaustive-deps

  // 포인터 → 틀 기준 비율. getBoundingClientRect 는 확대(transform/width)가 반영된 실제 크기
  const pos = (e: { clientX: number; clientY: number }, el: HTMLElement): [number, number] => {
    const r = el.getBoundingClientRect();
    const k = r.width ? size.w / r.width : 1;                             // 패드 자체가 transform 돼 있으면 보정
    const px = (e.clientX - r.left) * k, py = (e.clientY - r.top) * k;
    return [fr.w ? (px - fr.x) / fr.w : 0, fr.h ? (py - fr.y) / fr.h : 0];
  };
  const accept = (e: React.PointerEvent) => !penOnly || e.pointerType === "pen";

  const isEraser = (e: React.PointerEvent) => tool === "eraser" || (e.buttons & 32) !== 0;   // 32 = 펜 뒷면 지우개

  function eraseAt(x: number, y: number) {
    const rx = fr.w ? ERASE_R / fr.w : 0.02, ry = fr.h ? ERASE_R / fr.h : 0.02;          // 반지름도 틀 기준 비율로
    const hit = (s: Stroke) => s.points.some(([px, py]) => ((px - x) / rx) ** 2 + ((py - y) / ry) ** 2 <= 1);
    if (strokes.some(hit)) onChange(strokes.filter(s => !hit(s)));
  }

  function onDown(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!accept(e)) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const [x, y] = pos(e, e.currentTarget);
    if (isEraser(e)) { erasing.current = true; eraseAt(x, y); return; }
    cur.current = { t0: e.timeStamp, tool: e.pointerType, points: [[x, y, e.pressure || 0.5, 0]] };
    hzWin.current = [e.timeStamp];
  }

  function onMove(e: React.PointerEvent<HTMLCanvasElement>) {
    if (erasing.current) { const [x, y] = pos(e, e.currentTarget); eraseAt(x, y); return; }
    const s = cur.current;
    if (!s || !accept(e)) return;
    const el = e.currentTarget;
    const native = e.nativeEvent as PointerEvent;
    const batch = native.getCoalescedEvents?.() ?? [];
    const evs = batch.length ? batch : [native];
    for (const ev of evs) {
      const [x, y] = pos(ev, el);
      s.points.push([x, y, ev.pressure || 0.5, Math.round(ev.timeStamp - s.t0)]);
    }
    if (onStats) {
      hzWin.current.push(...evs.map(ev => ev.timeStamp));
      hzWin.current = hzWin.current.filter(t => t > e.timeStamp - 1000);
      const st = stats.current;
      st.events += evs.length; st.coalesced += batch.length > 1 ? batch.length - 1 : 0;
      st.pMin = Math.min(st.pMin, ...evs.map(v => v.pressure)); st.pMax = Math.max(st.pMax, ...evs.map(v => v.pressure));
      st.tool = e.pointerType; st.hz = hzWin.current.length;
      onStats({ ...st });
    }
    const ctx = liveRef.current?.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, size.w, size.h);
    drawStroke(ctx, s, "#16201C", fr);
    const pred = native.getPredictedEvents?.() ?? [];
    if (pred.length) {
      const tail: Stroke = { ...s, points: [...s.points.slice(-6), ...pred.map(ev => { const [x, y] = pos(ev, el); return [x, y, ev.pressure || 0.5, 0] as Pt; })] };
      drawStroke(ctx, tail, "rgba(22,32,28,0.35)", fr);
    }
  }

  function onUp(e: React.PointerEvent<HTMLCanvasElement>) {
    if (erasing.current) { erasing.current = false; e.currentTarget.releasePointerCapture(e.pointerId); return; }
    const s = cur.current;
    if (!s) return;
    cur.current = null;
    e.currentTarget.releasePointerCapture(e.pointerId);
    liveRef.current?.getContext("2d")?.clearRect(0, 0, size.w, size.h);
    if (s.points.length > 1) onChange([...strokes, s]);
  }

  return (
    <div ref={boxRef} className={`inkpad ${image ? "" : frame ? "overlay" : "blank"} ${tool === "eraser" ? "erasing" : ""} ${className ?? ""}`}>
      {image && <img ref={imgRef} src={image} alt="" onLoad={fit} draggable={false} />}
      {image && mask?.map(([y0, x0, y1, x1], i) => (
        // % 좌표라 확대(ZoomPane)·창 크기와 무관하게 이미지에 붙어 있다. 획은 이 위 캔버스에 그려지므로 필기는 가려지지 않는다
        <div key={i} className="mask" style={{ top: `${y0 / 10}%`, left: `${x0 / 10}%`, height: `${(y1 - y0) / 10}%`, width: `${(x1 - x0) / 10}%` }} />
      ))}
      <canvas ref={baseRef} className="layer" />
      <canvas ref={liveRef} className="layer top" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp} />
    </div>
  );
}
