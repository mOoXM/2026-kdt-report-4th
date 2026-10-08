r"""
physics_lab — 문항 분해형 학습 진단 플랫폼

패키지 구조
-----------
    physics_lab/
        db.py           SQLite 를 여는 유일한 문. 경로도 여기서만 조립
        accounts.py     계정 DB — 사용자 · 학원 · 반 · 명단 · 세션
        responses.py    응답 DB — 응시 기록 · 보기별 응답 · 시험지 · 과제
        schema.py       문항 구조 (Pydantic)
        demo_seed.py    데모 데이터

        serve/          API 서버 (FastAPI). 사용자별 라우터, api.py 가 조립
        engine/         진단 엔진 — 세부 개념 진단 · 시험지 자동 담기 · 결과 문구
        concept/        세부 개념 체계와 문항-개념 연결표
        similar/        유사 문항 엔진 (그림 + 글 특징값)
        offline/        사전 처리 결과를 읽는 창구 — 생성형 AI 문항 구조화 · 문항 구역

실행은 `uv run pl-<이름>` (pyproject.toml 의 [project.scripts]).
"""

__version__ = "0.2.0"
