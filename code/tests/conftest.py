from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_dev_mode(monkeypatch):
    """
    테스트는 .env 와 무관하게 돈다. .env 의 PL_DEV=1 이 auth.load_dotenv() 로 들어오면
    401 이어야 할 곳이 자동 로그인 200 이 된다. dev 를 검사하는 test_dev.py 는 자기 안에서 다시 켠다.
    """
    monkeypatch.delenv("PL_DEV", raising=False)
