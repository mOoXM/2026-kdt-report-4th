r"""
api.py — 조립. FastAPI 앱 하나에 사용자별 라우터를 단다 + React 화면 서빙

실행 (프로젝트 루트에서):
    uv run pl-serve                  (= uvicorn physics_lab.serve.api:app --reload)
    → http://127.0.0.1:8000/app/student/   학생 앱
    → http://127.0.0.1:8000/app/teacher/   강사 앱

화면
----
    /app/{앱}/…     React 앱 (frontend/apps/{앱}/dist). student · teacher
    /               → /app/student/
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ..db import ROOT
from . import auth, dev, student, teacher

FRONT_APPS = ROOT / "frontend" / "apps"      # frontend/apps/{앱}/dist  (npm run build)
APPS = ("student", "teacher")

app = FastAPI(title="physics-lab 진단 API")

auth.install(app)                            # /api/auth/…  + AccountsError → HTTP 코드
student.install(app)                         # /api/student/… + /images
teacher.install(app)                         # /api/teacher/… + /api/owner/…
dev.install(app)                             # /api/dev/…  .env 에 PL_DEV=1 일 때만 붙는다 (개발자 모드)


@app.get("/app/{name}", response_class=HTMLResponse)
@app.get("/app/{name}/{path:path}", response_class=HTMLResponse)
def spa(name: str, path: str = ""):
    """
    frontend/apps/{name}/dist 를 /app/{name}/ 아래에서 서빙한다. 실제 파일(assets/…, manifest)은 그대로 주고,
    그 밖의 경로는 전부 index.html — 라우팅은 브라우저 쪽 react-router 가 한다.
    """
    if name not in APPS:
        return HTMLResponse(f"<h1>없는 앱: {name}</h1><p>{', '.join(APPS)}</p>", status_code=404)
    dist = FRONT_APPS / name / "dist"
    if path and (dist / path).is_file():
        return FileResponse(dist / path)
    index_html = dist / "index.html"
    if not index_html.is_file():
        return HTMLResponse(f"<h1>frontend/apps/{name}/dist 가 없다</h1>"
                            "<p>frontend 폴더에서 npm install &amp;&amp; npm run build</p>", status_code=404)
    return HTMLResponse(index_html.read_text(encoding="utf-8"))


@app.get("/")
def index():
    return RedirectResponse("/app/student/")


def main() -> None:
    """`uv run pl-serve` — uvicorn 을 --reload 로 띄운다."""
    import uvicorn
    uvicorn.run("physics_lab.serve.api:app", reload=True)
