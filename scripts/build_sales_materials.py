"""営業提案用の資料（スライドPDF・動画風ウォークスルー）を生成する。

出力:
    docs/inquira_sales_deck.pdf          配布用スライド（A4横・1ページ1スライド）
    docs/inquira_sales_walkthrough.html  自動再生する動画風ウォークスルー
                                         （単一ファイル・画像は base64 埋め込みで自己完結）

使い方:
    python scripts/build_sales_materials.py

デザイン方針: 親しみやすい・図解重視。アイコン（インラインSVG）と
フロー図・3ステップ図・数値タイルで、IT に詳しくない読み手にも
直感的に伝わる構成。内容を直すときは SLIDES を編集して再実行する。
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
# アクセントカラー（名前 -> (濃色, 淡色タイント)）
# ---------------------------------------------------------------------------
PALETTE = {
    "blue": ("#2f6bed", "#e9f0ff"),
    "rose": ("#e1556f", "#fdecef"),
    "amber": ("#d98521", "#fdf1dc"),
    "green": ("#0e9f6e", "#e4f7ef"),
    "purple": ("#7a5bd6", "#efebfc"),
    "teal": ("#0d97a6", "#e0f4f6"),
}

# ---------------------------------------------------------------------------
# インライン SVG アイコン（24x24・stroke ベース）
# ---------------------------------------------------------------------------
ICONS = {
    "chat": '<path d="M5 4.5h14A2.5 2.5 0 0 1 21.5 7v7A2.5 2.5 0 0 1 19 16.5h-7l-5 4v-4H5A2.5 2.5 0 0 1 2.5 14V7A2.5 2.5 0 0 1 5 4.5Z"/>',
    "search": '<circle cx="11" cy="11" r="6.4"/><path d="M20.4 20.4l-4.8-4.8"/>',
    "doc": '<path d="M13.5 3.2H7.2a2 2 0 0 0-2 2v13.6a2 2 0 0 0 2 2h9.6a2 2 0 0 0 2-2V8.7Z"/><path d="M13.5 3.2v5.5h5.3"/><path d="M8.6 13h6.8M8.6 16.4h4.4"/>',
    "spark": '<path d="M12 3.2l1.9 5.5 5.5 1.8-5.5 1.8L12 17.8l-1.9-5.5L4.6 10.5l5.5-1.8Z"/><path d="M18.6 14.6l.6 1.9 1.9.6-1.9.6-.6 1.9-.6-1.9-1.9-.6 1.9-.6Z"/>',
    "lock": '<rect x="4.6" y="10.4" width="14.8" height="9.4" rx="2.2"/><path d="M8 10.4V7.8a4 4 0 0 1 8 0v2.6"/>',
    "clock": '<circle cx="12" cy="12" r="8.1"/><path d="M12 7.4V12l3.1 1.9"/>',
    "upload": '<path d="M12 15.4V4.2"/><path d="M7.6 8.6 12 4.2l4.4 4.4"/><path d="M5 14.4v3.4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3.4"/>',
    "check": '<path d="M5 12.6l4.7 4.7L19.4 7.2"/>',
    "people": '<circle cx="9.2" cy="8.2" r="3.3"/><path d="M3.5 19.8c0-3.2 2.6-5.3 5.7-5.3s5.7 2.1 5.7 5.3"/><path d="M16 5.1a3.3 3.3 0 0 1 0 6.6"/><path d="M17.6 14.8c2.6.4 3.9 2.4 3.9 5"/>',
    "refresh": '<path d="M19.8 11.3A7.8 7.8 0 0 0 6.7 6L4.2 8.5"/><path d="M4.2 4.1v4.5h4.5"/><path d="M4.2 12.7A7.8 7.8 0 0 0 17.3 18l2.5-2.5"/><path d="M19.8 20v-4.5h-4.5"/>',
    "shield": '<path d="M12 3.4l7.4 2.7v5.6c0 4.9-3.3 7.8-7.4 8.9-4.1-1.1-7.4-4-7.4-8.9V6.1Z"/><path d="M8.9 12l2.3 2.3 4.1-4.5"/>',
    "folder": '<path d="M4 6.9a2 2 0 0 1 2-2h3.5l2 2.4H18a2 2 0 0 1 2 2v8.1a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/>',
    "server": '<rect x="4.2" y="4.6" width="15.6" height="6.3" rx="1.8"/><rect x="4.2" y="13" width="15.6" height="6.3" rx="1.8"/><path d="M7.6 7.7h.02M7.6 16.1h.02"/>',
    "eyeoff": '<path d="M4 4l16 16"/><path d="M9.6 5.3A9 9 0 0 1 12 5c5.1 0 8.9 5.1 8.9 7a12.6 12.6 0 0 1-2.5 3"/><path d="M6.3 7.4A12.6 12.6 0 0 0 3.1 12c0 1.9 3.8 7 8.9 7a9 9 0 0 0 3.3-.7"/>',
    "alert": '<path d="M12 4.8l8.2 14.1a1 1 0 0 1-.9 1.5H4.7a1 1 0 0 1-.9-1.5Z"/><path d="M12 9.7v4.3M12 17.1h.02"/>',
    "arrow": '<path d="M4.5 12h13"/><path d="M12 6.2l6 5.8-6 5.8"/>',
    "bolt": '<path d="M13.4 3.2 5.6 13.3H11l-1 7.5 7.8-10.2h-5.3Z"/>',
    "target": '<circle cx="12" cy="12" r="8.1"/><circle cx="12" cy="12" r="3.3"/>',
    "heart": '<path d="M12 20.3C7 17 3.5 13.8 3.5 9.7A4.7 4.7 0 0 1 12 7a4.7 4.7 0 0 1 8.5 2.7c0 4.1-3.5 7.3-8.5 10.6Z"/>',
}


def svg(name: str, stroke: float = 1.9) -> str:
    return (
        f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
        f"{ICONS[name]}</svg>"
    )


# ---------------------------------------------------------------------------
# スライド定義
# ---------------------------------------------------------------------------
SLIDES: list[dict] = [
    {
        "kind": "cover",
        "title": "社内の「同じ質問」を、<br>自己解決に変える。",
        "sub": "中小企業向け　社内FAQプラットフォーム",
        "tags": ["ご提案資料", "経営層・情報システム部門さま向け"],
        "dwell": 5,
    },
    {
        "kind": "bullets",
        "accent": "rose",
        "kicker": "課題",
        "icon": "heart",
        "title": "こんなお悩み、ありませんか？",
        "lead": "社員からの問い合わせ対応に、担当者の時間が静かに奪われています。",
        "bullets": [
            ("chat", "同じ質問が繰り返し来る",
             "総務・人事・情シスに、毎回似た問い合わせが集中する"),
            ("search", "資料はあるのに見つからない",
             "マニュアルは整備済みでも「どこにあるか」が分からない"),
            ("people", "業務が属人化する",
             "ベテランや先輩に聞かないと進まず、新人が育ちにくい"),
            ("clock", "本業が止まる",
             "問い合わせ対応のたびに、担当者の集中が途切れる"),
        ],
        "dwell": 9,
    },
    {
        "kind": "bullets",
        "accent": "amber",
        "kicker": "よくある不安",
        "icon": "alert",
        "title": "「AIに社内資料を覚えさせる」のリスク",
        "lead": "生成AIへの“学習”には、見落とされがちな落とし穴があります。",
        "bullets": [
            ("lock", "機密情報が焼き込まれる",
             "一度学習させた情報はAIモデル内に残り、後から消しにくい"),
            ("refresh", "情報がすぐ古くなる",
             "資料を更新しても、学習済みの古い回答が出続けてしまう"),
            ("alert", "漏えい事故のリスク",
             "モデル経由で社外秘が、想定外の相手に出てしまう恐れ"),
        ],
        "dwell": 9,
    },
    {
        "kind": "flow",
        "accent": "blue",
        "kicker": "Inquira の仕組み",
        "icon": "spark",
        "title": "「覚えさせる」のではなく「参照する」",
        "lead": "Inquira は質問のたびに社内資料を読みに行く RAG 方式です。",
        "steps": [
            ("chat", "社員が質問", "ふだんの言葉で<br>聞くだけ"),
            ("search", "社内資料を検索", "関連する箇所だけを<br>探し出す"),
            ("spark", "AIが要点を整理", "見つけた箇所をもとに<br>回答を組み立てる"),
            ("doc", "出典付きで回答", "根拠の資料を<br>添えて返す"),
        ],
        "callout": "資料はAIに“覚えさせない”。質問のたびに、その場で“参照”するだけ。"
                   "だから機密はモデルに残らず、資料を差し替えれば回答もすぐ最新に。",
        "dwell": 11,
    },
    {
        "kind": "iconcards",
        "kicker": "導入メリット",
        "icon": "heart",
        "title": "Inquira がもたらす 3 つの価値",
        "lead": "「時間」「信頼」「安心」を、まとめて手に入れられます。",
        "cards": [
            ("blue", "clock", "対応時間を取り戻す",
             "社員が24時間いつでも自己解決。担当者は本来の業務に集中できます。"),
            ("purple", "shield", "“AIのウソ”を抑える",
             "出典付き・確信度表示で、根拠のない推測回答をさせません。"),
            ("green", "lock", "機密を社外に出さない",
             "自社サーバー導入とPII（個人情報）マスキングで情報統制を効かせられます。"),
        ],
        "dwell": 10,
    },
    {
        "kind": "content",
        "accent": "blue",
        "kicker": "製品画面",
        "icon": "doc",
        "title": "回答には、必ず“出典”が付く",
        "lead": "「どの資料のどこに書いてあるか」までワンクリックで確認できます。",
        "bullets": [
            ("doc", "根拠を明示",
             "回答の下に、参照した社内ドキュメントを表示"),
            ("search", "全文をその場で確認",
             "出典をクリックすれば、該当箇所の全文を閲覧できる"),
            ("check", "だから信用できる",
             "“それっぽい回答”ではなく、裏付けのある回答"),
        ],
        "image": "demo_qa_session.png",
        "dwell": 10,
    },
    {
        "kind": "content",
        "accent": "purple",
        "kicker": "信頼性",
        "icon": "shield",
        "title": "根拠が弱いときは、AIに答えさせない",
        "lead": "生成AI最大の不安「ハルシネーション（もっともらしいウソ）」への備え。",
        "bullets": [
            ("target", "確信度スコア",
             "回答の確からしさを 0〜100% で色分け表示"),
            ("shield", "推測回答をスキップ",
             "関連する社内資料が乏しい質問には推測で答えない"),
            ("check", "推測表現を禁止",
             "「おそらく」等の曖昧な言い回しを出さない設計"),
        ],
        "image": "screenshot_confidence.png",
        "dwell": 10,
    },
    {
        "kind": "content",
        "accent": "teal",
        "kicker": "かんたん運用",
        "icon": "upload",
        "title": "資料の取り込みはドラッグ＆ドロップ",
        "lead": "IT専任者がいなくても、現場の担当者だけで運用を回せます。",
        "bullets": [
            ("upload", "主要な形式に対応",
             "PDF / Excel / PowerPoint / Markdown / テキスト"),
            ("eyeoff", "機密箇所だけ除外",
             "取り込み時に、見せたくない部分だけを部分的に外せる"),
            ("folder", "まとめて一括登録",
             "複数ファイルを一度に確認して取り込み"),
        ],
        "image": "screenshot_upload_xlsx.png",
        "dwell": 10,
    },
    {
        "kind": "iconcards",
        "kicker": "情シス向け",
        "icon": "shield",
        "title": "情報システム部門が安心できる設計",
        "lead": "セキュリティと統制の観点でも、検討に耐える作りにしています。",
        "cards": [
            ("teal", "server", "自社サーバー導入に対応",
             "クラウドに出したくないデータは、オンプレミスで運用できます。"),
            ("amber", "eyeoff", "個人情報を自動マスキング",
             "メール・電話番号・マイナンバー等を、取り込み時に自動で伏字化。"),
            ("green", "shield", "アクセス制御と監査ログ",
             "Googleアカウントでログインを制限し、操作の記録を残せます。"),
        ],
        "dwell": 10,
    },
    {
        "kind": "stats",
        "accent": "blue",
        "kicker": "導入効果",
        "icon": "spark",
        "title": "数字で見る、導入後のインパクト",
        "lead": "問い合わせ対応の負担を、目に見えるかたちで軽くします。",
        "stats": [
            ("blue", "chat", "-70%", "ヘルプデスクへの<br>問い合わせ件数", "社員の自己解決による想定削減"),
            ("teal", "clock", "約10秒", "質問してから<br>出典付き回答まで", "その場で疑問が解消"),
            ("amber", "refresh", "24/365", "いつでも自己解決<br>できる体制", "担当者の不在時間も対応"),
            ("green", "target", "90%+", "関連資料の<br>ヒット率", "Embedding 構成での想定値"),
        ],
        "note": "※ 数値は想定値・構成例です。実際の効果は、資料の量や問い合わせ内容により異なります。",
        "dwell": 11,
    },
    {
        "kind": "compare",
        "accent": "blue",
        "kicker": "導入後の変化",
        "icon": "refresh",
        "title": "問い合わせ対応は、こう変わる",
        "lead": "「人に集中する対応」から「その場で解決する仕組み」へ。",
        "before": [
            "質問が特定の人に集中する",
            "資料を探すのに時間がかかる",
            "ナレッジが個人と紙に散在する",
            "新人は先輩に聞かないと進まない",
        ],
        "after": [
            "社員が24時間その場で自己解決",
            "出典付き回答で、すぐ裏付けを確認",
            "ナレッジが検索できる資産になる",
            "誰でも同じ答えにたどり着ける",
        ],
        "dwell": 10,
    },
    {
        "kind": "steps",
        "accent": "amber",
        "kicker": "導入ステップ",
        "icon": "bolt",
        "title": "スモールスタートで、すぐ試せる",
        "lead": "大がかりな導入プロジェクトは不要。3 ステップで始められます。",
        "steps": [
            ("folder", "資料を準備", "よくある質問の<br>元資料を集めるだけ"),
            ("bolt", "環境を起動", "Docker / uv で<br>最短その日に立ち上げ"),
            ("target", "1部署で PoC", "小さく試して<br>効果を確かめる"),
        ],
        "dwell": 10,
    },
    {
        "kind": "closing",
        "accent": "blue",
        "title": "まずは、貴社の資料で<br>試してみませんか？",
        "points": [
            "貴社のドキュメントを使った PoC（試験導入）から開始",
            "効果を確認してから、本格導入を判断",
            "導入・運用の設計まで、伴走してご支援します",
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
        _img_cache[filename] = (
            "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        )
    return _img_cache[filename]


# ---------------------------------------------------------------------------
# パーツ
# ---------------------------------------------------------------------------
def topbar(idx: int, total: int) -> str:
    return (
        '<div class="topbar">'
        f'<span class="brand"><span class="brand-mark">{svg("chat")}</span>Inquira</span>'
        f'<span class="pageno">{idx:02d}<span class="of"> / {total:02d}</span></span>'
        "</div>"
    )


def head(slide: dict) -> str:
    lead = f'<p class="lead">{slide["lead"]}</p>' if slide.get("lead") else ""
    return (
        '<div class="head">'
        f'<span class="kicker">{svg(slide["icon"])}{slide["kicker"]}</span>'
        f'<h2>{slide["title"]}</h2>'
        f"{lead}"
        "</div>"
    )


def accent_style(slide: dict) -> str:
    ac, tint = PALETTE[slide.get("accent", "blue")]
    return f'style="--ac:{ac};--tint:{tint}"'


def bullets_block(bullets: list) -> str:
    rows = []
    for icon, strong, text in bullets:
        rows.append(
            '<div class="ib">'
            f'<span class="ib-ic">{svg(icon)}</span>'
            '<div class="ib-tx">'
            f'<div class="ib-h">{strong}</div>'
            f'<div class="ib-d">{text}</div>'
            "</div></div>"
        )
    return f'<div class="iblist">{"".join(rows)}</div>'


# ---------------------------------------------------------------------------
# スライド描画
# ---------------------------------------------------------------------------
def render_slide(slide: dict, idx: int, total: int) -> str:
    kind = slide["kind"]

    if kind == "cover":
        tags = "".join(f"<span>{t}</span>" for t in slide["tags"])
        return (
            '<div class="slide cover" style="--ac:#2f6bed;--tint:#e9f0ff">'
            '<span class="blob b1"></span><span class="blob b2"></span>'
            '<span class="blob b3"></span>'
            '<div class="cover-inner">'
            f'<div class="cover-logo"><span class="cover-mark">{svg("chat")}</span>Inquira</div>'
            f'<h1>{slide["title"]}</h1>'
            f'<p class="cover-sub">{slide["sub"]}</p>'
            f'<div class="cover-tags">{tags}</div>'
            "</div>"
            '<div class="cover-foot">社内ヘルプデスク向け RAG プラットフォーム</div>'
            "</div>"
        )

    if kind == "closing":
        pts = "".join(
            f'<div class="cl-pt"><span class="cl-ic">{svg("check")}</span>'
            f"<span>{p}</span></div>"
            for p in slide["points"]
        )
        return (
            f'<div class="slide closing" {accent_style(slide)}>'
            + topbar(idx, total)
            + '<span class="blob b1"></span><span class="blob b2"></span>'
            '<div class="closing-inner">'
            f'<h2>{slide["title"]}</h2>'
            f'<div class="cl-pts">{pts}</div>'
            f'<div class="cta">{svg("arrow")}<span>{slide["cta"]}</span></div>'
            '<div class="cl-note">貴社のドキュメントで、まずは小さく試せます。</div>'
            "</div></div>"
        )

    if kind == "bullets":
        return (
            f'<div class="slide" {accent_style(slide)}>'
            + topbar(idx, total)
            + head(slide)
            + '<div class="body one-col">'
            + bullets_block(slide["bullets"])
            + "</div></div>"
        )

    if kind == "content":
        return (
            f'<div class="slide" {accent_style(slide)}>'
            + topbar(idx, total)
            + head(slide)
            + '<div class="body two-col">'
            + f'<div class="col-tx">{bullets_block(slide["bullets"])}</div>'
            + f'<div class="visual"><img src="{img_uri(slide["image"])}" alt=""></div>'
            + "</div></div>"
        )

    if kind == "iconcards":
        cards = []
        for color, icon, title, text in slide["cards"]:
            ac, tint = PALETTE[color]
            cards.append(
                f'<div class="ic-card" style="--ac:{ac};--tint:{tint}">'
                f'<span class="ic-card-ic">{svg(icon)}</span>'
                f'<div class="ic-card-t">{title}</div>'
                f'<div class="ic-card-d">{text}</div>'
                "</div>"
            )
        return (
            f'<div class="slide" {accent_style(slide)}>'
            + topbar(idx, total)
            + head(slide)
            + f'<div class="iccardwrap"><div class="iccards">{"".join(cards)}</div></div>'
            "</div>"
        )

    if kind == "flow":
        parts = []
        for i, (icon, title, desc) in enumerate(slide["steps"]):
            if i:
                parts.append(f'<span class="flow-arrow">{svg("arrow")}</span>')
            parts.append(
                '<div class="flow-step">'
                f'<span class="flow-no">{i + 1}</span>'
                f'<span class="flow-ic">{svg(icon)}</span>'
                f'<div class="flow-t">{title}</div>'
                f'<div class="flow-d">{desc}</div>'
                "</div>"
            )
        return (
            f'<div class="slide" {accent_style(slide)}>'
            + topbar(idx, total)
            + head(slide)
            + '<div class="flowwrap">'
            + f'<div class="flow">{"".join(parts)}</div>'
            + '<div class="flow-callout">'
            f'<span class="fc-ic">{svg("spark")}</span>'
            f'<span>{slide["callout"]}</span>'
            "</div></div></div>"
        )

    if kind == "steps":
        parts = []
        for i, (icon, title, desc) in enumerate(slide["steps"]):
            if i:
                parts.append(f'<span class="step-link">{svg("arrow")}</span>')
            parts.append(
                '<div class="step-card">'
                f'<span class="step-no">STEP {i + 1}</span>'
                f'<span class="step-ic">{svg(icon)}</span>'
                f'<div class="step-t">{title}</div>'
                f'<div class="step-d">{desc}</div>'
                "</div>"
            )
        return (
            f'<div class="slide" {accent_style(slide)}>'
            + topbar(idx, total)
            + head(slide)
            + f'<div class="stepwrap"><div class="steps">{"".join(parts)}</div></div>'
            "</div>"
        )

    if kind == "stats":
        tiles = []
        for color, icon, num, label, sub in slide["stats"]:
            ac, tint = PALETTE[color]
            tiles.append(
                f'<div class="stat" style="--ac:{ac};--tint:{tint}">'
                f'<span class="stat-ic">{svg(icon)}</span>'
                f'<div class="stat-num">{num}</div>'
                f'<div class="stat-label">{label}</div>'
                f'<div class="stat-sub">{sub}</div>'
                "</div>"
            )
        return (
            f'<div class="slide" {accent_style(slide)}>'
            + topbar(idx, total)
            + head(slide)
            + '<div class="statwrap">'
            + f'<div class="stats">{"".join(tiles)}</div>'
            + f'<div class="stat-note">{slide["note"]}</div>'
            "</div></div>"
        )

    if kind == "compare":
        before = "".join(
            f'<div class="cmp-row"><span class="cmp-ic before">{svg("alert", 2.1)}</span>'
            f"<span>{x}</span></div>"
            for x in slide["before"]
        )
        after = "".join(
            f'<div class="cmp-row"><span class="cmp-ic after">{svg("check", 2.4)}</span>'
            f"<span>{x}</span></div>"
            for x in slide["after"]
        )
        return (
            f'<div class="slide" {accent_style(slide)}>'
            + topbar(idx, total)
            + head(slide)
            + '<div class="cmpwrap"><div class="compare">'
            '<div class="cmp cmp-before">'
            '<div class="cmp-head"><span class="cmp-tag before">これまで</span></div>'
            f"{before}</div>"
            f'<span class="cmp-arrow">{svg("arrow")}</span>'
            '<div class="cmp cmp-after">'
            '<div class="cmp-head"><span class="cmp-tag after">Inquira 導入後</span></div>'
            f"{after}</div>"
            "</div></div></div>"
        )

    raise ValueError(f"unknown kind: {kind}")


# ---------------------------------------------------------------------------
# 共通スタイル
# ---------------------------------------------------------------------------
BASE_CSS = r"""
* { box-sizing: border-box; margin: 0; padding: 0; }
.slide {
  position: relative; overflow: hidden; background: #ffffff; color: #25304a;
  font-family: "IPAPGothic", "IPAGothic", "Hiragino Maru Gothic ProN",
               "Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", sans-serif;
}
svg { display: block; }

