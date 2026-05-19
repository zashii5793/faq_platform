"""FastAPI エントリポイント。Google SSO + 簡易 RAG + Claude 呼び出し。"""
from __future__ import annotations

from html import escape as _html_escape

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import audit, runtime_settings
from .auth import is_email_allowed, oauth, require_user
from .config import settings
from .ingest import analyze as ingest_analyze, ingest as ingest_commit
from .llm import answer
from .masking import mask
from .rag import get_index, record_feedback, reload_index


def _esc(s: str | None) -> str:
    """HTML エスケープ（XSS 防止）。組織名等のユーザー設定値を HTML に埋め込む前に必ず通す。"""
    return _html_escape(str(s or ""), quote=True)


app = FastAPI(title="Servicenet Internal FAQ (PoC)")

# 起動時に保存済みの組織情報オーバーライドを反映
runtime_settings.load_and_apply()
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    user = request.session.get("user")
    if not settings.demo_mode and (not user or not is_email_allowed(user.get("email", ""))):
        return HTMLResponse(_login_page(), status_code=200)
    user_email = (user or {}).get("email") or "demo@local"
    return HTMLResponse(_chat_page(user_email))


def _demo_banner_html() -> str:
    """DEMO_MODE 中、かつ APIキー未設定の場合の警告。"""
    if not settings.demo_mode:
        return ""
    if not settings.anthropic_api_key:
        return (
            '<div class="demo-banner">'
            '🚧 <b>デモモード</b>（APIキー未設定）— 回答は <b>ローカルモードのスタブ</b> です。'
            '実際の Claude 回答を見るには <code>.env</code> に '
            '<code>ANTHROPIC_API_KEY=sk-ant-...</code> を設定して再起動してください。'
            '</div>'
        )
    return (
        '<div class="demo-banner" style="background:#dbeafe;border-color:#93c5fd;color:#1e40af">'
        '🧪 <b>デモモード</b>（認証なし）— 本番運用前に <code>DEMO_MODE</code> を外してください。'
        '</div>'
    )


def _login_page() -> str:
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>{_esc(settings.product_name)} - {_esc(settings.org_name)}</title>
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
  <h1>{_esc(settings.product_name)}</h1>
  <p>{_esc(settings.org_name)}の{_esc(settings.assistant_role)}<br>
     社内ドキュメントから即座に回答します</p>
  <a class="btn" href="/auth/login">🔐 Googleでログイン</a>
