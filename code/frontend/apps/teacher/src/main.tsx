/**
 * main.tsx — 강사 앱 입구. basename="/app/teacher" (vite.config.ts 의 base 와 같다).
 * 라우트:
 *   /login                       로그인 · 가입(학원명 또는 초대 코드) · 비밀번호 변경
 *   /                            1 내 반 목록 (+ 원장: 학원 전체 탭)
 *   /classes/:cid                2 반 = 명단 + 시험 목록
 *   /classes/:cid/exams/new      3 시험지 구성 (새로)
 *   /exams/:eid/edit             3 시험지 구성 (구성 중인 것 고치기)
 *   /exams/:eid                  4 시험 진행 (확정·열기·현황·닫기)
 *   /exams/:eid/results          5 결과 (표 ① · 열 펼침 ② · 학생 ③ · 개념 토글)
 * 모든 화면이 Shell(상단 바 + 내비) 안에 있다. 로그인은 밖.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider, DevBar, Login, RequireAuth, Shell, type NavItem } from "@pl/shared";
import Home from "./pages/Home";
import ClassPage from "./pages/ClassPage";
import ExamBuilder from "./pages/ExamBuilder";
import ExamPage from "./pages/ExamPage";
import Results from "./pages/Results";

const NAV: NavItem[] = [
  { to: "/", label: "내 반", icon: "▤", end: true },
];

const page = (el: React.ReactNode, wide = false) => <RequireAuth><Shell title="물리 진단 · 강사" nav={NAV} wide={wide}>{el}</Shell></RequireAuth>;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename="/app/teacher">
      <AuthProvider app="teacher">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={page(<Home />)} />
          <Route path="/classes/:cid" element={page(<ClassPage />)} />
          <Route path="/classes/:cid/exams/new" element={page(<ExamBuilder />, true)} />
          <Route path="/exams/:eid/edit" element={page(<ExamBuilder />, true)} />
          <Route path="/exams/:eid" element={page(<ExamPage />)} />
          <Route path="/exams/:eid/results" element={page(<Results />, true)} />
        </Routes>
        <DevBar />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
