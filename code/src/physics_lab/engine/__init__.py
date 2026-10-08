"""engine — 진단 엔진. HTTP 를 모르는 도메인 모듈.

    interfaces.py        교체 가능한 부품의 약속 (진단 방식 · 문항 선택 방식)
    diagnosis.py         문항 DB + 연결표 → 세부 개념별 이해 수준 (기본 진단 엔진)
    exam_pick.py         시험지 자동 담기
    concept_display.py   개념 코드 → 학생 · 강사 화면 문구
"""
