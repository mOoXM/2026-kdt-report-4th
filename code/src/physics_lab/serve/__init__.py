"""serve — API 서버. 조각(라우터)을 따로 짓고 api.py 가 조립한다.

    api.py             FastAPI 앱 조립 + React 화면 서빙
    auth.py            /api/auth/…      로그인 · 세션 쿠키 · 권한 판단 (계정 DB)        공용
    student.py         /api/student/…   문항 · 제출 · 진단 · 연습 · 과제, /images        학생
    teacher.py         /api/teacher/…   반 · 명단 · 시험지 · 결과, /api/owner/…         강사 · 원장
    dev.py             /api/dev/…       개발자 모드 (PL_DEV=1 일 때만)                 개발

규칙: 라우터 파일은 도메인 모듈(accounts · responses · engine)을 부르고, 도메인은 HTTP 를 모른다.
"""
