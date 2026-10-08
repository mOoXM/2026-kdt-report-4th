/**
 * auth.tsx — "지금 누가 로그인돼 있나" 를 앱 전체가 공유한다.
 *
 * <AuthProvider app="student">  첫 로드에 /api/auth/me 를 한 번 부르고 결과를 컨텍스트에 둔다 (null = 안 됨).
 *                               app 은 이 번들이 어느 앱인지 — Login·RequireAuth 가 "여기 있어도 되는 사람인가" 를 가릴 때 쓴다.
 * useAuth()                     { app, user, loading, refresh, setUser }
 * <RequireAuth>                 로그인 안 됐으면 /login?next=지금경로 로, must_change=1 이면 비밀번호 변경 화면으로,
 *                               이 앱에 안 맞는 종류(학생 앱에 강사)면 그 사람의 앱으로 통째로 이동.
 *                               서버의 require_user 와 같은 규칙을 화면에서도 미리 적용하는 것 — 403 을 받고 나서
 *                               튕기는 것보다 처음부터 안 보여 주는 게 낫다. 최종 판단은 어차피 서버가 한다.
 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { APP_KINDS, ApiError, auth, homeOf, type AppName, type User } from "./api";

type Ctx = {
  app: AppName;
  user: User | null;
  dev: boolean;                        // 서버가 개발자 모드(PL_DEV=1)인가 — DevBar 가 뜬다
  loading: boolean;
  refresh: () => Promise<User | null>;
  setUser: (u: User | null) => void;
};

const AuthCtx = createContext<Ctx | null>(null);

export function AuthProvider({ app, children }: { app: AppName; children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [dev, setDev] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const { user, dev } = await auth.me();
      setUser(user); setDev(!!dev);
      return user;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { setUser(null); return null; }
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  return <AuthCtx.Provider value={{ app, user, dev, loading, refresh, setUser }}>{children}</AuthCtx.Provider>;
}

export function useAuth(): Ctx {
  const c = useContext(AuthCtx);
  if (!c) throw new Error("useAuth 는 AuthProvider 안에서만");
  return c;
}

/** 이 사용자가 이 앱에 들어와도 되는가. 운영자(is_admin)는 어느 앱이든 — 서버 권한 검사와 같은 규칙. */
export const belongsHere = (app: AppName, u: User) => !!u.is_admin || APP_KINDS[app].includes(u.kind);

/** 다른 앱으로 통째로 이동 (라우터 밖이므로 새로고침). */
export function leaveTo(u: User) {
  window.location.href = homeOf(u);
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { app, user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="loading">확인하는 중</div>;
  const next = encodeURIComponent(loc.pathname + loc.search);
  if (!user) return <Navigate to={`/login?next=${next}`} replace />;
  if (!belongsHere(app, user)) { leaveTo(user); return <div className="loading">이동하는 중</div>; }
  if (user.must_change) return <Navigate to={`/login?mode=password&next=${next}`} replace />;
  return <>{children}</>;
}
