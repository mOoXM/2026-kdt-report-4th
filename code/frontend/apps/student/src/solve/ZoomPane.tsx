/**
 * ZoomPane.tsx — 문항 패널의 확대·이동. 안의 내용(InkPad)을 transform(translate + scale) 으로 옮기고 키운다.
 *
 *   손가락 하나: 끌면 이동 (아이패드). 펜이 닿아 있거나 뗀 직후 PALM_MS 안의 터치는 손바닥으로 보고 무시한다
 *   손가락 둘:   벌리면 두 손가락 사이가 중심이 되어 확대, 함께 끌면 이동
 *   마우스:      Ctrl+휠 (트랙패드 핀치도 이걸로 온다), 오른쪽 위 − / 100% / + 버튼. 마우스 끌기는 안 한다
 *
 * 왜 transform 인가: 전엔 폭(%)을 키우고 scrollLeft 로 옮겼다. 처음 열면 문항 전체가 보이게 맞추므로 내용물이
 * 패널보다 작고, 그러면 스크롤이 없어서 손가락 사이가 아니라 가운데로 커졌다. translate 는 그 제약이 없다.
 * 펜은 InkPad 가 받는다 — 좌표가 getBoundingClientRect 비율이라 transform 이 걸려도 그대로 맞는다.
 * 캔버스 해상도는 제스처가 끝날 때 onScale(배율) 로 알려 InkPad 가 다시 맞춘다 (안 그러면 4배에서 획이 뭉개진다).
 *
 * 종이: 이미지 둘레에 여백을 두른 것이 "종이" 다. 학생은 여백에 쓰고 그 여백으로 확대한다.
 *       여백은 고정값 — 위·왼쪽 EDGE px (밑줄 치고 화살표 빼낼 만큼), 오른쪽은 패널 폭, 아래는 패널 높이 (각각 한 화면 분량).
 *       문항은 종이 왼쪽 위에 붙고 쓰는 공간은 오른쪽 → 아래로 열린다 (학생 필기 순서: 오른쪽 → 아래 → 왼쪽·위).
 *       경계는 이미지가 아니라 종이 기준 — 종이가 패널보다 작으면 패널 안 어디든, 크면 종이 밖 빈 공간이 안 생기게.
 *       둘 다 한 식으로: t ∈ [min(0, W − w·s), max(0, W − w·s)]  (w = 종이 폭). MIN=0.5 쯤에서 종이 전체가 패널에 들어온다 = 여백의 한계
 * "파트별 확대"(레이아웃 상자를 두드리면 그 구역만)는 여기 zoomTo(box) 하나 더 붙이면 된다.
 *
 * overlay: transform 을 **안 받는** 층을 패널 위에 하나 더 둔다 — 필기 캔버스가 여기 온다. 그래서 축소해서 생긴
 * 여백에도 써지고, 획은 onFrame(이미지가 지금 놓인 사각형)을 기준으로 그려져 이미지에 붙어 다닌다.
 * 덮개가 터치를 먼저 받지만 이벤트가 패널로 올라오므로 손가락 제스처는 그대로 된다.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";

const MIN = 0.5, MAX = 4;             // 100% 아래로도. 100% = 처음 열 때의 "전체가 보이는" 크기
const PALM_MS = 400;
const EDGE = 48;                      // 위·왼쪽 여백 (px, 배율 1)
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export type Frame = { x: number; y: number; w: number; h: number };
type Props = { children: ReactNode; resetKey?: string; onScale?: (s: number) => void;
               overlay?: ReactNode; onFrame?: (f: Frame) => void };

export default function ZoomPane({ children, resetKey, onScale, overlay, onFrame }: Props) {
  const ref = useRef<HTMLDivElement>(null);          // 패널 (overflow hidden)
  const innerRef = useRef<HTMLDivElement>(null);     // 내용물 (transform 이 걸리는 쪽)
  const view = useRef({ s: 1, tx: 0, ty: 0 });       // 현재 변환. 제스처마다 바뀌므로 상태가 아니라 ref
  const [zoom, setZoom] = useState(1);               // 버튼의 % 표시용
  const [fit, setFit] = useState(1);                 // 1 = 폭에 맞춤, <1 = 높이에 맞춰 줄임 (이미지 기본 폭 = fit × 패널 폭)
  const [pad, setPad] = useState({ l: EDGE, t: EDGE, r: 0, b: 0 });   // 종이 여백 (px, 배율 1). 오른쪽·아래는 패널 크기
  // ★ 손가락·휠 핸들러는 useEffect(…, []) 로 한 번만 등록돼 그 안의 apply 는 **처음 pad(r:0, b:0)** 를 붙든다.
  // 이미지가 로드돼 pad.r/b 가 패널 크기로 바뀌어도 모르고 틀을 (이미지+여백) 폭으로 계산 → 핀치 뒤 획이 이미지에서 떨어진다.
  // 그래서 틀 계산은 항상 padRef.current 를 읽는다 (onScaleRef·onFrameRef 와 같은 수법)
  const padRef = useRef(pad); padRef.current = pad;
  const penUntil = useRef(0);                        // 이 시각까지 터치를 무시 (펜이 닿아 있으면 Infinity)
  const onScaleRef = useRef(onScale); onScaleRef.current = onScale;
  const onFrameRef = useRef(onFrame); onFrameRef.current = onFrame;

  const apply = () => {
    const v = view.current, inner = innerRef.current;
    if (!inner) return;
    inner.style.transform = `translate(${v.tx}px, ${v.ty}px) scale(${v.s})`;
    // 덮개 필기의 기준 틀 = 이미지가 놓인 사각형 (종이에서 여백만큼 안쪽). pad 는 ref 로 — 오래된 클로저에서 불려도 지금 값
    const p = padRef.current;
    onFrameRef.current?.({ x: v.tx + p.l * v.s, y: v.ty + p.t * v.s,
                           w: (inner.offsetWidth - p.l - p.r) * v.s, h: (inner.offsetHeight - p.t - p.b) * v.s });
  };
  const bounds = () => {
    const el = ref.current!, inner = innerRef.current!;
    return { W: el.clientWidth, H: el.clientHeight, w: inner.offsetWidth, h: inner.offsetHeight };
  };
  const clampT = () => {
    const v = view.current, { W, H, w, h } = bounds();
    const sw = w * v.s, sh = h * v.s;
    v.tx = clamp(v.tx, Math.min(0, W - sw), Math.max(0, W - sw));
    v.ty = clamp(v.ty, Math.min(0, H - sh), Math.max(0, H - sh));
  };
  /** 배율 1. 이미지가 가로 가운데, 위에서 살짝 내려온 자리 (종이 가운데가 아니라 — 오른쪽·아래 여백이 넓어서) */
  const center = () => {
    if (!ref.current || !innerRef.current) return;
    const { W, w } = bounds();
    const p = padRef.current;
    const wImg = w - p.l - p.r;
    view.current = { s: 1, tx: (W - wImg) / 2 - p.l, ty: 8 - p.t };
    clampT(); apply(); setZoom(1); onScaleRef.current?.(1);
  };
  /** 화면 점(cx, cy)을 고정한 채 배율을 바꾼다: 그 점 아래의 내용물 점 c = (p − t)/s 가 그대로 p 에 오도록 t' = p − c·s' */
  const zoomAt = (next: number, cx: number, cy: number) => {
    const el = ref.current;
    if (!el) return;
    const v = view.current;
    next = clamp(next, MIN, MAX);
    const r = el.getBoundingClientRect();
    const px = cx - r.left, py = cy - r.top;
    const k = next / v.s;
    v.tx = px - (px - v.tx) * k;
    v.ty = py - (py - v.ty) * k;
    v.s = next;
    clampT(); apply(); setZoom(next);
  };
  const panBy = (dx: number, dy: number) => {
    const v = view.current;
    v.tx += dx; v.ty += dy;
    clampT(); apply();
  };
  const settle = () => onScaleRef.current?.(view.current.s);          // 제스처 끝: InkPad 해상도 맞추기

  // ---- 전체가 보이는 기본 배율: 안의 <img> 가로세로비 × 패널 크기. 바뀌면 가운데로
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const calc = () => {
      const img = el.querySelector("img");
      if (!img || !img.naturalWidth || !el.clientWidth) return;
      const hAtFull = el.clientWidth * (img.naturalHeight / img.naturalWidth);
      const f = Math.min(1, el.clientHeight / hAtFull);
      setFit(f);
      setPad({ l: EDGE, t: EDGE, r: el.clientWidth, b: el.clientHeight });   // 오른쪽·아래 = 한 화면 분량 (배율 1 기준 px)
    };
    calc();
    const ro = new ResizeObserver(calc);
    ro.observe(el);
    el.addEventListener("load", calc, true);                               // img load 는 버블이 없다 → 캡처로
    return () => { ro.disconnect(); el.removeEventListener("load", calc, true); };
  }, [resetKey]);
  useEffect(() => { center(); }, [fit, pad, resetKey]);                   // eslint-disable-line react-hooks/exhaustive-deps

  // ---- 펜 감시: 펜이 닿아 있는 동안과 뗀 직후의 터치는 손바닥이다
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const down = (e: PointerEvent) => { if (e.pointerType === "pen") penUntil.current = Infinity; };
    const up = (e: PointerEvent) => { if (e.pointerType === "pen") penUntil.current = performance.now() + PALM_MS; };
    el.addEventListener("pointerdown", down, true);
    el.addEventListener("pointerup", up, true);
    el.addEventListener("pointercancel", up, true);
    return () => { el.removeEventListener("pointerdown", down, true); el.removeEventListener("pointerup", up, true); el.removeEventListener("pointercancel", up, true); };
  }, []);

  // ---- 손가락
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let one: { x: number; y: number } | null = null;
    let two: { d: number; mx: number; my: number } | null = null;
    const palm = () => performance.now() < penUntil.current;
    const read2 = (e: TouchEvent) => {
      const [a, b] = [e.touches[0], e.touches[1]];
      return { d: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), mx: (a.clientX + b.clientX) / 2, my: (a.clientY + b.clientY) / 2 };
    };
    const start = (e: TouchEvent) => {
      if (palm()) return;
      e.preventDefault();                                                  // 사파리의 페이지 스크롤·확대를 막는다
      if (e.touches.length >= 2) { two = read2(e); one = null; }
      else if (e.touches.length === 1) { one = { x: e.touches[0].clientX, y: e.touches[0].clientY }; two = null; }
    };
    const move = (e: TouchEvent) => {
      if (palm()) return;
      e.preventDefault();
      if (e.touches.length >= 2) {
        if (!two) { two = read2(e); return; }
        const now = read2(e);
        panBy(now.mx - two.mx, now.my - two.my);                           // 함께 끌기 = 이동
        if (two.d > 0) zoomAt(view.current.s * (now.d / two.d), now.mx, now.my);   // 벌리기 = 그 사이를 중심으로 확대
        two = now;
      } else if (e.touches.length === 1 && one) {
        const t = e.touches[0];
        panBy(t.clientX - one.x, t.clientY - one.y);
        one = { x: t.clientX, y: t.clientY };
      }
    };
    const end = (e: TouchEvent) => {
      if (e.touches.length < 2) two = null;
      if (e.touches.length === 1) one = { x: e.touches[0].clientX, y: e.touches[0].clientY };   // 둘 → 하나: 이어서 이동
      if (e.touches.length === 0) { one = null; settle(); }
    };
    el.addEventListener("touchstart", start, { passive: false });
    el.addEventListener("touchmove", move, { passive: false });
    el.addEventListener("touchend", end);
    el.addEventListener("touchcancel", end);
    return () => { el.removeEventListener("touchstart", start); el.removeEventListener("touchmove", move); el.removeEventListener("touchend", end); el.removeEventListener("touchcancel", end); };
  }, []);                                                                   // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Ctrl+휠 (트랙패드 핀치 포함). 멈추고 200ms 뒤에 해상도 맞춤
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let timer = 0;
    const wheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      zoomAt(view.current.s * Math.exp(-e.deltaY / 300), e.clientX, e.clientY);
      window.clearTimeout(timer);
      timer = window.setTimeout(settle, 200);
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => { el.removeEventListener("wheel", wheel); window.clearTimeout(timer); };
  }, []);                                                                   // eslint-disable-line react-hooks/exhaustive-deps

  const mid = () => { const r = ref.current!.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2] as const; };
  const step = (f: number) => { zoomAt(view.current.s * f, ...mid()); settle(); };

  return (
    <div className="zoom">
      <div ref={ref} className="zoomview">
        <div ref={innerRef} className="zoominner paper" style={{ width: `${fit * 100}%`, padding: `${pad.t}px ${pad.r}px ${pad.b}px ${pad.l}px`, boxSizing: "content-box" }}>{children}</div>
        {overlay && <div className="zoomoverlay">{overlay}</div>}
      </div>
      <div className="zoomctl">
        <button className="ghost tiny" onClick={() => step(1 / 1.25)} disabled={zoom <= MIN}>−</button>
        <button className="ghost tiny mono" onClick={center}>{Math.round(zoom * 100)}%</button>
        <button className="ghost tiny" onClick={() => step(1.25)} disabled={zoom >= MAX}>+</button>
      </div>
    </div>
  );
}
