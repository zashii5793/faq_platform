"""FastAPI エントリポイント。Google SSO + 簡易 RAG + Claude 呼び出し。"""
from __future__ import annotations

from functools import lru_cache
from html import escape as _html_escape
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import (
    __version__,
    audit,
    faq_candidate_settings,
    faq_candidates,
    impact,
    runtime_settings,
    shared_qa,
)
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


@app.on_event("startup")
async def _detect_faq_candidates_on_startup() -> None:
    """設定で有効なら起動時に FAQ 候補検出を1回走らせる。失敗してもサービスは続行。"""
    try:
        if faq_candidate_settings.load().auto_detect_on_startup:
            faq_candidates.detect()
    except Exception as e:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning("FAQ 候補検出 失敗: %s", e)


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


def _data_storage_info_html() -> str:
    """データ保管場所と「サーバー管理者以外は直接アクセス不可」を明示するセクション。

    Inquira は完全ローカル保存型のため、データは Inquira を動かしているサーバー内にしか
    存在しない。サーバー管理者（情シス）以外の一般スタッフも、Inquira 提供元（運営）も、
    OS レベルではこのデータには到達できない — それを UI 上で明示する。
    """
    rows_data = [
        ("FAQマスター", settings.faq_master_dir),
        ("検索インデックス", settings.index_path),
        ("監査ログ", settings.audit_log_dir),
        ("フィードバック", settings.feedback_path),
        ("組織設定", settings.org_settings_path),
        ("アップロード原本", settings.raw_upload_dir),
    ]
    rows = "".join(
        f'<div class="data-path-row">'
        f'<div class="data-path-name">{_esc(name)}</div>'
        f'<code class="data-path-value">{_esc(str(Path(p).resolve()))}</code>'
        f"</div>"
        for name, p in rows_data
    )
    return f"""
  <details class="section section-admin" open>
    <summary>💾 データの保管場所</summary>
    <div class="data-paths">{rows}</div>
    <div class="data-access-note">
      <div class="dan-row"><b>🔒 サーバー管理者のみアクセス可</b><br>
        上記パスは <b>このサーバー内</b> のファイルです。OS レベルで読み書きするには
        <b>サーバー管理者権限（SSH ログイン）</b> が必要です。
        一般スタッフが Inquira の UI から見られるのは整形後の本文のみで、ファイル実体には届きません。</div>
      <div class="dan-row" style="margin-top:8px"><b>🌐 Inquira 運営からもアクセス不可</b><br>
        Inquira 提供元はこのサーバーへのアクセス権を <b>持っていません</b>。
        運営側からデータに直接触れることはできず、サポート対応時も
        貴社情シスから明示の許可と SSH 権限の発行があって初めてアクセスが可能になります。</div>
    </div>
  </details>
"""


def _data_trust_line_html() -> str:
    """画面下部に常時表示する、データ主権についての短い注記。"""
    return (
        '<div class="data-trust-line">'
        "🔒 データは貴社サーバー内に保管されています "
        "／ Inquira 運営（提供元）からはアクセスできません"
        "</div>"
    )


def _chat_page(user_email: str) -> str:
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>{_esc(settings.product_name)}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif;
     background:#f7f8fa;color:#1f2937;height:100vh;display:flex;font-size:15px;
     -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}}

aside{{width:300px;background:#fff;border-right:1px solid #e5e7eb;display:flex;flex-direction:column;
      flex-shrink:0;overflow-y:auto}}
