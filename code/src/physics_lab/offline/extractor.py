"""
extractor.py — 문항 구조화 (사전 처리). 문항 이미지 → 지문 · 보기 · 선지 JSON

생성형 AI 는 "처음 데이터를 싸게 만드는 도구" 로만 쓴다. 문항마다 한 번 뽑아 캐시하고, 학생이 풀 때는 부르지 않는다.
제공자는 ExtractionProvider(engine/interfaces.py) 약속만 지키면 바꿔 끼울 수 있다. 공개본에는 실제 제공자 구현을 넣지 않았다.

    from physics_lab.offline.extractor import extract
    data = extract(Path("data/ph1/images/demo_01.png"), provider=MyProvider())

캐시 키 = 이미지 내용 해시 + 프롬프트·스키마 해시. 같은 요청을 다시 과금하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..db import BUILD, DEFAULT_SUBJECT
from ..engine.interfaces import ExtractionProvider

PROMPT = (
    "다음은 고등학교 물리학Ⅰ 시험 문항 이미지입니다. "
    "주어진 JSON 스키마에 맞춰 문제 글, 그림 설명, 보기(ㄱ·ㄴ·ㄷ)와 선지(①~⑤)를 그대로 옮기세요. "
    "이미지에 없는 내용은 만들지 마세요."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "stem": {"type": "string", "description": "문제 글"},
        "diagram": {"type": "string", "description": "그림 설명. 그림이 없으면 빈 문자열"},
        "statements": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"label": {"type": "string"}, "text": {"type": "string"}},
                      "required": ["label", "text"]},
        },
        "choices": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"no": {"type": "integer"}, "text": {"type": "string"}},
                      "required": ["no", "text"]},
        },
    },
    "required": ["stem", "statements", "choices"],
}


def fingerprint() -> str:
    """프롬프트 + 스키마 해시. 둘 중 하나라도 바뀌면 캐시가 갈린다."""
    blob = PROMPT + json.dumps(RESPONSE_SCHEMA, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def cache_dir(provider: ExtractionProvider, subject: str = DEFAULT_SUBJECT) -> Path:
    return BUILD / subject / "cache" / provider.name / fingerprint()


def extract(image: Path, provider: ExtractionProvider, subject: str = DEFAULT_SUBJECT) -> dict:
    """캐시에 있으면 그것을, 없으면 제공자를 불러 뽑고 저장한다."""
    key = hashlib.sha256(image.read_bytes()).hexdigest()[:16]
    path = cache_dir(provider, subject) / f"{key}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    data = provider.generate(PROMPT, image, RESPONSE_SCHEMA)
    missing = [f for f in RESPONSE_SCHEMA["required"] if f not in data]
    if missing:
        raise ValueError(f"응답에 필드가 없다: {missing}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data
