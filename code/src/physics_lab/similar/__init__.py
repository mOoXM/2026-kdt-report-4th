"""similar — 유사 문항 엔진.

    index.py      특징값(build/ph1/embed/*.npy) 적재 + 코사인 최근접. 서버가 부른다 (numpy 뿐)
    evaluate.py   연결표에서 문항별 개념 라벨 읽기

특징값은 사전 처리에서 만든다 (그림: 이미지 특징 추출 모델, 글: 문장 특징 추출 모델).
공개본은 demo_seed.py 가 데모용 벡터를 넣는다.
"""
