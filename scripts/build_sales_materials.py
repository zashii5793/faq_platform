"""営業提案用の資料（スライドPDF・動画風ウォークスルー）を生成する。

出力:
    docs/inquira_sales_deck.pdf          配布用スライド（A4横・1ページ1スライド）
    docs/inquira_sales_walkthrough.html  自動再生する動画風ウォークスルー
                                         （単一ファイル・画像は base64 埋め込みで自己完結）

使い方:
    python scripts/build_sales_materials.py

内容を直すときは、このファイルの SLIDES を編集して再実行する。
想定読者: 中小企業の経営層・情報システム部門。
"""
from __future__ import annotations

import base64
from pathlib import Path

from weasyprint import HTML

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
PDF_OUT = DOCS / "inquira_sales_deck.pdf"
HTML_OUT = DOCS / "inquira_sales_walkthrough.html"

# ---------------------------------------------------------------------------
# スライド定義 — bullets は (太字, 説明) のタプル
# ---------------------------------------------------------------------------
SLIDES: list[dict] = [
    {
        "kind": "cover",
        "title": "社内の「同じ質問」を、<br>自己解決に変える。",
        "sub": "中小企業向け　社内FAQプラットフォーム",
        "tag": "ご提案資料",
        "dwell": 5,
    },
    {
        "kind": "content",
        "kicker": "課題",
        "title": "こんなお悩み、ありませんか？",
        "lead": "社員からの問い合わせ対応に、担当者の時間が奪われていませんか。",
        "bullets": [
            ("同じ質問が繰り返し来る", "総務・人事・情シスに、毎回似た問い合わせが集中する"),
            ("資料はあるのに見つからない", "マニュアルは整備済みでも「どこにあるか」が分からない"),
            ("業務が属人化する", "ベテランや先輩に聞かないと進まず、新人が育ちにくい"),
            ("本業が止まる", "問い合わせ対応のたびに、担当者の集中が途切れる"),
        ],
        "dwell": 9,
    },
    {
        "kind": "content",
        "kicker": "よくある不安",
        "title": "「AIに社内資料を覚えさせる」のリスク",
        "lead": "生成AIへの“学習”には、見落とされがちな落とし穴があります。",
        "bullets": [
            ("機密情報が焼き込まれる", "一度学習させた情報はAIモデル内に残り、後から消しにくい"),
            ("情報が古くなる", "資料を更新しても、学習済みの古い回答が出続ける"),
            ("漏えい事故のリスク", "モデル経由で社外秘が想定外の相手に出てしまう恐れ"),
        ],
        "dwell": 9,
    },
    {
        "kind": "content",
        "kicker": "Inquira の考え方",
        "title": "「覚えさせる」のではなく「参照する」",
        "lead": "Inquira は回答のたびに社内資料を読みに行く RAG 方式です。",
        "bullets": [
            ("AIモデルに焼き込まない", "機密情報はモデルに残らず、参照元の資料だけを根拠にする"),
            ("更新が即反映", "資料を差し替えれば、次の回答からすぐ最新の内容に"),
            ("データは自社の管理下", "自社サーバーへの設置に対応し、情報を社外に出さない"),
        ],
        "image": "screenshot_chat_sidebar.png",
        "dwell": 10,
    },
    {
        "kind": "cards",
        "kicker": "導入メリット",
        "title": "Inquira がもたらす3つの価値",
        "cards": [
            ("01", "対応時間を取り戻す",
             "社員が24時間いつでも自己解決。担当者は本来の業務に集中できます。"),
            ("02", "“AIのウソ”を抑える",
             "出典付き・確信度表示で、根拠のない推測回答をさせません。"),
            ("03", "機密を社外に出さない",
             "自社サーバー導入とPII（個人情報）マスキングで情報統制を効かせられます。"),
        ],
        "dwell": 10,
    },
    {
        "kind": "content",
        "kicker": "製品画面",
        "title": "回答には、必ず“出典”が付く",
        "lead": "「どの資料のどこに書いてあるか」までワンクリックで確認できます。",
        "bullets": [
            ("根拠を明示", "回答の下に、参照した社内ドキュメントを表示"),
            ("全文をその場で確認", "出典をクリックすれば該当箇所の全文を閲覧できる"),
            ("だから信用できる", "“それっぽい回答”ではなく、裏付けのある回答"),
        ],
        "image": "demo_qa_session.png",
        "dwell": 10,
    },
    {
        "kind": "content",
        "kicker": "信頼性",
        "title": "根拠が弱いときは、AIに答えさせない",
        "lead": "生成AI最大の不安「ハルシネーション（もっともらしいウソ）」への備え。",
        "bullets": [
            ("確信度スコア", "回答の確からしさを 0〜100% で色分け表示"),
            ("推測回答をスキップ", "関連する社内資料が乏しい質問には推測で答えない"),
            ("推測表現を禁止", "「おそらく」等の曖昧な言い回しを出さない設計"),
        ],
        "image": "screenshot_confidence.png",
        "dwell": 10,
    },
    {
        "kind": "content",
        "kicker": "かんたん運用",
        "title": "資料の取り込みはドラッグ＆ドロップ",
        "lead": "IT専任者がいなくても、現場の担当者だけで運用を回せます。",
        "bullets": [
            ("主要な形式に対応", "PDF / Excel / PowerPoint / Markdown / テキスト"),
            ("機密箇所だけ除外", "取り込み時に、見せたくない部分だけを部分的に外せる"),
            ("まとめて一括登録", "複数ファイルを一度に確認して取り込み"),
        ],
        "image": "screenshot_upload_xlsx.png",
        "dwell": 10,
    },
    {
        "kind": "content",
        "kicker": "情シス向け",
        "title": "情報システム部門が安心できる設計",
        "lead": "セキュリティと統制の観点でも、検討に耐える作りにしています。",
        "bullets": [
            ("自社サーバー導入に対応", "クラウドに出したくないデータはオンプレミスで運用"),
            ("個人情報を自動マスキング", "メール・電話番号・マイナンバー等を取り込み時に伏字化"),
            ("アクセス制御と監査ログ", "Googleアカウントでログインを制限し、操作を記録"),
        ],
        "dwell": 10,
    },
    {
        "kind": "content",
        "kicker": "導入のしやすさ",
        "title": "スモールスタートで、すぐ試せる",
        "lead": "大がかりな導入プロジェクトは不要。1部署・少数の資料から始められます。",
        "bullets": [
            ("最短コマンド1つで起動", "Docker または uv で、評価環境をその日のうちに用意"),
            ("まずは PoC から", "1部署・代表的な資料だけで効果を体感"),
            ("段階的に拡大", "手応えを見ながら対象部署・資料を広げていく"),
        ],
        "image": "screenshot_running_now.png",
        "dwell": 10,
    },
    {
        "kind": "compare",
        "kicker": "導入後の変化",
        "title": "問い合わせ対応は、こう変わる",
        "before": [
            "質問が特定の人に集中する",
            "資料を探すのに時間がかかる",
            "ナレッジが個人と紙に散在する",
            "新人は先輩に聞かないと進まない",
        ],
        "after": [
            "社員が24時間その場で自己解決",
            "出典付き回答ですぐ裏付けを確認",
            "ナレッジが検索できる資産になる",
            "誰でも同じ答えにたどり着ける",
        ],
        "note": "※ 効果の大きさは、資料の量や問い合わせ件数によって異なります。",
        "dwell": 10,
    },
    {
        "kind": "closing",
        "title": "まずは、貴社の資料で<br>試してみませんか？",
        "points": [
            "貴社のドキュメントを使った PoC（試験導入）から開始",
            "効果を確認してから、本格導入を判断",
            "導入・運用の設計までご支援します",
        ],
        "cta": "お問い合わせ・PoC のご相談はお気軽に",
        "dwell": 8,
    },
]

