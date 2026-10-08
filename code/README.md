# physics-lab — 문항 분해형 학습 진단 플랫폼

물리학Ⅰ ㄱ·ㄴ·ㄷ형 문항에서 학생이 **보기 하나하나를 어떻게 판단했는지** 받아,
그 보기가 요구하는 세부 개념 단위로 강점과 약점을 진단한다.

> **공개본 안내**
> 이 폴더는 과제 제출용 공개본이다. 서비스 전체(계정 · 반 · 시험 운영 · 풀이 화면 · 결과 표)는 그대로 동작하지만,
> 세부 개념 체계 · 진단 방식 · 시험지 자동 담기 · 유사도 결합 · 생성형 AI 지시문은 **단순한 기본 구현**으로 바꿔 넣었다.
> 문항은 이 저장소를 위해 새로 지은 데모 문항 10개이다(기출 아님).

## 구성

| 구성도 | 폴더 · 파일 | 하는 일 |
|---|---|---|
| 학생 앱 | `frontend/apps/student` | 문항 풀이(보기별 O · X · ?, 단답, ①~⑤), 필기 · 확대, 연습 · 과제 · 시험 |
| 강사 앱 | `frontend/apps/teacher` | 반 · 명단, 시험지 구성(자동 담기), 시험 열기 · 닫기, 결과 표 · 학생별 진단, 과제 내기 |
| API 서버 | `src/physics_lab/serve/` | FastAPI. `api.py` 가 사용자별 라우터(`auth` · `student` · `teacher` · `dev`)를 조립 |
| 진단 엔진 | `src/physics_lab/engine/` | `diagnosis.py` 개념별 진단 · `exam_pick.py` 자동 담기 · `concept_display.py` 결과 문구 · `interfaces.py` 교체 가능한 부품의 약속 |
| 유사 문항 엔진 | `src/physics_lab/similar/` | 그림 · 글 특징값의 코사인 유사도로 이웃 문항, 이웃의 개념으로 개념 제안 |
| 문항 DB | `build/ph1/physics.db` | 문항 · 보기 · 선지 · 난이도 정보 (`demo_seed.py` 가 만든다) |
| 문항-개념 연결표 | `data/ph1/concept_map.db`, `src/physics_lab/concept/` | 보기 ↔ 세부 개념. 사람이 확인한 라벨만 진단에 쓴다 |
| 응답 DB | `data/ph1/responses.db`, `responses.py`, `responses_schema.sql` | 응시 기록 · 보기별 응답(판단함/모르겠다/무응답) · 시험지 · 과제 |
| 계정 DB | `data/accounts.db`, `accounts.py`, `accounts_schema.sql` | 사용자 · 학원 · 반 · 명단 · 세션 (개인정보는 여기에만) |
| 사전 처리 | `src/physics_lab/offline/` | 생성형 AI 문항 구조화(제공자 인터페이스 + 캐시) · 문항 구역 박스 읽기 |

풀이 시점에는 AI 를 부르지 않는다. 사전 처리 결과(문항 DB · 구역 박스 · 특징값)를 서버가 읽기만 한다.

## 실행

필요한 것: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node.js LTS

```bash
uv sync                      # Python 의존성
uv run pl-demo-seed          # 데모 데이터: 문항 DB · 연결표 · 문항 이미지 · 구역 박스 · 특징값
cd frontend && npm install && npm run build && cd ..
```

개발자 모드로 서버를 띄운다 (로그인 없이 개발자 계정으로 들어가고, 화면 아래에 빨간 DEV 띠가 뜬다):

```bash
echo PL_DEV=1 > .env
uv run uvicorn physics_lab.serve.api:app --port 8000
```

- 강사 앱 <http://127.0.0.1:8000/app/teacher/> · 학생 앱 <http://127.0.0.1:8000/app/student/>
- 시연 순서: DEV 띠의 **seed**(학원 · 반 · 학생) → 강사 앱에서 시험지 만들기(자동 담기) → 열기
  → 시험 화면의 **DEV · 가짜 응답 채우기** 또는 DEV 띠에서 학생으로 바꿔 직접 풀기 → 닫기 → 결과 표 · 학생별 진단
- 배포할 때는 `.env` 에 `PL_DEV` 를 넣지 않는다 (없으면 개발자 라우터가 아예 붙지 않는다)

명령

| 명령 | 내용 |
|---|---|
| `uv run pl-demo-seed` | 데모 데이터 다시 만들기 |
| `uv run pl-diagnosis` | 가상 학생 하나로 진단 엔진 확인 |
| `uv run pl-accounts …` | 계정 · 학원 · 반 운영 명령 |
| `uv run pytest` | 자동 테스트 |

## 기술

Python 3.12 · FastAPI · SQLite(용도별 파일 분리, 외래키 · CHECK 제약) · numpy · Pillow ·
React · Vite · TypeScript(npm workspaces: `shared` + 앱 둘) · pytest