.brand{{padding:20px;border-bottom:1px solid #e5e7eb}}
.brand h1{{color:#1a73e8;font-size:24px;font-weight:700;letter-spacing:-.02em}}
.brand p{{color:#6b7280;font-size:13px;margin-top:3px}}
/* サイドバーセクション（details/summary 折り畳み式） */
.section{{padding:0;border-bottom:1px solid #f3f4f6}}
.section > summary{{padding:13px 20px;font-size:12.5px;color:#6b7280;font-weight:600;
                    letter-spacing:.04em;text-transform:uppercase;cursor:pointer;
                    list-style:none;display:flex;align-items:center;gap:8px;
                    user-select:none;transition:background .15s}}
.section > summary::-webkit-details-marker{{display:none}}
.section > summary::before{{content:"▸";color:#9ca3af;font-size:11px;
                            transition:transform .15s;flex-shrink:0;width:10px}}
.section[open] > summary::before{{transform:rotate(90deg)}}
.section > summary:hover{{background:#f9fafb;color:#1a73e8}}
.section > summary > span{{margin-left:auto;font-weight:500;color:#9ca3af;
                            font-size:12px;text-transform:none;letter-spacing:0}}
.section > *:not(summary){{padding-left:20px;padding-right:20px}}
.section > *:not(summary):last-child{{padding-bottom:14px}}
.section.section-admin > summary{{background:#fafafa;color:#9ca3af}}
.section.section-admin[open] > summary{{background:#f3f4f6;color:#6b7280}}
.section-divider{{padding:16px 20px 10px;font-size:11px;color:#9ca3af;text-align:center;
                  font-weight:600;letter-spacing:.1em;text-transform:uppercase;
                  background:#fafbfc;border-bottom:1px solid #f3f4f6}}
.section h3{{font-size:12.5px;color:#9ca3af;font-weight:600;letter-spacing:.04em;
            text-transform:uppercase;margin-bottom:10px;display:flex;align-items:center;gap:6px}}
/* よく聞かれる質問リスト */
.pop-item{{padding:10px 12px;margin:4px -12px;border-radius:8px;cursor:pointer;
           font-size:14px;color:#1f2937;line-height:1.5;display:flex;
           justify-content:space-between;align-items:center;gap:10px;
           transition:background .12s;font-weight:500;
           border-bottom:1px solid #f3f4f6}}
.pop-item:last-child{{border-bottom:0}}
.pop-item:hover{{background:#fff7ed;color:#1a73e8}}
.pop-item .pop-q{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}}
.pop-item .pop-count{{background:#fef3c7;color:#92400e;padding:3px 10px;
                      border-radius:12px;font-size:12px;font-weight:700;flex-shrink:0}}
#popular-queries{{max-height:280px;overflow-y:auto;padding-right:4px}}
#popular-queries::-webkit-scrollbar{{width:6px}}
#popular-queries::-webkit-scrollbar-thumb{{background:#d1d5db;border-radius:3px}}
/* みんなのナレッジ */
.kb-item{{padding:10px 12px;margin:4px -12px;border-radius:8px;cursor:pointer;
          font-size:13.5px;color:#1f2937;line-height:1.5;
          border-bottom:1px solid #f3f4f6;transition:background .12s;font-weight:500}}
.kb-item:last-of-type{{border-bottom:0}}
.kb-item:hover{{background:#ecfdf5;color:#065f46}}
.kb-q-line{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.kb-meta{{display:flex;gap:6px;align-items:center;margin-top:4px;font-size:11px;
          font-weight:400;color:#9ca3af}}
.kb-vote{{background:#d1fae5;color:#065f46;padding:1px 7px;border-radius:10px;
          font-weight:600;font-size:11px}}
.kb-vote.res{{background:#fef3c7;color:#92400e}}
.kb-author{{margin-left:auto;color:#6b7280}}
/* 入力中サジェスト */
.input-suggest{{max-width:960px;margin:0 auto;padding:10px 16px;background:#fffbeb;
                 border:1px solid #fde68a;border-radius:10px 10px 0 0;border-bottom:0;
                 font-size:13px;color:#78350f}}
.input-suggest .sg-title{{font-size:11px;color:#92400e;font-weight:600;
                           letter-spacing:.04em;margin-bottom:6px}}
.input-suggest .sg-item{{padding:6px 8px;border-radius:6px;cursor:pointer;
                          display:flex;justify-content:space-between;align-items:center;
                          gap:8px;transition:background .12s}}
.input-suggest .sg-item:hover{{background:#fef3c7}}
.input-suggest .sg-q{{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;
                       white-space:nowrap}}
.input-suggest .sg-tag{{background:#f59e0b;color:#fff;padding:1px 8px;border-radius:10px;
                         font-size:10.5px;font-weight:600;flex-shrink:0}}
.stat{{display:flex;justify-content:space-between;align-items:center;padding:5px 0;font-size:14px}}
.stat .label{{color:#6b7280}}
.stat .value{{color:#1f2937;font-weight:600}}
.stat .value.big{{font-size:24px;color:#1a73e8;letter-spacing:-.02em}}
.topic-item{{display:flex;justify-content:space-between;font-size:13px;padding:4px 0;color:#374151}}
.topic-item .count{{color:#9ca3af;font-size:11px}}
.history-item{{padding:10px 12px;margin:4px -12px;border-radius:8px;cursor:pointer;
              font-size:14px;color:#1f2937;line-height:1.5;transition:background .12s;
              font-weight:500;border-bottom:1px solid #f3f4f6}}
.history-item:last-child{{border-bottom:0}}
.history-item:hover{{background:#eff6ff;color:#1a73e8}}
#history{{max-height:380px;overflow-y:auto;padding-right:4px}}
#history::-webkit-scrollbar{{width:6px}}
#history::-webkit-scrollbar-thumb{{background:#d1d5db;border-radius:3px}}
#history::-webkit-scrollbar-thumb:hover{{background:#9ca3af}}
.cov-tags{{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}}
.tag{{background:#eef2ff;color:#4338ca;padding:3px 10px;border-radius:999px;font-size:12px}}
.cov-tag{{cursor:pointer;transition:background .12s}}
.cov-tag:hover{{background:#c7d2fe}}
.upload-link{{margin-top:10px;display:block;border:2px dashed #cbd5e1;border-radius:10px;
        padding:12px;text-align:center;font-size:13px;color:#6b7280;text-decoration:none;
        font-weight:500;transition:all .15s}}
.upload-link:hover{{border-color:#1a73e8;background:#eff6ff;color:#1a73e8}}
.fb-row{{display:flex;gap:8px;margin-bottom:8px}}
.fb-pill{{flex:1;background:#f9fafb;border-radius:10px;padding:10px;text-align:center;font-size:13px;
          font-weight:500}}
.fb-pill.up{{color:#10b981}}
.fb-pill.down{{color:#dc2626}}
.fb-pill .num{{font-size:22px;font-weight:700;display:block;letter-spacing:-.02em}}
.fb-issues{{font-size:13px;color:#374151;margin-top:8px}}
.fb-issues li{{padding:10px 12px;margin:3px -12px;list-style:none;line-height:1.5;
                border-radius:8px;cursor:pointer;font-weight:500;
                transition:background .12s;border-bottom:1px solid #f3f4f6}}
.fb-issues li:last-child{{border-bottom:0}}
.fb-issues li:hover{{background:#fef2f2}}
.fb-issues li.empty-list{{cursor:default;font-weight:400}}
.fb-issues li.empty-list:hover{{background:transparent;color:#9ca3af}}
.fb-q-line{{color:#1f2937}}
.fb-q-meta{{font-size:11.5px;color:#9ca3af;margin-top:3px;font-weight:400;display:flex;
            align-items:center;gap:8px}}
.fb-ans-badge{{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}}
.fb-ans-badge.ok{{background:#d1fae5;color:#065f46}}
.fb-ans-badge.ng{{background:#fee2e2;color:#991b1b}}
/* フィードバック数字をクリッカブルに */
.fb-pill:hover{{transform:translateY(-1px);box-shadow:0 2px 8px rgba(0,0,0,.06);
                transition:all .12s}}
.fb-pill .num{{transition:color .12s}}
/* フィードバック詳細モーダル内のスタイル */
.fb-section-title{{font-size:12px;color:#6b7280;text-transform:uppercase;
                    letter-spacing:.04em;margin:18px 0 8px;font-weight:600}}
.fb-section-title:first-child{{margin-top:0}}
.fb-q-box{{background:#f9fafb;padding:14px 16px;border-radius:10px;
            border-left:3px solid #1a73e8;font-size:14.5px;line-height:1.7;
            color:#1f2937;word-break:break-word}}
.fb-src{{display:flex;align-items:center;gap:10px;padding:10px 12px;margin:6px 0;
         background:#fafafa;border-radius:8px;font-size:13.5px;color:#374151}}
.fb-src .src-view-btn{{margin-left:auto}}
.fb-actions{{margin-top:20px;display:flex;justify-content:flex-end}}
.fb-actions .btn-primary{{background:#1a73e8;color:#fff;border:0;padding:10px 22px;
                          border-radius:10px;font-size:14px;cursor:pointer;
                          font-weight:600;transition:all .15s}}
.fb-actions .btn-primary:hover{{box-shadow:0 4px 12px rgba(26,115,232,.3);
                                  transform:translateY(-1px)}}
.fb-list-item{{padding:14px 16px;margin:6px 0;background:#fafafa;border-radius:10px;
                cursor:pointer;transition:background .15s;border-left:3px solid transparent}}
.fb-list-item:hover{{background:#eff6ff;border-left-color:#1a73e8}}
.empty-list{{font-size:12.5px;color:#9ca3af;font-style:italic;padding:4px 0}}

main{{flex:1;display:flex;flex-direction:column;min-width:0}}
.demo-banner{{background:#fef3c7;color:#92400e;padding:10px 16px;font-size:13px;
              border-bottom:1px solid #fcd34d;text-align:center}}
.demo-banner b{{font-weight:600}}
.demo-banner a{{color:#1e40af;text-decoration:underline}}
header{{background:#fff;border-bottom:1px solid #e5e7eb;padding:14px 28px;
       display:flex;justify-content:space-between;align-items:center}}
header .org{{font-size:15px;font-weight:600;color:#1f2937}}
.user{{font-size:13.5px;color:#6b7280}}
.user a{{color:#1a73e8;text-decoration:none;margin-left:10px;font-weight:500}}
.user a:hover{{text-decoration:underline}}
.user a.manual-link{{color:#9ca3af;font-weight:400}}
.user a.manual-link:hover{{color:#1a73e8}}
.chat{{flex:1;overflow-y:auto;padding:28px 36px;max-width:960px;width:100%;margin:0 auto}}
.empty{{text-align:center;color:#9ca3af;margin-top:60px}}
.empty h2{{color:#1f2937;margin-bottom:10px;font-size:26px;font-weight:600;letter-spacing:-.02em}}
.empty p{{margin:8px 0;font-size:15px}}
.suggestions{{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-top:24px;max-width:720px;margin-left:auto;margin-right:auto}}
.chip{{background:#fff;border:1px solid #e5e7eb;padding:10px 18px;border-radius:999px;
      font-size:14px;cursor:pointer;color:#374151;transition:all .15s;font-weight:500}}
.chip:hover{{background:#1a73e8;color:#fff;border-color:#1a73e8;
             box-shadow:0 4px 12px rgba(26,115,232,.25);transform:translateY(-1px)}}
.chip .src-hint{{color:#9ca3af;font-size:11px;margin-left:8px}}
.chip:hover .src-hint{{color:#bfdbfe}}
.chip.popular{{background:#fef3c7;border-color:#fcd34d;color:#78350f}}
.chip.popular:hover{{background:#f59e0b;color:#fff;border-color:#f59e0b;
                     box-shadow:0 4px 12px rgba(245,158,11,.3)}}
.chip.popular .src-hint{{color:#92400e}}
.chip.popular:hover .src-hint{{color:#fff7ed}}
.msg{{margin-bottom:24px}}
.msg.user{{text-align:right}}
.msg.user .bubble{{background:linear-gradient(135deg,#1a73e8 0%,#1557b0 100%);color:#fff;
                    margin-left:auto;box-shadow:0 2px 8px rgba(26,115,232,.18)}}
.msg.bot .bubble{{background:#fff;border:1px solid #e5e7eb;box-shadow:0 1px 4px rgba(0,0,0,.04)}}
.bubble{{padding:14px 18px;border-radius:14px;max-width:78%;display:inline-block;
        line-height:1.7;white-space:pre-wrap;text-align:left;word-break:break-word;
        font-size:15px}}
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
.confidence{{display:inline-flex;align-items:center;gap:8px;margin-top:8px;padding:6px 14px;
            border-radius:999px;font-size:12.5px;font-weight:600;max-width:78%}}
.confidence.high{{background:#d1fae5;color:#065f46}}
.confidence.mid{{background:#fef3c7;color:#92400e}}
.confidence.low{{background:#fed7aa;color:#9a3412}}
.confidence.none{{background:#fee2e2;color:#991b1b}}
.confidence-bar{{display:inline-block;width:70px;height:5px;background:rgba(0,0,0,.1);border-radius:3px;overflow:hidden}}
.confidence-bar > div{{height:100%;background:currentColor}}
.no-answer{{padding:14px 18px;background:#fef2f2;border-left:4px solid #fca5a5;
            border-radius:10px;color:#7f1d1d;font-size:14.5px;line-height:1.75;margin-bottom:6px}}
.no-answer::before{{content:"💭 ";font-size:16px}}
.reference-answer{{background:#fffbeb;border-left:4px solid #f59e0b;padding:14px 18px;
                   border-radius:10px;margin-bottom:6px;color:#78350f;font-size:14.5px;line-height:1.75}}
/* Markdown 回答の整形 */
.md-body{{line-height:1.85;font-size:15px;color:#374151}}
.md-body .md-h1{{font-size:16.5px;font-weight:700;color:#111827;margin:16px 0 10px;
                  padding-bottom:6px;border-bottom:2px solid #1a73e8}}
.md-body .md-h2{{font-size:15.5px;font-weight:600;color:#111827;margin:16px 0 8px;
                  padding:6px 10px;background:linear-gradient(90deg,#eff6ff 0%,transparent 100%);
                  border-left:4px solid #1a73e8;border-radius:0 6px 6px 0}}
.md-body .md-h3{{font-size:14.5px;font-weight:600;color:#1a73e8;margin:14px 0 6px;
                  padding-left:6px;position:relative}}
.md-body .md-h3::before{{content:"▸ ";color:#1a73e8;font-weight:700}}
.md-body .md-h4{{font-size:13px;font-weight:600;color:#4b5563;margin:10px 0 2px}}
.md-body .md-hr{{border:none;border-top:1px dashed #e5e7eb;margin:14px 0}}
.md-body .md-ul{{margin:8px 0;padding-left:8px;list-style:none}}
.md-body .md-ul li{{margin:6px 0;line-height:1.75;padding-left:22px;position:relative}}
.md-body .md-ul li::before{{content:"●";color:#3b82f6;font-size:8px;
                             position:absolute;left:8px;top:9px}}
.md-body .md-br{{height:8px}}
.md-body .md-line{{margin:4px 0}}
.md-body strong{{font-weight:600;color:#1d4ed8;background:linear-gradient(transparent 60%,#dbeafe 60%);
                  padding:0 2px}}
.md-body .md-code{{background:#f3f4f6;padding:2px 7px;border-radius:4px;font-size:12.5px;
                    font-family:Menlo,Consolas,monospace;color:#be123c;
                    border:1px solid #e5e7eb}}
.md-body .md-pre{{background:#0f172a;color:#e2e8f0;padding:12px 16px;border-radius:8px;
                   margin:10px 0;overflow-x:auto;font-size:12.5px;line-height:1.6}}
.md-body .md-pre code{{background:transparent;color:inherit;padding:0;font-size:inherit;border:0}}
/* 出典行: LLM が「**出典:**」と書く行を緑カードで強調 */
.md-body .md-citation{{margin-top:14px;padding:9px 14px;
                        background:linear-gradient(90deg,#ecfdf5 0%,#f0fdf4 100%);
                        border-left:3px solid #10b981;border-radius:0 8px 8px 0;
                        font-size:13px;color:#065f46;line-height:1.6}}
.md-body .md-citation strong{{background:transparent;color:#047857;padding:0}}
/* 全体的な余白感 */
.md-body > .md-line:first-child,
.md-body > .md-h1:first-child,
.md-body > .md-h2:first-child,
.md-body > .md-h3:first-child{{margin-top:0}}
.faq-request{{margin-top:10px;padding:10px 14px;background:#eff6ff;border:1px solid #bfdbfe;
              border-radius:10px;max-width:85%}}
.faq-request-msg{{font-size:12px;color:#1e40af;margin-bottom:8px}}
.faq-request-actions{{display:flex;flex-wrap:wrap;gap:6px}}
.faq-request-btn,.faq-share-btn{{border:0;padding:7px 14px;border-radius:8px;
                  font-size:12px;cursor:pointer;font-weight:500}}
.faq-request-btn{{background:#1a73e8;color:#fff}}
.faq-request-btn:hover{{background:#1557b0}}
.faq-share-btn{{background:#fff;color:#1a73e8;border:1px solid #1a73e8}}
.faq-share-btn:hover{{background:#eff6ff}}
.faq-request-btn:disabled,.faq-share-btn:disabled{{opacity:.6;cursor:not-allowed}}
.faq-request-done{{font-size:12px;color:#065f46;background:#d1fae5;padding:8px 12px;border-radius:6px}}
/* 共有モーダル */
.share-modal-overlay{{position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:9000;
                     display:flex;align-items:center;justify-content:center;padding:16px}}
.share-modal{{background:#fff;border-radius:14px;padding:24px;max-width:520px;width:100%;
              box-shadow:0 12px 40px rgba(0,0,0,.2);max-height:90vh;overflow-y:auto}}
.share-modal h3{{margin:0 0 12px;font-size:16px;color:#111827}}
.share-modal .label{{display:block;font-size:12px;color:#374151;margin:10px 0 4px;font-weight:500}}
.share-modal .q-preview{{background:#f9fafb;padding:10px 12px;border-radius:8px;
                         border-left:3px solid #9ca3af;font-size:13px;color:#1f2937;
                         margin-bottom:6px;word-break:break-word}}
.share-modal textarea{{width:100%;min-height:120px;padding:10px;font-family:inherit;font-size:13px;
                       border:1px solid #d1d5db;border-radius:8px;resize:vertical;line-height:1.6}}
.share-modal textarea:focus{{outline:0;border-color:#1a73e8}}
.share-modal .hint{{font-size:11px;color:#6b7280;margin-top:4px;line-height:1.5}}
.share-modal .check-row{{display:flex;align-items:flex-start;gap:8px;margin-top:14px;
                         padding:10px;background:#fef3c7;border-radius:8px}}
.share-modal .check-row input{{margin-top:2px}}
.share-modal .check-label{{font-size:12px;color:#78350f;line-height:1.5}}
.share-modal .check-label b{{font-weight:600}}
.share-modal .actions{{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}}
.share-modal .btn-primary{{background:#1a73e8;color:#fff;border:0;padding:8px 18px;
                            border-radius:8px;font-size:13px;cursor:pointer;font-weight:500}}
.share-modal .btn-primary:hover{{background:#1557b0}}
.share-modal .btn-cancel{{background:#fff;color:#6b7280;border:1px solid #d1d5db;
                          padding:8px 18px;border-radius:8px;font-size:13px;cursor:pointer}}
.share-modal .btn-cancel:hover{{background:#f9fafb}}
.sources{{margin-top:10px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px;
         padding:12px 16px;font-size:13.5px;max-width:88%}}
.sources summary{{cursor:pointer;color:#374151;font-weight:600;padding:3px 0;font-size:13.5px}}
.src{{padding:12px 0;border-bottom:1px solid #e5e7eb}}
.src:last-child{{border-bottom:0;padding-bottom:4px}}
.src-row{{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:5px}}
.src-name{{font-weight:600;color:#1f2937;font-size:13.5px;flex:1;min-width:0;
           overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.src-chunk-tag{{display:inline-block;background:#dbeafe;color:#1e40af;padding:2px 8px;
                border-radius:5px;font-size:11.5px;font-weight:500;margin-left:8px}}
.src-score{{color:#6b7280;font-size:11.5px;flex-shrink:0;background:#fff;
            padding:3px 10px;border-radius:12px;border:1px solid #e5e7eb;
            font-weight:600;white-space:nowrap}}
.src-score.high{{background:#d1fae5;color:#065f46;border-color:#a7f3d0}}
.src-score.mid{{background:#fef3c7;color:#92400e;border-color:#fde68a}}
.src-score.low{{background:#f3f4f6;color:#6b7280;border-color:#e5e7eb}}
.src-preview{{font-size:12.5px;color:#4b5563;line-height:1.6;background:#fff;
              padding:8px 12px;border-radius:8px;border-left:3px solid #bfdbfe;
              margin-top:6px;word-break:break-word}}
.src-actions{{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;align-items:center}}
.src-view-btn{{background:transparent;color:#1a73e8;border:1px solid #bfdbfe;
                padding:5px 14px;border-radius:8px;font-size:12.5px;cursor:pointer;font-weight:600;
                transition:all .15s}}
.src-view-btn:hover{{background:#eff6ff;border-color:#1a73e8}}
.src-orig-btn{{background:#eff6ff;color:#1a73e8;border:1px solid #bfdbfe;
                padding:5px 14px;border-radius:8px;font-size:12.5px;font-weight:600;
                text-decoration:none;display:inline-block;transition:all .15s}}
.src-orig-btn:hover{{background:#1a73e8;color:#fff;border-color:#1a73e8}}
/* 出典詳細モーダル（参照のみ） */
.chunk-modal-overlay{{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9500;
                     display:flex;align-items:center;justify-content:center;padding:16px}}
.chunk-modal{{background:#fff;border-radius:14px;max-width:780px;width:100%;max-height:90vh;
              display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.25)}}
.chunk-modal-header{{padding:16px 20px;border-bottom:1px solid #e5e7eb;display:flex;
                     justify-content:space-between;align-items:flex-start;gap:10px}}
.chunk-modal-title{{font-size:14px;font-weight:600;color:#111827;flex:1;
                    word-break:break-word;line-height:1.5}}
.chunk-modal-meta{{font-size:11px;color:#6b7280;margin-top:2px}}
.chunk-modal-close{{background:transparent;border:0;font-size:20px;cursor:pointer;
                    color:#9ca3af;padding:0 4px;line-height:1}}
.chunk-modal-close:hover{{color:#1f2937}}
.chunk-modal-actions{{display:flex;align-items:center;gap:10px}}
.chunk-modal-orig{{font-size:12px;color:#1a73e8;text-decoration:none;
                   padding:6px 10px;border:1px solid #bfdbfe;border-radius:6px;
                   background:#eff6ff;white-space:nowrap}}
.chunk-modal-orig:hover{{background:#dbeafe}}
.chunk-modal-body{{padding:18px 20px;overflow-y:auto;flex:1}}
.chunk-modal-text{{font-size:13px;line-height:1.75;color:#1f2937;white-space:pre-wrap;
                   word-break:break-word;background:#f9fafb;padding:14px 16px;
                   border-radius:8px;border-left:3px solid #1a73e8}}
.chunk-modal-section{{margin-top:18px}}
.chunk-modal-section h4{{font-size:12px;color:#6b7280;text-transform:uppercase;
                          letter-spacing:.05em;margin-bottom:8px;font-weight:600}}
.chunk-modal-neighbor{{padding:8px 10px;margin:3px 0;background:#fafafa;border-radius:6px;
                       font-size:12px;color:#4b5563;cursor:pointer;line-height:1.5;
                       border:1px solid transparent}}
.chunk-modal-neighbor:hover{{background:#eff6ff;border-color:#bfdbfe}}
.chunk-modal-neighbor.active{{background:#dbeafe;border-color:#1a73e8;color:#1e3a8a;font-weight:500}}
.chunk-modal-neighbor .nb-tag{{display:inline-block;background:#e5e7eb;color:#374151;
                                padding:0 6px;border-radius:4px;font-size:10.5px;margin-right:6px}}
.chunk-modal-footer{{padding:12px 20px;border-top:1px solid #e5e7eb;font-size:11px;
                     color:#9ca3af;display:flex;justify-content:space-between;align-items:center}}
.sources-hint{{font-size:12px;color:#6b7280;margin-top:6px;font-style:italic;line-height:1.5}}
.feedback{{display:inline-flex;gap:8px;margin-top:10px}}
.feedback button{{background:#fff;border:1px solid #e5e7eb;padding:6px 14px;
                  border-radius:8px;font-size:13px;color:#4b5563;cursor:pointer;
                  font-weight:500;transition:all .15s}}
.feedback button:hover{{background:#f3f4f6;border-color:#9ca3af}}
.feedback button.up.active{{background:#10b981;color:#fff;border-color:#10b981;
                              box-shadow:0 2px 6px rgba(16,185,129,.3)}}
.feedback button.down.active{{background:#dc2626;color:#fff;border-color:#dc2626;
                                box-shadow:0 2px 6px rgba(220,38,38,.3)}}
/* データ保管情報パネル（管理者ビュー） */
.data-paths{{margin-bottom:10px}}
.data-path-row{{display:flex;flex-direction:column;gap:2px;padding:6px 0;
                border-bottom:1px dashed #f3f4f6}}
.data-path-row:last-child{{border-bottom:0;padding-bottom:0}}
.data-path-name{{font-size:11px;color:#6b7280;font-weight:600}}
.data-path-value{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
                  font-size:11px;color:#374151;background:#f9fafb;padding:3px 6px;
                  border-radius:4px;word-break:break-all;display:block;
                  border:1px solid #f3f4f6}}
.data-access-note{{background:#fef9e7;border:1px solid #fde68a;border-radius:8px;
                    padding:10px 12px;font-size:11.5px;color:#78350f;line-height:1.6}}
.dan-row b{{color:#92400e}}
/* フッターの「データ主権」常時表示ライン */
.data-trust-line{{background:#f8fafc;border-top:1px solid #e5e7eb;
                  padding:8px 28px;font-size:11.5px;color:#475569;text-align:center;
                  letter-spacing:.01em}}
footer.input-area{{background:#fff;border-top:1px solid #e5e7eb;padding:16px 28px;
                    box-shadow:0 -1px 4px rgba(0,0,0,.03)}}
.input-wrap{{display:flex;gap:10px;max-width:960px;margin:0 auto}}
input.q{{flex:1;border:1px solid #d1d5db;border-radius:12px;padding:14px 18px;font-size:15px;
          font-family:inherit;transition:all .15s;background:#fafbfc}}
input.q:focus{{outline:none;border-color:#1a73e8;background:#fff;
                box-shadow:0 0 0 4px rgba(26,115,232,.12)}}
button.send{{background:linear-gradient(135deg,#1a73e8 0%,#1557b0 100%);color:#fff;border:0;
              border-radius:12px;padding:0 28px;font-weight:600;cursor:pointer;font-size:15px;
              min-width:80px;transition:all .15s;
              box-shadow:0 2px 6px rgba(26,115,232,.25)}}
button.send:hover{{box-shadow:0 4px 12px rgba(26,115,232,.35);transform:translateY(-1px)}}
button.send:disabled{{background:#9ca3af;box-shadow:none;transform:none;cursor:not-allowed}}
.loading{{display:inline-block;width:12px;height:12px;border:2px solid #e5e7eb;
         border-top-color:#1a73e8;border-radius:50%;animation:spin 1s linear infinite;
         vertical-align:middle;margin-left:6px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style></head><body>

<aside>
  <div class="brand">
    <h1>{_esc(settings.product_name)} <a class="version-badge" href="/api/version" target="_blank" title="クリックでバージョン情報・変更履歴を表示">v{__version__}</a></h1>
    <p>{_esc(settings.org_name)}</p>
  </div>

  <!-- ===== ユーザー向け（よく使う情報） ===== -->
  <details class="section" open>
    <summary>🕐 問い合わせ履歴 <span id="history-count"></span></summary>
    <div id="history"><div class="empty-list">読み込み中…</div></div>
  </details>

  <details class="section" open>
    <summary>⭐ よく聞かれる質問 <span id="popular-count"></span></summary>
    <div id="popular-queries"><div class="empty-list">読み込み中…</div></div>
  </details>

  <details class="section" open>
    <summary>🤝 みんなのナレッジ <span id="kb-count"></span></summary>
    <div id="kb-list"><div class="empty-list">読み込み中…</div></div>
    <a class="upload-link" href="/knowledge-base" style="margin-top:8px">📚 すべて見る</a>
  </details>

  <!-- ===== 管理者向け（折りたたみ可・デフォルト閉じる） ===== -->
  <div class="section-divider">— 管理者ビュー —</div>

  <details class="section section-admin" open>
    <summary>📊 分析（直近）</summary>
    <div class="stat"><span class="label">質問数</span><span class="value big" id="stat-queries">-</span></div>
    <div class="stat"><span class="label">回答率</span><span class="value" id="stat-answerrate">-</span></div>
    <div class="stat"><span class="label">平均確信度</span><span class="value" id="stat-confidence">-</span></div>
    <div class="stat" style="margin-top:6px"><span class="label">トップトピック</span></div>
    <div id="top-topics"><div class="empty-list">読み込み中…</div></div>
  </details>

  <details class="section section-admin" open>
    <summary>📚 取り込み状況</summary>
    <div class="stat"><span class="label">取り込み済み文書</span><span class="value" id="stat-docs">-</span></div>
    <div class="stat"><span class="label">総チャンク数</span><span class="value" id="stat-chunks">-</span></div>
    <a class="upload-link" href="/admin/upload">📁 ファイルを追加</a>
  </details>

  <details class="section section-admin" open>
    <summary>📁 カバー領域</summary>
    <div style="font-size:11px;color:#6b7280;margin-bottom:4px">取り込み済み文書のタグ</div>
    <div class="cov-tags" id="cov-tags"></div>
  </details>

  <details class="section section-admin" open>
    <summary>💬 フィードバック</summary>
    <div class="fb-row">
      <div class="fb-pill up"><span class="num" id="fb-up">0</span>👍 役立った</div>
      <div class="fb-pill down"><span class="num" id="fb-down">0</span>👎 要改善</div>
    </div>
  </details>

  <details class="section section-admin" open>
    <summary>⚠ 改善要望のあった質問 <span id="fb-issues-count"></span></summary>
    <ul id="fb-issues"><li class="empty-list" style="list-style:none;padding-left:0">なし</li></ul>
  </details>
{_data_storage_info_html()}
</aside>

<main>
  <header>
    <button class="menu-btn" id="menuBtn" aria-label="メニューを開く">☰</button>
    <div class="org">{_esc(settings.org_name)}の{_esc(settings.assistant_role)}</div>
    <div class="user">{user_email}<a class="manual-link" href="https://github.com/zashii5793/faq_platform#readme" target="_blank" rel="noopener" title="使い方マニュアル（GitHub）">📖 マニュアル</a><a href="/auth/logout">ログアウト</a></div>
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
  {_data_trust_line_html()}
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
    const histCount=document.getElementById('history-count');
    if(histCount) histCount.textContent = s.history.length ? `(${{s.history.length}}件)` : '';
    hist.innerHTML=s.history.length
      ? s.history.map(h=>`<div class="history-item" data-q="${{escape(h.question)}}" title="クリックでもう一度質問する"><div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${{escape(h.question.slice(0,60))}}${{h.question.length>60?'…':''}}</div><div style="color:#9ca3af;font-size:11px;font-weight:400;margin-top:2px">${{relTime(h.ts)}}</div></div>`).join('')
      : '<div class="empty-list">まだ履歴がありません</div>';
    hist.querySelectorAll('.history-item').forEach(el=>el.onclick=()=>{{input.value=el.dataset.q;form.requestSubmit();}});
    const tags=document.getElementById('cov-tags');
    tags.innerHTML=s.knowledge.documents.slice(0,8).map(d=>`<span class="tag cov-tag" data-doc="${{escape(d)}}" title="クリックで内容を表示">${{escape(d.replace('.md',''))}}</span>`).join('') || '<span class="empty-list">なし</span>';
    tags.querySelectorAll('.cov-tag').forEach(el=>{{ el.onclick=()=>openChunkViewer(el.dataset.doc); }});
    document.getElementById('fb-up').textContent=s.feedback.up;
    document.getElementById('fb-down').textContent=s.feedback.down;
    const issues=document.getElementById('fb-issues');
    const downEntries = s.feedback.down_entries || [];
    issues.innerHTML = downEntries.length
      ? downEntries.map((e,i)=>{{
          const ansBadge = e.has_answer
            ? '<span class="fb-ans-badge ok">✓回答済</span>'
            : '<span class="fb-ans-badge ng">⚠未回答</span>';
          return `<li data-idx="${{i}}" title="クリックで詳細を表示">
            <div class="fb-q-line">${{escape(e.question.slice(0,60))}}${{e.question.length>60?'…':''}}</div>
            <div class="fb-q-meta">${{ansBadge}} 確信度 ${{e.confidence}}%</div>
          </li>`;
        }}).join('')
      : '<li class="empty-list" style="list-style:none;padding-left:0">なし</li>';
    issues.querySelectorAll('li[data-idx]').forEach(el=>el.onclick=()=>{{
      openFeedbackDetail(downEntries[+el.dataset.idx], '👎 改善要望のあった質問');
    }});
    // フィードバック「役立った/要改善」の数字クリックで一覧モーダル
    const fbUpEl = document.getElementById('fb-up');
    const fbDownEl = document.getElementById('fb-down');
    if(fbUpEl){{
      fbUpEl.style.cursor = (s.feedback.up_entries||[]).length ? 'pointer' : 'default';
      fbUpEl.title = (s.feedback.up_entries||[]).length ? 'クリックで詳細一覧' : '';
      fbUpEl.onclick = ()=> {{
        if((s.feedback.up_entries||[]).length) openFeedbackList(s.feedback.up_entries, '👍 役に立ったと評価された質問');
      }};
    }}
    if(fbDownEl){{
      fbDownEl.style.cursor = downEntries.length ? 'pointer' : 'default';
      fbDownEl.title = downEntries.length ? 'クリックで詳細一覧' : '';
      fbDownEl.onclick = ()=> {{
        if(downEntries.length) openFeedbackList(downEntries, '👎 改善が必要と評価された質問');
      }};
    }}
    // サイドバー「よく聞かれる質問」（最新の人気質問・クリックで再質問）
    const popList = document.getElementById('popular-queries');
    const popCount = document.getElementById('popular-count');
    const popData = s.popular_queries || [];
    if(popList){{
      if(popCount) popCount.textContent = popData.length ? `(${{popData.length}}件)` : '';
      popList.innerHTML = popData.length
        ? popData.slice(0,30).map(p=>`<div class="pop-item" data-q="${{escape(p.question)}}" title="クリックでもう一度質問する"><span class="pop-q">${{escape(p.question.slice(0,60))}}${{p.question.length>60?'…':''}}</span><span class="pop-count">${{p.count}}回</span></div>`).join('')
        : '<div class="empty-list">まだ集計データがありません</div>';
      popList.querySelectorAll('.pop-item').forEach(el=>el.onclick=()=>{{input.value=el.dataset.q;form.requestSubmit();}});
    }}
    // サイドバー「みんなのナレッジ」: 共有Q&A の直近を表示
    loadSidebarKB();
    // 改善要望のあった質問のカウント表示
    const fbCnt = document.getElementById('fb-issues-count');
    if(fbCnt) fbCnt.textContent = s.feedback.down_questions.length ? `(${{s.feedback.down_questions.length}}件)` : '';
    // サジェスト：人気質問（過去30日に2回以上聞かれたもの）を優先、
    // 不足分は文書から動的生成で補完
    if(suggestionsEl){{
      const pop=s.popular_queries||[];
      const docs=s.knowledge.documents||[];
      const chips=[];
      // 人気質問を優先（実際にユーザーが聞いている質問なのでヒット率高）
      for(const p of pop.slice(0,4)){{
        chips.push(`<div class="chip popular" data-q="${{escape(p.question)}}">⭐ ${{escape(p.question.slice(0,40))}}${{p.question.length>40?'…':''}} <span class="src-hint">${{p.count}}回</span></div>`);
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
    // 「**出典:**」「**Source:**」「**参考:**」で始まる行は出典カードとして強調表示
    if(/^\\*\\*(出典|Source|参考)[:：]\\*\\*/.test(line.trim())){{
      out.push('<div class="md-citation">'+inlineMd(line)+'</div>');
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
      html+='<div class="no-answer">'+renderMarkdown(escape(data.answer))+'</div>';
    }} else if(data.is_reference) {{
      html+='<div class="reference-answer">'+renderMarkdown(escape(data.answer))+'</div>';
    }} else {{
      html+='<div class="md-body">'+renderMarkdown(escape(data.answer))+'</div>';
    }}
    html+='<div><span class="confidence '+confCls+'">'
          +'確信度 '+conf+'% · '+confLabel
          +'<span class="confidence-bar"><div style="width:'+conf+'%"></div></span></span></div>';
    if(data.sources && data.sources.length){{
      // has_answer=false でもキーワード検索で引っかかったチャンクは「関連候補」として提示
      const sourceLabel = data.has_answer
        ? `📎 参照ドキュメント ${{data.sources.length}}件`
        : `🔍 キーワード検索で見つかった関連候補 ${{data.sources.length}}件`;
      const hint = data.has_answer ? '' :
        '<div class="sources-hint">公式FAQには登録されていませんが、以下のチャンクがキーワードに一致しました。参考までにご確認ください。</div>';
      html+='<details class="sources" open><summary>'+sourceLabel+'</summary>';
      html+=hint;
      for(const s of data.sources){{
        // チャンクID から番号部分を抽出。"foo.md#3" → "3"
        const chunkRaw = (s.chunk_id||'').includes('#') ? s.chunk_id.split('#').pop() : '';
        // 数値だけのチャンクは「セクション N」、それ以外（例: xlsx の "Sheet0!r3"）はそのまま
        const chunkLabel = chunkRaw
          ? (/^\d+$/.test(chunkRaw) ? `セクション ${{chunkRaw}}` : chunkRaw)
          : '';
        // 関連度の色分け + ラベル（ユーザー視認性のため「高/中/低」を併記）
        let scoreCls = 'low', scoreLabel = '低';
        if(s.score >= 0.30){{ scoreCls = 'high'; scoreLabel = '高'; }}
        else if(s.score >= 0.15){{ scoreCls = 'mid'; scoreLabel = '中'; }}
        const preview = (s.preview||'').trim();
        const isShared = (s.source||'').startsWith('user-shared-');
        const sharedBadge = isShared
          ? '<span class="src-shared-tag" title="社員が共有した非公式回答（管理者承認前・参考として表示）">💬 ユーザー提供</span>'
          : '';
        const displayName = isShared
          ? '💬 ユーザー提供回答'  // ファイル名のままより分かりやすく
          : escape(s.source);
        // 原本ファイルが保存されていれば、新タブで開くリンクも併置（画像・図表確認用）
        const origBtn = s.original_filename
          ? '<a class="src-orig-btn" href="/api/originals/'
            + encodeURIComponent(s.original_filename)
            + '" target="_blank" rel="noopener" title="原本ファイル（PDF など）を新タブで開く">📎 原本を開く</a>'
          : '';
        html += '<div class="src '+(isShared?'shared':'')+'" data-chunk-id="'+escape(s.chunk_id||'')+'">'
              + '<div class="src-row">'
              +   '<span class="src-name">📄 '+displayName+sharedBadge
              +     (chunkLabel && !isShared ? '<span class="src-chunk-tag" title="ファイル内で取り込み時に分割された該当箇所（内部連番）">'+escape(chunkLabel)+'</span>' : '')
              +   '</span>'
              +   '<span class="src-score '+scoreCls+'">関連度 '+scoreLabel+' ('+s.score.toFixed(2)+')</span>'
              + '</div>'
              + (preview ? '<div class="src-preview">'+escape(preview)+'…</div>' : '')
              + '<div class="src-actions">'
              +   '<button class="src-view-btn" data-cid="'+escape(s.chunk_id||'')+'">🔍 全文を見る</button>'
              +   origBtn
              + '</div>'
              + '</div>';
      }}
      html+='</details>';
    }}
    // FAQ追加リクエストボタン（has_answer=false または is_reference のとき表示）
    const reqId='req-'+Date.now();
    if(!data.has_answer || data.is_reference){{
      html+=`<div class="faq-request" id="${{reqId}}">`
        +`<div class="faq-request-msg">💡 この質問が公式FAQに登録されていません。どちらか選んで管理者に届けましょう。</div>`
        +`<div class="faq-request-actions">`
        +  `<button class="faq-request-btn" data-q="${{escape(q)}}">📩 FAQ追加をリクエスト</button>`
        +  `<button class="faq-share-btn" data-q="${{escape(q)}}">💬 自分で見つけた答えを共有</button>`
        +`</div>`
        +`</div>`;
    }}
    const fbId='fb-'+Date.now();
    html+=`<div class="feedback" id="${{fbId}}"><button data-vote="up">👍 役に立った</button><button data-vote="down">👎 改善が必要</button></div>`;
    wait.querySelector('.bubble').innerHTML=html;
    // 出典詳細「全文を見る」ボタンの動作
    wait.querySelectorAll('.src-view-btn').forEach(btn => {{
      btn.onclick = () => openChunkViewer(btn.dataset.cid);
    }});
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
      // 「自分で見つけた答えを共有」モーダル
      const shareBtn=reqBox.querySelector('.faq-share-btn');
      if(shareBtn){{
        shareBtn.onclick=()=>{{
          openShareAnswerModal(q, async ({{answer, share}})=>{{
            try{{
              const r=await fetch('/api/faq-requests',{{method:'POST',
                headers:{{'Content-Type':'application/json'}},
                body:JSON.stringify({{question:q, answer, share}})}});
              if(!r.ok) throw new Error((await r.json()).detail||r.statusText);
              const result = await r.json();
              const indexedNote = result.indexed
                ? '<br>🔍 検索インデックスへの反映処理を開始しました。数分以内に他の人の検索結果にも表示されるようになります。'
                : '';
              const msg = share
                ? '✅ 教えてもらった回答を共有しました。管理者が確認後、公式FAQに追加されます。' + indexedNote
                : '✅ 自分用メモとして記録しました。管理者には共有されません。';
              reqBox.innerHTML='<div class="faq-request-done">'+msg+'</div>';
            }}catch(e){{
              alert('送信失敗: '+e.message);
            }}
          }});
        }};
      }}
    }}
    loadStats();
  }}catch(err){{wait.querySelector('.bubble').textContent='エラー: '+err.message}}
  sendBtn.disabled=false;input.focus();
}};

// フィードバック1件の詳細モーダル
async function openFeedbackDetail(entry, title){{
  const overlay = document.createElement('div');
  overlay.className = 'chunk-modal-overlay';
  const ansBadge = entry.has_answer
    ? '<span class="fb-ans-badge ok">✓回答済</span>'
    : '<span class="fb-ans-badge ng">⚠未回答</span>';
  const confCls = entry.confidence >= 80 ? 'high'
                : entry.confidence >= 50 ? 'mid'
                : entry.confidence >= 20 ? 'low' : 'none';
  const sourceLines = (entry.sources||[]).length
    ? entry.sources.map(sid => {{
        const fname = sid.includes('#') ? sid.split('#')[0] : sid;
        const cid = sid.includes('#') ? sid.split('#').pop() : '';
        const cidLabel = cid ? (/^\\d+$/.test(cid) ? 'セクション '+cid : cid) : '';
        return `<div class="fb-src" data-cid="${{escape(sid)}}">📄 ${{escape(fname)}}${{cidLabel ? ' <span class="src-chunk-tag">'+escape(cidLabel)+'</span>' : ''}}<button class="src-view-btn">🔍 全文を見る</button></div>`;
      }}).join('')
    : '<div class="empty-list">参照ソースなし（回答できなかった質問）</div>';
  overlay.innerHTML = `
    <div class="chunk-modal">
      <div class="chunk-modal-header">
        <div>
          <div class="chunk-modal-title">${{title}}</div>
          <div class="chunk-modal-meta">${{ansBadge}} 確信度 ${{entry.confidence}}% · ${{new Date(entry.ts).toLocaleString('ja-JP')}}</div>
        </div>
        <button class="chunk-modal-close" id="fbm-close">×</button>
      </div>
      <div class="chunk-modal-body">
        <div class="fb-section-title">📝 質問内容</div>
        <div class="fb-q-box">${{escape(entry.question)}}</div>
        <div class="fb-section-title">📎 回答時に参照したドキュメント</div>
        ${{sourceLines}}
        <div class="fb-actions">
          <button class="btn-primary" id="fbm-reask">💬 もう一度質問する</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = ()=> overlay.remove();
  overlay.querySelector('#fbm-close').onclick = close;
  overlay.onclick = e => {{ if(e.target === overlay) close(); }};
  overlay.querySelectorAll('.fb-src').forEach(el => {{
    el.querySelector('.src-view-btn').onclick = (ev) => {{
      ev.stopPropagation();
      openChunkViewer(el.dataset.cid);
    }};
  }});
  overlay.querySelector('#fbm-reask').onclick = ()=>{{
    close();
    const inputEl = document.getElementById('q');
    if(inputEl){{ inputEl.value = entry.question; document.getElementById('qa').requestSubmit(); }}
  }};
}}

// フィードバック一覧モーダル（👍 / 👎 数字クリック）
function openFeedbackList(entries, title){{
  const overlay = document.createElement('div');
  overlay.className = 'chunk-modal-overlay';
  const items = entries.map((e,i) => {{
    const ansBadge = e.has_answer
      ? '<span class="fb-ans-badge ok">✓回答済</span>'
      : '<span class="fb-ans-badge ng">⚠未回答</span>';
    return `<div class="fb-list-item" data-idx="${{i}}">
      <div class="fb-q-line">${{escape(e.question)}}</div>
      <div class="fb-q-meta">${{ansBadge}} 確信度 ${{e.confidence}}% · 参照 ${{(e.sources||[]).length}}件 · ${{new Date(e.ts).toLocaleString('ja-JP')}}</div>
    </div>`;
  }}).join('');
  overlay.innerHTML = `
    <div class="chunk-modal">
      <div class="chunk-modal-header">
        <div><div class="chunk-modal-title">${{title}}</div>
        <div class="chunk-modal-meta">${{entries.length}}件 — クリックで詳細を表示</div></div>
        <button class="chunk-modal-close" id="fbl-close">×</button>
      </div>
      <div class="chunk-modal-body">${{items}}</div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = ()=> overlay.remove();
  overlay.querySelector('#fbl-close').onclick = close;
  overlay.onclick = e => {{ if(e.target === overlay) close(); }};
  overlay.querySelectorAll('.fb-list-item').forEach(el => {{
    el.onclick = ()=> {{
      close();
      openFeedbackDetail(entries[+el.dataset.idx], title);
    }};
  }});
}}

// 出典チャンク詳細モーダル（参照のみ）
async function openChunkViewer(chunkId){{
  const overlay = document.createElement('div');
  overlay.className = 'chunk-modal-overlay';
  overlay.innerHTML = `
    <div class="chunk-modal">
      <div class="chunk-modal-header">
        <div>
          <div class="chunk-modal-title">⏳ 読み込み中…</div>
          <div class="chunk-modal-meta" id="cv-meta"></div>
        </div>
        <div class="chunk-modal-actions">
          <a class="chunk-modal-orig" id="cv-orig" hidden target="_blank" rel="noopener"
             title="ブラウザで原本ファイル（PDF など）を開く">📎 原本を開く</a>
          <button class="chunk-modal-close" id="cv-close">×</button>
        </div>
      </div>
      <div class="chunk-modal-body">
        <div class="chunk-modal-text" id="cv-text">読み込み中…</div>
        <div class="chunk-modal-section" id="cv-neighbors-wrap" hidden>
          <h4>📚 同じファイルの他のチャンク</h4>
          <div id="cv-neighbors"></div>
        </div>
      </div>
      <div class="chunk-modal-footer">
        <span>参照のみ・編集不可</span>
        <span>クリックで他のチャンクへ移動できます</span>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = ()=> overlay.remove();
  overlay.querySelector('#cv-close').onclick = close;
  overlay.onclick = e => {{ if(e.target === overlay) close(); }};
  document.addEventListener('keydown', function esc(e){{
    if(e.key === 'Escape'){{ close(); document.removeEventListener('keydown', esc); }}
  }});

  async function load(cid){{
    overlay.querySelector('#cv-text').textContent = '読み込み中…';
    try {{
      const r = await fetch('/api/chunks?chunk_id=' + encodeURIComponent(cid));
      if(!r.ok) throw new Error((await r.json()).detail || r.statusText);
      const data = await r.json();
      const c = data.chunk;
      const chunkRaw = (c.chunk_id||'').includes('#') ? c.chunk_id.split('#').pop() : '';
      const chunkLabel = chunkRaw
        ? (/^\\d+$/.test(chunkRaw) ? `セクション ${{chunkRaw}}` : chunkRaw)
        : '';
      overlay.querySelector('.chunk-modal-title').textContent = '📄 ' + c.source;
      overlay.querySelector('#cv-meta').textContent = chunkLabel || c.chunk_id;
      overlay.querySelector('#cv-text').textContent = c.text;
      // 原本（PDF/Excel 等）が保存されていればリンクを有効化
      const origLink = overlay.querySelector('#cv-orig');
      if(data.original_filename){{
        origLink.href = '/api/originals/' + encodeURIComponent(data.original_filename);
        origLink.hidden = false;
      }} else {{
        origLink.hidden = true;
      }}
      // 同じファイルの他チャンク
      const wrap = overlay.querySelector('#cv-neighbors-wrap');
      const list = overlay.querySelector('#cv-neighbors');
      if((data.neighbors||[]).length > 1){{
        wrap.hidden = false;
        list.innerHTML = data.neighbors.map(n => {{
          const r2 = (n.chunk_id||'').includes('#') ? n.chunk_id.split('#').pop() : '';
          const lbl = r2 ? (/^\\d+$/.test(r2) ? 'セクション '+r2 : r2) : '';
          const active = n.chunk_id === c.chunk_id ? 'active' : '';
          return `<div class="chunk-modal-neighbor ${{active}}" data-cid="${{escape(n.chunk_id)}}">`
               + (lbl ? `<span class="nb-tag">${{escape(lbl)}}</span>` : '')
               + escape(n.preview||'(空)')
               + `</div>`;
        }}).join('');
        list.querySelectorAll('.chunk-modal-neighbor').forEach(el => {{
          el.onclick = () => {{
            list.querySelectorAll('.chunk-modal-neighbor').forEach(x => x.classList.remove('active'));
            el.classList.add('active');
            load(el.dataset.cid);
          }};
        }});
      }} else {{
        wrap.hidden = true;
      }}
    }} catch(e) {{
      overlay.querySelector('#cv-text').textContent = '読み込み失敗: ' + e.message;
    }}
  }}
  load(chunkId);
}}

// 「自分で見つけた答えを共有」モーダルを開く
function openShareAnswerModal(question, onSubmit){{
  const overlay = document.createElement('div');
  overlay.className = 'share-modal-overlay';
  overlay.innerHTML = `
    <div class="share-modal">
      <h3>💬 自分で見つけた答えを共有</h3>
      <span class="label">質問</span>
      <div class="q-preview">${{escape(question)}}</div>
      <span class="label">人から教えてもらった、または自分で見つけた回答</span>
      <textarea id="share-answer-text" placeholder="例: 部長に聞いたところ、年度更新は人事マスタを最初に更新する必要があるとのこと。手順書は社内Wikiにあり..."></textarea>
      <div class="hint">空欄でも送信できますが、回答があると他の人がすぐ参照できます。</div>
      <div class="check-row">
        <input type="checkbox" id="share-checkbox" checked>
        <label for="share-checkbox" class="check-label">
          <b>他の人にも役立つと思うので、管理者に共有する</b><br>
          チェックを外すと「自分用メモ」として記録され、管理者には届きません。
        </label>
      </div>
      <div class="actions">
        <button class="btn-cancel" id="share-cancel">キャンセル</button>
        <button class="btn-primary" id="share-submit">📤 送信</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  const textarea = overlay.querySelector('#share-answer-text');
  const checkbox = overlay.querySelector('#share-checkbox');
  const submit = overlay.querySelector('#share-submit');
  const cancel = overlay.querySelector('#share-cancel');
  textarea.focus();
  const close = ()=> overlay.remove();
  cancel.onclick = close;
  overlay.onclick = e => {{ if(e.target === overlay) close(); }};
  submit.onclick = async ()=>{{
    submit.disabled = true; submit.textContent = '送信中…';
    try {{
      await onSubmit({{
        answer: textarea.value.trim(),
        share: checkbox.checked
      }});
      close();
    }} catch(e) {{
      submit.disabled = false; submit.textContent = '📤 送信';
    }}
  }};
}}

loadStats();
setInterval(loadStats, 30000);

// サイドバー「みんなのナレッジ」: 共有Q&A の直近5件を表示
async function loadSidebarKB(){{
  const list = document.getElementById('kb-list');
  const cnt = document.getElementById('kb-count');
  if(!list) return;
  try {{
    const r = await fetch('/api/knowledge-base?limit=5');
    if(!r.ok) throw new Error(r.statusText);
    const data = await r.json();
    if(cnt) cnt.textContent = data.total ? `(${{data.total}}件)` : '';
    if(!data.items.length){{
      list.innerHTML = '<div class="empty-list">まだ共有された回答はありません</div>';
      return;
    }}
    list.innerHTML = data.items.map(x => {{
      const upBadge = x.votes_up > 0 ? `<span class="kb-vote">👍${{x.votes_up}}</span>` : '';
      const resBadge = x.resolved_count > 0 ? `<span class="kb-vote res">✅${{x.resolved_count}}</span>` : '';
      return `<div class="kb-item" data-q="${{escape(x.question)}}" title="クリックでこの質問を投げる">
        <div class="kb-q-line">${{escape(x.question.slice(0,55))}}${{x.question.length>55?'…':''}}</div>
        <div class="kb-meta">${{upBadge}}${{resBadge}}<span class="kb-author">${{escape((x.contributor||'').split('@')[0]||'匿名')}}</span></div>
      </div>`;
    }}).join('');
    list.querySelectorAll('.kb-item').forEach(el => el.onclick = ()=>{{
      input.value = el.dataset.q;
      form.requestSubmit();
    }});
  }} catch(e) {{
    list.innerHTML = '<div class="empty-list">読み込み失敗</div>';
  }}
}}

// 入力中のリアルタイムサジェスト（人気質問・共有Q&A から類似抽出）
let suggestionTimer;
const suggestionBox = document.createElement('div');
suggestionBox.className = 'input-suggest';
suggestionBox.hidden = true;
input.parentElement.parentElement.insertBefore(suggestionBox, input.parentElement.parentElement.firstChild);

async function showInputSuggestions(){{
  const q = input.value.trim();
  if(q.length < 2){{ suggestionBox.hidden = true; return; }}
  // 共有Q&A の検索 API を流用
  try {{
    const r = await fetch('/api/knowledge-base?q=' + encodeURIComponent(q) + '&limit=5');
    if(!r.ok){{ suggestionBox.hidden = true; return; }}
    const data = await r.json();
    if(!data.items.length){{ suggestionBox.hidden = true; return; }}
    suggestionBox.innerHTML = '<div class="sg-title">💡 似た質問が既にあります</div>' +
      data.items.map(x => `<div class="sg-item" data-q="${{escape(x.question)}}">
        <span class="sg-q">${{escape(x.question.slice(0,60))}}${{x.question.length>60?'…':''}}</span>
        ${{x.resolved_count>0?`<span class="sg-tag">✅${{x.resolved_count}}</span>`:''}}
      </div>`).join('');
    suggestionBox.hidden = false;
    suggestionBox.querySelectorAll('.sg-item').forEach(el => el.onclick = ()=>{{
      input.value = el.dataset.q;
      suggestionBox.hidden = true;
      form.requestSubmit();
    }});
  }} catch(e) {{ suggestionBox.hidden = true; }}
}}
input.addEventListener('input', () => {{
  clearTimeout(suggestionTimer);
  suggestionTimer = setTimeout(showInputSuggestions, 280);
}});
input.addEventListener('blur', () => setTimeout(()=>suggestionBox.hidden=true, 200));

// URL の ?q=... があれば自動で質問を投入（共有Q&A 一覧から飛ばすため）
(() => {{
  const params = new URLSearchParams(location.search);
  const auto = params.get('q');
  if(auto){{
    input.value = auto;
    setTimeout(()=>form.requestSubmit(), 100);
    history.replaceState(null, '', '/');
  }}
}})();

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
    preview: str = ""  # チャンクの先頭プレビュー（UI 上で「何が引っかかったか」を見せる）
    original_filename: str | None = None  # 原本（PDF 等）が保存されていればファイル名


@lru_cache(maxsize=512)
def _resolve_original_filename(md_source: str) -> str | None:
    """.md ファイルの 1行目 ``# <元ファイル名>`` から原本ファイル名を解決。

    raw_upload_dir に実体がある場合のみ返す（旧データや欠落分は None）。
    検索ホットパスで N 件の出典それぞれに呼ばれるため lru_cache で I/O 削減。
    サーバー再起動でキャッシュは破棄されるので、再取り込み後は restart で反映。
    """
    try:
        md_path = settings.faq_master_dir / md_source
        if not md_path.is_file():
            return None
        first_line = md_path.read_text(encoding="utf-8").split("\n", 1)[0].strip()
        if not first_line.startswith("# "):
            return None
        candidate = Path(first_line[2:].strip()).name
        if not candidate:
            return None
        if (settings.raw_upload_dir / candidate).is_file():
            return candidate
        return None
    except OSError:
        return None


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


# LLM が「答えられない」と判断したフレーズ。検出時は sources / confidence を 0 に揃える
_NO_ANSWER_MARKERS = (
    "該当情報が見つかりませんでした",
    "関連する情報も見つかりませんでした",
)


def _llm_said_no_answer(response_text: str) -> bool:
    """LLM が「該当情報なし」と返したかを判定する。"""
    return any(m in response_text for m in _NO_ANSWER_MARKERS)


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

    # 出典の preview テキスト（チャンク先頭から)。UI が「何が引っかかったか」を表示する。
    # original_filename を載せておくと、出典直下に「原本を開く」リンクを出せる
    source_list = [
        Source(
            chunk_id=c.chunk_id,
            source=c.source,
            score=s,
            preview=c.text.strip().replace("\n", " ")[:140],
            original_filename=_resolve_original_filename(c.source),
        )
        for c, s in chunks
    ]

    # LLM が「該当情報なし」と判断したケースは、信号（confidence / has_answer）を揃える
    # ただし sources は残す（キーワード検索でヒットした関連候補として UI 表示）
    if _llm_said_no_answer(response_text):
        audit.record(
            "query",
            user=user["email"],
            question=masked_q,
            sources=[c.chunk_id for c, _ in chunks],
            confidence=0,
            answered=False,
            llm_no_answer=True,
        )
        return AskResponse(
            answer=response_text,
            sources=source_list,
            confidence=0,
            has_answer=False,
            is_reference=False,
        )

    audit.record(
        "query",
        user=user["email"],
        question=masked_q,
        sources=[c.chunk_id for c, _ in chunks],
        confidence=confidence,
        answered=True,
        answer=response_text,
        is_reference=is_reference,
    )
    return AskResponse(
        answer=response_text,
        sources=source_list,
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
    return HTMLResponse(_upload_page().replace("__VERSION__", __version__))


def _upload_page() -> str:
    return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ナレッジ追加 — Inquira</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif;
     background:#f7f8fa;color:#1f2937;min-height:100vh;padding:32px;font-size:15px;
     -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
.modal{background:#fff;max-width:980px;margin:0 auto;border-radius:16px;overflow:hidden;
       box-shadow:0 8px 32px rgba(0,0,0,.08)}
.modal-header{padding:20px 28px;border-bottom:1px solid #e5e7eb;display:flex;
              justify-content:space-between;align-items:center;background:#fafbfc}
.modal-header h2{font-size:20px;color:#111827;font-weight:600;letter-spacing:-.02em}
.modal-header h2 span{color:#1a73e8}
.modal-body{padding:28px}
/* バージョンバッジ */
.version-badge{display:inline-block;background:#e5e7eb;color:#6b7280;
                font-size:10px;font-weight:500;padding:1px 7px;border-radius:10px;
                vertical-align:middle;margin-left:6px;letter-spacing:.02em}
/* 共有(ユーザー提供)出典の枠スタイル */
.src.shared{background:#fef3c7;border-left:3px solid #f59e0b;padding-left:8px;
              margin-left:-8px}
.src-shared-tag{display:inline-block;background:#fbbf24;color:#78350f;
                  padding:1px 7px;border-radius:10px;font-size:10px;font-weight:600;
                  margin-left:6px}
/* 管理画面タブ */
.admin-tabs{display:flex;flex-wrap:wrap;gap:4px;padding:5px;background:#f3f4f6;
            border-radius:12px;margin-bottom:28px}
.admin-tab{flex:1;min-width:140px;padding:11px 18px;background:transparent;border:0;
           border-radius:10px;font-size:14px;font-weight:500;color:#6b7280;
           cursor:pointer;transition:all .15s;white-space:nowrap}
.admin-tab:hover{background:#fff;color:#1f2937}
.admin-tab.active{background:#fff;color:#1a73e8;box-shadow:0 2px 6px rgba(0,0,0,.08);font-weight:600}
.tab-badge{display:inline-block;background:#ef4444;color:#fff;font-size:10px;
           padding:1px 7px;border-radius:999px;margin-left:4px;font-weight:600;vertical-align:middle}
.admin-pane[hidden]{display:none}
/* === KPI カード (削減効果タブ) === */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:12px 0 24px}
.kpi-card{background:linear-gradient(180deg,#f0fdfa 0%,#ccfbf1 100%);
          border:1px solid #99f6e4;border-radius:12px;padding:18px 16px}
.kpi-card .kpi-num{font-size:30px;font-weight:700;color:#0f766e;line-height:1.1}
.kpi-card .kpi-num small{font-size:14px;font-weight:500;color:#475569;margin-left:4px}
.kpi-card .kpi-label{font-size:11px;color:#475569;margin-top:6px;letter-spacing:.04em;text-transform:uppercase}
.kpi-card .kpi-sub{font-size:12px;color:#475569;margin-top:8px}
.kpi-card .kpi-sub .pos{color:#059669;font-weight:600}
.kpi-card .kpi-sub .neg{color:#dc2626;font-weight:600}
/* === 月次推移バー === */
.monthly-bars{display:flex;align-items:flex-end;gap:6px;height:120px;padding:8px 0 4px;
              border-bottom:1px solid #e5e7eb;margin-bottom:6px;overflow-x:auto}
.monthly-bar{flex:0 0 38px;display:flex;flex-direction:column;align-items:center;gap:4px}
.monthly-bar .bar{width:24px;background:linear-gradient(180deg,#5eead4 0%,#14b8a6 100%);
                  border-radius:4px 4px 0 0;min-height:2px}
.monthly-bar .lbl{font-size:10px;color:#6b7280;writing-mode:vertical-rl;height:36px}
/* === 候補カード === */
.cand-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin:10px 0}
.cand-card .cand-q{font-size:14px;font-weight:600;color:#1f2937;margin-bottom:6px}
.cand-card .cand-meta{font-size:12px;color:#6b7280;margin-bottom:10px}
.cand-card .cand-meta .chip{display:inline-block;background:#f0fdfa;color:#0f766e;
                            padding:2px 8px;border-radius:999px;margin-right:6px;font-size:11px}
.cand-card .cand-answer{background:#f9fafb;border-left:3px solid #14b8a6;
                        padding:10px 14px;font-size:13px;color:#374151;border-radius:4px;
                        max-height:180px;overflow:auto;white-space:pre-wrap}
.cand-card .cand-other-qs{font-size:12px;color:#6b7280;margin-top:8px}
.cand-card .cand-actions{margin-top:12px;display:flex;gap:8px;flex-wrap:wrap}
.cand-card .btn-approve{background:#14b8a6;color:#fff;border:0;padding:8px 16px;
                        border-radius:6px;cursor:pointer;font-size:13px;font-weight:500}
.cand-card .btn-reject{background:transparent;color:#6b7280;border:1px solid #d1d5db;
                       padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px}
.cand-card .btn-edit{background:transparent;color:#1a73e8;border:1px solid #93c5fd;
                     padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px}
.cand-card.approved{opacity:.6;background:#f0fdf4}
.cand-card.rejected{opacity:.5;background:#fafafa}
/* === 設定パネル === */
.settings-panel{background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;
                padding:18px;margin-top:18px}
.settings-panel h4{margin:0 0 12px;font-size:14px;color:#1f2937}
.settings-panel .row{display:flex;gap:10px;align-items:center;margin:8px 0;font-size:13px;flex-wrap:wrap}
.settings-panel .row label{min-width:240px;color:#374151}
.settings-panel .row input[type=number]{width:90px;padding:5px 8px;border:1px solid #d1d5db;border-radius:6px}
.settings-panel .row input[type=range]{width:160px}
.settings-panel .save-btn{background:#1a73e8;color:#fff;border:0;padding:8px 16px;
                          border-radius:6px;cursor:pointer;font-size:13px;margin-top:8px}
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
/* hidden 属性が CSS の display:flex に負けないよう明示的に上書き
   （ingest 以外のタブでは取り込みフッターを隠す用途） */
.modal-footer[hidden]{display:none}
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
    <h2>📚 ナレッジ追加 <span>— Inquira</span> <a class="version-badge" href="/api/version" target="_blank" title="クリックでバージョン情報・変更履歴を表示">v__VERSION__</a></h2>
    <a href="/" style="color:#6b7280;text-decoration:none;font-size:13px">← チャットに戻る</a>
  </div>
  <div class="modal-body">

    <nav class="admin-tabs" id="adminTabs">
      <button class="admin-tab active" data-tab="ingest">📁 ファイル取り込み</button>
      <button class="admin-tab" data-tab="analytics">📊 利用状況</button>
      <button class="admin-tab" data-tab="impact">📈 削減効果</button>
      <button class="admin-tab" data-tab="candidates">🌱 FAQ 候補 <span id="candidatePendingBadge" class="tab-badge" hidden>0</span></button>
      <button class="admin-tab" data-tab="history">🔍 履歴・要望</button>
      <button class="admin-tab" data-tab="settings">⚙ 設定・出力</button>
    </nav>

    <!-- ===== タブ1: ファイル取り込み ===== -->
    <div class="admin-pane" data-pane="ingest">
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

    <div class="step-title" style="margin-top:32px"><span class="step-num">3</span>取り込み済み文書（メンテナンス）</div>
    <div id="docs-section" style="font-size:13px;color:#6b7280">
      <div class="empty-msg">読み込み中…</div>
    </div>
    </div><!-- /pane: ingest -->

    <!-- ===== タブ2: 利用状況 ===== -->
    <div class="admin-pane" data-pane="analytics" hidden>
    <div class="step-title"><span class="step-num">📊</span>利用状況ダッシュボード</div>
    <div id="dashboard-section" style="font-size:13px;color:#6b7280">
      <div class="empty-msg">読み込み中…</div>
    </div>
    </div><!-- /pane: analytics -->

    <!-- ===== タブ3: 履歴・要望 ===== -->
    <div class="admin-pane" data-pane="history" hidden>
    <div class="step-title"><span class="step-num">🔍</span>質問履歴を検索</div>
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

    <div class="step-title" style="margin-top:32px"><span class="step-num">📩</span>FAQ追加リクエスト</div>
    <div id="faq-requests-section" style="font-size:13px;color:#6b7280">
      <div class="empty-msg">読み込み中…</div>
    </div>
    </div><!-- /pane: history -->

    <!-- ===== タブ: 削減効果 ===== -->
    <div class="admin-pane" data-pane="impact" hidden>
    <div class="step-title"><span class="step-num">📈</span>Inquira がどれだけ工数を減らしたか</div>
    <p style="font-size:13px;color:#6b7280;margin-bottom:8px">
      AI が回答した質問数 × 1質問あたりの想定削減時間（=「資料を探す or 人に聞く」想定）で算出します。
      下部の<b>計算前提</b>を貴社の運用に合わせて調整してください。
    </p>
    <div id="impact-section" style="font-size:13px;color:#6b7280">
      <div class="empty-msg">読み込み中…</div>
    </div>
    </div><!-- /pane: impact -->

    <!-- ===== タブ: FAQ 候補 ===== -->
    <div class="admin-pane" data-pane="candidates" hidden>
    <div class="step-title"><span class="step-num">🌱</span>解決した会話から FAQ 候補を自動生成</div>
    <p style="font-size:13px;color:#6b7280;margin-bottom:8px">
      過去の質問履歴を分析し、<b>「複数のユーザーが繰り返し聞いた、高い確信度で回答された質問」</b> を FAQ 候補として提示します。
      承認すると正式な FAQ ドキュメントに昇格し、以後の検索結果にヒットするようになります。
    </p>
    <div id="candidates-section" style="font-size:13px;color:#6b7280">
      <div class="empty-msg">読み込み中…</div>
    </div>
    </div><!-- /pane: candidates -->

    <!-- ===== タブ4: 設定・出力 ===== -->
    <div class="admin-pane" data-pane="settings" hidden>
    <div class="step-title"><span class="step-num">⚙</span>組織情報（デモ・カスタマイズ用）</div>
    <div id="settings-section" style="font-size:13px;color:#6b7280">
      <div class="empty-msg">読み込み中…</div>
    </div>

    <div class="step-title" style="margin-top:32px"><span class="step-num">📥</span>レポート出力（社内提出・分析用）</div>
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
    </div><!-- /pane: settings -->

  </div>
  <div class="modal-footer" id="ingestFooter">
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
  const shared = requests.filter(r => r.kind === 'answer_shared' && r.share).length;
  const summary = `<div class="doc-summary"><b>${total}件のリクエスト</b> · 最新${requests.length}件を表示`
    + (shared ? ` · <span style="color:#065f46;font-weight:600">💬 ユーザー提供回答 ${shared}件</span>` : '')
    + `</div>`;
  const rows = requests.map(r => {
    const isShared = r.kind === 'answer_shared' && r.share;
    const isAnswerPrivate = r.kind === 'answer_shared' && !r.share;
    const badge = isShared
      ? '<span style="background:#d1fae5;color:#065f46;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;margin-left:6px">💬 回答付き(共有)</span>'
      : isAnswerPrivate
        ? '<span style="background:#f3f4f6;color:#6b7280;padding:2px 8px;border-radius:10px;font-size:11px;margin-left:6px">🔒 個人メモ</span>'
        : '';
    const answerBlock = r.answer
      ? `<div style="margin-top:6px;padding:8px 10px;background:#ecfdf5;border-left:3px solid #10b981;border-radius:6px;font-size:12px;color:#065f46;white-space:pre-wrap;word-break:break-word">
           <div style="font-weight:600;margin-bottom:3px">💬 ユーザーが教えてもらった回答:</div>
           ${escape(r.answer)}
         </div>`
      : '';
    return `
    <tr>
      <td>
        <div class="doc-name">${escape(r.question)}${badge}</div>
        <div class="doc-meta">${escape(r.user)} · ${fmtDate(r.ts)}</div>
        ${r.note ? `<div style="margin-top:4px;color:#6b7280;font-size:12px">📝 ${escape(r.note)}</div>` : ''}
        ${answerBlock}
      </td>
    </tr>`;
  }).join('');
  faqReqSection.innerHTML = summary + `
    <table class="doc-table">
      <thead><tr><th>質問内容</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div style="margin-top:8px;font-size:11px;color:#9ca3af">
      💡 「💬 回答付き」のリクエストは、その回答をMarkdownファイルにして「ファイルを投入」から取り込めば即FAQ化できます
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
  faq_master_dir: 'FAQ 格納フォルダ',
  raw_upload_dir: '原本ファイル格納フォルダ',
};
const SETTINGS_HINTS = {
  product_name: 'チャット画面のタイトルに表示されます（例: Inquira）',
  org_name: 'AIの自己紹介に使われます（例: 株式会社○○）',
  assistant_role: 'AIの役割設定（例: 社内ヘルプデスク / 顧客サポート）',
  masking_industry: 'PII検出の業界辞書（general / education / medical / finance）',
  faq_master_dir: '取り込み済み FAQ（クレンジング後の Markdown）の保存先。例: /opt/inquira/data/faq_master または /Users/me/inquira-data/faq',
  raw_upload_dir: 'アップロード元の原本ファイル（PDF/Excel等）の保存先。例: /opt/inquira/data/raw',
};
const SETTINGS_PATH_KEYS = new Set(['faq_master_dir', 'raw_upload_dir']);

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
    const isPath = SETTINGS_PATH_KEYS.has(k);
    const maxLen = isPath ? 500 : 200;
    const pathHint = isPath ? '<div class="setting-hint" style="color:#9a3412;">⚠ パス変更後は <b>取り込み済みデータを新フォルダに移してから</b> アプリ再起動を推奨。既存ファイルは自動移動されません。</div>' : '';
    return `
      <div class="setting-row">
        <label class="setting-label">
          ${SETTINGS_LABELS[k] || k}
          ${isOverride ? '<span class="setting-badge">UIから編集済</span>' : '<span class="setting-badge default">.env デフォルト</span>'}
        </label>
        <input type="text" data-key="${k}" value="${escape(eff[k] || '')}" maxlength="${maxLen}"/>
        <div class="setting-hint">${escape(SETTINGS_HINTS[k] || '')}</div>
        ${pathHint}
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
        <h4>⭐ 質問が多いトピック TOP6</h4>
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
loadImpact();
loadCandidates();

// ========== 📈 削減効果タブ ==========
async function loadImpact() {
  const sec = document.getElementById('impact-section');
  if (!sec) return;
  try {
    const r = await fetch('/api/admin/impact');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    renderImpact(d);
  } catch (e) {
    sec.innerHTML = `<div class="empty-msg">読み込みエラー: ${e.message}</div>`;
  }
}

function renderImpact(d) {
  const sec = document.getElementById('impact-section');
  const s = d.summary;
  const cfg = d.settings;
  const yen = (n) => (n || 0).toLocaleString('ja-JP');
  const last30 = d.last_30_days || {};
  const growth = last30.growth_pct || 0;
  const growthHtml = last30.vs_previous_30_days >= 0
    ? `<span class="pos">▲ ${growth}% 増</span>`
    : `<span class="neg">▼ ${Math.abs(growth)}% 減</span>`;

  const kpis = `
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-num">${yen(s.hours_saved)}<small>時間</small></div>
        <div class="kpi-label">累計 削減時間</div>
        <div class="kpi-sub">≒ <b>${yen(s.days_saved)}人日</b> 相当</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-num">¥${yen(s.cost_saved_yen)}</div>
        <div class="kpi-label">累計 削減コスト</div>
        <div class="kpi-sub">時給 ¥${yen(cfg.hourly_rate_yen)} 換算</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-num">${yen(s.total_answered)}<small>件</small></div>
        <div class="kpi-label">AI 回答済み質問</div>
        <div class="kpi-sub">回答率 <b>${s.answer_rate_pct}%</b></div>
      </div>
      <div class="kpi-card">
        <div class="kpi-num">${yen(s.unique_users)}<small>名</small></div>
        <div class="kpi-label">利用ユーザー数</div>
        <div class="kpi-sub">直近30日: ${yen(last30.answered)}件 ${growthHtml}</div>
      </div>
    </div>
  `;

  let monthlyHtml = '';
  if (d.monthly && d.monthly.length > 0) {
    const maxAns = Math.max(...d.monthly.map(m => m.answered || 0), 1);
    const bars = d.monthly.map(m => {
      const h = Math.max(2, Math.round((m.answered || 0) / maxAns * 100));
      return `<div class="monthly-bar" title="${m.month}: ${m.answered}件 / ${Math.round((m.minutes_saved||0)/60)}h">
        <div class="bar" style="height:${h}%"></div>
        <div class="lbl">${m.month}</div>
      </div>`;
    }).join('');
    monthlyHtml = `
      <div class="step-title" style="margin-top:18px"><span class="step-num">📊</span>月次 回答件数推移</div>
      <div class="monthly-bars">${bars}</div>
    `;
  }

  const settingsHtml = `
    <div class="settings-panel">
      <h4>⚙ 計算前提（貴社の運用に合わせて調整）</h4>
      <div class="row">
        <label>1質問あたりの削減時間（分）</label>
        <input type="number" id="impMinAns" min="1" max="120" value="${cfg.minutes_saved_per_answered_query}"/>
        <span style="color:#6b7280">※ AIなしで「資料を探す/人に聞く」想定</span>
      </div>
      <div class="row">
        <label>共有回答1件の整備削減（分）</label>
        <input type="number" id="impMinShared" min="0" max="240" value="${cfg.minutes_saved_per_faq_shared}"/>
      </div>
      <div class="row">
        <label>平均時給（円）</label>
        <input type="number" id="impHourly" min="500" max="20000" step="100" value="${cfg.hourly_rate_yen}"/>
      </div>
      <button class="save-btn" id="impSaveBtn">💾 保存して再計算</button>
    </div>
  `;

  sec.innerHTML = kpis + monthlyHtml + settingsHtml;
  document.getElementById('impSaveBtn').onclick = async () => {
    const body = {
      minutes_saved_per_answered_query: Number(document.getElementById('impMinAns').value),
      minutes_saved_per_faq_shared: Number(document.getElementById('impMinShared').value),
      hourly_rate_yen: Number(document.getElementById('impHourly').value),
    };
    await fetch('/api/admin/impact-settings', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    loadImpact();
  };
}

// ========== 🌱 FAQ 候補タブ ==========
let _candidatesData = null;
let _candidateSettings = null;

async function loadCandidates() {
  const sec = document.getElementById('candidates-section');
  if (!sec) return;
  try {
    const [listR, setR] = await Promise.all([
      fetch('/api/admin/faq-candidates'),
      fetch('/api/admin/faq-candidate-settings'),
    ]);
    if (!listR.ok || !setR.ok) throw new Error('HTTP error');
    _candidatesData = await listR.json();
    _candidateSettings = await setR.json();
    renderCandidates();
    // ナビバーのバッジ
    const badge = document.getElementById('candidatePendingBadge');
    const pending = (_candidatesData.counts || {}).pending || 0;
    if (badge) {
      badge.hidden = pending === 0;
      badge.textContent = pending;
    }
  } catch (e) {
    sec.innerHTML = `<div class="empty-msg">読み込みエラー: ${e.message}</div>`;
  }
}

function renderCandidates() {
  const sec = document.getElementById('candidates-section');
  const d = _candidatesData;
  const s = _candidateSettings;
  const counts = d.counts || {};

  const tabBar = `
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:14px;flex-wrap:wrap">
      <button class="cand-filter active" data-filter="pending">未承認 (${counts.pending||0})</button>
      <button class="cand-filter" data-filter="approved">承認済 (${counts.approved||0})</button>
      <button class="cand-filter" data-filter="rejected">却下 (${counts.rejected||0})</button>
      <span style="flex:1"></span>
      <button class="save-btn" id="candDetectBtn">🔄 再検出</button>
    </div>
    <div id="cand-list"></div>
  `;

  const settingsHtml = `
    <div class="settings-panel">
      <h4>⚙ 検出のしきい値</h4>
      <div class="row">
        <label>最低確信度 (0-100)</label>
        <input type="number" id="cMinConf" min="0" max="100" value="${s.min_confidence}"/>
      </div>
      <div class="row">
        <label>最低 質問回数（同類）</label>
        <input type="number" id="cMinCount" min="1" max="100" value="${s.min_asked_count}"/>
      </div>
      <div class="row">
        <label>最低 ユニークユーザー数</label>
        <input type="number" id="cMinUsers" min="1" max="100" value="${s.min_unique_users}"/>
      </div>
      <div class="row">
        <label>類似質問のしきい値 (0-1)</label>
        <input type="number" id="cSim" min="0" max="1" step="0.05" value="${s.similarity_threshold}"/>
      </div>
      <div class="row">
        <label>分析対象期間（日）</label>
        <input type="number" id="cLookback" min="1" max="365" value="${s.lookback_days}"/>
      </div>

      <h4 style="margin-top:18px;color:#dc2626">🤖 自動承認モード</h4>
      <div class="row">
        <label><input type="checkbox" id="cAuto" ${s.auto_approve_enabled ? 'checked':''}/> 自動承認を有効にする</label>
        <span style="color:#6b7280;font-size:12px">※ 下記の厳しめ条件を全て満たすと、人間の承認なしで FAQ 化されます</span>
      </div>
      <div class="row">
        <label>自動承認の最低確信度</label>
        <input type="number" id="cAutoConf" min="0" max="100" value="${s.auto_approve_min_confidence}"/>
      </div>
      <div class="row">
        <label>自動承認の最低 質問回数</label>
        <input type="number" id="cAutoCount" min="1" max="100" value="${s.auto_approve_min_asked_count}"/>
      </div>
      <div class="row">
        <label>自動承認の最低 ユーザー数</label>
        <input type="number" id="cAutoUsers" min="1" max="100" value="${s.auto_approve_min_unique_users}"/>
      </div>
      <div class="row">
        <label><input type="checkbox" id="cStartup" ${s.auto_detect_on_startup ? 'checked':''}/> 起動時に検出バッチを実行</label>
      </div>
      <button class="save-btn" id="candSaveSettingsBtn">💾 設定を保存</button>
    </div>
  `;

  sec.innerHTML = tabBar + settingsHtml;
  // フィルタボタンのスタイル
  document.querySelectorAll('.cand-filter').forEach(b => {
    b.style.cssText = 'background:transparent;border:1px solid #d1d5db;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;color:#6b7280';
  });
  document.querySelectorAll('.cand-filter.active').forEach(b => {
    b.style.cssText = 'background:#1a73e8;border:1px solid #1a73e8;color:#fff;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px';
  });

  renderCandidateList('pending');

  document.querySelectorAll('.cand-filter').forEach(b => {
    b.onclick = () => {
      document.querySelectorAll('.cand-filter').forEach(x => {
        x.classList.toggle('active', x === b);
        x.style.cssText = x === b
          ? 'background:#1a73e8;border:1px solid #1a73e8;color:#fff;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px'
          : 'background:transparent;border:1px solid #d1d5db;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;color:#6b7280';
      });
      renderCandidateList(b.dataset.filter);
    };
  });

  document.getElementById('candDetectBtn').onclick = async () => {
    const btn = document.getElementById('candDetectBtn');
    btn.textContent = '🔄 検出中…';
    btn.disabled = true;
    try {
      const r = await fetch('/api/admin/faq-candidates/detect', {method: 'POST'});
      const stats = await r.json();
      alert(
        `検出完了\\n\\n` +
        `新規候補: ${stats.new}\\n` +
        `自動承認: ${stats.auto_approved}\\n` +
        `既存FAQと重複: ${stats.skipped_existing_faq}\\n` +
        `既存候補と重複: ${stats.skipped_existing_candidate}\\n` +
        `しきい値未満: ${stats.below_threshold}`
      );
      loadCandidates();
    } finally {
      btn.textContent = '🔄 再検出';
      btn.disabled = false;
    }
  };

  document.getElementById('candSaveSettingsBtn').onclick = async () => {
    const body = {
      min_confidence: Number(document.getElementById('cMinConf').value),
      min_asked_count: Number(document.getElementById('cMinCount').value),
      min_unique_users: Number(document.getElementById('cMinUsers').value),
      similarity_threshold: Number(document.getElementById('cSim').value),
      lookback_days: Number(document.getElementById('cLookback').value),
      auto_approve_enabled: document.getElementById('cAuto').checked,
      auto_approve_min_confidence: Number(document.getElementById('cAutoConf').value),
      auto_approve_min_asked_count: Number(document.getElementById('cAutoCount').value),
      auto_approve_min_unique_users: Number(document.getElementById('cAutoUsers').value),
      auto_detect_on_startup: document.getElementById('cStartup').checked,
    };
    await fetch('/api/admin/faq-candidate-settings', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    alert('設定を保存しました');
    loadCandidates();
  };
}

function renderCandidateList(filter) {
  const list = document.getElementById('cand-list');
  const all = _candidatesData.candidates || [];
  const items = all.filter(c => c.status === filter);
  if (items.length === 0) {
    list.innerHTML = `<div class="empty-msg">該当する候補はありません。「🔄 再検出」で監査ログを分析できます。</div>`;
    return;
  }
  list.innerHTML = items.map(c => {
    const escH = s => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const qs = c.question_examples || [];
    const otherQs = qs.slice(1, 5);
    const otherHtml = otherQs.length ? `<div class="cand-other-qs">同類質問: ${otherQs.map(q => escH(q)).join(' / ')}</div>` : '';
    const period = `${(c.first_seen||'').slice(0,10)} 〜 ${(c.last_seen||'').slice(0,10)}`;
    const actions = c.status === 'pending'
      ? `<div class="cand-actions">
          <button class="btn-approve" data-action="approve" data-id="${c.id}">✓ 承認して FAQ 化</button>
          <button class="btn-edit" data-action="edit" data-id="${c.id}">✎ 編集して承認</button>
          <button class="btn-reject" data-action="reject" data-id="${c.id}">却下</button>
        </div>`
      : `<div class="cand-meta" style="margin-top:8px">
          ${c.status === 'approved' ? '✓ 承認済 ' : '✗ 却下済 '}
          ${escH(c.reviewed_by || '')} ${(c.reviewed_at||'').slice(0,10)}
          ${c.approved_doc_path ? `<br/><small>📄 <code>${escH(c.approved_doc_path)}</code></small>` : ''}
        </div>`;
    return `
      <div class="cand-card ${c.status}">
        <div class="cand-q">Q: ${escH(qs[0] || '（無題）')}</div>
        <div class="cand-meta">
          <span class="chip">確信度 ${c.confidence}%</span>
          <span class="chip">${(c.support||{}).asked_count||0} 件聞かれた</span>
          <span class="chip">${(c.support||{}).unique_users||0} 名のユーザー</span>
          <span style="color:#9ca3af">${period}</span>
        </div>
        <div class="cand-answer">${escH(c.answer)}</div>
        ${otherHtml}
        ${actions}
      </div>
    `;
  }).join('');

  list.querySelectorAll('[data-action]').forEach(btn => {
    btn.onclick = () => handleCandidateAction(btn.dataset.action, btn.dataset.id);
  });
}

async function handleCandidateAction(action, cid) {
  const cand = (_candidatesData.candidates || []).find(c => c.id === cid);
  if (!cand) return;
  if (action === 'approve') {
    if (!confirm('この候補を FAQ として承認しますか？\\n承認後すぐに検索結果に反映されます。')) return;
    await fetch(`/api/admin/faq-candidates/${cid}/approve`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    loadCandidates();
  } else if (action === 'reject') {
    const note = prompt('却下理由（任意）:');
    if (note === null) return;
    await fetch(`/api/admin/faq-candidates/${cid}/reject`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({note: note || null}),
    });
    loadCandidates();
  } else if (action === 'edit') {
    const q = prompt('質問文を編集:', cand.question_examples[0] || '');
    if (q === null) return;
    const a = prompt('回答文を編集:', cand.answer || '');
    if (a === null) return;
    await fetch(`/api/admin/faq-candidates/${cid}/approve`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q, answer: a, note: '編集して承認'}),
    });
    loadCandidates();
  }
}

// === 管理画面タブ切り替え ===
const _VALID_TABS = ['ingest','analytics','impact','candidates','history','settings'];
document.querySelectorAll('.admin-tab').forEach(tab => {
  tab.onclick = () => {
    const target = tab.dataset.tab;
    document.querySelectorAll('.admin-tab').forEach(t => t.classList.toggle('active', t === tab));
    document.querySelectorAll('.admin-pane').forEach(p => {
      p.hidden = p.dataset.pane !== target;
    });
    // 取り込みフッター（未取り込み件数・取り込み確定ボタン）は ingest タブでのみ意味があるので
    // 他タブでは隠す
    const ingestFooter = document.getElementById('ingestFooter');
    if (ingestFooter) ingestFooter.hidden = target !== 'ingest';
    // URL のフラグメントを更新（ブックマーク・履歴用）
    history.replaceState(null, '', '#' + target);
  };
});
// 初期表示: URL フラグメントがあればそのタブを開く
(() => {
  const h = (location.hash || '').replace('#', '');
  if (h && _VALID_TABS.includes(h)) {
    const t = document.querySelector(`.admin-tab[data-tab="${h}"]`);
    if (t) t.click();
  }
})();
</script>
</body></html>"""


@app.get("/api/admin/stats")
async def admin_stats(user: dict = Depends(require_user)):
    """サイドバー集計用。ナレッジ状態・履歴・トップトピック・フィードバックを返す。"""
    from collections import Counter

    idx = get_index()
    recent = audit.read_recent(1000)
    queries = [e for e in recent if e.get("event") == "query"]
    feedback = [e for e in recent if e.get("event") == "feedback"]

    history = [
        {"question": q.get("question", ""), "ts": q.get("ts", ""),
         "sources": q.get("sources", []), "confidence": q.get("confidence", 0)}
        for q in queries[:100]
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

    # 各フィードバックに対応する query イベントを引き合わせて、
    # 確信度・参照ソース・回答済みかどうかを付与する（UI 詳細表示用）
    def _enrich_feedback(fb_entries: list[dict]) -> list[dict]:
        out = []
        for fb in fb_entries:
            q = fb.get("question", "")
            # 同じ質問テキストの query イベントを直近で探す
            matching = next(
                (qe for qe in queries
                 if (qe.get("question") or "") == q),
                None,
            )
            out.append({
                "question": q,
                "ts": fb.get("ts", ""),
                "sources": (matching or {}).get("sources", fb.get("sources", [])),
                "confidence": (matching or {}).get("confidence", 0),
                "has_answer": (matching or {}).get("answered", False),
                "is_reference": (matching or {}).get("is_reference", False),
            })
        return out

    up_entries = _enrich_feedback([f for f in feedback if f.get("vote") == "up"])[:20]
    down_entries = _enrich_feedback([f for f in feedback if f.get("vote") == "down"])[:20]
    # 後方互換: down_questions は古い形式（文字列リスト）も残す
    down_questions = [e["question"] for e in down_entries[:5]]

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
        "feedback": {
            "up": fb_up,
            "down": fb_down,
            "down_questions": down_questions,  # 後方互換（旧 UI 用）
            "up_entries": up_entries,
            "down_entries": down_entries,
        },
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
    answer: str = ""  # ユーザーが別途人から教えてもらった回答（任意）
    share: bool = False  # 「他の人にも役立つので管理者に共有する」フラグ


def _save_shared_answer_as_doc(question: str, answer: str, user_email: str) -> str | None:
    """共有許可されたユーザー提供回答を Markdown ファイル化して FAQマスターに保存。

    保存先: {settings.faq_master_dir}/user_shared/{timestamp}-{question-prefix}.md
    保存後に reload_index() で検索インデックスへ反映される。

    Returns:
        保存したファイルのパス文字列、または失敗時 None。
    """
    from datetime import datetime
    import re as _re

    safe_q_prefix = _re.sub(r"[^\w一-鿿ぁ-んァ-ヶー]+", "_", question[:40]).strip("_") or "shared"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    settings.faq_master_dir.mkdir(parents=True, exist_ok=True)
    # ファイル名プレフィックスで識別（UI 側で「user-shared-」始まりかを判定）
    out_path = settings.faq_master_dir / f"user-shared-{ts}-{safe_q_prefix}.md"
    body = (
        f"# {question}\n\n"
        f"> 💬 **ユーザー提供回答**（社員 {user_email} が {ts} に共有）\n"
        f"> 管理者の正式承認前ですが、参考までに検索結果に含まれます\n\n"
        f"## 質問\n\n{question}\n\n"
        f"## 回答（ユーザー提供）\n\n{answer}\n"
    )
    try:
        out_path.write_text(body, encoding="utf-8")
        return str(out_path)
    except OSError:
        return None


@app.post("/api/faq-requests")
async def api_faq_request(
    payload: FaqRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_user),
):
    """FAQ追加リクエストを受け付ける。

    用途:
      1. 質問しても回答が得られなかった → 管理者に FAQ 追加を依頼
      2. ユーザーが別途人から答えを教えてもらった → その回答を共有して FAQ 化を依頼
         share=true なら検索インデックスにも追加（他の人の検索にも引っかかるように）

    インデックス再構築は大規模データだと数分かかるため BackgroundTasks に逃がし、
    レスポンスは即時返す（保存自体はリクエスト内で完了している）。
    """
    q = (payload.question or "").strip()
    a = (payload.answer or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="質問本文が空です")
    if len(q) > 2000:
        raise HTTPException(status_code=400, detail="質問が長すぎます（2000文字以内）")
    if len(a) > 5000:
        raise HTTPException(status_code=400, detail="回答が長すぎます（5000文字以内）")
    # ユーザー提供回答がある場合は kind="answer_shared" としてサブカテゴリ化
    kind = "answer_shared" if a else "question_only"
    indexed_path: str | None = None
    # 共有許可付きユーザー回答は検索インデックスへも追加（他の人の検索にヒットする）
    if a and payload.share:
        indexed_path = _save_shared_answer_as_doc(q, a, user["email"])
        if indexed_path:
            background_tasks.add_task(reload_index)
    audit.record(
        "faq_request",
        user=user["email"],
        question=q,
        note=(payload.note or "")[:500],
        answer=a[:5000],
        share=bool(payload.share),
        kind=kind,
        indexed_path=indexed_path,
    )
    return {"ok": True, "kind": kind, "indexed": bool(indexed_path)}


@app.get("/api/admin/faq-requests")
async def admin_list_faq_requests(user: dict = Depends(require_user)):
    """未対応のFAQ追加リクエスト一覧を返す（直近100件）。
    answer_shared（ユーザー提供回答付き）が先頭に来るようソート。
    """
    recent = audit.read_recent(1000)
    requests = [
        {
            "question": e.get("question", ""),
            "note": e.get("note", ""),
            "answer": e.get("answer", ""),
            "share": bool(e.get("share", False)),
            "kind": e.get("kind", "question_only"),
            "user": e.get("user", ""),
            "ts": e.get("ts", ""),
        }
        for e in recent if e.get("event") == "faq_request"
    ]
    # ユーザー提供回答付き && 共有許可ありを優先表示
    requests.sort(key=lambda r: (
        0 if (r["kind"] == "answer_shared" and r["share"]) else 1,
        0 if r["kind"] == "answer_shared" else 1,
    ))
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
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"{settings.max_upload_mb}MB を超えるファイルは取り込めません",
        )
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
    # 取り込みに成功した場合、原本ファイルも保存しておく（画面キャプチャ等の閲覧用）。
    # 失敗時は保存しない（中途半端な状態を残さない）。
    if n > 0:
        try:
            settings.raw_upload_dir.mkdir(parents=True, exist_ok=True)
            # result.filename は _safe_filename を通っているのでパストラバーサルの心配は無いが
            # 念のため basename のみ採用
            safe_name = Path(result.filename).name
            (settings.raw_upload_dir / safe_name).write_bytes(content)
        except OSError:
            # 原本保存に失敗してもインデックス取り込み自体は成功しているので致命ではない
            pass
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


@app.get("/api/chunks")
async def api_get_chunk(chunk_id: str, user: dict = Depends(require_user)):
    """指定チャンクの全文と、同じファイル内の他チャンク（プレビュー）を返す。

    回答の「出典」をクリックして中身を直接確認できるようにする（参照のみ・編集不可）。
    """
    idx = get_index()
    target = None
    first_of_source = None
    same_file: list[dict] = []
    target_source = chunk_id.split("#")[0] if "#" in chunk_id else chunk_id
    for c in idx.chunks:
        if c.chunk_id == chunk_id:
            target = c
        if c.source == target_source:
            if first_of_source is None:
                first_of_source = c
            same_file.append({
                "chunk_id": c.chunk_id,
                "preview": c.text.strip().replace("\n", " ")[:160],
            })
    # ファイル名だけが渡された場合（カバー領域タグなど）は先頭チャンクを表示する
    if target is None:
        target = first_of_source
    if target is None:
        raise HTTPException(status_code=404, detail=f"チャンクが見つかりません: {chunk_id}")
    # 原本（PDF/Excel 等）が raw_upload_dir に保存されていればファイル名を返す
    original_filename = _resolve_original_filename(target.source)
    return {
        "chunk": {
            "chunk_id": target.chunk_id,
            "source": target.source,
            "text": target.text,
        },
        "neighbors": same_file[:50],  # 同じファイル内の他チャンク一覧（上限50）
        "original_filename": original_filename,
    }


@app.get("/api/originals/{filename:path}")
async def api_get_original(filename: str, user: dict = Depends(require_user)):
    """取り込み済みファイルの原本（PDF/Excel 等）を配信する。

    pypdf 等のテキスト抽出では画面キャプチャや図表が落ちるため、
    必要に応じてユーザーが元ファイルをそのまま閲覧できるようにする。

    パストラバーサル対策として ``Path(filename).name`` で basename のみ採用し、
    raw_upload_dir 配下のファイルだけを返す。
    """
    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="不正なファイル名")
    target = (settings.raw_upload_dir / safe_name).resolve()
    base = settings.raw_upload_dir.resolve()
    try:
        target.relative_to(base)  # 配下に居ない（=シンボリックリンク等）なら拒否
    except ValueError:
        raise HTTPException(status_code=400, detail="不正なファイルパス")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="原本ファイルが見つかりません")
    # ブラウザで PDF を直接開けるよう inline 表示
    return FileResponse(target, filename=safe_name, content_disposition_type="inline")


@app.get("/api/knowledge-base")
async def api_knowledge_base(
    q: str = "",
    limit: int = 50,
    user: dict = Depends(require_user),
):
    """共有Q&A 一覧 / 検索 API（社員提供のナレッジ）。"""
    items = shared_qa.search(q, limit=limit) if q else shared_qa.list_shared_qas()[:limit]
    return {
        "total": len(shared_qa.list_shared_qas()),
        "shown": len(items),
        "query": q,
        "items": [
            {
                "file_id": x.file_id,
                "source": x.source,
                "question": x.question,
                "answer": x.answer,
                "contributor": x.contributor,
                "shared_at": x.shared_at,
                "votes_up": x.votes_up,
                "votes_down": x.votes_down,
                "resolved_count": x.resolved_count,
            }
            for x in items
        ],
    }


class SharedQAVote(BaseModel):
    file_id: str
    kind: str  # "up" / "down" / "resolved"


@app.post("/api/knowledge-base/vote")
async def api_knowledge_base_vote(payload: SharedQAVote, user: dict = Depends(require_user)):
    """共有Q&A への投票（役立った / 役に立たなかった / 解決した）。"""
    if payload.kind not in ("up", "down", "resolved"):
        raise HTTPException(status_code=400, detail="kind は up / down / resolved")
    qa = shared_qa.get_shared_qa(payload.file_id)
    if qa is None:
        raise HTTPException(status_code=404, detail="共有Q&A が見つかりません")
    entry = shared_qa.vote(payload.file_id, payload.kind)
    audit.record(
        "kb_vote",
        user=user["email"],
        file_id=payload.file_id,
        kind=payload.kind,
    )
    return {"ok": True, "meta": entry}


@app.get("/knowledge-base", response_class=HTMLResponse)
async def knowledge_base_page(request: Request) -> HTMLResponse:
    """社員が共有した Q&A を閲覧するページ。"""
    if not settings.demo_mode:
        user = request.session.get("user")
        if not user or not is_email_allowed(user.get("email", "")):
            return HTMLResponse('<a href="/auth/login">Googleでログイン</a>', status_code=200)
    return HTMLResponse(_knowledge_base_page().replace("__VERSION__", __version__))


def _knowledge_base_page() -> str:
    return """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>みんなのナレッジ — Inquira</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif;
     background:#f7f8fa;color:#1f2937;min-height:100vh;font-size:15px;
     -webkit-font-smoothing:antialiased}
.page{max-width:920px;margin:0 auto;padding:32px 24px}
.page-header{display:flex;justify-content:space-between;align-items:flex-end;
             margin-bottom:24px;flex-wrap:wrap;gap:12px}
h1{font-size:26px;color:#111827;font-weight:700;letter-spacing:-.02em}
h1 .version-badge{display:inline-block;background:#e5e7eb;color:#6b7280;font-size:11px;
                  font-weight:500;padding:2px 9px;border-radius:12px;margin-left:8px;
                  vertical-align:middle}
.subtitle{color:#6b7280;font-size:14px;margin-top:4px}
.back-link{color:#1a73e8;text-decoration:none;font-size:14px;font-weight:500}
.back-link:hover{text-decoration:underline}
.toolbar{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}
.search-input{flex:1;min-width:260px;padding:12px 16px;border:1px solid #d1d5db;
              border-radius:10px;font-size:15px;background:#fff;font-family:inherit}
.search-input:focus{outline:none;border-color:#1a73e8;box-shadow:0 0 0 4px rgba(26,115,232,.12)}
.stats-row{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}
.stat-card{flex:1;min-width:140px;background:#fff;border:1px solid #e5e7eb;
           border-radius:12px;padding:16px}
.stat-card .label{font-size:12px;color:#6b7280;font-weight:500;text-transform:uppercase;
                   letter-spacing:.04em}
.stat-card .value{font-size:28px;color:#1a73e8;font-weight:700;margin-top:4px;letter-spacing:-.02em}
.stat-card.clickable{cursor:pointer;transition:all .15s;position:relative}
.stat-card.clickable:hover{border-color:#1a73e8;box-shadow:0 4px 12px rgba(26,115,232,.12);transform:translateY(-1px)}
.stat-card .stat-hint{font-size:11px;color:#1a73e8;margin-top:6px;font-weight:500;opacity:0;transition:opacity .15s}
.stat-card.clickable:hover .stat-hint{opacity:1}
/* 貢献者モーダル */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9000;
                display:flex;align-items:center;justify-content:center;padding:20px}
.modal-box{background:#fff;border-radius:14px;max-width:480px;width:100%;max-height:80vh;
            display:flex;flex-direction:column;box-shadow:0 20px 50px rgba(0,0,0,.25)}
.modal-header{display:flex;align-items:center;justify-content:space-between;
               padding:18px 22px;border-bottom:1px solid #e5e7eb}
.modal-header h3{margin:0;font-size:16px;color:#111827}
.modal-close{background:transparent;border:0;font-size:24px;color:#9ca3af;cursor:pointer;
              line-height:1;padding:0 4px}
.modal-close:hover{color:#374151}
.modal-body{padding:18px 22px;overflow-y:auto}
.modal-desc{font-size:13px;color:#6b7280;margin:0 0 14px}
.contributor-row{display:flex;justify-content:space-between;align-items:center;
                  padding:10px 12px;border-bottom:1px solid #f3f4f6;font-size:14px}
.contributor-row:last-child{border-bottom:0}
.contributor-name{color:#1f2937;font-weight:500}
.contributor-count{color:#1a73e8;font-weight:600;font-size:13px;
                    background:#dbeafe;padding:2px 10px;border-radius:10px}
.qa-list{display:flex;flex-direction:column;gap:14px}
.qa-card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:20px 22px;
         transition:box-shadow .15s}
.qa-card:hover{box-shadow:0 4px 16px rgba(0,0,0,.06)}
.qa-q{font-size:16px;font-weight:600;color:#111827;line-height:1.5;margin-bottom:6px;
       cursor:pointer}
.qa-q:hover{color:#1a73e8}
.qa-q::before{content:"❓ ";color:#1a73e8}
.qa-meta{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:#9ca3af;
          margin-bottom:10px}
.qa-meta .badge{background:#f3f4f6;padding:2px 8px;border-radius:10px;font-weight:500}
.qa-meta .badge.contributor{background:#dbeafe;color:#1e40af}
.qa-meta .badge.up{background:#d1fae5;color:#065f46}
.qa-meta .badge.resolved{background:#fef3c7;color:#92400e}
.qa-a{background:#f9fafb;border-left:3px solid #10b981;border-radius:0 8px 8px 0;
       padding:12px 16px;font-size:14px;line-height:1.7;color:#1f2937;
       white-space:pre-wrap;word-break:break-word;
       max-height:120px;overflow:hidden;position:relative;transition:max-height .25s}
.qa-a.expanded{max-height:none}
.qa-a-fade{position:absolute;bottom:0;left:0;right:0;height:32px;
            background:linear-gradient(transparent,#f9fafb);pointer-events:none}
.qa-a.expanded .qa-a-fade{display:none}
.qa-toggle{margin-top:8px;background:transparent;color:#6b7280;border:0;font-size:12px;
            cursor:pointer;padding:4px 0;font-weight:500}
.qa-toggle:hover{color:#1a73e8}
.qa-actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.qa-actions button{background:#fff;border:1px solid #e5e7eb;padding:6px 14px;
                    border-radius:8px;font-size:13px;color:#4b5563;cursor:pointer;
                    font-weight:500;transition:all .15s}
.qa-actions button:hover{background:#f9fafb;border-color:#9ca3af}
.qa-actions button.voted{background:#d1fae5;border-color:#10b981;color:#065f46}
.qa-actions button.resolved{background:#fef3c7;border-color:#f59e0b;color:#92400e}
.qa-actions button:disabled{cursor:not-allowed;opacity:.7}
.empty{text-align:center;color:#9ca3af;padding:60px 20px;font-size:15px}
.empty h2{color:#374151;font-size:20px;margin-bottom:8px}
@media (max-width: 600px){
  .page{padding:20px 14px}
  h1{font-size:22px}
}
</style></head><body>
<div class="page">
  <div class="page-header">
    <div>
      <h1>🤝 みんなのナレッジ <span class="version-badge">v__VERSION__</span></h1>
      <div class="subtitle">社員が共有した質問と回答の蓄積</div>
    </div>
    <a class="back-link" href="/">← チャットに戻る</a>
  </div>

  <div class="stats-row" id="stats-row"></div>

  <div class="toolbar">
    <input type="text" class="search-input" id="kbSearch"
           placeholder="🔍 質問・回答を検索（部分一致）" autocomplete="off">
  </div>

  <div class="qa-list" id="qaList">
    <div class="empty">読み込み中…</div>
  </div>
</div>

<script>
function escape(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c])}
function fmtDate(iso){
  if(!iso) return '';
  const d = new Date(iso);
  if(isNaN(d)) return iso;
  return d.toLocaleDateString('ja-JP') + ' ' + d.toLocaleTimeString('ja-JP',{hour:'2-digit',minute:'2-digit'});
}

let voted = JSON.parse(localStorage.getItem('kb_voted') || '{}');
let resolved = JSON.parse(localStorage.getItem('kb_resolved') || '{}');

async function loadKB(q=''){
  const url = '/api/knowledge-base' + (q ? '?q=' + encodeURIComponent(q) : '');
  const r = await fetch(url);
  if(!r.ok){
    document.getElementById('qaList').innerHTML = '<div class="empty"><h2>読み込み失敗</h2></div>';
    return;
  }
  const data = await r.json();
  renderStats(data);
  renderList(data.items);
}

function renderStats(data){
  const items = data.items || [];
  const totalUp = items.reduce((a,x)=>a+x.votes_up, 0);
  const totalResolved = items.reduce((a,x)=>a+x.resolved_count, 0);
  // 貢献者ごとの投稿数を集計
  const contribCount = {};
  for(const x of items){
    if(!x.contributor) continue;
    contribCount[x.contributor] = (contribCount[x.contributor] || 0) + 1;
  }
  const contributors = Object.keys(contribCount).length;
  document.getElementById('stats-row').innerHTML = `
    <div class="stat-card"><div class="label">📚 蓄積されたQ&A</div><div class="value">${data.total}</div></div>
    <div class="stat-card"><div class="label">👍 役立った投票</div><div class="value">${totalUp}</div></div>
    <div class="stat-card"><div class="label">✅ 解決報告</div><div class="value">${totalResolved}</div></div>
    <div class="stat-card clickable" id="stat-contributors" title="クリックで貢献者一覧を表示">
      <div class="label">👥 貢献した社員</div>
      <div class="value">${contributors}</div>
      <div class="stat-hint">▾ 詳細を見る</div>
    </div>
  `;
  // 貢献者カードのクリックハンドラ
  const card = document.getElementById('stat-contributors');
  if(card && contributors > 0){
    card.onclick = () => showContributorsModal(contribCount);
  }
}

function showContributorsModal(contribCount){
  // 投稿数の多い順にソート
  const sorted = Object.entries(contribCount).sort((a,b) => b[1] - a[1]);
  const rows = sorted.map(([name, count]) => `
    <div class="contributor-row">
      <span class="contributor-name">📝 ${escape(name)}</span>
      <span class="contributor-count">${count} 件</span>
    </div>
  `).join('');
  const html = `
    <div class="modal-overlay" id="contributors-overlay">
      <div class="modal-box">
        <div class="modal-header">
          <h3>👥 貢献者一覧（${sorted.length}名）</h3>
          <button class="modal-close" aria-label="閉じる">×</button>
        </div>
        <div class="modal-body">
          <p class="modal-desc">「みんなのナレッジ」に Q&A を共有した社員の一覧です。</p>
          ${rows}
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', html);
  const overlay = document.getElementById('contributors-overlay');
  const close = () => overlay.remove();
  overlay.querySelector('.modal-close').onclick = close;
  overlay.onclick = (e) => { if(e.target === overlay) close(); };
  document.addEventListener('keydown', function escHandler(e){
    if(e.key === 'Escape'){ close(); document.removeEventListener('keydown', escHandler); }
  });
}

function renderList(items){
  const list = document.getElementById('qaList');
  if(!items.length){
    list.innerHTML = '<div class="empty"><h2>該当するQ&Aがありません</h2><p>検索条件を変えるか、チャットで質問してみてください</p></div>';
    return;
  }
  list.innerHTML = items.map(x => {
    const upDone = voted[x.file_id] === 'up';
    const resDone = !!resolved[x.file_id];
    return `
    <div class="qa-card" data-id="${escape(x.file_id)}">
      <div class="qa-q" data-q="${escape(x.question)}">${escape(x.question)}</div>
      <div class="qa-meta">
        ${x.contributor ? `<span class="badge contributor">📝 ${escape(x.contributor)}</span>` : ''}
        <span class="badge">${fmtDate(x.shared_at)}</span>
        ${x.votes_up > 0 ? `<span class="badge up">👍 ${x.votes_up}</span>` : ''}
        ${x.resolved_count > 0 ? `<span class="badge resolved">✅ ${x.resolved_count}人が解決</span>` : ''}
      </div>
      <div class="qa-a">${escape(x.answer)}<div class="qa-a-fade"></div></div>
      <button class="qa-toggle">▾ 全文を表示</button>
      <div class="qa-actions">
        <button class="vote-up ${upDone?'voted':''}" data-kind="up" ${upDone?'disabled':''}>👍 役立った ${upDone?'(済)':''}</button>
        <button class="vote-resolved ${resDone?'resolved':''}" data-kind="resolved" ${resDone?'disabled':''}>✅ 解決した ${resDone?'(済)':''}</button>
        <button class="vote-down" data-kind="down">👎 違うかも</button>
        <button class="reask">💬 これと同じ質問をする</button>
      </div>
    </div>
    `;
  }).join('');
  // クリックハンドラ
  list.querySelectorAll('.qa-toggle').forEach(btn => {
    btn.onclick = () => {
      const a = btn.previousElementSibling;
      const expanded = a.classList.toggle('expanded');
      btn.textContent = expanded ? '▴ 折りたたむ' : '▾ 全文を表示';
    };
  });
  list.querySelectorAll('.qa-q').forEach(el => {
    el.onclick = () => location.href = '/?q=' + encodeURIComponent(el.dataset.q);
  });
  list.querySelectorAll('.reask').forEach(btn => {
    btn.onclick = () => {
      const card = btn.closest('.qa-card');
      const q = card.querySelector('.qa-q').dataset.q;
      location.href = '/?q=' + encodeURIComponent(q);
    };
  });
  list.querySelectorAll('.vote-up, .vote-resolved, .vote-down').forEach(btn => {
    btn.onclick = async () => {
      const card = btn.closest('.qa-card');
      const fileId = card.dataset.id;
      const kind = btn.dataset.kind;
      btn.disabled = true;
      try {
        const r = await fetch('/api/knowledge-base/vote', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({file_id: fileId, kind})
        });
        if(!r.ok) throw new Error((await r.json()).detail || r.statusText);
        if(kind === 'up'){ voted[fileId] = 'up'; localStorage.setItem('kb_voted', JSON.stringify(voted)); }
        if(kind === 'resolved'){ resolved[fileId] = true; localStorage.setItem('kb_resolved', JSON.stringify(resolved)); }
        loadKB(document.getElementById('kbSearch').value.trim());
      } catch(e) {
        alert('投票失敗: ' + e.message);
        btn.disabled = false;
      }
    };
  });
}

let searchTimer;
document.getElementById('kbSearch').addEventListener('input', e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadKB(e.target.value.trim()), 250);
});

loadKB();
</script>
</body></html>"""


@app.get("/api/version", response_class=HTMLResponse)
async def api_version():
    """現在のバージョン情報と直近の変更履歴を返す（要認証なし）。"""
    changelog_path = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    changelog_md = ""
    if changelog_path.exists():
        try:
            changelog_md = changelog_path.read_text(encoding="utf-8")
        except OSError:
            changelog_md = ""
    safe_md = _esc(changelog_md)
    return HTMLResponse(f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>バージョン情報 — Inquira v{__version__}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif;
     background:#f7f8fa;color:#1f2937;padding:32px;line-height:1.7;font-size:15px}}
.card{{background:#fff;max-width:820px;margin:0 auto;border-radius:14px;
       padding:32px;box-shadow:0 4px 24px rgba(0,0,0,.08)}}
h1{{font-size:24px;color:#1a73e8;margin-bottom:6px}}
.meta{{color:#6b7280;font-size:13px;margin-bottom:24px;padding-bottom:14px;
       border-bottom:1px solid #e5e7eb}}
pre{{white-space:pre-wrap;font-family:inherit;font-size:14px;color:#374151;
     background:transparent;line-height:1.75}}
a.back{{display:inline-block;margin-bottom:18px;color:#1a73e8;text-decoration:none}}
a.back:hover{{text-decoration:underline}}
</style></head><body>
<div class="card">
  <a class="back" href="/">← チャットに戻る</a>
  <h1>Inquira v{__version__}</h1>
  <div class="meta">Semantic Versioning (MAJOR.MINOR.PATCH) に従ったリリース管理</div>
  <pre>{safe_md}</pre>
</div></body></html>""")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# ===========================================================================
# FAQ 候補化エンドポイント（管理画面の「🌱 FAQ 候補」タブから利用）
# ===========================================================================

from dataclasses import asdict as _dc_asdict  # noqa: E402


class FaqCandidateApproveRequest(BaseModel):
    question: str | None = None
    answer: str | None = None
    note: str | None = None


class FaqCandidateRejectRequest(BaseModel):
    note: str | None = None


class FaqCandidateSettingsUpdate(BaseModel):
    min_confidence: int | None = None
    min_asked_count: int | None = None
    min_unique_users: int | None = None
    similarity_threshold: float | None = None
    lookback_days: int | None = None
    auto_approve_enabled: bool | None = None
    auto_approve_min_confidence: int | None = None
    auto_approve_min_asked_count: int | None = None
    auto_approve_min_unique_users: int | None = None
    auto_detect_on_startup: bool | None = None


@app.get("/api/admin/faq-candidates")
async def api_faq_candidates_list(
    status: str | None = None,
    user: dict = Depends(require_user),
):
    items = faq_candidates.list_all(status=status)
    return {
        "candidates": [_dc_asdict(c) for c in items],
        "counts": faq_candidates.count_by_status(),
    }


@app.post("/api/admin/faq-candidates/detect")
async def api_faq_candidates_detect(user: dict = Depends(require_user)):
    stats = faq_candidates.detect()
    audit.record("faq_candidate_detect", user=user["email"], **stats)
    return stats


@app.post("/api/admin/faq-candidates/{cid}/approve")
async def api_faq_candidates_approve(
    cid: str,
    payload: FaqCandidateApproveRequest,
    user: dict = Depends(require_user),
):
    try:
        c = faq_candidates.approve(
            cid,
            reviewer=user["email"],
            question=payload.question,
            answer=payload.answer,
            note=payload.note,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="候補が見つかりません")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit.record(
        "faq_candidate_approve",
        user=user["email"],
        candidate_id=cid,
        doc_path=c.approved_doc_path,
    )
    return _dc_asdict(c)


@app.post("/api/admin/faq-candidates/{cid}/reject")
async def api_faq_candidates_reject(
    cid: str,
    payload: FaqCandidateRejectRequest,
    user: dict = Depends(require_user),
):
    try:
        c = faq_candidates.reject(cid, reviewer=user["email"], note=payload.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="候補が見つかりません")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit.record("faq_candidate_reject", user=user["email"], candidate_id=cid)
    return _dc_asdict(c)


@app.get("/api/admin/faq-candidate-settings")
async def api_faq_candidate_settings_get(user: dict = Depends(require_user)):
    return _dc_asdict(faq_candidate_settings.load())


@app.put("/api/admin/faq-candidate-settings")
async def api_faq_candidate_settings_put(
    payload: FaqCandidateSettingsUpdate,
    user: dict = Depends(require_user),
):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    s = faq_candidate_settings.update(**updates)
    audit.record("faq_candidate_settings_update", user=user["email"], **updates)
    return _dc_asdict(s)


# ===========================================================================
# 工数削減レポート（管理画面の「📈 削減効果」タブから利用）
# ===========================================================================


class ImpactSettingsUpdate(BaseModel):
    minutes_saved_per_answered_query: int | None = None
    minutes_saved_per_faq_shared: int | None = None
    hourly_rate_yen: int | None = None


@app.get("/api/admin/impact")
async def api_impact(days: int = 365, user: dict = Depends(require_user)):
    return impact.compute(days=days)


@app.put("/api/admin/impact-settings")
async def api_impact_settings_put(
    payload: ImpactSettingsUpdate,
    user: dict = Depends(require_user),
):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    s = impact.update_settings(**updates)
    audit.record("impact_settings_update", user=user["email"], **updates)
    return _dc_asdict(s)