# ---------------------------------------------------------------------------
# 画像 → data URI（PDF・HTML どちらも自己完結させる）
# ---------------------------------------------------------------------------
_img_cache: dict[str, str] = {}


def img_uri(filename: str) -> str:
    if filename not in _img_cache:
        raw = (DOCS / filename).read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        _img_cache[filename] = f"data:image/png;base64,{b64}"
    return _img_cache[filename]


# ---------------------------------------------------------------------------
# スライド本文の HTML（PDF・HTML で共通）
# ---------------------------------------------------------------------------
def _bullets_html(bullets: list) -> str:
    rows = []
    for b in bullets:
        if isinstance(b, tuple):
            strong, rest = b
            rows.append(
                f'<li><span class="b-mark">✓</span>'
                f'<span class="b-text"><b>{strong}</b><br>{rest}</span></li>'
            )
        else:
            rows.append(
                f'<li><span class="b-mark">✓</span>'
                f'<span class="b-text">{b}</span></li>'
            )
    return f'<ul class="bullets">{"".join(rows)}</ul>'


def _topbar(idx: int, total: int) -> str:
    return (
        '<div class="topbar">'
        '<span class="brand">Inquira</span>'
        f'<span class="pageno">{idx:02d} <span class="of">/ {total:02d}</span></span>'
        "</div>"
    )


