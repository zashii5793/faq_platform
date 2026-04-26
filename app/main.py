"""FastAPI エントリポイント。Google SSO + 簡易 RAG + Claude 呼び出し。"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import audit
from .auth import is_email_allowed, oauth, require_user
from .config import settings
from .llm import answer
from .masking import mask
from .rag import get_index, reload_index

app = FastAPI(title="Servicenet Internal FAQ (PoC)")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    user = request.session.get("user")
    if not user or not is_email_allowed(user.get("email", "")):
        return HTMLResponse(
            '<a href="/auth/login">Googleでログイン</a>',
            status_code=200,
        )
    return HTMLResponse(
        f"""
        <h1>社内FAQ (PoC)</h1>
        <p>{user['email']} としてログイン中 - <a href="/auth/logout">ログアウト</a></p>
        <form id="qa">
          <input name="question" style="width: 80%" placeholder="質問を入力" required>
          <button type="submit">送信</button>
        </form>
        <pre id="out"></pre>
        <script>
          document.getElementById('qa').onsubmit = async (e) => {{
            e.preventDefault();
            const q = e.target.question.value;
            const r = await fetch('/api/ask', {{
              method: 'POST', headers: {{'Content-Type':'application/json'}},
              body: JSON.stringify({{question: q}})
            }});
            const data = await r.json();
            document.getElementById('out').textContent = JSON.stringify(data, null, 2);
          }};
        </script>
        """
    )


@app.get("/auth/login")
async def login(request: Request):
    return await oauth.google.authorize_redirect(request, settings.google_redirect_uri)


@app.get("/auth/callback")
async def callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user = token.get("userinfo") or {}
    email = user.get("email", "")
    if not is_email_allowed(email):
        audit.record("login_denied", user=email)
        raise HTTPException(status_code=403, detail=f"{email} は許可されていません")
    request.session["user"] = {"email": email, "name": user.get("name")}
    audit.record("login_success", user=email)
    return RedirectResponse(url="/")


@app.get("/auth/logout")
async def logout(request: Request):
    user = request.session.get("user", {})
    audit.record("logout", user=user.get("email"))
    request.session.clear()
    return RedirectResponse(url="/")


class AskRequest(BaseModel):
    question: str


class Source(BaseModel):
    chunk_id: str
    source: str
    score: float


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]


@app.post("/api/ask", response_model=AskResponse)
async def ask(payload: AskRequest, user: dict = Depends(require_user)) -> AskResponse:
    masked_q = mask(payload.question)
    chunks = get_index().search(masked_q, top_k=5)
    response_text = answer(masked_q, chunks)
    audit.record(
        "query",
        user=user["email"],
        question=masked_q,
        sources=[c.chunk_id for c, _ in chunks],
    )
    return AskResponse(
        answer=response_text,
        sources=[
            Source(chunk_id=c.chunk_id, source=c.source, score=s) for c, s in chunks
        ],
    )


@app.post("/api/admin/reload-index")
async def admin_reload(user: dict = Depends(require_user)):
    idx = reload_index()
    audit.record("reload_index", user=user["email"], n_chunks=len(idx.chunks))
    return {"chunks": len(idx.chunks)}


@app.get("/healthz")
async def healthz():
    return {"ok": True}
