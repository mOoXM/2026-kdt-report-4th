/**
 * hooks.ts — 화면이 서버를 부를 때의 세 상태(불러오는 중 / 됨 / 오류)를 한 줄로.
 *   const { data, err, loading, reload } = useLoad(() => teacher.home(), [])
 * 오류 문장은 서버 것 그대로 (ApiError.message). 네트워크면 고정 문장.
 */
import { useCallback, useEffect, useState, type DependencyList } from "react";
import { ApiError } from "./api";

export const errorText = (e: unknown): string =>
  e instanceof ApiError ? e.message : "서버에 연결할 수 없습니다";

export function useLoad<T>(fn: () => Promise<T>, deps: DependencyList) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick(n => n + 1), []);
  useEffect(() => {
    let alive = true;
    setLoading(true); setErr(null);
    fn().then(d => { if (alive) setData(d); })
        .catch(e => { if (alive) setErr(errorText(e)); })
        .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, err, loading, reload, setData };
}

/** 버튼 하나가 서버를 부를 때: busy 와 오류만. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true); setErr(null);
    try { return await fn(); } catch (e) { setErr(errorText(e)); return undefined; } finally { setBusy(false); }
  }, []);
  return { busy, err, run, setErr };
}

/** 날짜 짧게: '2026-10-07T04:10:00Z' → '10.7' / 같은 해 아니면 '25.10.7' */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const y = d.getFullYear() === new Date().getFullYear() ? "" : `${String(d.getFullYear()).slice(2)}.`;
  return `${y}${d.getMonth() + 1}.${d.getDate()}`;
}