def render_slide(slide: dict, idx: int, total: int) -> str:
    kind = slide["kind"]

    if kind == "cover":
        return (
            '<div class="slide cover">'
            '<div class="cover-glow"></div>'
            '<div class="cover-inner">'
            '<div class="logo">Inquira</div>'
            f'<h1>{slide["title"]}</h1>'
            f'<p class="cover-sub">{slide["sub"]}</p>'
            f'<div class="cover-tag">{slide["tag"]}</div>'
            "</div></div>"
        )

    if kind == "closing":
        pts = "".join(
            f'<li><span class="b-mark">→</span>'
            f'<span class="b-text">{p}</span></li>'
            for p in slide["points"]
        )
        return (
            '<div class="slide closing">'
            + _topbar(idx, total)
            + '<div class="closing-inner">'
            f'<h2>{slide["title"]}</h2>'
            f'<ul class="bullets">{pts}</ul>'
            f'<div class="cta">{slide["cta"]}</div>'
            "</div></div>"
        )

    if kind == "cards":
        cards = "".join(
            f'<div class="card"><div class="card-no">{no}</div>'
            f'<div class="card-title">{title}</div>'
            f'<div class="card-text">{text}</div></div>'
            for no, title, text in slide["cards"]
        )
        return (
            '<div class="slide content">'
            + _topbar(idx, total)
            + '<div class="head">'
            f'<div class="kicker">{slide["kicker"]}</div>'
            f'<h2>{slide["title"]}</h2>'
            "</div>"
            f'<div class="cards">{cards}</div>'
            "</div>"
        )

    if kind == "compare":
        before = "".join(f"<li>{x}</li>" for x in slide["before"])
        after = "".join(f"<li>{x}</li>" for x in slide["after"])
        return (
            '<div class="slide content">'
            + _topbar(idx, total)
            + '<div class="head">'
            f'<div class="kicker">{slide["kicker"]}</div>'
            f'<h2>{slide["title"]}</h2>'
            "</div>"
            '<div class="compare">'
            '<div class="cmp cmp-before"><div class="cmp-label">Before</div>'
            f"<ul>{before}</ul></div>"
            '<div class="cmp-arrow">▶</div>'
            '<div class="cmp cmp-after"><div class="cmp-label">After</div>'
            f"<ul>{after}</ul></div>"
            "</div>"
            f'<div class="note">{slide["note"]}</div>'
            "</div>"
        )

    # kind == "content"
    has_img = bool(slide.get("image"))
    text_block = (
        '<div class="text">'
        f'<div class="kicker">{slide["kicker"]}</div>'
        f'<h2>{slide["title"]}</h2>'
        f'<p class="lead">{slide["lead"]}</p>'
        + _bullets_html(slide["bullets"])
        + "</div>"
    )
    visual = (
        f'<div class="visual"><img src="{img_uri(slide["image"])}" alt=""></div>'
        if has_img
        else ""
    )
    body_cls = "body two-col" if has_img else "body one-col"
    return (
        '<div class="slide content">'
        + _topbar(idx, total)
        + f'<div class="{body_cls}">{text_block}{visual}</div>'
        "</div>"
    )


