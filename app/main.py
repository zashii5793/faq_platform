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
from .rag import get_index, record_feedback, reload_index

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
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>{settings.product_name}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif;
     background:#f7f8fa;color:#1f2937;height:100vh;display:flex;font-size:14px}}

aside{{width:280px;background:#fff;border-right:1px solid #e5e7eb;display:flex;flex-direction:column;
      flex-shrink:0;overflow-y:auto}}
.brand{{padding:18px;border-bottom:1px solid #e5e7eb}}
.brand h1{{color:#1a73e8;font-size:22px;font-weight:700}}
.brand p{{color:#6b7280;font-size:12px;margin-top:2px}}
.section{{padding:14px 18px;border-bottom:1px solid #f3f4f6}}
.section h3{{font-size:11px;color:#9ca3af;font-weight:600;letter-spacing:.05em;
            text-transform:uppercase;margin-bottom:8px;display:flex;align-items:center;gap:6px}}
.stat{{display:flex;justify-content:space-between;align-items:center;padding:4px 0;font-size:13px}}
.stat .label{{color:#6b7280}}
.stat .value{{color:#1f2937;font-weight:600}}
.stat .value.big{{font-size:20px;color:#1a73e8}}
.topic-item{{display:flex;justify-content:space-between;font-size:12px;padding:3px 0;color:#374151}}
.topic-item .count{{color:#9ca3af;font-size:11px}}
.history-item{{padding:6px 8px;margin:3px -8px;border-radius:6px;cursor:pointer;
              font-size:12px;color:#374151;line-height:1.4}}
.history-item:hover{{background:#f3f4f6}}
.cov-tags{{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}}
.tag{{background:#eef2ff;color:#4338ca;padding:2px 8px;border-radius:999px;font-size:11px}}
.upload-link{{margin-top:8px;display:block;border:2px dashed #cbd5e1;border-radius:8px;
        padding:10px;text-align:center;font-size:12px;color:#6b7280;text-decoration:none}}
.upload-link:hover{{border-color:#1a73e8;background:#eff6ff;color:#1a73e8}}
.fb-row{{display:flex;gap:6px;margin-bottom:6px}}
.fb-pill{{flex:1;background:#f9fafb;border-radius:8px;padding:6px;text-align:center;font-size:12px}}
.fb-pill.up{{color:#10b981}}
.fb-pill.down{{color:#dc2626}}
.fb-pill .num{{font-size:18px;font-weight:700;display:block}}
.fb-issues{{font-size:11px;color:#6b7280;margin-top:6px}}
.fb-issues li{{padding:3px 0;list-style:none}}
.fb-issues li:before{{content:"⚠ ";color:#f59e0b}}
.empty-list{{font-size:11px;color:#9ca3af;font-style:italic}}

main{{flex:1;display:flex;flex-direction:column;min-width:0}}
header{{background:#fff;border-bottom:1px solid #e5e7eb;padding:12px 24px;
       display:flex;justify-content:space-between;align-items:center}}
header .org{{font-size:14px;font-weight:600;color:#1f2937}}
.user{{font-size:13px;color:#6b7280}}
.user a{{color:#1a73e8;text-decoration:none;margin-left:8px}}
.chat{{flex:1;overflow-y:auto;padding:24px 32px;max-width:920px;width:100%;margin:0 auto}}
.empty{{text-align:center;color:#9ca3af;margin-top:60px}}
.empty h2{{color:#374151;margin-bottom:8px;font-size:22px}}
.empty p{{margin:6px 0}}
.suggestions{{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:20px;max-width:680px;margin-left:auto;margin-right:auto}}
.chip{{background:#fff;border:1px solid #e5e7eb;padding:8px 14px;border-radius:999px;
      font-size:13px;cursor:pointer;color:#374151}}
.chip:hover{{background:#1a73e8;color:#fff;border-color:#1a73e8}}
.chip .src-hint{{color:#9ca3af;font-size:10px;margin-left:6px}}
.chip:hover .src-hint{{color:#bfdbfe}}
.msg{{margin-bottom:20px}}
.msg.user{{text-align:right}}
.msg.user .bubble{{background:#1a73e8;color:#fff;margin-left:auto}}
.msg.bot .bubble{{background:#fff;border:1px solid #e5e7eb}}
.bubble{{padding:12px 16px;border-radius:14px;max-width:75%;display:inline-block;
        line-height:1.6;white-space:pre-wrap;text-align:left;word-break:break-word}}
.menu-btn{{display:none;background:none;border:0;padding:6px 10px;font-size:22px;cursor:pointer;color:#1f2937}}
.scrim{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:99}}
@media (max-width: 900px) {{
  aside{{position:fixed;left:0;top:0;bottom:0;width:280px;z-index:100;
        transform:translateX(-100%);transition:transform .25s}}
  aside.open{{transform:translateX(0)}}
  .scrim.show{{display:block}}
  .menu-btn{{display:inline-flex}}
  header .org{{font-size:13px;flex:1}}
  .bubble{{max-width:90%}}
  .sources,.confidence,.mask-info{{max-width:90%}}
  .chat{{padding:16px}}
  .suggestions{{flex-direction:column;gap:6px}}
  .chip{{font-size:12px;padding:8px 12px}}
}}
@media (max-width: 480px) {{
  header{{padding:10px 12px}}
  .user{{display:none}}
  input.q{{font-size:16px}} /* iOS の自動ズーム防止 */
}}
.confidence{{display:inline-flex;align-items:center;gap:6px;margin-top:6px;padding:4px 10px;
            border-radius:999px;font-size:11px;font-weight:600;max-width:75%}}
.confidence.high{{background:#d1fae5;color:#065f46}}
.confidence.mid{{background:#fef3c7;color:#92400e}}
.confidence.low{{background:#fed7aa;color:#9a3412}}
.confidence.none{{background:#fee2e2;color:#991b1b}}
.confidence-bar{{display:inline-block;width:60px;height:4px;background:rgba(0,0,0,.1);border-radius:2px;overflow:hidden}}
.confidence-bar > div{{height:100%;background:currentColor}}
.no-answer{{color:#991b1b;font-style:italic}}
.sources{{margin-top:8px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;
         padding:10px 14px;font-size:12px;max-width:75%}}
.sources summary{{cursor:pointer;color:#4b5563;font-weight:500}}
.src{{padding:6px 0;border-bottom:1px solid #f3f4f6}}
.src:last-child{{border-bottom:0}}
.src-name{{font-weight:600;color:#1f2937}}
.src-score{{color:#9ca3af;font-size:10px;margin-left:6px}}
.feedback{{display:inline-flex;gap:6px;margin-top:6px}}
.feedback button{{background:transparent;border:1px solid #e5e7eb;padding:3px 10px;
                  border-radius:6px;font-size:11px;color:#4b5563;cursor:pointer}}
.feedback button:hover{{background:#f3f4f6}}
.feedback button.up.active{{background:#10b981;color:#fff;border-color:#10b981}}
.feedback button.down.active{{background:#dc2626;color:#fff;border-color:#dc2626}}
footer.input-area{{background:#fff;border-top:1px solid #e5e7eb;padding:12px 24px}}
.input-wrap{{display:flex;gap:8px;max-width:920px;margin:0 auto}}
input.q{{flex:1;border:1px solid #e5e7eb;border-radius:10px;padding:12px 16px;font-size:14px;font-family:inherit}}
input.q:focus{{outline:none;border-color:#1a73e8;box-shadow:0 0 0 3px rgba(26,115,232,.15)}}
button.send{{background:#1a73e8;color:#fff;border:0;border-radius:10px;padding:0 22px;font-weight:500;cursor:pointer}}
button.send:disabled{{background:#9ca3af}}
.loading{{display:inline-block;width:12px;height:12px;border:2px solid #e5e7eb;
         border-top-color:#1a73e8;border-radius:50%;animation:spin 1s linear infinite;
         vertical-align:middle;margin-left:6px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style></head><body>

<aside>
  <div class="brand">
    <h1>{settings.product_name}</h1>
    <p>{settings.org_name}</p>
  </div>

  <div class="section">
    <h3>📊 分析（直近）</h3>
    <div class="stat"><span class="label">質問数</span><span class="value big" id="stat-queries">-</span></div>
    <div class="stat"><span class="label">回答率</span><span class="value" id="stat-answerrate">-</span></div>
    <div class="stat"><span class="label">平均確信度</span><span class="value" id="stat-confidence">-</span></div>
    <div class="stat" style="margin-top:6px"><span class="label">トップトピック</span></div>
    <div id="top-topics"><div class="empty-list">読み込み中…</div></div>
  </div>

  <div class="section">
    <h3>🕐 問い合わせ履歴</h3>
    <div id="history"><div class="empty-list">読み込み中…</div></div>
  </div>

  <div class="section">
    <h3>📚 ナレッジ取り込み状況</h3>
    <div class="stat"><span class="label">取り込み済み文書</span><span class="value" id="stat-docs">-</span></div>
    <div class="stat"><span class="label">総チャンク数</span><span class="value" id="stat-chunks">-</span></div>
    <div style="margin-top:6px;font-size:11px;color:#6b7280">カバー領域</div>
    <div class="cov-tags" id="cov-tags"></div>
    <a class="upload-link" href="/admin/upload">📁 ファイルを追加</a>
  </div>

  <div class="section">
    <h3>💬 フィードバック</h3>
    <div class="fb-row">
      <div class="fb-pill up"><span class="num" id="fb-up">0</span>👍 役立った</div>
      <div class="fb-pill down"><span class="num" id="fb-down">0</span>👎 要改善</div>
    </div>
    <div class="fb-issues">
      <div style="font-size:11px;color:#9ca3af;margin-bottom:4px">改善要望のあった質問</div>
      <ul id="fb-issues"><li class="empty-list" style="list-style:none;padding-left:0">なし</li></ul>
    </div>
  </div>
</aside>

<main>
  <header>
    <button class="menu-btn" id="menuBtn" aria-label="メニューを開く">☰</button>
    <div class="org">{settings.org_name}の{settings.assistant_role}</div>
    <div class="user">{user_email}<a href="/auth/logout">ログアウト</a></div>
  </header>
  <div class="scrim" id="scrim"></div>

  <div class="chat" id="chat">
    <div class="empty" id="empty">
      <h2>👋 どんなことでも聞いてください</h2>
      <p>取り込み済み文書を参照して、出典付きで回答します</p>
      <div class="suggestions" id="suggestions"></div>
      <p style="margin-top:20px;font-size:11px;color:#9ca3af">
        💡 サジェストは取り込み済み文書から自動生成されます
      </p>
    </div>
  </div>

  <footer class="input-area">
    <div class="input-wrap">
      <form id="qa" style="display:flex;gap:8px;flex:1">
        <input class="q" id="q" placeholder="質問を入力（例: 経費精算の領収書はいつまでに提出？）" autocomplete="off" required>
        <button class="send" type="submit">送信</button>
      </form>
    </div>
  </footer>
</main>

<script>
const chat=document.getElementById('chat'),empty=document.getElementById('empty'),
      form=document.getElementById('qa'),input=document.getElementById('q'),
      sendBtn=form.querySelector('button.send'),
      suggestionsEl=document.getElementById('suggestions');

function escape(s){{return String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c])}}

function relTime(iso){{
  if(!iso)return '';
  const ms=Date.now()-new Date(iso).getTime();
  if(ms<60000)return Math.floor(ms/1000)+'秒前';
  if(ms<3600000)return Math.floor(ms/60000)+'分前';
  if(ms<86400000)return Math.floor(ms/3600000)+'時間前';
  return Math.floor(ms/86400000)+'日前';
}}

async function loadStats(){{
  try {{
    const r=await fetch('/api/admin/stats');
    if(!r.ok) return;
    const s=await r.json();
    document.getElementById('stat-queries').textContent=s.analytics.n_queries_today;
    document.getElementById('stat-answerrate').textContent=s.analytics.answer_rate+'%';
    document.getElementById('stat-confidence').textContent=s.analytics.avg_confidence+'%';
    document.getElementById('stat-docs').textContent=s.knowledge.n_documents;
    document.getElementById('stat-chunks').textContent=s.knowledge.n_chunks;
    const topics=document.getElementById('top-topics');
    topics.innerHTML=s.analytics.top_topics.length
      ? s.analytics.top_topics.map(([n,c])=>`<div class="topic-item"><span>${{escape(n.replace('.md',''))}}</span><span class="count">${{c}}件</span></div>`).join('')
      : '<div class="empty-list">まだ質問がありません</div>';
    const hist=document.getElementById('history');
    hist.innerHTML=s.history.length
      ? s.history.map(h=>`<div class="history-item" data-q="${{escape(h.question)}}"><div>${{escape(h.question.slice(0,40))}}${{h.question.length>40?'…':''}}</div><div style="color:#9ca3af;font-size:10px">${{relTime(h.ts)}}</div></div>`).join('')
      : '<div class="empty-list">まだ履歴がありません</div>';
    hist.querySelectorAll('.history-item').forEach(el=>el.onclick=()=>{{input.value=el.dataset.q;form.requestSubmit();}});
    const tags=document.getElementById('cov-tags');
    tags.innerHTML=s.knowledge.documents.slice(0,8).map(d=>`<span class="tag">${{escape(d.replace('.md',''))}}</span>`).join('') || '<span class="empty-list">なし</span>';
    document.getElementById('fb-up').textContent=s.feedback.up;
    document.getElementById('fb-down').textContent=s.feedback.down;
    const issues=document.getElementById('fb-issues');
    issues.innerHTML=s.feedback.down_questions.length
      ? s.feedback.down_questions.map(q=>`<li>${{escape(q.slice(0,40))}}${{q.length>40?'…':''}}</li>`).join('')
      : '<li class="empty-list" style="list-style:none;padding-left:0">なし</li>';
    // サジェストを文書から動的生成
    if(suggestionsEl && s.knowledge.documents.length){{
      const templates=['{{}}について教えて','{{}}の使い方は？','{{}}の手順を知りたい','{{}}でトラブルが起きた時'];
      suggestionsEl.innerHTML=s.knowledge.documents.slice(0,6).map((d,i)=>{{
        const topic=d.replace('.md','');
        const tpl=templates[i%templates.length];
        const q=tpl.replace('{{}}',topic);
        return `<div class="chip" data-q="${{escape(q)}}">${{escape(q)}} <span class="src-hint">${{escape(d)}}</span></div>`;
      }}).join('');
      suggestionsEl.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{{input.value=c.dataset.q;form.requestSubmit();}});
    }}
  }} catch(e) {{ console.error('stats error', e); }}
}}

function addMsg(role,html){{
  if(empty && empty.parentNode) empty.remove();
  const d=document.createElement('div');d.className='msg '+role;
  d.innerHTML='<div class="bubble">'+html+'</div>';
  chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d;
}}

form.onsubmit=async e=>{{
  e.preventDefault();const q=input.value.trim();if(!q)return;
  input.value='';sendBtn.disabled=true;
  addMsg('user',escape(q));
  const wait=addMsg('bot','回答を生成中<span class="loading"></span>');
  try{{
    const r=await fetch('/api/ask',{{method:'POST',headers:{{'Content-Type':'application/json'}},
                                     body:JSON.stringify({{question:q}})}});
    const data=await r.json();
    const conf = data.confidence || 0;
    let confCls='none', confLabel='回答不可';
    if(conf >= 80) {{ confCls='high'; confLabel='高い'; }}
    else if(conf >= 50) {{ confCls='mid'; confLabel='中程度'; }}
    else if(conf >= 20) {{ confCls='low'; confLabel='低い（要確認）'; }}
    let html='';
    if(!data.has_answer) {{
      html+='<div class="no-answer">'+escape(data.answer)+'</div>';
    }} else {{
      html+=escape(data.answer);
    }}
    html+='<div><span class="confidence '+confCls+'">'
          +'確信度 '+conf+'% · '+confLabel
          +'<span class="confidence-bar"><div style="width:'+conf+'%"></div></span></span></div>';
    if(data.sources && data.sources.length){{
      html+='<details class="sources" open><summary>📎 参照ドキュメント '+data.sources.length+'件</summary>';
      for(const s of data.sources){{
        html+='<div class="src"><span class="src-name">'+escape(s.source)+'</span>'
              +'<span class="src-score">関連度 '+s.score.toFixed(2)+'</span></div>';
      }}
      html+='</details>';
    }}
    const fbId='fb-'+Date.now();
    html+=`<div class="feedback" id="${{fbId}}"><button data-vote="up">👍 役に立った</button><button data-vote="down">👎 改善が必要</button></div>`;
    wait.querySelector('.bubble').innerHTML=html;
    const fb=document.getElementById(fbId);
    if(fb){{
      fb.querySelectorAll('button').forEach(b=>b.onclick=async()=>{{
        const vote=b.dataset.vote;
        fb.querySelectorAll('button').forEach(x=>x.classList.remove('up','down','active'));
        b.classList.add(vote,'active');
        await fetch('/api/feedback',{{method:'POST',headers:{{'Content-Type':'application/json'}},
                                     body:JSON.stringify({{question:q,vote,sources:(data.sources||[]).map(s=>s.source)}})}});
        loadStats();
      }});
    }}
    loadStats();
  }}catch(err){{wait.querySelector('.bubble').textContent='エラー: '+err.message}}
  sendBtn.disabled=false;input.focus();
}};

loadStats();
setInterval(loadStats, 30000);

// モバイル: ハンバーガーメニュー
const aside=document.querySelector('aside'),scrim=document.getElementById('scrim'),menuBtn=document.getElementById('menuBtn');
if(menuBtn) {{
  menuBtn.onclick=()=>{{ aside.classList.add('open'); scrim.classList.add('show'); }};
  scrim.onclick=()=>{{ aside.classList.remove('open'); scrim.classList.remove('show'); }};
}}
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
    confidence: int  # 0-100
    has_answer: bool


def _compute_confidence(scored_chunks: list[tuple]) -> int:
    """top-score とサポート件数から確信度（0-100）を算出。

    判定ロジック:
      - top-1 < min_score_threshold → 0 (NO ANSWER)
      - top-1 が中程度 (< 0.18) かつ top-2/top-1 比率が小さい (< 0.3) → 0
        ＝ 1位だけ突出した単発ノイズマッチを排除
      - それ以外は base = 30 + top × 250 (cap 95) + 関連件数ボーナス
    """
    if not scored_chunks:
        return 0
    top = scored_chunks[0][1]
    if top < settings.min_score_threshold:
        return 0
    # 突出ノイズ判定: 上位スコアが弱め＋差が大きい場合
    if top < 0.18 and len(scored_chunks) >= 2:
        second = scored_chunks[1][1]
        if second / top < 0.3:
            return 0
    base = min(95, int(30 + top * 250))
    relevant = sum(1 for _, s in scored_chunks if s >= settings.min_score_threshold)
    return min(98, base + max(0, relevant - 1) * 3)


NO_ANSWER_TEXT = (
    "該当情報が見つかりませんでした。\n"
    "取り込み済みドキュメントから関連内容を発見できませんでした。\n"
    "別の表現で再度質問するか、社内ヘルプデスクに直接お問い合わせください。"
)


@app.post("/api/ask", response_model=AskResponse)
async def ask(payload: AskRequest, user: dict = Depends(require_user)) -> AskResponse:
    masked_q = mask(payload.question)
    chunks = get_index().search(masked_q, top_k=5)
    confidence = _compute_confidence(chunks)

    # 閾値未満なら LLM を呼ばずに「該当情報なし」を返す（ハルシネーション抑制）
    if confidence == 0:
        audit.record(
            "query",
            user=user["email"],
            question=masked_q,
            sources=[],
            confidence=0,
            answered=False,
        )
        return AskResponse(
            answer=NO_ANSWER_TEXT,
            sources=[],
            confidence=0,
            has_answer=False,
        )

    response_text = answer(masked_q, chunks)
    audit.record(
        "query",
        user=user["email"],
        question=masked_q,
        sources=[c.chunk_id for c, _ in chunks],
        confidence=confidence,
        answered=True,
    )
    return AskResponse(
        answer=response_text,
        sources=[
            Source(chunk_id=c.chunk_id, source=c.source, score=s) for c, s in chunks
        ],
        confidence=confidence,
        has_answer=True,
    )


@app.get("/admin/upload", response_class=HTMLResponse)
async def admin_upload_page(request: Request) -> HTMLResponse:
    """ナレッジ取り込み画面。`/api/admin/analyze` と `/api/admin/ingest` を叩く。"""
    if not settings.demo_mode:
        user = request.session.get("user")
        if not user or not is_email_allowed(user.get("email", "")):
            return HTMLResponse('<a href="/auth/login">Googleでログイン</a>', status_code=200)
    return HTMLResponse(_upload_page())


def _upload_page() -> str:
    return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ナレッジ追加 — Inquira</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif;
     background:#f7f8fa;color:#1f2937;min-height:100vh;padding:32px;font-size:14px}
.modal{background:#fff;max-width:920px;margin:0 auto;border-radius:14px;overflow:hidden;
       box-shadow:0 4px 24px rgba(0,0,0,.08)}
.modal-header{padding:18px 24px;border-bottom:1px solid #e5e7eb;display:flex;
              justify-content:space-between;align-items:center;background:#fafbfc}
.modal-header h2{font-size:18px;color:#111827}
.modal-header h2 span{color:#1a73e8}
.modal-body{padding:24px}
.step-title{font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:.05em;
            font-weight:600;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.step-num{background:#1a73e8;color:#fff;width:22px;height:22px;border-radius:50%;
          display:inline-flex;align-items:center;justify-content:center;font-size:12px}
.upload-zone{display:block;border:2px dashed #93c5fd;background:#eff6ff;border-radius:12px;
             padding:36px;text-align:center;cursor:pointer;transition:all .15s}
.upload-zone:hover,.upload-zone.dragover{background:#dbeafe;border-color:#1a73e8}
.upload-zone .icon{font-size:36px;margin-bottom:8px}
.upload-zone .main{font-size:15px;color:#1e3a8a;font-weight:500}
.upload-zone .sub{font-size:12px;color:#6b7280;margin-top:6px}
.formats{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin-top:14px}
.fmt{background:#fff;border:1px solid #e5e7eb;border-radius:6px;padding:3px 9px;font-size:11px;color:#374151;font-weight:500}
input[type=file]{display:none}
.file-card{border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:12px}
.file-card.ok{border-left:4px solid #10b981}
.file-card.warn{border-left:4px solid #f59e0b}
.file-card.danger{border-left:4px solid #dc2626;background:#fef2f2}
.fc-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px}
.fc-title{display:flex;align-items:center;gap:10px}
.fc-icon{font-size:24px}
.fc-name{font-weight:600;color:#111827}
.fc-meta{font-size:11px;color:#9ca3af;margin-top:2px}
.fc-badge{padding:4px 10px;border-radius:999px;font-size:11px;font-weight:600;flex-shrink:0}
.fc-badge.ok{background:#d1fae5;color:#065f46}
.fc-badge.warn{background:#fef3c7;color:#92400e}
.fc-badge.danger{background:#fee2e2;color:#991b1b}
.fc-grid{display:grid;grid-template-columns:120px 1fr;gap:6px 14px;font-size:13px;line-height:1.5;margin-bottom:10px}
.fc-grid dt{color:#6b7280}
.fc-grid dd{color:#1f2937}
.concern{display:flex;align-items:flex-start;gap:6px;margin:3px 0}
.concern.warn{color:#92400e}
.concern.danger{color:#991b1b;font-weight:500}
.fc-actions{display:flex;gap:6px;margin-top:8px}
.fc-actions button{padding:6px 12px;border:1px solid #e5e7eb;border-radius:6px;background:#fff;
                   font-size:12px;cursor:pointer;color:#374151}
.fc-actions button:hover{background:#f3f4f6}
.fc-actions button.primary{background:#1a73e8;color:#fff;border-color:#1a73e8}
.fc-actions button.primary:disabled{background:#9ca3af;cursor:not-allowed}
.fc-actions button.ingested{background:#10b981;color:#fff;border-color:#10b981;cursor:default}
.fc-actions button.skipped{background:#6b7280;color:#fff;border-color:#6b7280}
.fc-status{font-size:11px;color:#9ca3af;margin-left:auto;align-self:center}
.file-card.included{box-shadow:0 0 0 1px #1a73e8 inset}
.file-card.skipped-state{opacity:.55}
.chunk-list{margin-top:10px;border-top:1px dashed #e5e7eb;padding-top:10px}
.chunk-list summary{cursor:pointer;color:#4b5563;font-weight:500;font-size:12px;outline:none;padding:4px 0}
.chunk-list summary:hover{color:#1a73e8}
.chunk-row{display:flex;gap:10px;padding:8px;border-radius:8px;margin:4px 0;align-items:flex-start;
           background:#f9fafb;border:1px solid #f3f4f6}
.chunk-row.excluded{opacity:.45;background:#f3f4f6}
.chunk-row.danger{background:#fef2f2;border-color:#fecaca}
.chunk-row.warn{background:#fffbeb;border-color:#fed7aa}
.chunk-row input[type=checkbox]{margin-top:3px;flex-shrink:0;cursor:pointer}
.chunk-info{flex:1;min-width:0}
.chunk-id{font-family:'SF Mono',Consolas,monospace;font-size:10px;color:#9ca3af;display:block}
.chunk-flag{display:inline-block;font-size:10px;padding:1px 6px;border-radius:999px;margin-right:4px;font-weight:600}
.chunk-flag.ok{background:#d1fae5;color:#065f46}
.chunk-flag.warn{background:#fef3c7;color:#92400e}
.chunk-flag.danger{background:#fee2e2;color:#991b1b}
.chunk-text{font-size:11px;color:#374151;line-height:1.4;margin-top:3px;
            display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.chunk-reason{font-size:10px;color:#92400e;margin-top:2px}
.bulk-ops{display:flex;gap:6px;margin:6px 0;font-size:11px}
.bulk-ops button{padding:3px 8px;border:1px solid #d1d5db;background:#fff;border-radius:4px;cursor:pointer;color:#4b5563}
.bulk-ops button:hover{background:#f3f4f6}
.modal-footer{padding:14px 24px;border-top:1px solid #e5e7eb;background:#fafbfc;
              display:flex;justify-content:space-between;align-items:center;gap:14px}
.summary{font-size:13px;color:#6b7280}
.summary b{color:#111827}
button.confirm{background:#1a73e8;color:#fff;border:0;border-radius:8px;padding:10px 22px;
               font-weight:500;cursor:pointer;font-size:14px}
button.confirm:hover{background:#1557b0}
button.confirm:disabled{background:#9ca3af;cursor:not-allowed}
@media (max-width: 720px) {
  body{padding:0}
  .modal{border-radius:0;max-width:100%;min-height:100vh;box-shadow:none}
  .modal-body{padding:16px}
  .fc-grid{grid-template-columns:1fr;gap:4px}
  .fc-grid dt{color:#9ca3af;font-size:11px;text-transform:uppercase;margin-top:6px}
  .fc-actions{flex-wrap:wrap}
  .upload-zone{padding:24px 16px}
  .modal-footer{flex-direction:column;align-items:stretch;gap:10px}
  .modal-footer button.confirm{width:100%}
}
.modal-footer{padding:16px 24px;border-top:1px solid #e5e7eb;background:#fafbfc;
              display:flex;justify-content:space-between;align-items:center}
.summary{font-size:13px;color:#6b7280}
.summary b{color:#111827}
.empty-msg{text-align:center;color:#9ca3af;padding:24px;font-size:13px}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid #e5e7eb;
         border-top-color:#1a73e8;border-radius:50%;animation:spin 1s linear infinite;
         vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
.error-msg{color:#991b1b;font-size:12px;margin-top:6px}
</style></head><body>
<div class="modal">
  <div class="modal-header">
    <h2>📚 ナレッジ追加 <span>— Inquira</span></h2>
    <a href="/" style="color:#6b7280;text-decoration:none;font-size:13px">← チャットに戻る</a>
  </div>
  <div class="modal-body">
    <div class="step-title"><span class="step-num">1</span>ファイルを投入</div>
    <label class="upload-zone" id="dropzone">
      <div class="icon">📁</div>
      <div class="main">ドラッグ＆ドロップ または クリックして選択</div>
      <div class="sub">パース・PII検出・推奨判定を自動実行します</div>
      <div class="formats">
        <span class="fmt">PDF</span>
        <span class="fmt">Excel</span>
        <span class="fmt">PowerPoint</span>
        <span class="fmt">CSV</span>
        <span class="fmt">Markdown</span>
        <span class="fmt">テキスト</span>
        <span class="fmt">JSON</span>
      </div>
      <input type="file" id="fileInput" multiple accept=".md,.txt,.csv,.json,.pdf,.xlsx,.xls,.pptx,.ppt">
    </label>

    <div class="step-title" style="margin-top:28px"><span class="step-num">2</span>クレンジング結果</div>
    <div id="results">
      <div class="empty-msg">ファイルをドロップすると、ここに解析結果が表示されます</div>
    </div>
  </div>
  <div class="modal-footer">
    <div class="summary" id="summary">未取り込み</div>
    <button class="confirm" id="confirmBtn" disabled>選択を確定して取り込む (0件)</button>
  </div>
</div>

<script>
const dz = document.getElementById('dropzone');
const fi = document.getElementById('fileInput');
const results = document.getElementById('results');
const summary = document.getElementById('summary');
const confirmBtn = document.getElementById('confirmBtn');

// 解析済みファイルのキュー: {id, file, analysis, state: 'included'|'skipped'|'ingested'|'danger'}
const queue = [];
let nextId = 0;

function escape(s){return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function fmtBytes(b){if(b<1024)return b+'B';if(b<1024*1024)return (b/1024).toFixed(1)+'KB';return (b/1024/1024).toFixed(1)+'MB'}
function badge(rec){return {ok:'✅ 取り込み可',warn:'⚠ 確認必要',danger:'🔴 取り込み非推奨'}[rec]||rec}
function iconFor(format){return {markdown:'📝',text:'📝',csv:'📊',json:'📋',pdf:'📄',xlsx:'📊',pptx:'📰'}[format]||'📄'}

function updateSummary(){
  const inc = queue.filter(q => q.state === 'included').length;
  const ingested = queue.filter(q => q.state === 'ingested').length;
  const skipped = queue.filter(q => q.state === 'skipped').length;
  const danger = queue.filter(q => q.state === 'danger').length;
  // チャンク単位の総数
  let totalChunks = 0, includedChunks = 0;
  for(const q of queue){
    if(q.state !== 'included') continue;
    const chs = q.analysis.chunks || [];
    totalChunks += chs.length;
    includedChunks += chs.filter(c => !q.excluded?.has(c.chunk_id)).length;
  }
  summary.innerHTML = `<b>${queue.length}件解析</b> · 取り込み対象 <b style="color:#1a73e8">${inc}件</b>` +
    (totalChunks ? ` (チャンク <b>${includedChunks}/${totalChunks}</b>)` : '') +
    (ingested ? ` · 取り込み済み ${ingested}件` : '') +
    (skipped ? ` · スキップ ${skipped}件` : '') +
    (danger ? ` · <span style="color:#dc2626">危険判定 ${danger}件</span>` : '');
  confirmBtn.disabled = inc === 0 || includedChunks === 0;
  confirmBtn.textContent = `選択を確定して取り込む (${includedChunks}チャンク)`;
}

function renderConcerns(f){
  const cs = [];
  const rec = f.recommendation;
  const cls = rec === 'danger' ? 'danger' : 'warn';
  if(f.findings.pii_counts && Object.keys(f.findings.pii_counts).length){
    const list = Object.entries(f.findings.pii_counts).map(([k,v]) => `${k}${v}件`).join(', ');
    cs.push(`<div class="concern ${cls}">${rec==='danger'?'🔴':'⚠'} PII検出: ${escape(list)}</div>`);
  }
  if(f.findings.confidential_markers && f.findings.confidential_markers.length){
    cs.push(`<div class="concern warn">⚠ 機密マーカー: ${escape(f.findings.confidential_markers.join(', '))}</div>`);
  }
  if(f.findings.name_candidates >= 5){
    cs.push(`<div class="concern ${cls}">⚠ 個人氏名候補 ${f.findings.name_candidates}件</div>`);
  }
  return cs.length ? cs.join('') : '<span style="color:#9ca3af">懸念事項なし</span>';
}

function renderCard(item){
  const {analysis} = item;
  const card = document.createElement('div');
  item.card = card;

  // チャンク単位の除外を初期化: danger チャンクは自動除外
  if(!item.excluded){
    item.excluded = new Set();
    for(const c of (analysis.chunks||[])){
      if(c.recommendation === 'danger') item.excluded.add(c.chunk_id);
    }
  }
  const flagBadge = (rec) => {
    if(rec === 'ok') return `<span class="chunk-flag ok">✓ OK</span>`;
    if(rec === 'warn') return `<span class="chunk-flag warn">⚠ 要確認</span>`;
    if(rec === 'danger') return `<span class="chunk-flag danger">✕ 危険</span>`;
    return '';
  };
  const dangerChunks = (analysis.chunks||[]).filter(c => c.recommendation === 'danger').length;
  const warnChunks = (analysis.chunks||[]).filter(c => c.recommendation === 'warn').length;

  card.innerHTML = `
    <div class="fc-header">
      <div class="fc-title">
        <span class="fc-icon">${iconFor(analysis.format)}</span>
        <div>
          <div class="fc-name">${escape(analysis.filename)}</div>
          <div class="fc-meta">${fmtBytes(analysis.size_bytes)} · ${analysis.format} · ${analysis.n_chunks}チャンク · SHA-256 ${analysis.sha256.slice(0,8)}</div>
        </div>
      </div>
      <span class="fc-badge ${analysis.recommendation}">${badge(analysis.recommendation)}</span>
    </div>
    <dl class="fc-grid">
      <dt>判定理由</dt><dd>${escape(analysis.reason)}</dd>
      <dt>検出された懸念</dt><dd>${renderConcerns(analysis)}</dd>
      <dt>チャンク内訳</dt><dd>OK ${analysis.n_chunks - warnChunks - dangerChunks} / 要確認 ${warnChunks} / 危険 ${dangerChunks}</dd>
    </dl>
    <details class="chunk-list">
      <summary>📋 チャンク単位で確認・選択（${analysis.n_chunks}件）</summary>
      <div class="bulk-ops">
        <button data-op="all">全て取り込む</button>
        <button data-op="exclude-warn">要確認チャンクを除外</button>
        <button data-op="exclude-danger">危険チャンクのみ除外</button>
        <button data-op="none">全てスキップ</button>
      </div>
      <div class="chunks-container"></div>
    </details>
    <div class="fc-actions"></div>
  `;

  // チャンク行
  const container = card.querySelector('.chunks-container');
  for(const c of (analysis.chunks||[])){
    const row = document.createElement('label');
    row.className = 'chunk-row ' + c.recommendation;
    if(item.excluded.has(c.chunk_id)) row.classList.add('excluded');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = !item.excluded.has(c.chunk_id);
    cb.onchange = () => {
      if(cb.checked) item.excluded.delete(c.chunk_id);
      else item.excluded.add(c.chunk_id);
      row.classList.toggle('excluded', !cb.checked);
      updateSummary();
    };
    row.appendChild(cb);
    const info = document.createElement('div');
    info.className = 'chunk-info';
    info.innerHTML = `
      <span class="chunk-id">${escape(c.chunk_id)}</span>
      ${flagBadge(c.recommendation)}
      <div class="chunk-text">${escape(c.preview)}…</div>
      ${c.reason && c.recommendation !== 'ok' ? `<div class="chunk-reason">⚠ ${escape(c.reason)}</div>` : ''}
    `;
    row.appendChild(info);
    container.appendChild(row);
  }

  // 一括操作
  card.querySelectorAll('.bulk-ops button').forEach(btn => {
    btn.onclick = (e) => {
      e.preventDefault();
      const op = btn.dataset.op;
      item.excluded.clear();
      for(const c of (analysis.chunks||[])){
        if(op === 'none') item.excluded.add(c.chunk_id);
        else if(op === 'exclude-warn' && (c.recommendation === 'warn' || c.recommendation === 'danger')) item.excluded.add(c.chunk_id);
        else if(op === 'exclude-danger' && c.recommendation === 'danger') item.excluded.add(c.chunk_id);
      }
      // 行のチェックボックス更新
      container.querySelectorAll('.chunk-row').forEach((row, i) => {
        const cid = analysis.chunks[i].chunk_id;
        const cb = row.querySelector('input[type=checkbox]');
        cb.checked = !item.excluded.has(cid);
        row.classList.toggle('excluded', !cb.checked);
      });
      updateSummary();
    };
  });

  const actions = card.querySelector('.fc-actions');
  applyState(item);
  const btnSkip = document.createElement('button');
  const updateSkipLabel = () => {
    btnSkip.textContent = item.state === 'skipped' ? '取り込み対象に戻す' : 'ファイル全体をスキップ';
  };
  updateSkipLabel();
  btnSkip.onclick = () => {
    item.state = item.state === 'included' ? 'skipped' : 'included';
    updateSkipLabel();
    applyState(item);
    updateSummary();
  };
  actions.appendChild(btnSkip);
  return card;
}

function applyState(item){
  const c = item.card;
  if(!c) return;
  c.className = 'file-card ' + item.analysis.recommendation;
  if(item.state === 'included') c.classList.add('included');
  else if(item.state === 'skipped') c.classList.add('skipped-state');
}

async function analyzeFile(file){
  // remove "empty" placeholder if present
  const empty = results.querySelector('.empty-msg');
  if(empty) empty.remove();

  // pending card
  const pending = document.createElement('div');
  pending.className = 'file-card';
  pending.innerHTML = `<div class="fc-header"><div class="fc-title"><span class="fc-icon">📄</span><div><div class="fc-name">${escape(file.name)}</div><div class="fc-meta">${fmtBytes(file.size)} · 解析中…</div></div></div><span class="spinner"></span></div>`;
  results.appendChild(pending);

  try {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/admin/analyze', {method:'POST', body:fd});
    if(!r.ok){
      const err = await r.json();
      pending.outerHTML = `<div class="file-card danger"><div class="fc-header"><div class="fc-title"><span class="fc-icon">❌</span><div><div class="fc-name">${escape(file.name)}</div><div class="fc-meta">解析エラー: ${escape(err.detail||r.statusText)}</div></div></div></div></div>`;
      return;
    }
    const analysis = await r.json();
    // ファイル全体が danger でも、安全なチャンクが残るなら included にする（チャンク除外で対応）
    const hasNonDanger = (analysis.chunks||[]).some(c => c.recommendation !== 'danger');
    const state = (analysis.recommendation === 'danger' && !hasNonDanger) ? 'danger' : 'included';
    const item = {id: ++nextId, file, analysis, state};
    queue.push(item);
    pending.replaceWith(renderCard(item));
    updateSummary();
  } catch(e) {
    pending.outerHTML = `<div class="file-card danger"><div class="fc-meta">通信エラー: ${escape(e.message)}</div></div>`;
  }
}

confirmBtn.onclick = async () => {
  const targets = queue.filter(q => q.state === 'included');
  if(!targets.length) return;
  confirmBtn.disabled = true;
  confirmBtn.innerHTML = '<span class="spinner"></span>取り込み中…';
  let success = 0, failed = 0, ingestedChunks = 0;
  for(const item of targets){
    item.card.classList.add('included');
    const includedChunks = (item.analysis.chunks||[]).filter(c => !item.excluded?.has(c.chunk_id));
    if(includedChunks.length === 0){
      item.state = 'skipped';
      continue;
    }
    const fd = new FormData();
    fd.append('file', item.file);
    const excludedIds = Array.from(item.excluded || []).join(',');
    const url = '/api/admin/ingest?excluded_chunk_ids=' + encodeURIComponent(excludedIds);
    try {
      const r = await fetch(url, {method:'POST', body:fd});
      if(!r.ok) throw new Error((await r.json()).detail || r.statusText);
      const d = await r.json();
      item.state = 'ingested';
      item.card.classList.remove('included');
      const excludedNote = d.excluded_chunks > 0 ? ` (${d.excluded_chunks}チャンク除外)` : '';
      item.card.querySelector('.fc-badge').textContent = `✓ 取り込み済み (${d.ingested_chunks}チャンク${excludedNote})`;
      item.card.querySelector('.fc-badge').className = 'fc-badge ok';
      item.card.querySelector('.fc-actions').innerHTML = '';
      success++;
      ingestedChunks += d.ingested_chunks;
    } catch(e) {
      const err = document.createElement('div');
      err.className = 'error-msg';
      err.textContent = '取り込み失敗: ' + e.message;
      item.card.appendChild(err);
      failed++;
    }
  }
  updateSummary();
  alert(`取り込み完了: ${success}件成功 (${ingestedChunks}チャンク) / ${failed}件失敗`);
};

fi.onchange = e => { for(const f of e.target.files) analyzeFile(f); fi.value=''; };
['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('dragover') }));
['dragleave','drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('dragover') }));
dz.addEventListener('drop', e => { for(const f of e.dataTransfer.files) analyzeFile(f); });
</script>
</body></html>"""


@app.get("/api/admin/stats")
async def admin_stats(user: dict = Depends(require_user)):
    """サイドバー集計用。ナレッジ状態・履歴・トップトピック・フィードバックを返す。"""
    from collections import Counter

    idx = get_index()
    recent = audit.read_recent(200)
    queries = [e for e in recent if e.get("event") == "query"]
    feedback = [e for e in recent if e.get("event") == "feedback"]

    history = [
        {"question": q.get("question", ""), "ts": q.get("ts", ""),
         "sources": q.get("sources", []), "confidence": q.get("confidence", 0)}
        for q in queries[:8]
    ]
    top_topics: Counter = Counter()
    for q in queries:
        srcs = q.get("sources") or []
        if srcs:
            top_topics[srcs[0].split("#")[0]] += 1

    confs = [q.get("confidence", 0) for q in queries if "confidence" in q]
    answered = sum(1 for q in queries if q.get("answered") is True)
    avg_confidence = round(sum(confs) / len(confs)) if confs else 0
    answer_rate = round(answered / len(queries) * 100) if queries else 0

    fb_up = sum(1 for f in feedback if f.get("vote") == "up")
    fb_down = sum(1 for f in feedback if f.get("vote") == "down")
    down_questions = [f.get("question", "") for f in feedback if f.get("vote") == "down"][:3]

    sources = sorted({c.source for c in idx.chunks})

    return {
        "knowledge": {
            "n_documents": len(sources),
            "n_chunks": len(idx.chunks),
            "documents": sources,
        },
        "analytics": {
            "n_queries_today": len(queries),
            "top_topics": top_topics.most_common(5),
            "avg_confidence": avg_confidence,
            "answer_rate": answer_rate,
        },
        "history": history,
        "feedback": {"up": fb_up, "down": fb_down, "down_questions": down_questions},
    }


class FeedbackRequest(BaseModel):
    question: str
    vote: str
    sources: list[str] = []


@app.post("/api/feedback")
async def api_feedback(payload: FeedbackRequest, user: dict = Depends(require_user)):
    if payload.vote not in ("up", "down"):
        raise HTTPException(status_code=400, detail="vote must be up/down")
    # 監査ログに記録
    audit.record("feedback", user=user["email"], question=payload.question,
                 vote=payload.vote, sources=payload.sources)
    # 検索ランキングへの学習反映
    record_feedback(payload.sources, payload.vote)
    return {"ok": True}


@app.post("/api/admin/reload-index")
async def admin_reload(user: dict = Depends(require_user)):
    idx = reload_index()
    audit.record("reload_index", user=user["email"], n_chunks=len(idx.chunks))
    return {"chunks": len(idx.chunks)}


@app.post("/api/admin/analyze")
async def admin_analyze(file: UploadFile = File(...), user: dict = Depends(require_user)):
    """ファイルをパース・スキャンしクレンジング結果を返す（DB書き込みなし）。

    レスポンスにはファイル全体の判定 + 各チャンクの個別判定を含む。
    UI 側はチャンク単位で「取り込む / スキップ」を選べる。
    """
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
    chunks_payload = []
    for c, cf in zip(result.chunks, result.chunk_findings):
        chunks_payload.append({
            "chunk_id": c.chunk_id,
            "text": c.text,
            "preview": c.text[:160],
            "recommendation": cf.recommendation,
            "reason": cf.reason,
            "findings": {
                "pii_counts": cf.pii_counts,
                "confidential_markers": cf.confidential_markers,
                "name_candidates": cf.name_candidates,
            },
        })
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
        "chunks": chunks_payload,
    }


@app.post("/api/admin/ingest")
async def admin_ingest(
    file: UploadFile = File(...),
    apply_masking: bool = True,
    excluded_chunk_ids: str = "",  # カンマ区切り
    force: bool = False,
    user: dict = Depends(require_user),
):
    """ファイルを取り込み FAQマスターに保存。

    Args:
      excluded_chunk_ids: カンマ区切りのチャンクID一覧。これらは取り込み対象から外す
      force: True なら danger 判定の文書でも除外チャンク後の残りを取り込む
    """
    content = await file.read()
    try:
        result = ingest_analyze(file.filename or "uploaded", content, settings.masking_industry)
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e))

    excluded = {x.strip() for x in excluded_chunk_ids.split(",") if x.strip()}

    # ファイル全体が danger でも、危険チャンクを除外すれば OK な場合は取り込み可
    if result.recommendation == "danger" and not force:
        # 危険チャンクが全て excluded に含まれているかチェック
        danger_chunks = {
            c.chunk_id for c, cf in zip(result.chunks, result.chunk_findings)
            if cf.recommendation == "danger"
        }
        if not danger_chunks.issubset(excluded):
            raise HTTPException(
                status_code=400,
                detail=f"取り込み非推奨のため拒否: {result.reason} "
                       f"（危険判定のチャンク {len(danger_chunks - excluded)} 件を除外して再試行してください）",
            )
    n = ingest_commit(
        result, settings.faq_master_dir,
        apply_masking=apply_masking,
        industry=settings.masking_industry,
        excluded_chunk_ids=excluded,
    )
    reload_index()
    audit.record(
        "ingest",
        user=user["email"],
        filename=result.filename,
        sha256=result.sha256[:12],
        n_chunks=n,
        excluded_count=len(excluded),
        masked=apply_masking,
    )
    return {
        "ingested_chunks": n,
        "excluded_chunks": len(excluded),
        "filename": result.filename,
        "recommendation": result.recommendation,
    }


@app.get("/healthz")
async def healthz():
    return {"ok": True}
