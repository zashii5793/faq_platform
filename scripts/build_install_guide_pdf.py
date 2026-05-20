"""自社サーバー（オンプレミス）導入ガイドの PDF を生成する。

使い方:
    pip install weasyprint
    python scripts/build_install_guide_pdf.py

出力: docs/self_hosted_install_guide.pdf

HTML/CSS を weasyprint で PDF 化する。日本語は IPA ゴシック
（システムにインストール済み）を使用。内容を直したいときは
このファイルの HTML 文字列を編集して再実行する。
"""
from __future__ import annotations

from pathlib import Path

from weasyprint import HTML

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "self_hosted_install_guide.pdf"

HTML_DOC = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>自社サーバー導入ガイド</title>
<style>
@page {
  size: A4;
  margin: 20mm 18mm 22mm 18mm;
  @bottom-right {
    content: "Inquira 自社サーバー導入ガイド  —  " counter(page) " / " counter(pages);
    font-size: 8.5pt; color: #9ca3af;
  }
}
@page :first { @bottom-right { content: ""; } }
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: "IPAPGothic", "IPAGothic", sans-serif;
  color: #1f2937; font-size: 10.5pt; line-height: 1.75;
}
code, pre { font-family: "IPAGothic", monospace; }

/* ===== 表紙 ===== */
.cover { page-break-after: always; padding-top: 60mm; text-align: center; }
.cover .product { font-size: 16pt; color: #1a73e8; font-weight: bold;
  letter-spacing: .15em; }
.cover h1 { font-size: 30pt; color: #111827; margin: 14mm 0 6mm;
  line-height: 1.3; letter-spacing: .02em; }