# ---------------------------------------------------------------------------
# 共通スタイル
# ---------------------------------------------------------------------------
BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
.slide {
  position: relative; overflow: hidden;
  background: #ffffff; color: #1f2937;
  font-family: "IPAPGothic", "IPAGothic", "Hiragino Kaku Gothic ProN",
               "Yu Gothic", "Meiryo", sans-serif;
}
.topbar {
  position: absolute; top: 0; left: 0; right: 0; height: 13mm;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 14mm; border-bottom: 1px solid #eef1f5;
}
.brand { font-size: 5mm; font-weight: bold; color: #1a73e8; letter-spacing: .04em; }
.pageno { font-size: 3.6mm; color: #9ca3af; font-weight: bold; }
.pageno .of { color: #d1d5db; font-weight: normal; }

.head { position: absolute; top: 20mm; left: 14mm; right: 14mm; }
.kicker {
  display: inline-block; background: #e8f0fe; color: #1a73e8;
  font-size: 3.4mm; font-weight: bold; padding: 1.4mm 4mm;
  border-radius: 999px; margin-bottom: 4mm; letter-spacing: .04em;
}
h2 { font-size: 9.5mm; line-height: 1.3; color: #111827; letter-spacing: .01em; }
.lead { font-size: 4.4mm; color: #4b5563; margin-top: 4mm; line-height: 1.6; }

.body { position: absolute; top: 21mm; left: 14mm; right: 14mm; bottom: 12mm; }
.body.two-col { display: flex; gap: 11mm; align-items: center; }
.two-col .text { flex: 1.05; }
.two-col .visual {
  flex: 1.25; display: flex; justify-content: center; align-items: center;
}
.body.one-col { display: flex; flex-direction: column; justify-content: center; }
.one-col .text { width: 100%; }

.bullets { list-style: none; margin-top: 7mm; }
.bullets li {
  display: flex; align-items: flex-start; gap: 4mm;
  margin-bottom: 5mm; line-height: 1.55;
}
.b-mark {
  flex: none; width: 7mm; height: 7mm; border-radius: 50%;
  background: #1a73e8; color: #fff; font-size: 4mm; font-weight: bold;
  display: flex; align-items: center; justify-content: center;
  margin-top: .4mm;
}
.b-text { font-size: 4mm; color: #4b5563; }
.b-text b { font-size: 4.7mm; color: #111827; }

.visual img {
  max-width: 100%; max-height: 150mm; width: auto; height: auto;
  border-radius: 4mm; border: 1px solid #e5e7eb;
  box-shadow: 0 6mm 16mm rgba(17,24,39,.16);
}

/* --- cover --- */
.cover { background: #0b1f3a; color: #fff; }
.cover-glow {
  position: absolute; width: 160mm; height: 160mm; border-radius: 50%;
  right: -50mm; top: -60mm;
  background: radial-gradient(circle, rgba(26,115,232,.55), rgba(26,115,232,0) 70%);
}
.cover-inner { position: absolute; left: 22mm; top: 56mm; right: 22mm; }
.logo {
  font-size: 6mm; font-weight: bold; letter-spacing: .12em;
  color: #7eb0f4; margin-bottom: 9mm;
}
.cover h1 { font-size: 15mm; line-height: 1.32; color: #fff; }
.cover-sub { font-size: 5mm; color: #b9c6d8; margin-top: 9mm; }
.cover-tag {
  display: inline-block; margin-top: 11mm;
  border: 1px solid #3a5a86; color: #9fb4cf;
  font-size: 3.8mm; padding: 2mm 6mm; border-radius: 999px;
}

/* --- cards --- */
.cards {
  position: absolute; top: 54mm; left: 14mm; right: 14mm; bottom: 22mm;
  display: flex; gap: 7mm;
}
.card {
  flex: 1; background: #f8fafc; border: 1px solid #e5e7eb;
  border-radius: 5mm; padding: 10mm 9mm;
  border-top: 3mm solid #1a73e8;
  display: flex; flex-direction: column; justify-content: center;
}
.card-no {
  font-size: 11mm; font-weight: bold; color: #1a73e8; opacity: .3;
  line-height: 1;
}
.card-title {
  font-size: 6mm; font-weight: bold; color: #111827;
  margin: 6mm 0 5mm; line-height: 1.35;
}
.card-text { font-size: 4.1mm; color: #4b5563; line-height: 1.7; }

/* --- compare --- */
.compare {
  position: absolute; top: 80mm; left: 14mm; right: 14mm;
  display: flex; align-items: stretch; gap: 5mm;
}
.cmp { flex: 1; border-radius: 5mm; padding: 9mm 9mm 7mm; }
.cmp-before { background: #fef2f2; border: 1px solid #fecaca; }
.cmp-after { background: #ecfdf5; border: 1px solid #a7f3d0; }
.cmp-label {
  font-size: 4.6mm; font-weight: bold; margin-bottom: 5mm;
  letter-spacing: .05em;
}
.cmp-before .cmp-label { color: #dc2626; }
.cmp-after .cmp-label { color: #059669; }
.cmp ul { list-style: none; }
.cmp li {
  font-size: 4.1mm; color: #374151; line-height: 1.5;
  padding: 4.2mm 0 4.2mm 6mm; position: relative;
  border-bottom: 1px dashed rgba(0,0,0,.08);
}
.cmp li:last-child { border-bottom: 0; }
.cmp-before li::before { content: "·"; position: absolute; left: 1mm; color: #dc2626; font-weight: bold; }
.cmp-after li::before { content: "✓"; position: absolute; left: 0; color: #059669; font-weight: bold; }
.cmp-arrow { align-self: center; color: #1a73e8; font-size: 7mm; }
.note {
  position: absolute; left: 14mm; right: 14mm; bottom: 11mm;
  font-size: 3.3mm; color: #9ca3af;
}

/* --- closing --- */
.closing { background: #0b1f3a; color: #fff; }
.closing .topbar { border-bottom-color: rgba(255,255,255,.12); }
.closing .brand { color: #7eb0f4; }
.closing .pageno { color: #6b87ad; }
.closing .pageno .of { color: #44597a; }
.closing-inner {
  position: absolute; left: 22mm; right: 22mm; top: 13mm; bottom: 0;
  display: flex; flex-direction: column; justify-content: center;
}
.closing h2 { color: #fff; font-size: 11mm; }
.closing .bullets { margin-top: 9mm; }
.closing .b-mark { background: #1a73e8; }
.closing .b-text { color: #cdd9e8; font-size: 4.4mm; }
.cta {
  margin-top: 11mm; align-self: flex-start;
  background: #1a73e8; color: #fff; font-size: 4.6mm; font-weight: bold;
  padding: 4mm 9mm; border-radius: 999px;
}
"""

# ---------------------------------------------------------------------------
# PDF 出力
# ---------------------------------------------------------------------------
def build_pdf() -> None:
    total = len(SLIDES)
    slides_html = "".join(
        render_slide(s, i + 1, total) for i, s in enumerate(SLIDES)
    )
    doc = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>
@page {{ size: A4 landscape; margin: 0; }}
html, body {{ margin: 0; padding: 0; }}
.slide {{
  width: 297mm; height: 210mm;
  page-break-after: always;
}}
.slide:last-child {{ page-break-after: auto; }}
{BASE_CSS}
</style></head><body>{slides_html}</body></html>"""
    HTML(string=doc, base_url=str(REPO)).write_pdf(str(PDF_OUT))
    print(f"  PDF      -> {PDF_OUT.relative_to(REPO)}  ({PDF_OUT.stat().st_size // 1024} KB)")


# ---------------------------------------------------------------------------
# 動画風 HTML ウォークスルー出力
# ---------------------------------------------------------------------------
def build_walkthrough() -> None:
    total = len(SLIDES)
    sections = []
    for i, s in enumerate(SLIDES):
        dwell = int(s.get("dwell", 9))
        sections.append(
            f'<div class="frame" data-dwell="{dwell}">'
            + render_slide(s, i + 1, total)
            + "</div>"
        )
    frames_html = "".join(sections)

    doc = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inquira ご紹介ウォークスルー</title>
<style>
{BASE_CSS}
html,body {{ height:100%; background:#0a1322; }}
body {{
  display:flex; align-items:center; justify-content:center;
  font-family:"Hiragino Kaku Gothic ProN","Yu Gothic","Meiryo",sans-serif;
}}
.player {{ width:min(96vw, 1100px); }}
.stage {{
  position:relative; width:100%; aspect-ratio:297/210;
  border-radius:14px; overflow:hidden;
  box-shadow:0 24px 60px rgba(0,0,0,.55);
  background:#fff;
}}
.frame {{
  position:absolute; inset:0;
  opacity:0; transition:opacity .55s ease;
  pointer-events:none;
}}
.frame.active {{ opacity:1; pointer-events:auto; }}
/* スライド本文は 297mm 基準で作ってあるので stage 幅にスケールさせる */
.frame .slide {{
  position:absolute; top:0; left:0;
  width:297mm; height:210mm;
  transform-origin:top left;
}}
.progress {{
  margin-top:14px; height:5px; border-radius:3px;
  background:rgba(255,255,255,.14); overflow:hidden;
}}
.progress-bar {{
  height:100%; width:0; background:linear-gradient(90deg,#1a73e8,#7eb0f4);
}}
.progress-bar.run {{ width:100%; }}
.controls {{
  margin-top:14px; display:flex; align-items:center; gap:14px;
  color:#cdd9e8; font-size:14px;
}}
.controls button {{
  background:#16263f; color:#dce6f3; border:1px solid #2c3f5c;
  border-radius:9px; padding:9px 16px; font-size:14px; cursor:pointer;
  font-family:inherit; transition:background .15s;
}}
.controls button:hover {{ background:#1f3454; }}
.controls .play {{ background:#1a73e8; border-color:#1a73e8; color:#fff; font-weight:bold; }}
.controls .play:hover {{ background:#1761c4; }}
.counter {{ margin-left:auto; font-variant-numeric:tabular-nums; }}
.hint {{ margin-top:9px; color:#5b76a0; font-size:12px; text-align:center; }}
.dots {{ display:flex; gap:6px; }}
.dot {{
  width:9px; height:9px; border-radius:50%; background:#2c3f5c;
  border:0; padding:0; cursor:pointer;
}}
.dot.active {{ background:#1a73e8; }}
</style></head><body>
<div class="player">
  <div class="stage" id="stage">{frames_html}</div>
  <div class="progress"><div class="progress-bar" id="bar"></div></div>
  <div class="controls">
    <button class="play" id="play">⏸ 一時停止</button>
    <button id="prev">‹ 戻る</button>
    <button id="next">次へ ›</button>
    <div class="dots" id="dots"></div>
    <span class="counter" id="counter"></span>
  </div>
  <div class="hint">自動再生中　—　← → キーで移動、スペースキーで再生／停止</div>
</div>
<script>
const frames=[...document.querySelectorAll('.frame')];
const bar=document.getElementById('bar');
const playBtn=document.getElementById('play');
const counter=document.getElementById('counter');
const dotsWrap=document.getElementById('dots');
let cur=0, playing=true, timer=null;

frames.forEach((_,i)=>{{
  const d=document.createElement('button');
  d.className='dot'; d.onclick=()=>{{go(i); pause();}};
  dotsWrap.appendChild(d);
}});
const dots=[...dotsWrap.children];

// 297mm 基準のスライドを stage 幅にフィットさせる
function fit(){{
  const stage=document.getElementById('stage');
  const w=stage.clientWidth;
  const base=297*96/25.4;            // 297mm を px に
  const scale=w/base;
  frames.forEach(f=>{{
    const sl=f.querySelector('.slide');
    if(sl) sl.style.transform='scale('+scale+')';
  }});
}}
window.addEventListener('resize', fit);

function render(){{
  frames.forEach((f,i)=>f.classList.toggle('active', i===cur));
  dots.forEach((d,i)=>d.classList.toggle('active', i===cur));
  counter.textContent=(cur+1)+' / '+frames.length;
}}
function startBar(sec){{
  bar.classList.remove('run');
  bar.style.transition='none'; bar.style.width='0';
  void bar.offsetWidth;
  bar.style.transition='width '+sec+'s linear';
  bar.style.width='100%';
}}
function schedule(){{
  clearTimeout(timer);
  if(!playing) return;
  const sec=parseInt(frames[cur].dataset.dwell||'9',10);
  startBar(sec);
  timer=setTimeout(()=>{{
    if(cur<frames.length-1){{ go(cur+1); }}
    else {{ pause(); }}
  }}, sec*1000);
}}
function go(i){{
  cur=(i+frames.length)%frames.length;
  render();
  if(playing) schedule();
}}
function play(){{
  playing=true; playBtn.textContent='⏸ 一時停止';
  playBtn.classList.add('play');
  if(cur===frames.length-1) cur=0;
  render(); schedule();
}}
function pause(){{
  playing=false; playBtn.textContent='▶ 再生';
  clearTimeout(timer);
  bar.style.transition='none';
}}
playBtn.onclick=()=> playing?pause():play();
document.getElementById('next').onclick=()=>{{go(cur+1); if(playing) schedule();}};
document.getElementById('prev').onclick=()=>{{go(cur-1); if(playing) schedule();}};
document.addEventListener('keydown',e=>{{
  if(e.key==='ArrowRight'){{go(cur+1); if(playing) schedule();}}
  else if(e.key==='ArrowLeft'){{go(cur-1); if(playing) schedule();}}
  else if(e.key===' '){{e.preventDefault(); playing?pause():play();}}
}});
fit(); render(); schedule();
</script>
</body></html>"""
    HTML_OUT.write_text(doc, encoding="utf-8")
    print(f"  HTML     -> {HTML_OUT.relative_to(REPO)}  ({HTML_OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    print("営業提案資料を生成します…")
    build_pdf()
    build_walkthrough()
    print("完了。")
