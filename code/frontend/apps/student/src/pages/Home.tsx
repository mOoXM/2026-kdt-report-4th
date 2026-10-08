/**
 * Home.tsx — 학생 앱 홈. 열린 시험(강사가 낸 것)이 맨 위, 그 아래 연습·필기 시험대.
 * 열린 시험은 /api/student/exams — 내 반에서 진행 중인 것만. 제출한 것은 흐리게 (결과는 강사가 공개할 때).
 */
import { Link } from "react-router-dom";
import { Empty, PageHead, Pill, assignments, exams, shortDate, useAuth, useLoad } from "@pl/shared";

export default function Home() {
  const { user } = useAuth();
  const { data, err, loading } = useLoad(() => exams.list(), [user?.user_id]);
  const asg = useLoad(() => assignments.list(), [user?.user_id]);
  if (!user) return null;                                   // RequireAuth 가 막는다
  const open = data?.exams ?? [];
  const todo = (asg.data?.batches ?? []).filter(b => b.n_done < b.n);
  return (
    <>
      <PageHead title="열린 시험" sub={user.kind === "guest" ? "게스트는 연습만 할 수 있습니다" : "선생님이 낸 시험이 여기 보입니다"} />
      {loading ? <div className="loading">불러오는 중</div> : err ? <Empty>{err}</Empty> : open.length === 0 ? <Empty>지금 열린 시험이 없습니다.</Empty> : (
        <div className="rows" style={{ gap: 8 }}>
          {open.map(e => e.submitted ? (
            <div key={e.exam_set_id} className="examcard done">
              <span className="t"><b>{e.title}</b><span>{e.class_name} · {e.n_items}문항</span></span>
              <Pill tone="ok">제출함</Pill>
            </div>
          ) : (
            <Link key={e.exam_set_id} to={`/exam/${e.exam_set_id}`} className="examcard">
              <span className="t"><b>{e.title}</b><span>{e.class_name} · {e.n_items}문항 · {e.mode === "diagnostic" ? "ㄱㄴㄷ 판단" : "①~⑤"}</span></span>
              <button>풀기 →</button>
            </Link>))}
        </div>)}

      {todo.length > 0 && (
        <>
          <h2 style={{ fontSize: 15, margin: "28px 0 10px" }}>과제</h2>
          <div className="rows" style={{ gap: 8 }}>
            {todo.map(b => (
              <Link key={b.assigned_at} to={`/assignment/${encodeURIComponent(b.assigned_at)}`} className="examcard">
                <span className="t"><b>{b.target_label ? `${b.target_label} 과제` : "선생님 과제"}</b>
                  <span>{shortDate(b.assigned_at)} · {b.n - b.n_done}문항 남음{b.due_at ? ` · ${shortDate(b.due_at)}까지` : ""}</span></span>
                <button>풀기 →</button>
              </Link>))}
          </div>
        </>)}

      <h2 style={{ fontSize: 15, margin: "28px 0 10px" }}>혼자 연습</h2>
      <div className="rows" style={{ gap: 8 }}>
        <Link to="/practice" className="examcard"><span className="t"><b>연습</b><span>문항을 하나씩 풀고 바로 결과 (진단 / 실전 모드)</span></span></Link>
        <Link to="/ink" className="examcard"><span className="t"><b>필기 시험대</b><span>아이패드에서 펜으로 써 보기</span></span></Link>
      </div>
    </>
  );
}
