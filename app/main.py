"""FastAPI エントリポイント。Google SSO + 簡易 RAG + Claude 呼び出し。"""
from __future__ import annotations

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import audit
from .auth import is_email_allowed, oauth, require_user
from .config import settings
from .ingest import analyze as ingest_analyze, ingest as ingest_commit
from .llm import answer
from .masking import mask
from .rag import get_index, reload_index

app = FastAPI(title="Servicenet Internal FAQ (PoC)")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    user = request.session.get("user")
    if not settings.demo_mode and (not user or not is_email_allowed(user.get("email", ""))):
        return HTMLResponse(_login_page(), status_code=200)
    user_email = (user or {}).get("email") or "demo@local"
    return HTMLResponse(_chat_page(user_email))


def _login_page() -> str:
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>{settings.product_name} - {settings.org_name}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     background:#f7f8fa;display:flex;align-items:center;justify-content:center;
     height:100vh;margin:0;color:#1f2937}}
.card{{background:#fff;padding:48px;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,.06);
     text-align:center;max-width:420px}}
h1{{margin:0 0 8px;font-size:28px;color:#111827}}
p{{color:#6b7280;margin:0 0 24px}}
.btn{{background:#1a73e8;color:#fff;padding:12px 24px;border-radius:8px;
     text-decoration:none;font-weight:500;display:inline-flex;gap:8px;align-items:center}}
.btn:hover{{background:#1557b0}}
.tag{{display:inline-block;background:#eef2ff;color:#4338ca;padding:4px 10px;
     border-radius:999px;font-size:12px;margin-bottom:16px}}
</style></head><body>
<div class="card">
  <div class="tag">社内専用</div>
  <h1>{settings.product_name}</h1>
  <p>{settings.org_name}の{settings.assistant_role}<br>
     社内ドキュメントから即座に回答します</p>
  <a class="btn" href="/auth/login">🔐 Googleでログイン</a>
</div></body></html>"""


def _chat_page(user_email: str) -> str:
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>{settings.product_name}</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     background:#f7f8fa;margin:0;color:#1f2937;height:100vh;display:flex;flex-direction:column}}
header{{background:#fff;border-bottom:1px solid #e5e7eb;padding:12px 24px;
       display:flex;justify-content:space-between;align-items:center}}
.logo{{font-size:20px;font-weight:700;color:#1a73e8}}
.logo small{{color:#6b7280;font-weight:400;font-size:13px;margin-left:6px}}
.user{{font-size:13px;color:#6b7280}}
.user a{{color:#1a73e8;text-decoration:none;margin-left:8px}}
main{{flex:1;display:flex;flex-direction:column;max-width:840px;margin:0 auto;width:100%;padding:0 16px}}
.chat{{flex:1;overflow-y:auto;padding:24px 0}}
.empty{{text-align:center;color:#9ca3af;margin-top:80px}}
.empty h2{{color:#374151;margin-bottom:12px}}
.suggestions{{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:24px}}
.chip{{background:#fff;border:1px solid #e5e7eb;padding:8px 16px;border-radius:999px;
      font-size:13px;cursor:pointer;color:#374151}}
.chip:hover{{background:#f3f4f6}}
.msg{{margin-bottom:24px}}
.msg.user .bubble{{background:#1a73e8;color:#fff;margin-left:auto}}
.msg.bot .bubble{{background:#fff;border:1px solid #e5e7eb}}
.bubble{{padding:14px 18px;border-radius:14px;max-width:78%;white-space:pre-wrap;
        line-height:1.6;display:inline-block}}
.msg.user{{text-align:right}}
.sources{{margin-top:10px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;
         padding:12px 16px;font-size:13px;max-width:78%}}
.sources summary{{cursor:pointer;color:#4b5563;font-weight:500}}
.src{{padding:8px 0;border-bottom:1px solid #f3f4f6}}
.src:last-child{{border-bottom:0}}
.src-name{{font-weight:600;color:#1f2937}}
.src-score{{color:#9ca3af;font-size:11px;margin-left:8px}}
.src-text{{color:#6b7280;font-size:12px;margin-top:4px;line-height:1.5;
          display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.feedback{{display:inline-flex;gap:6px;margin-top:8px}}
.feedback button{{background:transparent;border:1px solid #e5e7eb;padding:4px 10px;
                  border-radius:6px;cursor:pointer;font-size:12px}}
.feedback button:hover{{background:#f3f4f6}}
form#qa{{display:flex;gap:8px;padding:16px 0;border-top:1px solid #e5e7eb;background:#f7f8fa}}
input#q{{flex:1;border:1px solid #e5e7eb;border-radius:10px;padding:12px 16px;
        font-size:15px;font-family:inherit}}
input#q:focus{{outline:none;border-color:#1a73e8;box-shadow:0 0 0 3px rgba(26,115,232,.15)}}
button.send{{background:#1a73e8;color:#fff;border:0;border-radius:10px;
            padding:0 24px;font-size:15px;font-weight:500;cursor:pointer}}
button.send:hover{{background:#1557b0}}
button.send:disabled{{background:#9ca3af}}
.loading{{display:inline-block;width:14px;height:14px;border:2px solid #e5e7eb;
         border-top-color:#1a73e8;border-radius:50%;animation:spin 1s linear infinite;
         vertical-align:middle;margin-left:6px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<header>
  <div class="logo">{settings.product_name}<small>{settings.org_name}の{settings.assistant_role}</small></div>
  <div class="user">{user_email}<a href="/auth/logout">ログアウト</a></div>
</header>
<main>
  <div class="chat" id="chat">
    <div class="empty" id="empty">
      <h2>👋 どんなことでも聞いてください</h2>
      <p>社内ドキュメントを参照して、出典付きで回答します</p>
      <div class="suggestions">
        <div class="chip" data-q="出席登録の保存ボタンが効きません">出席登録の保存ボタンが効きません</div>
        <div class="chip" data-q="経費精算の締め日はいつですか">経費精算の締め日はいつですか</div>
        <div class="chip" data-q="VPNが繋がらない時の対処法">VPNが繋がらない時の対処法</div>
        <div class="chip" data-q="有給休暇の申請方法">有給休暇の申請方法</div>
      </div>
    </div>
  </div>
  <form id="qa">
    <input id="q" placeholder="質問を入力（例: 経費精算の領収書はいつまでに提出？）" autocomplete="off" required>
    <button class="send" type="submit">送信</button>
  </form>
</main>
<script>
const chat=document.getElementById('chat'),empty=document.getElementById('empty'),
      form=document.getElementById('qa'),input=document.getElementById('q'),
      btn=form.querySelector('button');
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{{input.value=c.dataset.q;form.requestSubmit()}});
function escape(s){{return s.replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c])}}
function addMsg(role,html){{
  if(empty)empty.remove();
  const d=document.createElement('div');d.className='msg '+role;
  d.innerHTML='<div class="bubble">'+html+'</div>';
  chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d;
}}
form.onsubmit=async e=>{{
  e.preventDefault();const q=input.value.trim();if(!q)return;
  input.value='';btn.disabled=true;
  addMsg('user',escape(q));
  const wait=addMsg('bot','回答を生成中<span class="loading"></span>');
  try{{
    const r=await fetch('/api/ask',{{method:'POST',headers:{{'Content-Type':'application/json'}},
                                     body:JSON.stringify({{question:q}})}});
    const data=await r.json();
    let html=escape(data.answer||'(回答なし)');
    if(data.sources&&data.sources.length){{
      html+='<details class="sources" open><summary>📎 参照ドキュメント '+data.sources.length+'件</summary>';
      for(const s of data.sources){{
        html+='<div class="src"><span class="src-name">'+escape(s.source)+'</span>'
              +'<span class="src-score">関連度 '+s.score.toFixed(2)+'</span></div>';
      }}
      html+='</details>';
    }}
    html+='<div class="feedback"><button>👍 役に立った</button><button>👎 改善が必要</button></div>';
    wait.querySelector('.bubble').innerHTML=html;
  }}catch(err){{wait.querySelector('.bubble').textContent='エラー: '+err.message}}
  btn.disabled=false;input.focus();
}};
</script></body></html>"""


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


@app.post("/api/admin/analyze")
async def admin_analyze(file: UploadFile = File(...), user: dict = Depends(require_user)):
    """ファイルをパース・スキャンしクレンジング結果を返す（DB書き込みなし）。"""
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="50MB を超えるファイルは未対応")
    try:
        result = ingest_analyze(file.filename or "uploaded", content, settings.masking_industry)
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e))
    audit.record(
        "analyze",
        user=user["email"],
        filename=result.filename,
        sha256=result.sha256[:12],
        recommendation=result.recommendation,
    )
    return {
        "filename": result.filename,
        "sha256": result.sha256,
        "size_bytes": result.size_bytes,
        "format": result.format,
        "n_chunks": result.n_chunks,
        "findings": {
            "pii_counts": result.findings.pii_counts,
            "confidential_markers": result.findings.confidential_markers,
            "name_candidates": result.findings.name_candidates,
        },
        "recommendation": result.recommendation,
        "reason": result.reason,
        "preview": [c.text[:200] for c in result.chunks[:3]],
    }


class IngestRequest(BaseModel):
    apply_masking: bool = True


@app.post("/api/admin/ingest")
async def admin_ingest(
    payload: IngestRequest = IngestRequest(),
    file: UploadFile = File(...),
    user: dict = Depends(require_user),
):
    """ファイルを取り込み FAQマスターに保存。マスキング適用後にインデックス更新。"""
    content = await file.read()
    try:
        result = ingest_analyze(file.filename or "uploaded", content, settings.masking_industry)
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e))
    if result.recommendation == "danger":
        raise HTTPException(
            status_code=400,
            detail=f"取り込み非推奨のため拒否: {result.reason}",
        )
    n = ingest_commit(
        result, settings.faq_master_dir,
        apply_masking=payload.apply_masking,
        industry=settings.masking_industry,
    )
    reload_index()
    audit.record(
        "ingest",
        user=user["email"],
        filename=result.filename,
        sha256=result.sha256[:12],
        n_chunks=n,
        masked=payload.apply_masking,
    )
    return {"ingested_chunks": n, "filename": result.filename, "recommendation": result.recommendation}


@app.get("/healthz")
async def healthz():
    return {"ok": True}
