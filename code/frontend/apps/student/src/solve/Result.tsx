/**
 * Result.tsx — 연습 결과. 서버가 채점·진단해 준 것을 그대로 보여 준다 (화면이 계산하지 않는다).
 *   summary  답한 판단 단위 수 · 맞힌 수
 *   tiers    "무엇부터" 문장들 (심한 순)
 *   sections 그룹별 개념: 숙달 / 경계 / 미숙달 / 판단 불가 + 틀린 보기
 * 옛 index.html 의 결과 부분을 React 로 옮긴 최소판. 추천 문항 이어 풀기는 /api/student/recommend 가 붙으면.
 */
import { Link } from "react-router-dom";
import type { Item, SubmitResult } from "@pl/shared";

const STATUS_CLASS: Record<string, string> = { "숙달": "ok", "경계": "weak", "미숙달": "false", "판단 불가": "soft" };

type Props = { res: SubmitResult; items: Item[]; onAgain: () => void; onMore?: () => void; busy?: boolean; recommended?: boolean };

export default function Result({ res, items, onAgain, onMore, busy, recommended }: Props) {
  const title = Object.fromEntries(items.map(i => [i.item_key, i.title]));
  const { answered, correct } = res.summary;
  const nWrong = new Set(res.sections.flatMap(sec => sec.concepts.flatMap(k => k.wrong.map(w => w.item_key)))).size;
  return (
    <main className="card wide">
      <h1>결과 {recommended && <span className="soft tiny">· 추천 문항 (진단에는 안 섞임)</span>}</h1>
      <p><b>{correct} / {answered}</b> <span className="soft">판단 단위 (모르겠다·무응답은 뺌)</span>
         <span className="soft tiny"> · {res.attempt_id}</span></p>

      {res.tiers.length > 0 && (
        <div className="tiers">
          {res.tiers.map(t => <p key={t.title}><b>{t.title}</b> {t.text}</p>)}
        </div>
      )}

      {res.sections.map(sec => (
        <section key={sec.group} className="conceptgroup">
          <h2>{sec.group}</h2>
          {sec.concepts.map(k => (
            <div key={k.code} className="concept">
              <div className="concepthead">
                <span className={`st ${STATUS_CLASS[k.status] ?? ""}`}>{k.status}</span>
                <b>{k.label}</b>
                <span className="soft tiny">{k.n_correct}/{k.n_units}{k.score !== null ? ` · ${Math.round(k.score * 100)}%` : ""}</span>
              </div>
              {k.wrong.length > 0 && (
                <ul className="wrong">
                  {k.wrong.map(w => (
                    <li key={w.item_key + w.label}>
                      {title[w.item_key] ?? w.item_key} <b>{w.label}</b>
                      {w.error_rate !== null && <span className="soft tiny"> · 전국 오판율 {Math.round(w.error_rate)}%</span>}
                      {w.also.length > 0 && <span className="soft tiny"> · 함께 필요: {w.also.join(", ")}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </section>
      ))}

      <p>
        {onMore && <button onClick={onMore} disabled={busy}>{busy ? "…" : nWrong ? `틀린 ${nWrong}문항과 비슷한 문제 이어서 풀기` : "비슷한 문제 이어서 풀기"}</button>}{" "}
        <button className="ghost" onClick={onAgain}>처음부터</button> <Link to="/" className="soft">홈</Link>
      </p>
    </main>
  );
}
