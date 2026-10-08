/**
 * main.tsx — 학생 앱 입구. 라우트: /login · /(홈: 열린 시험) · /exam/:eid(시험 길) · /practice(연습) · /ink(필기 시험대). 로그인 뒤에만.
 * basename="/app/student" — FastAPI 가 apps/student/dist 를 /app/student/ 아래에서 서빙한다 (vite.config.ts 의 base 와 같다).
 * 공용 부품(AuthProvider·RequireAuth·Login)은 @pl/shared 에서 온다. app="student" 가 "여기 학생·게스트만" 을 정한다.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider, DevBar, Login, RequireAuth, Shell, type NavItem } from "@pl/shared";
import Home from "./pages/Home";
import Exam from "./pages/Exam";
import Ink from "./pages/Ink";
import Practice from "./pages/Practice";
import Assignment from "./pages/Assignment";

const NAV: NavItem[] = [{ to: "/", label: "홈", icon: "▤", end: true }, { to: "/practice", label: "연습", icon: "✎" }];

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename="/app/student">
      <AuthProvider app="student">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<RequireAuth><Shell title="물리 진단" nav={NAV}><Home /></Shell></RequireAuth>} />
          <Route path="/exam/:eid" element={<RequireAuth><Exam /></RequireAuth>} />
          <Route path="/practice" element={<RequireAuth><Practice /></RequireAuth>} />
          <Route path="/assignment/:at" element={<RequireAuth><Assignment /></RequireAuth>} />
          <Route path="/ink" element={<RequireAuth><Ink /></RequireAuth>} />
        </Routes>
        <DevBar />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