</div></body></html>"""


def _chat_page(user_email: str) -> str:
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>{_esc(settings.product_name)}</title>
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
.demo-banner{{background:#fef3c7;color:#92400e;padding:8px 14px;font-size:12px;
              border-bottom:1px solid #fcd34d;text-align:center}}
.demo-banner b{{font-weight:600}}
.demo-banner a{{color:#1e40af;text-decoration:underline}}
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
.chip.popular{{background:#fef3c7;border-color:#fcd34d;color:#78350f}}
.chip.popular:hover{{background:#f59e0b;color:#fff;border-color:#f59e0b}}
.chip.popular .src-hint{{color:#92400e}}
.chip.popular:hover .src-hint{{color:#fff7ed}}
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
.reference-answer{{background:#fffbeb;border-left:3px solid #f59e0b;padding:10px 14px;
                   border-radius:8px;margin-bottom:4px;color:#78350f;font-size:13px;line-height:1.6}}
/* Markdown 回答の整形 */
.md-body{{line-height:1.7;font-size:14px;color:#1f2937}}
.md-body .md-h1{{font-size:16px;font-weight:600;color:#111827;margin:14px 0 8px;padding-bottom:5px;border-bottom:2px solid #e5e7eb}}
.md-body .md-h2{{font-size:15px;font-weight:600;color:#111827;margin:14px 0 6px;padding-left:8px;border-left:3px solid #1a73e8}}
.md-body .md-h3{{font-size:14px;font-weight:600;color:#1a73e8;margin:12px 0 4px}}
.md-body .md-h4{{font-size:13px;font-weight:600;color:#4b5563;margin:10px 0 2px}}
.md-body .md-hr{{border:none;border-top:1px dashed #e5e7eb;margin:12px 0}}
.md-body .md-ul{{margin:6px 0 6px 0;padding-left:22px}}
.md-body .md-ul li{{margin:3px 0;line-height:1.7}}
.md-body .md-br{{height:6px}}
.md-body .md-line{{margin:2px 0}}
.md-body strong{{font-weight:600;color:#111827}}
.md-body .md-code{{background:#f3f4f6;padding:1px 6px;border-radius:3px;font-size:12.5px;
                    font-family:Menlo,Consolas,monospace;color:#be123c}}
.md-body .md-pre{{background:#0f172a;color:#e2e8f0;padding:10px 14px;border-radius:6px;
                   margin:8px 0;overflow-x:auto;font-size:12.5px}}
.md-body .md-pre code{{background:transparent;color:inherit;padding:0;font-size:inherit}}
.faq-request{{margin-top:10px;padding:10px 14px;background:#eff6ff;border:1px solid #bfdbfe;
              border-radius:10px;max-width:75%}}
.faq-request-msg{{font-size:12px;color:#1e40af;margin-bottom:6px}}
.faq-request-btn{{background:#1a73e8;color:#fff;border:0;padding:6px 14px;border-radius:8px;
                  font-size:12px;cursor:pointer;font-weight:500}}
.faq-request-btn:hover{{background:#1557b0}}
.faq-request-btn:disabled{{opacity:.6;cursor:not-allowed}}
.faq-request-done{{font-size:12px;color:#065f46;background:#d1fae5;padding:8px 12px;border-radius:6px}}
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
    <h1>{_esc(settings.product_name)}</h1>
    <p>{_esc(settings.org_name)}</p>
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
    <div class="org">{_esc(settings.org_name)}の{_esc(settings.assistant_role)}</div>
    <div class="user">{user_email}<a href="/auth/logout">ログアウト</a></div>
  </header>
  {_demo_banner_html()}
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
    // サジェスト：人気質問（過去30日に2回以上聞かれたもの）を優先、
    // 不足分は文書から動的生成で補完
    if(suggestionsEl){{
      const pop=s.popular_queries||[];
      const docs=s.knowledge.documents||[];
      const chips=[];
      // 人気質問を優先（実際にユーザーが聞いている質問なのでヒット率高）
      for(const p of pop.slice(0,4)){{
        chips.push(`<div class="chip popular" data-q="${{escape(p.question)}}">🔥 ${{escape(p.question.slice(0,40))}}${{p.question.length>40?'…':''}} <span class="src-hint">${{p.count}}回</span></div>`);
      }}
      // 文書ベースで残り埋め
      const templates=['{{}}について教えて','{{}}の使い方は？','{{}}の手順を知りたい','{{}}でトラブルが起きた時'];
      const need=Math.max(0,6-chips.length);
      for(let i=0;i<need && i<docs.length;i++){{
        const topic=docs[i].replace('.md','');
        const tpl=templates[i%templates.length];
        const q=tpl.replace('{{}}',topic);
        chips.push(`<div class="chip" data-q="${{escape(q)}}">${{escape(q)}} <span class="src-hint">${{escape(docs[i])}}</span></div>`);
      }}
      suggestionsEl.innerHTML=chips.join('');
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

// 簡易 Markdown → HTML レンダラー（escape() 通過後に呼ぶ。安全）
function renderMarkdown(escapedText){{
  let lines = escapedText.split('\\n');
  let out = [];
  let inList = false;
  let inCode = false;
  for(let i=0;i<lines.length;i++){{
    let line = lines[i];
    // コードブロック ```
    if(/^```/.test(line.trim())){{
      if(inCode){{ out.push('</code></pre>'); inCode = false; }}
      else {{ out.push('<pre class="md-pre"><code>'); inCode = true; }}
      continue;
    }}
    if(inCode){{ out.push(line); continue; }}
    // 区切り線 ---
    if(/^---+\\s*$/.test(line.trim())){{
      if(inList){{ out.push('</ul>'); inList = false; }}
      out.push('<hr class="md-hr">');
      continue;
    }}
    // 見出し (### / ## / # を順に判定)
    let m;
    if((m = line.match(/^####\\s+(.+)$/))){{
      if(inList){{ out.push('</ul>'); inList = false; }}
      out.push('<div class="md-h4">'+inlineMd(m[1])+'</div>'); continue;
    }}
    if((m = line.match(/^###\\s+(.+)$/))){{
      if(inList){{ out.push('</ul>'); inList = false; }}
      out.push('<div class="md-h3">'+inlineMd(m[1])+'</div>'); continue;
    }}
    if((m = line.match(/^##\\s+(.+)$/))){{
      if(inList){{ out.push('</ul>'); inList = false; }}
      out.push('<div class="md-h2">'+inlineMd(m[1])+'</div>'); continue;
    }}
    if((m = line.match(/^#\\s+(.+)$/))){{
      if(inList){{ out.push('</ul>'); inList = false; }}
      out.push('<div class="md-h1">'+inlineMd(m[1])+'</div>'); continue;
    }}
    // リスト項目 - or *
    if((m = line.match(/^\\s*[-*]\\s+(.+)$/))){{
      if(!inList){{ out.push('<ul class="md-ul">'); inList = true; }}
      out.push('<li>'+inlineMd(m[1])+'</li>');
      continue;
    }}
    if(inList){{ out.push('</ul>'); inList = false; }}
    // 空行
    if(line.trim() === ''){{
      out.push('<div class="md-br"></div>');
      continue;
    }}
    // 通常行
    out.push('<div class="md-line">'+inlineMd(line)+'</div>');
  }}
  if(inList) out.push('</ul>');
  if(inCode) out.push('</code></pre>');
  return out.join('');
}}
function inlineMd(s){{
  // **bold** → <strong>
  s = s.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
  // `code` → <code>
  s = s.replace(/`([^`]+)`/g, '<code class="md-code">$1</code>');
  return s;
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
    }} else if(data.is_reference) {{
      html+='<div class="reference-answer">'+renderMarkdown(escape(data.answer))+'</div>';
    }} else {{
      html+='<div class="md-body">'+renderMarkdown(escape(data.answer))+'</div>';
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
    // FAQ追加リクエストボタン（has_answer=false または is_reference のとき表示）
    const reqId='req-'+Date.now();
    if(!data.has_answer || data.is_reference){{
      html+=`<div class="faq-request" id="${{reqId}}">`
        +`<div class="faq-request-msg">💡 この質問が公式FAQに登録されていません。管理者にFAQ追加をリクエストしますか？</div>`
        +`<button class="faq-request-btn" data-q="${{escape(q)}}">📩 FAQ追加をリクエスト</button>`
        +`</div>`;
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
    const reqBox=document.getElementById(reqId);
    if(reqBox){{
      const btn=reqBox.querySelector('.faq-request-btn');
      btn.onclick=async()=>{{
        btn.disabled=true; btn.textContent='送信中…';
        try{{
          const r=await fetch('/api/faq-requests',{{method:'POST',
            headers:{{'Content-Type':'application/json'}},
            body:JSON.stringify({{question:q,note:''}})}});
          if(!r.ok) throw new Error((await r.json()).detail||r.statusText);
          reqBox.innerHTML='<div class="faq-request-done">✅ 管理者にリクエストを送信しました。FAQに追加されるまでお待ちください。</div>';
        }}catch(e){{
          btn.disabled=false; btn.textContent='📩 FAQ追加をリクエスト';
          alert('送信失敗: '+e.message);
        }}
      }};
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
    is_reference: bool = False  # 公式FAQ未登録の参考情報として返したか


def _compute_confidence(scored_chunks: list[tuple]) -> int:
    """top-score とサポート件数から確信度（0-100）を算出。

    判定ロジック:
      - top-1 < min_score_threshold → 0 (NO ANSWER)
      - top-1 が低め (< 0.12) かつ top-2/top-1 比率が小さい (< 0.3) → 0
        ＝ ノイズマッチを排除（top1 が中以上ならノイズではなく正解1件ヒットと判断）
      - それ以外は base = 30 + top × 250 (cap 95) + 関連件数ボーナス
    """
    if not scored_chunks:
        return 0
    top = scored_chunks[0][1]
    if top < settings.min_score_threshold:
        return 0
    # 突出ノイズ判定: top1 が弱く（< 0.12）2位との差が極端な場合のみ
    # 0.12 以上は正解1件にヒットしている可能性が高いので回答に進める
    if top < 0.12 and len(scored_chunks) >= 2:
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


REFERENCE_PREFIX = "⚠ 公式FAQ未登録の参考情報です（正確性は保証されません）\n\n"


@app.post("/api/ask", response_model=AskResponse)
async def ask(payload: AskRequest, user: dict = Depends(require_user)) -> AskResponse:
    masked_q = mask(payload.question)
    chunks = get_index().search(masked_q, top_k=5)
    confidence = _compute_confidence(chunks)

    # チャンクが完全に空 → 「該当情報なし」を返す（FAQ追加リクエストを促す）
    if not chunks:
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
            is_reference=False,
        )

    # 確信度が低い場合は「参考情報」として返す（B モード）
    # - confidence == 0: 完全該当なし、でも何かしらヒットしたチャンクはあるので参考情報として提示
    # - confidence < 50: 低〜中確信度、参考情報フラグ付き
    is_reference = confidence < 50

    try:
        response_text = answer(masked_q, chunks, reference_mode=is_reference)
        if is_reference:
            response_text = REFERENCE_PREFIX + response_text
    except Exception as e:
        from anthropic import APIStatusError, APIConnectionError
        if isinstance(e, APIStatusError):
            if e.status_code == 401:
                detail = "Anthropic API キーが無効です。.env の ANTHROPIC_API_KEY を確認してください。"
            elif e.status_code == 400 and "credit" in str(e).lower():
                detail = "Anthropic API のクレジット残高が不足しています。Console で購入してください。"
            elif e.status_code == 429:
                detail = "レートリミットに達しました。少し待ってから再試行してください。"
            else:
                detail = f"Anthropic API エラー ({e.status_code}): {str(e)[:200]}"
        elif isinstance(e, APIConnectionError):
            detail = "Anthropic API への接続に失敗しました（ネットワーク／プロキシを確認）。"
        else:
            detail = f"LLM 呼び出しエラー: {type(e).__name__}: {str(e)[:200]}"
        audit.record(
            "query_error", user=user["email"], question=masked_q,
            error=type(e).__name__, detail=detail[:200],
        )
        raise HTTPException(status_code=502, detail=detail) from e

    audit.record(
        "query",
        user=user["email"],
        question=masked_q,
        sources=[c.chunk_id for c, _ in chunks],
        confidence=confidence,
        answered=True,
        is_reference=is_reference,
    )
    return AskResponse(
        answer=response_text,
        sources=[
            Source(chunk_id=c.chunk_id, source=c.source, score=s) for c, s in chunks
        ],
        confidence=confidence,
        has_answer=True,
        is_reference=is_reference,
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
.fc-counts{display:flex;flex-wrap:wrap;gap:8px;padding:10px 12px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;margin-bottom:12px;font-size:13px}
.fc-counts .total{font-weight:600;color:#111827}
.fc-counts .chip{padding:2px 8px;border-radius:6px;font-size:12px}
.fc-counts .chip.ok{background:#d1fae5;color:#065f46}
.fc-counts .chip.warn{background:#fef3c7;color:#92400e}
.fc-counts .chip.danger{background:#fee2e2;color:#991b1b}
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
.doc-table{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}
.doc-table th{text-align:left;color:#6b7280;font-weight:500;padding:8px 10px;
              border-bottom:1px solid #e5e7eb;font-size:12px}
.doc-table td{padding:10px;border-bottom:1px solid #f3f4f6;color:#111827}
.doc-table tr:hover{background:#fafbfc}
.doc-name{font-weight:500;word-break:break-all}
.doc-meta{color:#9ca3af;font-size:11px}
.doc-delete-btn{padding:6px 12px;background:#fff;color:#dc2626;border:1px solid #fecaca;
                border-radius:6px;font-size:12px;cursor:pointer}
.doc-delete-btn:hover{background:#fef2f2;border-color:#dc2626}
.doc-delete-btn:disabled{opacity:.5;cursor:not-allowed}
.doc-summary{padding:10px 12px;background:#f9fafb;border-radius:8px;font-size:12px;
             color:#6b7280;margin-bottom:8px}
.doc-summary b{color:#111827}
.export-btn{padding:6px 12px;background:#fff;color:#1a73e8;border:1px solid #bfdbfe;
            border-radius:6px;font-size:12px;cursor:pointer;font-weight:500}
.export-btn:hover{background:#eff6ff;border-color:#1a73e8}
.export-btn:disabled{opacity:.5;cursor:not-allowed}
.setting-row{margin-bottom:12px}
.setting-label{display:block;font-size:12px;color:#374151;font-weight:500;margin-bottom:4px;
               display:flex;align-items:center;gap:8px}
.setting-badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:400;
               background:#dbeafe;color:#1e40af}
.setting-badge.default{background:#f3f4f6;color:#6b7280}
.setting-row input[type=text]{width:100%;padding:8px 10px;border:1px solid #d1d5db;
                              border-radius:6px;font-size:13px;box-sizing:border-box}
.setting-row input[type=text]:focus{outline:0;border-color:#1a73e8;box-shadow:0 0 0 3px rgba(26,115,232,.15)}
.setting-hint{margin-top:2px;font-size:11px;color:#9ca3af}
.setting-save-btn{padding:8px 16px;background:#1a73e8;color:#fff;border:0;border-radius:6px;
                  font-size:13px;cursor:pointer;font-weight:500}
.setting-save-btn:hover{background:#1557b0}
.setting-save-btn:disabled{opacity:.6;cursor:not-allowed}
.setting-reset-btn{padding:8px 16px;background:#fff;color:#6b7280;border:1px solid #d1d5db;
                   border-radius:6px;font-size:13px;cursor:pointer}
.setting-reset-btn:hover{background:#f9fafb;color:#dc2626;border-color:#fecaca}
/* ダッシュボード */
.dash-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:16px}
.dash-tile{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px}
.dash-tile-label{font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em}
.dash-tile-value{font-size:22px;font-weight:600;color:#111827;margin-top:4px}
.dash-tile-sub{font-size:11px;color:#9ca3af;margin-top:2px}
.dash-tile.good .dash-tile-value{color:#065f46}
.dash-tile.warn .dash-tile-value{color:#92400e}
.dash-tile.bad .dash-tile-value{color:#991b1b}
.dash-bars{display:flex;align-items:flex-end;gap:2px;height:80px;padding:8px 0;
           background:#fafbfc;border-radius:8px;padding-left:8px;padding-right:8px;overflow-x:auto}
.dash-bar{flex:0 0 auto;width:18px;display:flex;flex-direction:column;align-items:center;
          min-width:18px;height:100%;justify-content:flex-end;cursor:default;position:relative}
.dash-bar-fill{width:100%;background:#1a73e8;border-radius:2px 2px 0 0;
               min-height:1px;transition:background .15s}
.dash-bar:hover .dash-bar-fill{background:#1557b0}
.dash-bar-label{font-size:9px;color:#9ca3af;margin-top:3px;writing-mode:vertical-rl;
                transform:rotate(180deg);max-height:36px}
.dash-bar-tip{position:absolute;bottom:100%;left:50%;transform:translateX(-50%);
              background:#111827;color:#fff;padding:4px 8px;border-radius:4px;
              font-size:11px;white-space:nowrap;display:none;z-index:10;margin-bottom:4px}
.dash-bar:hover .dash-bar-tip{display:block}
.dash-section{margin-top:14px}
.dash-section h4{margin:0 0 8px;font-size:13px;color:#374151;font-weight:600}
.dash-list{display:flex;flex-direction:column;gap:4px}
.dash-list-row{display:flex;justify-content:space-between;padding:6px 10px;background:#fafbfc;
               border-radius:6px;font-size:12px}
.dash-list-row b{color:#1a73e8;font-weight:600}
@media (max-width:480px){
  .doc-table th.col-modified,.doc-table td.col-modified{display:none}
}
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

    <div class="step-title" style="margin-top:32px"><span class="step-num">3</span>利用状況ダッシュボード</div>
    <div id="dashboard-section" style="font-size:13px;color:#6b7280">
      <div class="empty-msg">読み込み中…</div>
    </div>

    <div class="step-title" style="margin-top:32px"><span class="step-num">4</span>取り込み済み文書（メンテナンス）</div>
    <div id="docs-section" style="font-size:13px;color:#6b7280">
      <div class="empty-msg">読み込み中…</div>
    </div>

    <div class="step-title" style="margin-top:32px"><span class="step-num">5</span>質問履歴を検索</div>
    <div id="queries-search-section" style="font-size:13px;color:#6b7280">
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px">
        <input type="text" id="querySearchInput" placeholder="🔍 質問本文で検索（部分一致）" style="flex:1;min-width:200px;padding:6px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px"/>
        <select id="querySearchAnswered" style="padding:6px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px">
          <option value="all">すべて</option>
          <option value="yes">回答済</option>
          <option value="no">未回答</option>
          <option value="reference">参考情報</option>
        </select>
        <select id="querySearchDays" style="padding:6px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px">
          <option value="7">過去 7日</option>
          <option value="30" selected>過去 30日</option>
          <option value="90">過去 90日</option>
        </select>
        <button class="export-btn" id="querySearchBtn">検索</button>
      </div>
      <div id="queries-search-results">
        <div class="empty-msg">検索条件を指定して「検索」を押してください</div>
      </div>
    </div>

    <div class="step-title" style="margin-top:32px"><span class="step-num">6</span>FAQ追加リクエスト</div>
    <div id="faq-requests-section" style="font-size:13px;color:#6b7280">
      <div class="empty-msg">読み込み中…</div>
    </div>

    <div class="step-title" style="margin-top:32px"><span class="step-num">7</span>組織情報（デモ・カスタマイズ用）</div>
    <div id="settings-section" style="font-size:13px;color:#6b7280">
      <div class="empty-msg">読み込み中…</div>
    </div>

    <div class="step-title" style="margin-top:32px"><span class="step-num">8</span>レポート出力（社内提出・分析用）</div>
    <div id="export-section" style="font-size:13px;color:#6b7280">
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <label>期間:
          <select id="exportDays" style="padding:4px 8px;border:1px solid #d1d5db;border-radius:6px">
            <option value="7">過去 7日</option>
            <option value="30" selected>過去 30日</option>
            <option value="90">過去 90日</option>
            <option value="365">過去 1年</option>
          </select>
        </label>
        <button class="export-btn" data-event="query" data-format="csv">📊 質問履歴 CSV</button>
        <button class="export-btn" data-event="faq_request" data-format="csv">📩 FAQリクエスト CSV</button>
        <button class="export-btn" data-event="feedback" data-format="csv">👍 フィードバック CSV</button>
        <button class="export-btn" data-event="all" data-format="json">🗂 全ログ JSON</button>
      </div>
      <div style="margin-top:8px;font-size:11px;color:#9ca3af">
        💡 CSV は Excel/Numbers で開けます（UTF-8 BOM 付き）。月次顧客レポートや改善分析にお使いください
      </div>
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
    <div class="fc-counts">
      <span class="total">📊 データ件数: ${analysis.n_chunks.toLocaleString()}チャンク</span>
      <span class="chip ok">✅ 取り込み可 ${(analysis.n_chunks - warnChunks - dangerChunks).toLocaleString()}件</span>
      ${warnChunks > 0 ? `<span class="chip warn">⚠ 要確認 ${warnChunks.toLocaleString()}件</span>` : ''}
      ${dangerChunks > 0 ? `<span class="chip danger">🔴 危険 ${dangerChunks.toLocaleString()}件</span>` : ''}
    </div>
    <dl class="fc-grid">
      <dt>判定理由</dt><dd>${escape(analysis.reason)}</dd>
      <dt>検出された懸念</dt><dd>${renderConcerns(analysis)}</dd>
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
    // 0チャンク（画像のみPDF・空ファイル等）はそもそも取り込み不可なので、明確に警告カードに置き換える
    if(!analysis.chunks || analysis.chunks.length === 0){
      pending.outerHTML = `<div class="file-card danger">
        <div class="fc-header">
          <div class="fc-title">
            <span class="fc-icon">⚠</span>
            <div>
              <div class="fc-name">${escape(file.name)}</div>
              <div class="fc-meta">${fmtBytes(file.size)} · ${escape(analysis.format||'?')} · 0チャンク</div>
            </div>
          </div>
          <span class="fc-badge danger">取り込み不可</span>
        </div>
        <div style="padding:12px;background:#fef2f2;border-radius:8px;margin-top:8px;font-size:13px;color:#991b1b">
          📋 <b>${escape(analysis.reason||'テキストを抽出できませんでした')}</b><br><br>
          <b>原因と対策:</b><br>
          ・スキャン PDF / 画像のみ PDF → OCR が必要（v2 で対応予定）<br>
          ・パスワード保護 PDF → 解除してから再投入<br>
          ・空ファイル → ファイルが空でないか確認<br><br>
          💡 <b>回避策</b>: PDF を Word/Markdown に変換するか、PDF からテキストをコピー&ペーストして .txt として投入してください
        </div>
      </div>`;
      return;
    }
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
      // 赤色（danger）判定なら「警告を無視して取り込む」ボタンを常に提示
      // マスキング処理は適用されるので、検出された PII は [メール] 等の記号に置換される
      if(item.analysis.recommendation === 'danger') {
        const force = document.createElement('button');
        force.textContent = '⚠ 警告を無視して取り込む（PIIは自動マスク）';
        force.style.cssText = 'margin-top:10px;background:#dc2626;color:#fff;padding:8px 14px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500';
        force.onclick = async () => {
          if(!confirm('PII (氏名・メール等) が大量に検出されています。マスキング処理は適用されますが、本当に取り込みますか？')) return;
          force.disabled = true;
          force.textContent = '⏳ 取り込み中…';
          const fd2 = new FormData();
          fd2.append('file', item.file);
          const url2 = '/api/admin/ingest?force=true&excluded_chunk_ids=' + encodeURIComponent(excludedIds);
          try {
            const r2 = await fetch(url2, {method:'POST', body:fd2});
            if(!r2.ok) throw new Error((await r2.json()).detail || r2.statusText);
            const d2 = await r2.json();
            item.state = 'ingested';
            item.card.querySelector('.fc-badge').textContent = `⚠ 強制取り込み済み (${d2.ingested_chunks}チャンク・マスク済)`;
            item.card.querySelector('.fc-badge').className = 'fc-badge warn';
            err.remove();
            force.remove();
            failed--;
            success++;
            ingestedChunks += d2.ingested_chunks;
            updateSummary();
          } catch(e2) {
            force.disabled = false;
            force.textContent = '⚠ 警告を無視して取り込む（PIIは自動マスク）';
            err.textContent = '強制取り込みも失敗: ' + e2.message;
          }
        };
        item.card.appendChild(force);
      }
    }
  }
  updateSummary();
  alert(`取り込み完了: ${success}件成功 (${ingestedChunks}チャンク) / ${failed}件失敗`);
};

fi.onchange = e => { for(const f of e.target.files) analyzeFile(f); fi.value=''; };
['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('dragover') }));
['dragleave','drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('dragover') }));
dz.addEventListener('drop', e => { for(const f of e.dataTransfer.files) analyzeFile(f); });

// === 取り込み済み文書一覧（メンテナンス） ===
const docsSection = document.getElementById('docs-section');

function fmtDate(iso){
  try {
    const d = new Date(iso);
    const y = d.getFullYear(), m = String(d.getMonth()+1).padStart(2,'0'), day = String(d.getDate()).padStart(2,'0');
    const hh = String(d.getHours()).padStart(2,'0'), mm = String(d.getMinutes()).padStart(2,'0');
    return `${y}-${m}-${day} ${hh}:${mm}`;
  } catch(e) { return iso; }
}

async function loadDocuments(){
  docsSection.innerHTML = '<div class="empty-msg"><span class="spinner"></span>読み込み中…</div>';
  try {
    const r = await fetch('/api/admin/documents');
    if(!r.ok) throw new Error(r.statusText);
    const d = await r.json();
    renderDocuments(d.documents || []);
  } catch(e) {
    docsSection.innerHTML = `<div class="error-msg">読み込み失敗: ${escape(e.message)}</div>`;
  }
}

function renderDocuments(docs){
  if(!docs.length){
    docsSection.innerHTML = '<div class="empty-msg">取り込み済み文書はまだありません</div>';
    return;
  }
  const totalBytes = docs.reduce((s,d) => s + d.size_bytes, 0);
  const totalChunks = docs.reduce((s,d) => s + d.n_chunks, 0);
  const summary = `<div class="doc-summary"><b>${docs.length}文書</b> · 合計 <b>${fmtBytes(totalBytes)}</b> · チャンク <b>${totalChunks}</b></div>`;
  const rows = docs.map(d => `
    <tr data-filename="${escape(d.filename)}">
      <td>
        <div class="doc-name">${escape(d.filename)}</div>
        <div class="doc-meta">${fmtBytes(d.size_bytes)} · ${d.n_chunks}チャンク</div>
      </td>
      <td class="col-modified" style="color:#6b7280;font-size:12px;white-space:nowrap">${fmtDate(d.modified_at)}</td>
      <td style="text-align:right">
        <button class="doc-delete-btn" data-filename="${escape(d.filename)}">削除</button>
      </td>
    </tr>
  `).join('');
  docsSection.innerHTML = summary + `
    <table class="doc-table">
      <thead><tr>
        <th>ファイル名</th>
        <th class="col-modified">最終更新</th>
        <th style="text-align:right;width:80px">操作</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
  docsSection.querySelectorAll('.doc-delete-btn').forEach(btn => {
    btn.onclick = () => deleteDocument(btn.dataset.filename, btn);
  });
}

async function deleteDocument(filename, btn){
  if(!confirm(`「${filename}」を削除します。よろしいですか？\\n\\nこの操作はインデックスから完全に取り除きます。`)) return;
  btn.disabled = true;
  btn.textContent = '削除中…';
  try {
    const r = await fetch('/api/admin/documents/' + encodeURIComponent(filename), {method:'DELETE'});
    if(!r.ok){
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || r.statusText);
    }
    const d = await r.json();
    await loadDocuments();
    // チャット側ヘッダの統計も更新したい場合は次回ロード時に反映される
    alert(`削除しました: ${filename}\\n残チャンク数: ${d.n_chunks_after}`);
  } catch(e) {
    btn.disabled = false;
    btn.textContent = '削除';
    alert('削除失敗: ' + e.message);
  }
}

// 取り込み完了後に一覧を再読込するためのフック
const _origConfirmHandler = confirmBtn.onclick;
confirmBtn.onclick = async () => {
  await _origConfirmHandler();
  loadDocuments();
  loadFaqRequests();
};

// === FAQ追加リクエスト一覧 ===
const faqReqSection = document.getElementById('faq-requests-section');

async function loadFaqRequests(){
  faqReqSection.innerHTML = '<div class="empty-msg"><span class="spinner"></span>読み込み中…</div>';
  try {
    const r = await fetch('/api/admin/faq-requests');
    if(!r.ok) throw new Error(r.statusText);
    const d = await r.json();
    renderFaqRequests(d.requests || [], d.total || 0);
  } catch(e) {
    faqReqSection.innerHTML = `<div class="error-msg">読み込み失敗: ${escape(e.message)}</div>`;
  }
}

function renderFaqRequests(requests, total){
  if(!requests.length){
    faqReqSection.innerHTML = '<div class="empty-msg">未対応のFAQ追加リクエストはありません</div>';
    return;
  }
  const summary = `<div class="doc-summary"><b>${total}件のリクエスト</b> · 最新${requests.length}件を表示</div>`;
  const rows = requests.map(r => `
    <tr>
      <td>
        <div class="doc-name">${escape(r.question)}</div>
        <div class="doc-meta">${escape(r.user)} · ${fmtDate(r.ts)}</div>
        ${r.note ? `<div style="margin-top:4px;color:#6b7280;font-size:12px">📝 ${escape(r.note)}</div>` : ''}
      </td>
    </tr>
  `).join('');
  faqReqSection.innerHTML = summary + `
    <table class="doc-table">
      <thead><tr><th>質問内容</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div style="margin-top:8px;font-size:11px;color:#9ca3af">
      💡 これらの質問に対応するドキュメントを作成して、上の「ファイルを投入」から取り込んでください
    </div>
  `;
}

// === エクスポート機能 ===
document.querySelectorAll('.export-btn').forEach(btn => {
  btn.onclick = async () => {
    const days = document.getElementById('exportDays').value;
    const event = btn.dataset.event;
    const format = btn.dataset.format;
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳ 生成中…';
    try {
      const url = `/api/admin/export?days=${days}&format=${format}&event=${event}`;
      const r = await fetch(url);
      if(!r.ok){
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || r.statusText);
      }
      // ファイルダウンロード
      const blob = await r.blob();
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      const cd = r.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename="([^"]+)"/);
      link.download = m ? m[1] : `export.${format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(link.href);
    } catch(e){
      alert('エクスポート失敗: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  };
});

// === 組織情報の編集 ===
const settingsSection = document.getElementById('settings-section');

const SETTINGS_LABELS = {
  product_name: 'プロダクト名',
  org_name: '組織名',
  assistant_role: 'アシスタント役割',
  masking_industry: 'マスキング業界プリセット',
};
const SETTINGS_HINTS = {
  product_name: 'チャット画面のタイトルに表示されます（例: Inquira）',
  org_name: 'AIの自己紹介に使われます（例: 株式会社○○）',
  assistant_role: 'AIの役割設定（例: 社内ヘルプデスク / 顧客サポート）',
  masking_industry: 'PII検出の業界辞書（general / education / medical / finance）',
};

async function loadSettings(){
  settingsSection.innerHTML = '<div class="empty-msg"><span class="spinner"></span>読み込み中…</div>';
  try {
    const r = await fetch('/api/admin/settings');
    if(!r.ok) throw new Error(r.statusText);
    const d = await r.json();
    renderSettings(d);
  } catch(e) {
    settingsSection.innerHTML = `<div class="error-msg">読み込み失敗: ${escape(e.message)}</div>`;
  }
}

function renderSettings(data){
  const eff = data.effective || {};
  const overrides = data.overrides || {};
  const keys = data.editable_keys || [];
  const rows = keys.map(k => {
    const isOverride = k in overrides;
    return `
      <div class="setting-row">
        <label class="setting-label">
          ${SETTINGS_LABELS[k] || k}
          ${isOverride ? '<span class="setting-badge">UIから編集済</span>' : '<span class="setting-badge default">.env デフォルト</span>'}
        </label>
        <input type="text" data-key="${k}" value="${escape(eff[k] || '')}" maxlength="200"/>
        <div class="setting-hint">${escape(SETTINGS_HINTS[k] || '')}</div>
      </div>
    `;
  }).join('');
  settingsSection.innerHTML = `
    <div class="doc-summary">💡 ここで変更した内容は <b>即時反映＋次回起動時にも保持</b> されます。デモ用に貴社向けへカスタマイズしてください。</div>
    ${rows}
    <div style="display:flex;gap:8px;margin-top:12px">
      <button class="setting-save-btn">💾 変更を保存</button>
      <button class="setting-reset-btn">↩ .env デフォルトに戻す</button>
    </div>
  `;
  settingsSection.querySelector('.setting-save-btn').onclick = saveSettings;
  settingsSection.querySelector('.setting-reset-btn').onclick = resetSettings;
}

async function saveSettings(){
  const inputs = settingsSection.querySelectorAll('input[data-key]');
  const updates = {};
  for(const inp of inputs){
    updates[inp.dataset.key] = inp.value.trim();
  }
  const btn = settingsSection.querySelector('.setting-save-btn');
  btn.disabled = true; btn.textContent = '保存中…';
  try {
    const r = await fetch('/api/admin/settings', {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(updates),
    });
    if(!r.ok){
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || r.statusText);
    }
    await loadSettings();
    alert('✅ 保存しました。チャット画面（/）でも反映されています');
  } catch(e){
    btn.disabled = false; btn.textContent = '💾 変更を保存';
    alert('保存失敗: ' + e.message);
  }
}

async function resetSettings(){
  if(!confirm('UIで編集した組織情報を全て削除し、.env のデフォルトに戻します。よろしいですか？\\n（即座に反映されない項目もあります）')) return;
  try {
    const r = await fetch('/api/admin/settings', {method:'DELETE'});
    if(!r.ok) throw new Error(r.statusText);
    await loadSettings();
    alert('✅ オーバーライドを削除しました');
  } catch(e){
    alert('失敗: ' + e.message);
  }
}

// === 利用状況ダッシュボード ===
const dashboardSection = document.getElementById('dashboard-section');

async function loadDashboard(){
  dashboardSection.innerHTML = '<div class="empty-msg"><span class="spinner"></span>読み込み中…</div>';
  try {
    const r = await fetch('/api/admin/dashboard?days=14');
    if(!r.ok) throw new Error(r.statusText);
    const d = await r.json();
    renderDashboard(d);
  } catch(e) {
    dashboardSection.innerHTML = `<div class="error-msg">読み込み失敗: ${escape(e.message)}</div>`;
  }
}

function dashTile(label, value, sub, cls){
  cls = cls || '';
  return `<div class="dash-tile ${cls}">
    <div class="dash-tile-label">${escape(label)}</div>
    <div class="dash-tile-value">${escape(String(value))}</div>
    ${sub ? `<div class="dash-tile-sub">${escape(sub)}</div>` : ''}
  </div>`;
}

function renderDashboard(d){
  const t = d.totals || {};
  const daily = d.daily || [];

  // タイル
  const ansRateCls = t.answer_rate >= 70 ? 'good' : t.answer_rate >= 40 ? 'warn' : 'bad';
  const confCls = t.avg_confidence >= 70 ? 'good' : t.avg_confidence >= 40 ? 'warn' : 'bad';
  const tiles = [
    dashTile('質問総数', t.queries || 0, `過去${d.days}日`),
    dashTile('回答率', (t.answer_rate || 0)+'%',
      `通常${t.answered||0}＋参考${t.reference||0} / ${t.queries||0}件`, ansRateCls),
    dashTile('平均確信度', (t.avg_confidence || 0)+'%', '', confCls),
    dashTile('未回答', t.no_answer || 0, t.queries ? `${Math.round((t.no_answer||0)/t.queries*100)}%` : '', t.no_answer ? 'bad' : ''),
    dashTile('FAQ要望', t.faq_requests || 0, '管理者要対応'),
    dashTile('ユニーク利用者', t.unique_users || 0, '期間内'),
  ].join('');

  // 日次バーチャート（質問数）
  const maxQ = Math.max(1, ...daily.map(x => x.queries));
  const bars = daily.map(x => {
    const h = (x.queries / maxQ * 70) || 0;
    const ml = x.date.slice(5);  // MM-DD
    return `<div class="dash-bar" title="${escape(x.date)}: ${x.queries}件">
      <div class="dash-bar-tip">${escape(x.date)}<br>質問 ${x.queries} / 確信度 ${x.avg_confidence}%</div>
      <div class="dash-bar-fill" style="height:${h}px"></div>
      <div class="dash-bar-label">${escape(ml)}</div>
    </div>`;
  }).join('');

  // トピック・ユーザー
  const topicRows = (d.top_topics || []).slice(0,6).map(t =>
    `<div class="dash-list-row"><span>${escape(t.source)}</span><b>${t.count}件</b></div>`
  ).join('') || '<div class="empty-msg" style="padding:8px">データなし</div>';
  const userRows = (d.top_users || []).slice(0,6).map(u =>
    `<div class="dash-list-row"><span>${escape(u.user)}</span><b>${u.count}件</b></div>`
  ).join('') || '<div class="empty-msg" style="padding:8px">データなし</div>';

  // LLM 利用量＆キャッシュ
  const lu = d.llm_usage || {};
  const llmBlock = lu.calls ? `
    <div class="dash-section">
      <h4>💰 LLM API 利用量（プロンプトキャッシュ効率）</h4>
      <div class="dash-list">
        <div class="dash-list-row"><span>API 呼び出し</span><b>${lu.calls} 回</b></div>
        <div class="dash-list-row"><span>入力トークン（通常）</span><b>${lu.input_tokens.toLocaleString()}</b></div>
        <div class="dash-list-row"><span>入力トークン（キャッシュ書込）</span><b>${lu.cache_creation_tokens.toLocaleString()}</b></div>
        <div class="dash-list-row"><span>入力トークン（キャッシュ読込・割引対象）</span><b style="color:#065f46">${lu.cache_read_tokens.toLocaleString()}</b></div>
        <div class="dash-list-row"><span>出力トークン</span><b>${lu.output_tokens.toLocaleString()}</b></div>
        <div class="dash-list-row"><span>キャッシュヒット率</span><b style="color:${lu.cache_hit_rate >= 30 ? '#065f46' : '#9ca3af'}">${lu.cache_hit_rate}%</b></div>
      </div>
      <div style="margin-top:6px;font-size:11px;color:#9ca3af">
        ※ キャッシュは Anthropic 側で最小トークン数を超えた場合のみ作成されます（Haiku 4.5 は 2048 tok）
      </div>
    </div>
  ` : '';

  dashboardSection.innerHTML = `
    <div class="dash-tiles">${tiles}</div>
    <div class="dash-section">
      <h4>📊 日次質問数（過去${d.days}日）</h4>
      <div class="dash-bars">${bars}</div>
    </div>
    <div class="dash-section" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px">
      <div>
        <h4>🔥 質問が多いトピック TOP6</h4>
        <div class="dash-list">${topicRows}</div>
      </div>
      <div>
        <h4>👤 アクティブ利用者 TOP6</h4>
        <div class="dash-list">${userRows}</div>
      </div>
    </div>
    ${llmBlock}
  `;
}

// === 質問履歴の検索 ===
const querySearchBtn = document.getElementById('querySearchBtn');
const querySearchInput = document.getElementById('querySearchInput');
const querySearchResults = document.getElementById('queries-search-results');

async function runQuerySearch(){
  const q = querySearchInput.value.trim();
  const days = document.getElementById('querySearchDays').value;
  const answered = document.getElementById('querySearchAnswered').value;
  querySearchResults.innerHTML = '<div class="empty-msg"><span class="spinner"></span>検索中…</div>';
  try {
    const url = `/api/admin/queries?q=${encodeURIComponent(q)}&days=${days}&answered=${answered}&limit=100`;
    const r = await fetch(url);
    if(!r.ok){
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || r.statusText);
    }
    const d = await r.json();
    renderQuerySearchResults(d);
  } catch(e) {
    querySearchResults.innerHTML = `<div class="error-msg">検索失敗: ${escape(e.message)}</div>`;
  }
}

function renderQuerySearchResults(d){
  const results = d.results || [];
  if(!results.length){
    querySearchResults.innerHTML = '<div class="empty-msg">該当する質問が見つかりませんでした</div>';
    return;
  }
  const summary = `<div class="doc-summary"><b>${d.total}件ヒット</b> · 最新${results.length}件を表示</div>`;
  const rows = results.map(r => {
    const confCls = r.confidence >= 70 ? '#065f46' : r.confidence >= 40 ? '#92400e' : '#9ca3af';
    const statusBadge = !r.answered
      ? '<span class="setting-badge" style="background:#fee2e2;color:#991b1b">未回答</span>'
      : r.is_reference
      ? '<span class="setting-badge" style="background:#fef3c7;color:#92400e">参考情報</span>'
      : '<span class="setting-badge" style="background:#d1fae5;color:#065f46">回答済</span>';
    return `
      <tr>
        <td>
          <div class="doc-name">${escape(r.question)}</div>
          <div class="doc-meta">${escape(r.user)} · ${fmtDate(r.ts)} ${statusBadge} <span style="color:${confCls}">確信度${r.confidence}%</span></div>
          ${r.sources && r.sources.length ? `<div style="margin-top:4px;font-size:11px;color:#6b7280">📎 ${escape(r.sources.slice(0,3).join(', '))}</div>` : ''}
        </td>
      </tr>
    `;
  }).join('');
  querySearchResults.innerHTML = summary + `
    <table class="doc-table"><thead><tr><th>質問・コンテキスト</th></tr></thead>
    <tbody>${rows}</tbody></table>
  `;
}

if(querySearchBtn){
  querySearchBtn.onclick = runQuerySearch;
  querySearchInput.addEventListener('keydown', (e) => {
    if(e.key === 'Enter') runQuerySearch();
  });
}

loadDashboard();
loadDocuments();
loadFaqRequests();
loadSettings();
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

    # 人気質問サジェスト：回答に成功した質問の出現頻度トップ
    # （個人特定可能な質問でも、複数回出てきたものは「みんなが聞いてる」サイン）
    long_range = audit.read_range(days=30)
    answered_queries = [
        (q.get("question") or "").strip()
        for q in long_range
        if q.get("event") == "query" and q.get("answered") is True
    ]
    question_counts: Counter = Counter(q for q in answered_queries if len(q) >= 4)
    popular_queries = [
        {"question": q, "count": c}
        for q, c in question_counts.most_common(8)
        if c >= 2  # 2回以上聞かれたものだけサジェスト
    ]

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
        "popular_queries": popular_queries,
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


class FaqRequest(BaseModel):
    question: str
    note: str = ""  # 任意の補足情報


@app.post("/api/faq-requests")
async def api_faq_request(payload: FaqRequest, user: dict = Depends(require_user)):
    """FAQ追加リクエストを受け付ける。

    ユーザーが質問しても回答が得られなかった場合、管理者にFAQ追加を依頼するためのエンドポイント。
    監査ログに記録される。
    """
    q = (payload.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="質問本文が空です")
    if len(q) > 2000:
        raise HTTPException(status_code=400, detail="質問が長すぎます（2000文字以内）")
    audit.record(
        "faq_request",
        user=user["email"],
        question=q,
        note=(payload.note or "")[:500],
    )
    return {"ok": True}


@app.get("/api/admin/faq-requests")
async def admin_list_faq_requests(user: dict = Depends(require_user)):
    """未対応のFAQ追加リクエスト一覧を返す（直近100件）。"""
    recent = audit.read_recent(1000)
    requests = [
        {
            "question": e.get("question", ""),
            "note": e.get("note", ""),
            "user": e.get("user", ""),
            "ts": e.get("ts", ""),
        }
        for e in recent if e.get("event") == "faq_request"
    ]
    return {"requests": requests[:100], "total": len(requests)}


@app.get("/api/admin/settings")
async def admin_get_settings(user: dict = Depends(require_user)):
    """組織情報の現在値と、ファイル保存されているオーバーライドを返す。"""
    return {
        "effective": runtime_settings.get_effective(),
        "overrides": runtime_settings.current_overrides(),
        "editable_keys": sorted(runtime_settings.EDITABLE_KEYS),
    }


class SettingsUpdate(BaseModel):
    product_name: str | None = None
    org_name: str | None = None
    assistant_role: str | None = None
    masking_industry: str | None = None


@app.put("/api/admin/settings")
async def admin_update_settings(
    payload: SettingsUpdate,
    user: dict = Depends(require_user),
):
    """組織情報を更新（即時反映＋ファイル保存）。"""
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="更新項目が空です")
    try:
        applied = runtime_settings.update(updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    audit.record(
        "settings_update",
        user=user["email"],
        keys=sorted(applied.keys()),
    )
    return {"applied": applied, "effective": runtime_settings.get_effective()}


@app.delete("/api/admin/settings")
async def admin_reset_settings(user: dict = Depends(require_user)):
    """全オーバーライドを削除し `.env` のデフォルトに戻す（再起動が必要な項目あり）。"""
    runtime_settings.reset()
    audit.record("settings_reset", user=user["email"])
    return {"ok": True, "note": "再起動で .env 値が反映されます"}


@app.get("/api/admin/queries")
async def admin_search_queries(
    q: str = "",
    days: int = 30,
    min_confidence: int = 0,
    max_confidence: int = 100,
    answered: str = "all",
    limit: int = 100,
    user: dict = Depends(require_user),
):
    """質問履歴の検索・絞り込み（管理者向け）。

    Args:
      q: 質問本文の部分一致（大文字小文字無視）
      days: 過去 N 日（1〜365）
      min_confidence, max_confidence: 確信度の範囲
      answered: "all" / "yes"（answered=True）/ "no"（answered=False）/ "reference"
      limit: 返却件数上限（最大 500）
    """
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days は 1〜365 の範囲")
    if min_confidence < 0 or max_confidence > 100 or min_confidence > max_confidence:
        raise HTTPException(status_code=400, detail="confidence の範囲が不正")
    if answered not in ("all", "yes", "no", "reference"):
        raise HTTPException(status_code=400, detail="answered は all/yes/no/reference")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit は 1〜500")

    entries = audit.read_range(days=days)
    queries = [e for e in entries if e.get("event") == "query"]

    q_lower = q.lower().strip()
    results = []
    for e in queries:
        question = e.get("question", "")
        conf = e.get("confidence", 0)
        ans = bool(e.get("answered"))
        ref = bool(e.get("is_reference"))
        if q_lower and q_lower not in question.lower():
            continue
        if conf < min_confidence or conf > max_confidence:
            continue
        if answered == "yes" and not ans:
            continue
        if answered == "no" and ans:
            continue
        if answered == "reference" and not ref:
            continue
        results.append({
            "ts": e.get("ts", ""),
            "user": e.get("user", ""),
            "question": question,
            "confidence": conf,
            "answered": ans,
            "is_reference": ref,
            "sources": e.get("sources", []),
        })

    # 新しい順
    results.sort(key=lambda r: r["ts"], reverse=True)
    return {
        "results": results[:limit],
        "total": len(results),
        "filters": {
            "q": q, "days": days,
            "min_confidence": min_confidence, "max_confidence": max_confidence,
            "answered": answered,
        },
    }


@app.get("/api/admin/dashboard")
async def admin_dashboard(days: int = 14, user: dict = Depends(require_user)):
    """日次の使用量ダッシュボード用集計。

    過去 days 日分の以下を返す:
      - daily: [{date, queries, answered, reference, no_answer, avg_confidence, unique_users}]
      - totals: 期間合計
      - top_topics: トピック別質問数（ソースファイル別）
      - top_users: ユーザー別質問数（個人特定避けたい場合は集計のみ）
      - faq_requests_count: 期間内のFAQ追加リクエスト件数
    """
    from collections import Counter, defaultdict
    from datetime import datetime, timedelta, timezone

    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days は 1〜365 の範囲")

    entries = audit.read_range(days=days)
    queries = [e for e in entries if e.get("event") == "query"]
    faq_requests = [e for e in entries if e.get("event") == "faq_request"]
    llm_usages = [e for e in entries if e.get("event") == "llm_usage"]

    # 日次集計（UTC 日付で grouping、表示側でローカルに変換）
    by_date: dict[str, dict] = defaultdict(lambda: {
        "queries": 0, "answered": 0, "reference": 0, "no_answer": 0,
        "confidence_sum": 0, "confidence_n": 0, "users": set(),
    })
    for q in queries:
        ts = q.get("ts", "")
        if not ts:
            continue
        date = ts[:10]  # YYYY-MM-DD
        bucket = by_date[date]
        bucket["queries"] += 1
        if q.get("answered") is True:
            if q.get("is_reference") is True:
                bucket["reference"] += 1
            else:
                bucket["answered"] += 1
        else:
            bucket["no_answer"] += 1
        if "confidence" in q:
            bucket["confidence_sum"] += q["confidence"]
            bucket["confidence_n"] += 1
        if q.get("user"):
            bucket["users"].add(q["user"])

    # 過去 days 日の全日付を埋める（質問ゼロの日も 0 として表示）
    today = datetime.now(timezone.utc).date()
    daily = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        b = by_date.get(d, {
            "queries": 0, "answered": 0, "reference": 0, "no_answer": 0,
            "confidence_sum": 0, "confidence_n": 0, "users": set(),
        })
        avg_conf = round(b["confidence_sum"] / b["confidence_n"]) if b["confidence_n"] else 0
        daily.append({
            "date": d,
            "queries": b["queries"],
            "answered": b["answered"],
            "reference": b["reference"],
            "no_answer": b["no_answer"],
            "avg_confidence": avg_conf,
            "unique_users": len(b["users"]) if isinstance(b["users"], set) else 0,
        })

    # 期間合計
    totals = {
        "queries": sum(d["queries"] for d in daily),
        "answered": sum(d["answered"] for d in daily),
        "reference": sum(d["reference"] for d in daily),
        "no_answer": sum(d["no_answer"] for d in daily),
        "unique_users": len({q.get("user") for q in queries if q.get("user")}),
        "faq_requests": len(faq_requests),
    }
    if totals["queries"]:
        totals["answer_rate"] = round(
            (totals["answered"] + totals["reference"]) / totals["queries"] * 100
        )
        confs = [q.get("confidence", 0) for q in queries if "confidence" in q]
        totals["avg_confidence"] = round(sum(confs) / len(confs)) if confs else 0
    else:
        totals["answer_rate"] = 0
        totals["avg_confidence"] = 0

    # トピック別（出典の1つ目の文書名で集計）
    topic_counter: Counter = Counter()
    for q in queries:
        srcs = q.get("sources") or []
        if srcs:
            topic = srcs[0].split("#")[0] if isinstance(srcs[0], str) else ""
            if topic:
                topic_counter[topic] += 1
    top_topics = [
        {"source": s, "count": c} for s, c in topic_counter.most_common(10)
    ]

    # ユーザー別（集計のみ、個人特定を避けたい場合は count のみ参考）
    user_counter: Counter = Counter(
        q.get("user", "(unknown)") for q in queries if q.get("user")
    )
    top_users = [
        {"user": u, "count": c} for u, c in user_counter.most_common(10)
    ]

    # LLM 使用量・キャッシュ集計（プロンプトキャッシュ実装の効果可視化）
    input_tok = sum(u.get("input_tokens", 0) or 0 for u in llm_usages)
    output_tok = sum(u.get("output_tokens", 0) or 0 for u in llm_usages)
    cache_creation = sum(u.get("cache_creation_input_tokens", 0) or 0 for u in llm_usages)
    cache_read = sum(u.get("cache_read_input_tokens", 0) or 0 for u in llm_usages)
    cache_hit_rate = (
        round(cache_read / (cache_read + input_tok + cache_creation) * 100)
        if (cache_read + input_tok + cache_creation) > 0 else 0
    )
    llm_usage = {
        "calls": len(llm_usages),
        "input_tokens": input_tok,
        "output_tokens": output_tok,
        "cache_creation_tokens": cache_creation,
        "cache_read_tokens": cache_read,
        "cache_hit_rate": cache_hit_rate,
    }

    return {
        "days": days,
        "daily": daily,
        "totals": totals,
        "top_topics": top_topics,
        "top_users": top_users,
        "llm_usage": llm_usage,
    }


@app.get("/api/admin/export")
async def admin_export(
    days: int = 30,
    format: str = "csv",
    event: str = "query",
    user: dict = Depends(require_user),
):
    """質問履歴・監査ログを CSV または JSON でエクスポート。

    Args:
      days: 何日前まで取得するか（デフォルト30日）
      format: 'csv' または 'json'
      event: フィルタするイベント種別（query / feedback / faq_request / all）
    """
    import csv
    import io
    from datetime import datetime
    from fastapi.responses import StreamingResponse, JSONResponse

    if format not in ("csv", "json"):
        raise HTTPException(status_code=400, detail="format は 'csv' または 'json'")
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days は 1〜365 の範囲")

    entries = audit.read_range(days=days)
    if event != "all":
        entries = [e for e in entries if e.get("event") == event]

    audit.record(
        "export", user=user["email"], format=format,
        event_filter=event, days=days, n_rows=len(entries),
    )

    filename_stem = f"inquira-{event}-{datetime.now().strftime('%Y%m%d')}"

    if format == "json":
        return JSONResponse(
            content={"entries": entries, "n_rows": len(entries), "days": days, "event": event},
            headers={"Content-Disposition": f'attachment; filename="{filename_stem}.json"'},
        )

    # CSV - 質問履歴向けに整形
    buf = io.StringIO()
    if event == "query":
        cols = ["ts", "user", "question", "confidence", "answered",
                "is_reference", "sources"]
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for e in entries:
            row = {c: e.get(c, "") for c in cols}
            if isinstance(row["sources"], list):
                row["sources"] = "; ".join(row["sources"])
            writer.writerow(row)
    elif event == "faq_request":
        cols = ["ts", "user", "question", "note"]
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for e in entries:
            writer.writerow({c: e.get(c, "") for c in cols})
    elif event == "feedback":
        cols = ["ts", "user", "question", "vote", "sources"]
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for e in entries:
            row = {c: e.get(c, "") for c in cols}
            if isinstance(row["sources"], list):
                row["sources"] = "; ".join(row["sources"])
            writer.writerow(row)
    else:
        # 全イベント or その他: 全フィールド出力
        all_keys: list[str] = []
        seen: set[str] = set()
        for e in entries:
            for k in e.keys():
                if k not in seen:
                    seen.add(k)
                    all_keys.append(k)
        writer = csv.DictWriter(buf, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for e in entries:
            row = {k: ("; ".join(v) if isinstance(v, list) else v) for k, v in e.items()}
            writer.writerow(row)

    # Excel互換のため UTF-8 BOM を先頭に
    csv_bytes = ("﻿" + buf.getvalue()).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename_stem}.csv"'},
    )


@app.post("/api/admin/reload-index")
async def admin_reload(user: dict = Depends(require_user)):
    idx = reload_index()
    audit.record("reload_index", user=user["email"], n_chunks=len(idx.chunks))
    return {"chunks": len(idx.chunks)}


@app.get("/api/admin/documents")
async def admin_list_documents(user: dict = Depends(require_user)):
    """FAQマスターに取り込み済みの文書一覧を返す。"""
    from datetime import datetime, timezone

    faq_dir = settings.faq_master_dir
    if not faq_dir.exists():
        return {"documents": []}

    idx = get_index()
    chunks_per_source: dict[str, int] = {}
    for c in idx.chunks:
        chunks_per_source[c.source] = chunks_per_source.get(c.source, 0) + 1

    docs = []
    for path in sorted(faq_dir.glob("**/*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        rel = path.relative_to(faq_dir)
        rel_str = str(rel)
        stat = path.stat()
        docs.append({
            "filename": rel_str,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "n_chunks": chunks_per_source.get(rel_str, 0),
        })
    return {"documents": docs}


@app.delete("/api/admin/documents/{filename:path}")
async def admin_delete_document(filename: str, user: dict = Depends(require_user)):
    """FAQマスターから1文書を削除。インデックスを再構築する。"""
    import os
    # パストラバーサル対策: ファイル名にスラッシュやドットドットがあれば拒否
    if ".." in filename or filename.startswith("/") or "\x00" in filename:
        raise HTTPException(status_code=400, detail="不正なファイル名です")

    faq_dir = settings.faq_master_dir.resolve()
    target = (faq_dir / filename).resolve()
    # target が faq_dir 配下であることを保証
    try:
        target.relative_to(faq_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="不正なファイル名です") from None

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"見つかりません: {filename}")

    # 削除実行
    size_bytes = target.stat().st_size
    os.remove(target)

    # インデックス再構築
    new_idx = reload_index()

    audit.record(
        "delete_document",
        user=user["email"],
        filename=filename,
        size_bytes=size_bytes,
        n_chunks_after=len(new_idx.chunks),
    )
    return {
        "deleted": filename,
        "size_bytes": size_bytes,
        "n_chunks_after": len(new_idx.chunks),
    }


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
    except Exception as e:
        # パーサが予期せぬ例外（壊れたPDF/Excel等）を投げても 500 にしない
        audit.record(
            "analyze_error",
            user=user["email"],
            filename=file.filename or "uploaded",
            error=type(e).__name__,
            detail=str(e)[:200],
        )
        raise HTTPException(
            status_code=422,
            detail=f"ファイル解析に失敗しました（{type(e).__name__}）。"
                   f"ファイルが壊れているか、対応していない形式の可能性があります。"
                   f" 詳細: {str(e)[:200]}",
        ) from e
    audit.record(
        "analyze",
        user=user["email"],
        filename=result.filename,
        sha256=result.sha256[:12],
        recommendation=result.recommendation,
        n_chunks=result.n_chunks,
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
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"ファイル解析に失敗しました（{type(e).__name__}）。"
                   f"ファイルが壊れているか、対応していない形式の可能性があります。",
        ) from e

    if result.n_chunks == 0:
        raise HTTPException(
            status_code=422,
            detail="テキストを抽出できなかったため取り込めません。"
                   "スキャン PDF や画像のみの PDF は OCR 処理が必要です（v2 で対応予定）。"
                   "テキスト埋込み済みの PDF または Markdown/Word での提供をお願いします。",
        )

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
