/**
 * Shell.tsx — 앱 틀. 상단 바(제목 · 누구인지 · 로그아웃) + 내비.
 *   넓은 화면(≥ 900px, 아이패드 가로·노트북)  왼쪽 세로 내비
 *   좁은 화면(아이폰·아이패드 세로)            아래 탭 바 (홈 버튼 영역은 safe-area 로 비운다)
 * 두 앱이 같이 쓴다. nav 는 각 앱이 넘긴다. 풀이 화면(Solve)처럼 전체 화면이 필요한 곳은 Shell 을 안 쓴다.
 */
import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { auth } from "./api";
import { useAuth } from "./auth";

export type NavItem = { to: string; label: string; icon: string; end?: boolean };

const KIND = { teacher: "강사", student: "학생", guest: "게스트" } as const;

export default function Shell({ title, nav, children, wide }: { title: string; nav: NavItem[]; children: ReactNode; wide?: boolean }) {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  async function logout() {
    await auth.logout();
    setUser(null);
    navigate("/login", { replace: true });
  }
  return (
    <div className="shell">
      <header className="topbar">
        <NavLink to="/" className="brand">{title}</NavLink>
        {user && (
          <span className="who">
            <b>{user.display_name ?? user.login_key ?? user.email}</b>
            <span className="soft tiny"> · {KIND[user.kind]}{user.is_admin ? " · 운영자" : ""}</span>
            <button className="ghost tiny" onClick={logout}>로그아웃</button>
          </span>
        )}
      </header>
      <nav className="sidenav">
        {nav.map(n => (
          <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "on" : "")}>
            <i aria-hidden>{n.icon}</i><span>{n.label}</span>
          </NavLink>
        ))}
      </nav>
      <main className={wide ? "page wide" : "page"}>{children}</main>
      <nav className="tabbar">
        {nav.map(n => (
          <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "on" : "")}>
            <i aria-hidden>{n.icon}</i><span>{n.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

/** 상태 알약: 시험 상태·숙달 등. tone 은 토큰 색 이름 */
export function Pill({ tone, children }: { tone: "ok" | "weak" | "false" | "soft" | "true"; children: ReactNode }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

/** 페이지 머리: 제목 + 보조 문장 + 오른쪽 액션 */
export function PageHead({ title, sub, crumbs, actions }: { title: ReactNode; sub?: ReactNode; crumbs?: { to: string; label: string }[]; actions?: ReactNode }) {
  return (
    <header className="phead">
      <div>
        {crumbs && crumbs.length > 0 && (
          <p className="crumbs">{crumbs.map((c, i) => <span key={c.to}>{i > 0 && " / "}<NavLink to={c.to}>{c.label}</NavLink></span>)}</p>
        )}
        <h1>{title}</h1>
        {sub && <p className="soft">{sub}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