.cover .sub { font-size: 12pt; color: #6b7280; }
.cover .rule { width: 40mm; height: 3px; background: #1a73e8;
  margin: 12mm auto; }
.cover .meta { margin-top: 30mm; font-size: 10pt; color: #6b7280;
  line-height: 2; }
.cover .meta strong { color: #1f2937; }

/* ===== 見出し ===== */
h2 { font-size: 15pt; color: #111827; margin: 9mm 0 4mm;
  padding-bottom: 2mm; border-bottom: 2px solid #1a73e8;
  page-break-after: avoid; }
h3 { font-size: 11.5pt; color: #1a73e8; margin: 6mm 0 2.5mm;
  page-break-after: avoid; }
p { margin: 2mm 0; }
ul, ol { margin: 2mm 0 2mm 6mm; }
li { margin: 1mm 0; }

/* ===== STEP バッジ ===== */
.step-h { display: flex; align-items: center; gap: 4mm;
  margin: 9mm 0 4mm; page-break-after: avoid; }
.step-h .num { background: #1a73e8; color: #fff; font-weight: bold;
  font-size: 11pt; min-width: 11mm; height: 11mm; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; }
.step-h .ttl { font-size: 14pt; color: #111827; font-weight: bold; }

/* ===== コードブロック ===== */
pre { background: #1e293b; color: #e2e8f0; font-size: 8.8pt;
  padding: 3.5mm 4mm; border-radius: 2mm; margin: 3mm 0;
  white-space: pre-wrap; word-break: break-all; line-height: 1.6; }
p code, li code, td code { background: #eef2ff; color: #3730a3;
  font-size: 9pt; padding: 0.3mm 1.5mm; border-radius: 1mm; }

/* ===== 注意・ヒントボックス ===== */
.box { padding: 3mm 4mm; border-radius: 2mm; margin: 3mm 0;
  font-size: 9.6pt; }
.box.note { background: #fffbeb; border-left: 3px solid #f59e0b; }
.box.tip  { background: #ecfdf5; border-left: 3px solid #10b981; }
.box.warn { background: #fef2f2; border-left: 3px solid #ef4444; }
.box .label { font-weight: bold; display: block; margin-bottom: 1mm; }

/* ===== 表 ===== */
table { width: 100%; border-collapse: collapse; margin: 3mm 0;
  font-size: 9.4pt; }
th, td { border: 1px solid #d1d5db; padding: 2mm 2.5mm; text-align: left;
  vertical-align: top; }
th { background: #f1f5f9; font-weight: bold; color: #1f2937; }

/* ===== チェックリスト ===== */
.check { list-style: none; margin-left: 0; }
.check li { padding-left: 7mm; position: relative; margin: 1.5mm 0; }
.check li::before { content: "\\2610"; position: absolute; left: 0;
  font-size: 12pt; color: #1a73e8; }

/* ===== フロー図 ===== */
.flow { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 2mm;
  padding: 4mm; margin: 3mm 0; font-size: 9pt; line-height: 2.1; }
.flow .s { background: #1a73e8; color: #fff; padding: 1mm 2.5mm;
  border-radius: 1.5mm; font-weight: bold; white-space: nowrap; }
.flow .arrow { color: #94a3b8; font-weight: bold; }

.lead { font-size: 10.5pt; color: #374151; }
.section { page-break-inside: auto; }
</style></head><body>

<!-- ============ 表紙 ============ -->
<div class="cover">
  <div class="product">INQUIRA</div>
  <h1>自社サーバー<br>導入ガイド</h1>
  <div class="rule"></div>
  <div class="sub">オンプレミス環境への<br>インストール手順書</div>
  <div class="meta">
    対象読者 &nbsp;<strong>情報システム・インフラ担当者</strong><br>
    所要時間 &nbsp;<strong>半日 〜 1日</strong><br>
    発行 &nbsp;<strong>[組織名]</strong> &nbsp;/&nbsp; 2026年5月
  </div>
</div>

<!-- ============ 1. はじめに ============ -->
<div class="section">
<h2>1. この資料について</h2>
<p class="lead">本書は、社内ヘルプデスク AI「Inquira」を<strong>自社で管理する
サーバー（オンプレミス）</strong>へ導入するための手順書です。
Render などの外部クラウドを使わず、データを自社の管理下に置いたまま運用したい
組織を対象としています。</p>

<h3>自社サーバー導入のメリット</h3>
<table>
<tr><th>観点</th><th>内容</th></tr>
<tr><td>データ主権</td><td>社内文書・質問ログがすべて自社サーバー内に留まり、外部に送信されない（AI 回答生成時のみ Anthropic API を利用）</td></tr>
<tr><td>セキュリティ</td><td>社内ネットワーク内に閉じた運用や、IP 制限が自由に設定できる</td></tr>
<tr><td>コスト</td><td>既存サーバーを活用すれば月額のホスティング費が不要</td></tr>
</table>

<div class="box note"><span class="label">前提知識</span>
Linux の基本操作（SSH 接続・ファイル編集・コマンド実行）ができる方を想定しています。
不安な場合は §8 の導入支援窓口までご相談ください。</div>
</div>

<!-- ============ 2. 必要なもの ============ -->
<div class="section">
<h2>2. 始める前に — 必要なものチェックリスト</h2>
<p>導入を始める前に、以下がすべて揃っているか確認してください。</p>
<ul class="check">
<li><strong>Linux サーバー 1台</strong> … CPU 2コア以上 / メモリ 4GB 以上 / 空き容量 20GB 以上（Ubuntu 22.04 LTS 等を推奨）</li>
<li><strong>サーバーへの管理者権限</strong> … <code>sudo</code> が使えるアカウント</li>
<li><strong>独自ドメイン</strong> … 例 <code>inquira.your-company.co.jp</code>（HTTPS 化に必須）</li>
<li><strong>Google Workspace の管理権限</strong> … 社員ログイン認証に使用</li>
<li><strong>Anthropic API キー</strong> … AI 回答の生成に使用（取得方法は STEP 3 を参照）</li>
</ul>

<div class="box tip"><span class="label">サーバーの置き場所</span>
社内 LAN 内のサーバーでも、データセンターやクラウド上の仮想マシン（AWS EC2 等）でも
構いません。社外の社員もアクセスする場合は、インターネットから到達できる場所に
設置し、独自ドメインと HTTPS を設定してください。</div>
</div>

<!-- ============ 3. 全体像 ============ -->
<div class="section">
<h2>3. 導入の全体像</h2>
<p>導入は次の 8 ステップで進みます。上から順に実施してください。</p>
<div class="flow">
<span class="s">STEP1 サーバー準備</span> <span class="arrow">&rarr;</span>
<span class="s">STEP2 アプリ配置</span> <span class="arrow">&rarr;</span>
<span class="s">STEP3 設定ファイル作成</span> <span class="arrow">&rarr;</span>
<span class="s">STEP4 Google ログイン設定</span><br>
<span class="arrow">&rarr;</span>
<span class="s">STEP5 起動と HTTPS 化</span> <span class="arrow">&rarr;</span>
<span class="s">STEP6 自動起動の設定</span> <span class="arrow">&rarr;</span>
<span class="s">STEP7 動作確認</span> <span class="arrow">&rarr;</span>
<span class="s">STEP8 社内文書の取り込み</span>
</div>
<p>STEP1〜7 で <strong>半日程度</strong>、STEP8 の文書取り込みは分量により
<strong>半日〜1日</strong>が目安です。</p>
</div>

<!-- ============ STEP 1 ============ -->
<div class="section">
<div class="step-h"><span class="num">1</span><span class="ttl">サーバーを準備する</span></div>
<p>サーバーに SSH で接続し、Inquira の動作に必要な <strong>Docker</strong> を導入します。
Docker を使うことで、Python のバージョン差などを気にせず安定して動かせます。</p>

<h3>1-1. Docker のインストール（Ubuntu の例）</h3>
<pre>sudo apt update
sudo apt install -y docker.io docker-compose-plugin git
sudo systemctl enable --now docker</pre>

<h3>1-2. ファイアウォールの設定</h3>
<p>外部に公開するのは <strong>80番・443番ポートのみ</strong>とし、アプリ本体が使う
8000番ポートは外部に開けません（後述の nginx 経由でのみアクセスさせます）。</p>
<pre>sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable</pre>
</div>

<!-- ============ STEP 2 ============ -->
<div class="section">
<div class="step-h"><span class="num">2</span><span class="ttl">Inquira を配置する</span></div>
<p>アプリ本体をサーバーにダウンロードします。</p>
<pre>cd /opt
sudo git clone https://github.com/zashii5793/faq_platform.git inquira
cd inquira</pre>
<p>以降の作業は、この <code>/opt/inquira</code> ディレクトリ内で行います。</p>
</div>

<!-- ============ STEP 3 ============ -->
<div class="section">
<div class="step-h"><span class="num">3</span><span class="ttl">設定ファイル（.env）を作成する</span></div>

<h3>3-1. Anthropic API キーを取得する</h3>
<ol>
<li><code>https://console.anthropic.com/</code> にアクセスしてログイン</li>
<li>「Plans &amp; Billing」で支払い方法（クレジットカード）を登録</li>
<li>「Create Key」で API キーを発行し、<strong>全文をコピー</strong></li>
</ol>
<div class="box warn"><span class="label">注意</span>
API キーの全文は発行画面を閉じると二度と表示されません。必ずその場で
安全な場所に控えてください。</div>

<h3>3-2. 設定ファイルを編集する</h3>
<p>ひな形をコピーして、テキストエディタで開きます。</p>
<pre>cp .env.example .env
nano .env</pre>
<p>本番運用では、最低限つぎの項目を設定します。</p>
<pre>ANTHROPIC_API_KEY=sk-ant-api03-（取得したキー）
CLAUDE_MODEL=claude-haiku-4-5-20251001
ORG_NAME=株式会社○○
ASSISTANT_ROLE=社内ヘルプデスク

DEMO_MODE=false
SESSION_SECRET=（下のコマンドで生成した値）
GOOGLE_CLIENT_ID=（STEP4 で取得）
GOOGLE_CLIENT_SECRET=（STEP4 で取得）
GOOGLE_REDIRECT_URI=https://inquira.your-company.co.jp/auth/callback
ALLOWED_DOMAIN=your-company.co.jp</pre>
<p><code>SESSION_SECRET</code> はセッション暗号化用のランダム文字列です。
次のコマンドで生成し、出力値を貼り付けてください。</p>
<pre>openssl rand -hex 32</pre>
<div class="box tip"><span class="label">ヒント</span>
<code>ALLOWED_DOMAIN</code> に自社ドメインを指定すると、そのドメインの
メールアドレスを持つ社員だけがログインできます。
<code>CLAUDE_MODEL</code> は <code>claude-haiku-4-5-20251001</code>（低コスト）が
おすすめです。より高精度を求める場合は <code>claude-sonnet-4-6</code> に変更できます。</div>
</div>

<!-- ============ STEP 4 ============ -->
<div class="section">
<div class="step-h"><span class="num">4</span><span class="ttl">Google ログインを設定する</span></div>
<p>社員は Google アカウントでログインします。Google Cloud Console で
認証情報を発行してください。</p>
<ol>
<li>Google Cloud Console でプロジェクトを新規作成</li>
<li>「OAuth 同意画面」を <strong>内部（Internal）</strong>で設定</li>
<li>「認証情報」→「OAuth クライアント ID」を作成（種類: ウェブアプリケーション）</li>
<li>承認済みリダイレクト URI に次を登録:<br>
<code>https://inquira.your-company.co.jp/auth/callback</code></li>
<li>発行された <strong>クライアント ID</strong> と <strong>クライアントシークレット</strong>を
STEP3 の <code>.env</code> に貼り付け</li>
</ol>
<div class="box note"><span class="label">詳しい手順</span>
画面キャプチャ付きの詳細手順は、別資料
<code>docs/google_oauth_setup.md</code> に用意しています。所要 30分〜1時間です。</div>
</div>

<!-- ============ STEP 5 ============ -->
<div class="section">
<div class="step-h"><span class="num">5</span><span class="ttl">起動して HTTPS でアクセスできるようにする</span></div>

<h3>5-1. アプリを起動する</h3>
<pre>sudo docker compose up -d --build</pre>
<p>数分のビルドの後、サーバー内部の 8000番ポートでアプリが起動します。
まずはサーバー上で動作を確認します。</p>
<pre>curl http://127.0.0.1:8000/healthz
# → {"ok":true} と表示されれば起動成功</pre>

<h3>5-2. nginx でドメイン公開＋HTTPS 化</h3>
<p>外部からは nginx（リバースプロキシ）経由でアクセスさせ、通信を HTTPS で
暗号化します。<code>/etc/nginx/sites-available/inquira.conf</code> を作成します。</p>
<pre>server {
    listen 80;
    server_name inquira.your-company.co.jp;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl http2;
    server_name inquira.your-company.co.jp;

    ssl_certificate     /etc/letsencrypt/live/inquira.your-company.co.jp/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/inquira.your-company.co.jp/privkey.pem;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    client_max_body_size 60M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}</pre>
<p>設定を有効化し、無料の SSL 証明書を取得します。</p>
<pre>sudo ln -s /etc/nginx/sites-available/inquira.conf /etc/nginx/sites-enabled/
sudo nginx -t &amp;&amp; sudo systemctl reload nginx
sudo certbot --nginx -d inquira.your-company.co.jp</pre>
<div class="box note"><span class="label">事前準備</span>
独自ドメインの DNS で、<code>inquira.your-company.co.jp</code> がこのサーバーの
IP アドレスを指すよう A レコードを設定しておいてください（certbot の証明書取得に必要です）。</div>
</div>

<!-- ============ STEP 6 ============ -->
<div class="section">
<div class="step-h"><span class="num">6</span><span class="ttl">サーバー再起動後も自動で立ち上がるようにする</span></div>
<p>STEP5 の <code>docker compose</code> で起動したコンテナは、サーバーを再起動しても
自動的に立ち上がる設定になっています。Docker サービス自体が OS 起動時に
有効化されていることを確認してください。</p>
<pre>sudo systemctl enable docker</pre>
<p>正しく動いているかは、次のコマンドで確認できます。</p>
<pre>sudo docker compose ps
# → State が「running」「Up」であれば正常</pre>
</div>

<!-- ============ STEP 7 ============ -->
<div class="section">
<div class="step-h"><span class="num">7</span><span class="ttl">動作を確認する</span></div>
<p>ブラウザと以下のチェックリストで、導入が完了しているか確認します。</p>
<ul class="check">
<li>ブラウザで <code>https://inquira.your-company.co.jp/</code> を開くと
<strong>ログイン画面</strong>が表示される</li>
<li>「Google でログイン」から社員アカウントでログインできる</li>
<li>ログイン後、<strong>チャット画面</strong>が表示される</li>
<li>社外ドメインのアカウントではログインを拒否される（<code>ALLOWED_DOMAIN</code> が有効）</li>
<li>アドレスバーに鍵マークが表示される（HTTPS 化の成功）</li>
</ul>
<div class="box warn"><span class="label">うまくいかないときは</span>
本書 §7 のトラブルシューティングを参照してください。
ログインループが起きる場合は <code>SESSION_SECRET</code> 未設定が、
「ローカルモード」表示の場合は API キー未設定が主な原因です。</div>
</div>

<!-- ============ STEP 8 ============ -->
<div class="section">
<div class="step-h"><span class="num">8</span><span class="ttl">社内文書を取り込む</span></div>
<p>最後に、AI が回答の根拠とする社内マニュアル・FAQ を登録します。</p>
<ol>
<li>管理者アカウントでログインし、ブラウザで <code>/admin/upload</code> を開く</li>
<li>マニュアル類をドラッグ＆ドロップ（複数同時可）</li>
<li>個人情報の自動検出結果（クレンジング結果）を確認</li>
<li>「選択を確定して取り込む」で完了</li>
</ol>
<table>
<tr><th>形式</th><th>推奨度</th><th>備考</th></tr>
<tr><td>Markdown / テキスト</td><td>★★★</td><td>検索精度が最も高い</td></tr>
<tr><td>PDF</td><td>★★</td><td>レイアウトが複雑だと精度低下</td></tr>
<tr><td>Excel / PowerPoint</td><td>★★</td><td>Q&amp;A 表・スライド単位で取込</td></tr>
<tr><td>Word</td><td>★</td><td>整形が崩れる場合あり</td></tr>
</table>
<div class="box tip"><span class="label">精度を上げるコツ</span>
「1ファイル＝1テーマ」で分け、見出しを <code>#</code> <code>##</code> で明確にし、
固有名詞や数値を省略せず明記すると、回答精度が大きく向上します。</div>
</div>

<!-- ============ 6. 運用 ============ -->
<div class="section">
<h2>6. 日常の運用</h2>
<h3>バックアップ</h3>
<p>取り込んだ文書・監査ログ・設定ファイルをまとめて保存します。
毎晩 2 時に自動実行する場合は <code>crontab -e</code> で次を追記します。</p>
<pre>0 2 * * * cd /opt/inquira &amp;&amp; ./scripts/backup.sh /path/to/backup-storage</pre>
<h3>ログの確認</h3>
<pre># アプリのログ
sudo docker compose logs -f
# 監査ログ（誰がいつ何を質問したか）
tail -f /opt/inquira/data/audit/audit-$(date +%F).jsonl</pre>
</div>

<!-- ============ 7. トラブルシューティング ============ -->
<div class="section">
<h2>7. トラブルシューティング</h2>
<table>
<tr><th>症状</th><th>主な原因と対処</th></tr>
<tr><td>「ローカルモード：APIキー未設定」と表示される</td>
<td><code>.env</code> の <code>ANTHROPIC_API_KEY</code> を確認し、
<code>docker compose up -d</code> でコンテナを再起動する</td></tr>
<tr><td>ログイン後すぐログイン画面に戻る</td>
<td><code>SESSION_SECRET</code> が空または短い。
<code>openssl rand -hex 32</code> で生成して設定する</td></tr>
<tr><td>質問しても「該当情報が見つかりませんでした」ばかり</td>
<td>関連文書が未登録。STEP8 の手順で社内文書を取り込む</td></tr>
<tr><td>ブラウザで開けない / 証明書エラー</td>
<td>DNS の A レコード設定と certbot の証明書取得が完了しているか確認する</td></tr>
</table>
</div>

<!-- ============ 8. サポート ============ -->
<div class="section">
<h2>8. 導入支援窓口</h2>
<p>導入でお困りの際は、下記までお問い合わせください。
リモート接続によるセットアップ代行や、文書取り込みの代行も承ります（別途見積）。</p>
<table>
<tr><th>窓口</th><th>連絡先</th></tr>
<tr><td>メール</td><td>[contact@example.com]</td></tr>
<tr><td>営業時間</td><td>平日 10:00 - 18:00</td></tr>
</table>
<div class="box note"><span class="label">関連資料</span>
本書と合わせて、<code>docs/setup_for_admin.md</code>（管理者運用ガイド）、
<code>docs/google_oauth_setup.md</code>（Google ログイン詳細手順）、
<code>docs/api_cost_analysis.md</code>（API コスト試算）もご活用ください。</div>
</div>

</body></html>"""


def main() -> None:
    HTML(string=HTML_DOC).write_pdf(str(OUTPUT))
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"生成完了: {OUTPUT}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