/* ===== トップバー ===== */
.topbar {
  position: absolute; top: 0; left: 0; right: 0; height: 13mm;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 16mm;
}
.brand { display: flex; align-items: center; gap: 2.4mm;
  font-size: 4.6mm; font-weight: bold; color: #25304a; letter-spacing: .03em; }
.brand-mark {
  width: 7mm; height: 7mm; border-radius: 2.2mm; background: var(--ac);
  color: #fff; display: flex; align-items: center; justify-content: center;
}
.brand-mark svg { width: 4mm; height: 4mm; }
.pageno { font-size: 3.6mm; color: var(--ac); font-weight: bold;
  font-variant-numeric: tabular-nums; }
.pageno .of { color: #c2cad8; font-weight: normal; }

/* ===== 見出し ===== */
.head {
  position: absolute; top: 18mm; left: 16mm; right: 16mm;
  display: flex; flex-direction: column; align-items: flex-start;
}
.kicker {
  display: flex; align-items: center; gap: 1.8mm; white-space: nowrap;
  background: var(--tint); color: var(--ac);
  font-size: 3.5mm; font-weight: bold; padding: 1.7mm 4.6mm 1.7mm 3.4mm;
  border-radius: 999px; margin-bottom: 4.5mm; letter-spacing: .03em;
}
.kicker svg { width: 4.2mm; height: 4.2mm; }
h2 { font-size: 9mm; line-height: 1.34; color: #1b2540; letter-spacing: .01em; }
.lead { font-size: 4.3mm; color: #5b6781; margin-top: 3.6mm; line-height: 1.6; }

/* ===== 本文（アイコン箇条書き） ===== */
.body { position: absolute; left: 16mm; right: 16mm; top: 58mm; bottom: 13mm; }
.body.one-col { display: flex; flex-direction: column; justify-content: center; }
.body.two-col { display: flex; gap: 11mm; align-items: center; }
.two-col .col-tx { flex: 1.04; }
.two-col .visual {
  flex: 1.22; display: flex; align-items: center; justify-content: center;
}
.iblist { display: flex; flex-direction: column; gap: 5mm; }
.ib {
  display: flex; align-items: center; gap: 4.6mm;
  background: #fbfcfe; border: 1px solid #e9edf4; border-radius: 4.6mm;
  padding: 6mm 7mm;
}
.ib-ic {
  flex: none; width: 12mm; height: 12mm; border-radius: 3.6mm;
  background: var(--tint); color: var(--ac);
  display: flex; align-items: center; justify-content: center;
}
.ib-ic svg { width: 6.6mm; height: 6.6mm; }
.ib-h { font-size: 4.9mm; font-weight: bold; color: #1b2540; }
.ib-d { font-size: 3.9mm; color: #616d85; margin-top: 1.3mm; line-height: 1.55; }

.visual img {
  max-width: 100%; max-height: 132mm; width: auto; height: auto;
  border-radius: 4.5mm; border: 1px solid #e7ebf2;
  box-shadow: 0 7mm 18mm rgba(20,33,66,.16);
}

/* ===== 表紙 ===== */
.cover { background: #f3f7ff; }
.cover .blob { position: absolute; border-radius: 50%; }
.cover .b1 { width: 150mm; height: 150mm; right: -42mm; top: -52mm;
  background: radial-gradient(circle, #d8e6ff, rgba(216,230,255,0) 70%); }
.cover .b2 { width: 95mm; height: 95mm; right: 38mm; bottom: -40mm;
  background: radial-gradient(circle, #d4f3f2, rgba(212,243,242,0) 70%); }
.cover .b3 { width: 70mm; height: 70mm; left: -26mm; bottom: 12mm;
  background: radial-gradient(circle, #fde7cf, rgba(253,231,207,0) 72%); }
.cover-inner { position: absolute; left: 24mm; top: 56mm; right: 24mm; }
.cover-logo {
  display: flex; align-items: center; gap: 3mm;
  font-size: 6.4mm; font-weight: bold; color: #1b2540; margin-bottom: 9mm;
  letter-spacing: .04em;
}
.cover-mark {
  width: 11mm; height: 11mm; border-radius: 3.4mm; background: var(--ac);
  color: #fff; display: flex; align-items: center; justify-content: center;
}
.cover-mark svg { width: 6.2mm; height: 6.2mm; }
.cover h1 { font-size: 15.5mm; line-height: 1.36; color: #1b2540;
  letter-spacing: .01em; }
.cover-sub { font-size: 5mm; color: #5b6781; margin-top: 8mm; }
.cover-tags { display: flex; gap: 3mm; margin-top: 10mm; }
.cover-tags span {
  background: #fff; border: 1px solid #d8e1f0; color: #46527a;
  font-size: 3.6mm; font-weight: bold;
  padding: 2.2mm 5mm; border-radius: 999px;
}
.cover-foot {
  position: absolute; left: 24mm; bottom: 16mm;
  font-size: 3.5mm; color: #97a2b8; letter-spacing: .04em;
}

/* ===== アイコンカード ===== */
.iccardwrap {
  position: absolute; left: 16mm; right: 16mm; top: 53mm; bottom: 15mm;
  display: flex; align-items: center;
}
.iccards { display: flex; gap: 6mm; width: 100%; }
.ic-card {
  flex: 1; background: #fbfcfe; border: 1px solid #e9edf4;
  border-radius: 5.5mm; padding: 21mm 8mm;
  display: flex; flex-direction: column; justify-content: center;
  border-top: 3.4mm solid var(--ac);
}
.ic-card-ic {
  width: 19mm; height: 19mm; border-radius: 5.4mm;
  background: var(--tint); color: var(--ac);
  display: flex; align-items: center; justify-content: center;
}
.ic-card-ic svg { width: 10.6mm; height: 10.6mm; }
.ic-card-t { font-size: 5.4mm; font-weight: bold; color: #1b2540;
  margin: 7mm 0 4.5mm; line-height: 1.4; white-space: nowrap; }
.ic-card-d { font-size: 4mm; color: #616d85; line-height: 1.74; }

/* ===== フロー図 ===== */
.flowwrap {
  position: absolute; left: 16mm; right: 16mm; top: 56mm; bottom: 14mm;
  display: flex; flex-direction: column; justify-content: center; gap: 9mm;
}
.flow { display: flex; align-items: stretch; }
.flow-step {
  flex: 1; position: relative; background: #fbfcfe;
  border: 1px solid #e9edf4; border-radius: 5mm; padding: 11mm 5mm 9mm;
  text-align: center;
  display: flex; flex-direction: column; justify-content: center;
  align-items: center;
}
.flow-no {
  position: absolute; top: -4.6mm; left: 50%; margin-left: -4.6mm;
  width: 9.2mm; height: 9.2mm; border-radius: 50%;
  background: var(--ac); color: #fff;
  font-size: 4.3mm; font-weight: bold;
  display: flex; align-items: center; justify-content: center;
}
.flow-ic {
  width: 15mm; height: 15mm; border-radius: 50%; margin: 0 auto;
  background: var(--tint); color: var(--ac);
  display: flex; align-items: center; justify-content: center;
}
.flow-ic svg { width: 8.4mm; height: 8.4mm; }
.flow-t { font-size: 4.7mm; font-weight: bold; color: #1b2540; margin-top: 4.5mm; }
.flow-d { font-size: 3.5mm; color: #616d85; margin-top: 2.4mm; line-height: 1.5; }
.flow-arrow {
  flex: none; width: 12mm; display: flex; align-items: center;
  justify-content: center; color: var(--ac);
}
.flow-arrow svg { width: 7mm; height: 7mm; }
.flow-callout {
  display: flex; align-items: center; gap: 4mm;
  background: var(--tint); border-radius: 4.5mm; padding: 6mm 8mm;
}
.fc-ic { flex: none; width: 10mm; height: 10mm; border-radius: 50%;
  background: var(--ac); color: #fff;
  display: flex; align-items: center; justify-content: center; }
.fc-ic svg { width: 5.6mm; height: 5.6mm; }
.flow-callout span:last-child {
  font-size: 4mm; color: #2f3a57; line-height: 1.62; font-weight: bold;
}

/* ===== 3ステップ図 ===== */
.stepwrap {
  position: absolute; left: 16mm; right: 16mm; top: 56mm; bottom: 16mm;
  display: flex; flex-direction: column; justify-content: center;
}
.steps { display: flex; align-items: center; }
.step-card {
  flex: 1; background: #fbfcfe; border: 1px solid #e9edf4;
  border-radius: 5.5mm; padding: 13mm 7mm; text-align: center;
  display: flex; flex-direction: column; justify-content: center;
  align-items: center;
}
.step-no {
  display: inline-block; background: var(--tint); color: var(--ac);
  font-size: 3.4mm; font-weight: bold; letter-spacing: .08em;
  padding: 1.5mm 4.4mm; border-radius: 999px;
}
.step-ic {
  width: 19mm; height: 19mm; border-radius: 50%; margin: 6mm auto 0;
  background: var(--ac); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.step-ic svg { width: 10.5mm; height: 10.5mm; }
.step-t { font-size: 5.6mm; font-weight: bold; color: #1b2540; margin-top: 5.5mm; }
.step-d { font-size: 3.8mm; color: #616d85; margin-top: 3mm; line-height: 1.6; }
.step-link { flex: none; width: 13mm; display: flex; justify-content: center;
  color: var(--ac); }
.step-link svg { width: 7.6mm; height: 7.6mm; }

/* ===== 数値タイル ===== */
.statwrap {
  position: absolute; left: 16mm; right: 16mm; top: 55mm; bottom: 13mm;
  display: flex; flex-direction: column; justify-content: center; gap: 7mm;
}
.stats { display: flex; gap: 6mm; }
.stat {
  flex: 1; background: #fbfcfe; border: 1px solid #e9edf4;
  border-radius: 5.5mm; padding: 12mm 5mm; text-align: center;
  display: flex; flex-direction: column; justify-content: center;
  align-items: center;
}
.stat-ic {
  width: 13mm; height: 13mm; border-radius: 50%; margin: 0 auto 4mm;
  background: var(--tint); color: var(--ac);
  display: flex; align-items: center; justify-content: center;
}
.stat-ic svg { width: 7mm; height: 7mm; }
.stat-num { font-size: 15mm; font-weight: bold; color: var(--ac);
  line-height: 1; letter-spacing: -.01em; white-space: nowrap; }
.stat-label { font-size: 4mm; font-weight: bold; color: #1b2540;
  margin-top: 4.5mm; line-height: 1.45; }
.stat-sub { font-size: 3.2mm; color: #8590a6; margin-top: 2.6mm; line-height: 1.45; }
.stat-note { font-size: 3.3mm; color: #97a2b8; text-align: center; }

/* ===== ビフォーアフター ===== */
.cmpwrap {
  position: absolute; left: 16mm; right: 16mm; top: 56mm; bottom: 16mm;
  display: flex; flex-direction: column; justify-content: center;
}
.compare { display: flex; align-items: stretch; gap: 4mm; }
.cmp { flex: 1; border-radius: 5.5mm; padding: 8mm 8mm 7mm; }
.cmp-before { background: #fdeef0; border: 1px solid #f6cdd4; }
.cmp-after { background: #e6f7ef; border: 1px solid #b9e7d2; }
.cmp-head { margin-bottom: 5mm; }
.cmp-tag {
  display: inline-block; font-size: 4mm; font-weight: bold;
  padding: 1.8mm 5mm; border-radius: 999px;
}
.cmp-tag.before { background: #e1556f; color: #fff; }
.cmp-tag.after { background: #0e9f6e; color: #fff; }
.cmp-row {
  display: flex; align-items: center; gap: 3.4mm;
  padding: 3.7mm 0; border-bottom: 1px dashed rgba(27,37,64,.1);
  font-size: 4.05mm; color: #38425f;
}
.cmp-row:last-child { border-bottom: 0; }
.cmp-ic {
  flex: none; width: 7.6mm; height: 7.6mm; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
}
.cmp-ic svg { width: 4.6mm; height: 4.6mm; }
.cmp-ic.before { background: #f6cdd4; color: #d23b58; }
.cmp-ic.after { background: #b9e7d2; color: #0e9f6e; }
.cmp-arrow { flex: none; width: 12mm; display: flex; align-items: center;
  justify-content: center; color: #2f6bed; }
.cmp-arrow svg { width: 8mm; height: 8mm; }

/* ===== 結び ===== */
.closing { background: #f3f7ff; }
.closing .blob { position: absolute; border-radius: 50%; }
.closing .b1 { width: 140mm; height: 140mm; right: -46mm; top: -48mm;
  background: radial-gradient(circle, #d8e6ff, rgba(216,230,255,0) 70%); }
.closing .b2 { width: 88mm; height: 88mm; left: -30mm; bottom: -34mm;
  background: radial-gradient(circle, #d4f3f2, rgba(212,243,242,0) 70%); }
.closing-inner {
  position: absolute; left: 24mm; right: 24mm; top: 13mm; bottom: 0;
  display: flex; flex-direction: column; justify-content: center;
}
.closing h2 { font-size: 11.5mm; line-height: 1.36; color: #1b2540; }
.cl-pts { margin-top: 9mm; display: flex; flex-direction: column; gap: 3.8mm; }
.cl-pt { display: flex; align-items: center; gap: 3.4mm;
  font-size: 4.4mm; color: #38425f; }
.cl-ic {
  flex: none; width: 8.4mm; height: 8.4mm; border-radius: 50%;
  background: var(--ac); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.cl-ic svg { width: 5mm; height: 5mm; }
.cta {
  margin-top: 11mm; align-self: flex-start; white-space: nowrap;
  display: flex; align-items: center; gap: 3mm;
  background: var(--ac); color: #fff; font-size: 4.7mm; font-weight: bold;
  padding: 4.4mm 8.5mm; border-radius: 999px;
  box-shadow: 0 5mm 13mm rgba(47,107,237,.32);
}
.cta svg { width: 5.4mm; height: 5.4mm; }
.cl-note { margin-top: 6mm; font-size: 3.7mm; color: #8590a6; }
"""

# ---------------------------------------------------------------------------
# PDF 出力
# ---------------------------------------------------------------------------
def build_pdf() -> None:
    total = len(SLIDES)
    body = "".join(render_slide(s, i + 1, total) for i, s in enumerate(SLIDES))
    doc = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>
@page {{ size: A4 landscape; margin: 0; }}
html, body {{ margin: 0; padding: 0; }}
.slide {{ width: 297mm; height: 210mm; page-break-after: always; }}
.slide:last-child {{ page-break-after: auto; }}
{BASE_CSS}
</style></head><body>{body}</body></html>"""
    HTML(string=doc, base_url=str(REPO)).write_pdf(str(PDF_OUT))
    print(f"  PDF      -> {PDF_OUT.relative_to(REPO)}  ({PDF_OUT.stat().st_size // 1024} KB)")


# ---------------------------------------------------------------------------
# 動画風 HTML ウォークスルー出力
# ---------------------------------------------------------------------------
def build_walkthrough() -> None:
    total = len(SLIDES)
    frames = "".join(
        f'<div class="frame" data-dwell="{int(s.get("dwell", 9))}">'
        + render_slide(s, i + 1, total)
        + "</div>"
        for i, s in enumerate(SLIDES)
    )
    doc = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Inquira ご紹介ウォークスルー</title>
<style>
{BASE_CSS}
html,body {{ height:100%; background:#0a1322; }}
body {{ display:flex; align-items:center; justify-content:center;
  font-family:"Hiragino Kaku Gothic ProN","Yu Gothic","Meiryo",sans-serif; }}
.player {{ width:min(96vw, 1120px); }}
.stage {{
  position:relative; width:100%; aspect-ratio:297/210;
  border-radius:16px; overflow:hidden; background:#fff;
  box-shadow:0 26px 64px rgba(0,0,0,.55);
}}
.frame {{ position:absolute; inset:0; opacity:0;
  transition:opacity .55s ease; pointer-events:none; }}
.frame.active {{ opacity:1; pointer-events:auto; }}
.frame .slide {{ position:absolute; top:0; left:0;
  width:297mm; height:210mm; transform-origin:top left; }}
.progress {{ margin-top:14px; height:5px; border-radius:3px;
  background:rgba(255,255,255,.14); overflow:hidden; }}
.progress-bar {{ height:100%; width:0;
  background:linear-gradient(90deg,#2f6bed,#7aa6f6); }}
.controls {{ margin-top:14px; display:flex; align-items:center; gap:12px;
  color:#cdd9e8; font-size:14px; }}
.controls button {{ background:#16263f; color:#dce6f3; border:1px solid #2c3f5c;
  border-radius:10px; padding:9px 16px; font-size:14px; cursor:pointer;
  font-family:inherit; }}
.controls button:hover {{ background:#1f3454; }}
.controls .play {{ background:#2f6bed; border-color:#2f6bed; color:#fff;
  font-weight:bold; }}
.counter {{ margin-left:auto; font-variant-numeric:tabular-nums; }}
.dots {{ display:flex; gap:6px; }}
.dot {{ width:9px; height:9px; border-radius:50%; background:#2c3f5c;
  border:0; padding:0; cursor:pointer; }}
.dot.active {{ background:#2f6bed; }}
.hint {{ margin-top:9px; color:#5b76a0; font-size:12px; text-align:center; }}
</style></head><body>
<div class="player">
  <div class="stage" id="stage">{frames}</div>
  <div class="progress"><div class="progress-bar" id="bar"></div></div>
  <div class="controls">
    <button class="play" id="play">&#10073;&#10073; 一時停止</button>
    <button id="prev">&#8249; 戻る</button>
    <button id="next">次へ &#8250;</button>
    <div class="dots" id="dots"></div>
    <span class="counter" id="counter"></span>
  </div>
  <div class="hint">自動再生中 &mdash; &larr; &rarr; キーで移動、スペースキーで再生／停止</div>
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
function fit(){{
  const w=document.getElementById('stage').clientWidth;
  const scale=w/(297*96/25.4);
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
  bar.style.transition='none'; bar.style.width='0';
  void bar.offsetWidth;
  bar.style.transition='width '+sec+'s linear'; bar.style.width='100%';
}}
function schedule(){{
  clearTimeout(timer);
  if(!playing) return;
  const sec=parseInt(frames[cur].dataset.dwell||'9',10);
  startBar(sec);
  timer=setTimeout(()=>{{ cur<frames.length-1 ? go(cur+1) : pause(); }}, sec*1000);
}}
function go(i){{ cur=(i+frames.length)%frames.length; render(); if(playing) schedule(); }}
function play(){{
  playing=true; playBtn.innerHTML='&#10073;&#10073; 一時停止';
  if(cur===frames.length-1) cur=0;
  render(); schedule();
}}
function pause(){{
  playing=false; playBtn.innerHTML='&#9654; 再生';
  clearTimeout(timer); bar.style.transition='none';
}}
playBtn.onclick=()=> playing?pause():play();
document.getElementById('next').onclick=()=>go(cur+1);
document.getElementById('prev').onclick=()=>go(cur-1);
document.addEventListener('keydown',e=>{{
  if(e.key==='ArrowRight') go(cur+1);
  else if(e.key==='ArrowLeft') go(cur-1);
  else if(e.key===' '){{ e.preventDefault(); playing?pause():play(); }}
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
