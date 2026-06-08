"""A社 一般社員 (利用者) 向けクイックスタートの PDF を生成。

使い方:
    pip install weasyprint
    python scripts/build_a_company_user_quickstart.py

出力:
    docs/a_company_user_quickstart.html
    docs/a_company_user_quickstart.pdf

「URL を開く → Google ログイン → 質問する」の 3 ステップ案内。
A社管理者がナレッジ投入を終えた後、社員に配布する利用ガイド。
"""
from __future__ import annotations

from pathlib import Path

from weasyprint import HTML

OUT_DIR = Path(__file__).resolve().parents[1] / "docs"
OUT_PDF = OUT_DIR / "a_company_user_quickstart.pdf"
OUT_HTML = OUT_DIR / "a_company_user_quickstart.html"


HTML_DOC = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>Inquira 利用ガイド — A社社員向け</title>
<style>
@page {
  size: A4;
  margin: 14mm 14mm 14mm 14mm;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: "IPAPGothic", "IPAGothic", "Hiragino Sans", sans-serif;
  color: #1f2937; font-size: 10pt; line-height: 1.55;
}

/* === ヘッダー === */
.header {
  background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
  color: #fff;
  padding: 14px 18px;
  border-radius: 10px;
  margin-bottom: 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header .left .eyebrow {
  font-size: 9pt;
  letter-spacing: 0.18em;
  opacity: 0.85;
}
.header .left h1 {
  font-size: 18pt;
  font-weight: 700;
  letter-spacing: -0.01em;
  margin-top: 2px;
}
.header .right {
  text-align: right;
  font-size: 8.5pt;
  opacity: 0.92;
  line-height: 1.5;
}

/* === リード === */
.lead {
  background: #eff6ff;
  border-left: 4px solid #3b82f6;
  padding: 9px 12px;
  font-size: 9.5pt;
  border-radius: 0 6px 6px 0;
  margin-bottom: 14px;
}
.lead b { color: #1e40af; }

/* === ステップ === */
.steps {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
  margin-bottom: 14px;
}
.step {
  background: #fff;
  border: 1.5px solid #93c5fd;
  border-radius: 10px;
  padding: 12px 12px 14px;
  position: relative;
}
.step .num {
  position: absolute;
  top: -10px;
  left: 12px;
  background: #3b82f6;
  color: #fff;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  text-align: center;
  font-size: 11pt;
  font-weight: 700;
  line-height: 24px;
}
.step h3 {
  font-size: 11pt;
  color: #1e40af;
  margin: 6px 0 6px;
  font-weight: 700;
}
.step .body {
  font-size: 9pt;
  color: #374151;
}
.step .body code {
  background: #eff6ff;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 8.5pt;
  word-break: break-all;
}
.step .visual {
  background: #eff6ff;
  border: 1.5px dashed #93c5fd;
  border-radius: 8px;
  padding: 14px 6px;
  text-align: center;
  margin: 8px 0;
  font-size: 8.5pt;
  color: #1e40af;
}
.step .visual .icon {
  font-size: 22pt;
  display: block;
  margin-bottom: 4px;
}

/* === 質問のコツ === */
.tips {
  background: #f9fafb;
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 12px;
}
.tips h2 {
  font-size: 10pt;
  color: #1e40af;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 6px;
}
.tips ul {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 16px;
  list-style: none;
  font-size: 9pt;
}
.tips ul li::before {
  content: "💡 ";
  color: #f59e0b;
}

/* === 回答画面の読み方 === */
.readme-answer {
  background: #f0fdf4;
  border-left: 4px solid #10b981;
  border-radius: 0 6px 6px 0;
  padding: 10px 14px;
  margin-bottom: 12px;
}
.readme-answer h2 {
  font-size: 10pt;
  color: #065f46;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 6px;
}
.readme-answer .labels {
  display: flex;
  gap: 14px;
  font-size: 9pt;
}
.readme-answer .labels div { flex: 1; }
.readme-answer .badge {
  display: inline-block;
  background: #10b981;
  color: #fff;
  font-size: 8pt;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 999px;
  margin-right: 4px;
}
.readme-answer .badge.ref { background: #f59e0b; }
.readme-answer .badge.no  { background: #6b7280; }

/* === FAQ・困ったら === */
.troubleshoot {
  background: #fffbeb;
  border-left: 4px solid #f59e0b;
  border-radius: 0 6px 6px 0;
  padding: 9px 12px;
  font-size: 9pt;
  margin-bottom: 12px;
}
.troubleshoot h2 {
  font-size: 9pt;
  color: #92400e;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 4px;
}
.troubleshoot .row {
  display: flex;
  gap: 10px;
  margin-top: 4px;
}
.troubleshoot .row span { flex: 1; }

/* === フッター === */
.footer {
  border-top: 1px solid #e5e7eb;
  padding-top: 8px;
  display: flex;
  justify-content: space-between;
  font-size: 8.5pt;
  color: #6b7280;
}
.footer .left b { color: #1e40af; }
</style>
</head>
<body>

<div class="header">
  <div class="left">
    <div class="eyebrow">QUICK START GUIDE</div>
    <h1>Inquira 利用ガイド</h1>
  </div>
  <div class="right">
    宛先: <b>A株式会社 社員のみなさま</b><br/>
    所要時間: <b>初回 30 秒</b><br/>
    URL: <b>https://faq.a-corp.jp/</b>
  </div>
</div>

<div class="lead">
  Inquira は、社内マニュアル・規程・FAQ を AI が代理で答えてくれる <b>社内向け検索＆Q&A サービス</b> です。<br/>
  <b>「資料を探すのに時間がかかる」「情シスや人事に同じ質問するのが気が引ける」</b> といった困りごとを、AI に投げて即解決できます。
</div>

<div class="steps">

  <div class="step">
    <div class="num">1</div>
    <h3>URL を開く</h3>
    <div class="visual">
      <span class="icon">🌐</span>
      ブラウザで開く
    </div>
    <div class="body">
      社内ポータルや配信メールの案内から <code>https://faq.a-corp.jp/</code> を開きます。<br/>
      ブックマークしておくと便利です。
    </div>
  </div>

  <div class="step">
    <div class="num">2</div>
    <h3>Google ログイン</h3>
    <div class="visual">
      <span class="icon">🔐</span>
      会社の Google アカウント
    </div>
    <div class="body">
      [Google でログイン] ボタンを押し、<b>会社支給の Gmail アカウント</b> でログインしてください。<br/>
      初回のみ「権限の許可」を求められます。
    </div>
  </div>

  <div class="step">
    <div class="num">3</div>
    <h3>質問を入力</h3>
    <div class="visual">
      <span class="icon">💬</span>
      日本語で気軽に
    </div>
    <div class="body">
      画面下の入力欄に、知りたいことを日本語で書いて Enter。<br/>
      <b>数秒</b>で AI が出典付きで回答します。
    </div>
  </div>

</div>

<div class="tips">
  <h2>💡 上手な聞き方のコツ</h2>
  <ul>
    <li>「経費精算の期限は？」のような <b>短い質問</b> で OK</li>
    <li>専門用語より <b>普段の言葉</b> で書いた方がヒットします</li>
    <li>聞き直し OK。前の回答を踏まえて続けて質問できます</li>
    <li>うまく答えてくれない時は <b>言い換え</b> てみてください</li>
  </ul>
</div>

<div class="readme-answer">
  <h2>📖 回答画面の見方</h2>
  <div class="labels">
    <div><span class="badge">回答</span> 出典付きの確信度の高い回答。そのまま信頼して OK。</div>
    <div><span class="badge ref">参考情報</span> 関連性は中程度。出典を確認してください。</div>
    <div><span class="badge no">該当なし</span> ナレッジに情報がない。「FAQ追加リクエスト」を送ると管理者が対応します。</div>
  </div>
</div>

<div class="troubleshoot">
  <h2>❓ 困ったとき</h2>
  <div class="row">
    <span><b>ログインできない</b>: 会社支給の Gmail でログインしてください。私用 Gmail は弾かれます。</span>
    <span><b>欲しい答えが出ない</b>: 「FAQ追加リクエスト」ボタンから管理者に追加依頼を送れます。</span>
  </div>
</div>

<div class="footer">
  <div class="left"><b>Inquira</b> — A株式会社 社内向け Q&A サービス</div>
  <div class="right">不明点は社内情シスへ</div>
</div>

</body></html>
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(HTML_DOC, encoding="utf-8")
    HTML(string=HTML_DOC).write_pdf(str(OUT_PDF))
    print(f"OK: {OUT_HTML}")
    print(f"OK: {OUT_PDF}")


if __name__ == "__main__":
    main()
