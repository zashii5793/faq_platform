# Inquira 導入手順 — A株式会社 全工程ガイド

> 想定読者: A社 IT 部門ご担当者様 / 提供側オペレーター
> 想定環境: Windows Server 2019 / 2022（Linux も末尾に併記）
> 所要時間: 提供側 15 分 + A社作業 30 分〜1 時間

---

## ✅ 本番稼働状態

| 項目 | 値 |
|---|---|
| 公開 URL | `https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/` |
| 構成 | Windows Server + IIS リバプロ + Inquira (uvicorn) |
| 認証 | Google OAuth (管理者ホワイトリスト方式) |
| データ保存先 | `<UNC_SHARE_PATH>` |
| 詳細レポート | [`docs/a_company_deployment_report.md`](../../docs/a_company_deployment_report.md) (テンプレート) |

> 顧客固有値 (`<INQUIRA_HOST>`, `<CUSTOMER_DOMAIN>`, `<UNC_SHARE_PATH>` 等) は **このリポジトリに絶対にコミットしない**。
> 実値は `.private/` 配下で管理してください。

導入時の試行錯誤と教訓は [`docs/deployment_lessons_learned.md`](../../docs/deployment_lessons_learned.md) を参照。

---

## 全体像 — 誰が何をやるか

```
[提供側]           [A社 IT 部門]              [A社 管理者]            [A社 社員]
   │
   ① OAuth 設定 ──────────────────────────────────────────────►
       (Console で                                              認証OK
        A社管理者の
        Gmail を登録)
   │
   ② API キー入り
      .env をお渡し ──► ③ Python インストール
                       ④ GitHub から DL
                       ⑤ install.ps1 実行
                                │
                       ⑥ 動作確認 (localhost) ──► ⑦ ブラウザで
                                                      アクセス
                                                  ⑧ Google ログイン
                                                  ⑨ ナレッジ投入
                                                        │
                                                  ⑩ 社員に URL ─────► ⑪ 利用開始
                                                      告知
```

---

## Part 1. 提供側（自分）の事前準備（15 分）

> ⚠ A社 IT 部門の作業を始める **前** に必ず完了させること。
> これを忘れると、A社の管理者が Google ログイン時に「アクセスがブロックされました」エラーになります。

### 1-1. Google Cloud Console で「テストユーザー」を登録（5 分）

OAuth 同意画面が **テストモード** の状態だと、登録済みの Gmail だけがログインできます。
A社の管理者 4 名の Gmail を、テストユーザーとして登録します。

1. https://console.cloud.google.com/apis/credentials/consent を開く
2. 該当のプロジェクトを選択
3. ページ下部の **「テスト ユーザー」** セクションまでスクロール
4. **「ADD USERS」** ボタンを押す
5. A社管理者の Gmail アドレスを 1 行ずつ入力（最大 100 名まで）
6. **「保存」**

> 💡 本番展開で「テストユーザー登録」を毎回やりたくない場合は、OAuth 同意画面を「**本番**」モードに切り替えてください（Google 審査あり）。

### 1-2. OAuth クライアントに Redirect URI を追加（5 分）

A社のアクセス URL に対応するコールバック先を OAuth クライアントに登録します。

1. https://console.cloud.google.com/apis/credentials を開く
2. 該当の OAuth 2.0 クライアント ID をクリック
3. **「承認済みのリダイレクト URI」** セクションで **「URI を追加」**
4. 以下を追加：
   - `http://localhost:8000/auth/callback`（A社サーバー上でローカルテスト用）
   - （将来公開する場合）`https://faq.a-corp.jp/auth/callback`
5. **「保存」**

### 1-3. A社用 `.env` を準備（5 分）

以下の 5 項目を実値で埋めた `.env` を作り、A社 IT 部門にお渡しします（メール本文 or ZIP 添付など）。

```env
ANTHROPIC_API_KEY=sk-ant-xxxxx                        # 自分のキー
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com     # 自分の OAuth クライアント
GOOGLE_CLIENT_SECRET=xxxxx                            # 同上
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback   # まずは localhost で
ALLOWED_EMAILS=<管理者1の Gmail>,<管理者2の Gmail>,...  # A社管理者 (Part 1-1 と同じ)
```

> ⚠ この `.env` は **メール本文には貼らず、暗号化 ZIP 添付** か別ルートで渡してください。
> API キーが含まれます。

---

## Part 2. A社 IT 部門の作業（インストール、30 分〜1 時間）

### 2-1. Python 3.11 をインストール（10 分）

PowerShell で確認：

```powershell
py --version
```

`Python 3.11.x` 以上が出れば次へ。出なければインストール：

#### A. python.org からインストーラを取得（管理者権限不要）

```powershell
$url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
Invoke-WebRequest -Uri $url -OutFile "$env:USERPROFILE\Downloads\python-3.11.9.exe" -UseBasicParsing
& "$env:USERPROFILE\Downloads\python-3.11.9.exe"
```

インストーラ画面：
1. ⚠ 下の **「Add python.exe to PATH」にチェック**
2. **「Customize installation」** を押す
3. オプション画面 →「Next」
4. Advanced Options 画面で：
   - **「Install Python for all users」のチェックを外す**（管理者権限不要にする）
   - 「Add Python to environment variables」にチェック
5. 「Install」

#### インストール後

PowerShell を一度閉じて開き直して、確認：

```powershell
py --version
# → Python 3.11.9
```

### 2-2. ネットワーク共有へのアクセス確認（5 分）

データ保存先の共有フォルダにアクセスできるか確認：

```powershell
# エクスプローラーで開いて読み書きできるか確認
explorer "<DATA_SHARE>"
# ↑ <DATA_SHARE> は提供側からお伝えする共有フォルダパス（\\で始まる UNC パス）

# PowerShell から存在確認
Test-Path "<DATA_SHARE>"

# 接続資格情報の永続化（毎回ログオン時に認証不要にする）
net use "<DATA_SHARE>" /persistent:yes
```

`Test-Path` が `True` を返し、エクスプローラーでファイル作成/削除できれば OK。

### 2-3. GitHub からソースをダウンロード（3 分）

```powershell
# 作業ディレクトリ作成
mkdir C:\Temp\inquira -Force | Out-Null
cd C:\Temp\inquira

# GitHub から ZIP ダウンロード
$url = "https://github.com/zashii5793/faq_platform/archive/refs/heads/claude/add-roadmap-docs-RmQNp.zip"
Invoke-WebRequest -Uri $url -OutFile faq_platform.zip -UseBasicParsing

# 解凍
Expand-Archive -Path .\faq_platform.zip -DestinationPath . -Force

# tenants/a_company に移動
cd .\faq_platform-claude-add-roadmap-docs-RmQNp\tenants\a_company
dir
```

`install.ps1` `.env.template` `README.md` が見えれば OK。

### 2-4. `.env` を配置（2 分）

提供側からお渡しした `.env`（Part 1-3 で作成）を、このフォルダに配置してください。

メモ帳で内容確認：

```powershell
notepad .env
```

5 項目（API キー、OAuth、Redirect URI、ALLOWED_EMAILS）が実値で埋まっていることを確認。

### 2-5. インストール実行（5 分）

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1 -DataDir "<DATA_SHARE>"
```

`✅ Inquira 起動完了` が出れば成功です。表示される URL を控えておきます：

```
このPCから (ローカル):  http://localhost:8000/
社内 LAN から:          http://<IPアドレス>:8000/
```

### 2-6. 動作確認（2 分）

```powershell
Invoke-WebRequest http://127.0.0.1:8000/healthz
```

`StatusCode: 200` で本文が `{"ok": true}` なら正常稼働。

ブラウザで `http://localhost:8000/` を開いて、Google ログイン画面が表示されれば OK。

---

## Part 2.5. HTTPS 化（IIS リバースプロキシ、20 分）

> Part 2 までで `http://localhost:8000/` で動作確認できたら、HTTPS 化して社員に開放します。
> 以下の `<CUSTOMER_DOMAIN>` / `<INQUIRA_HOST>` / `<INQUIRA_SERVER_IP>` 等は実値に置換して使ってください。

### 2.5-1. 社内 DNS に A レコード登録（AD 管理者へ依頼）

AD サーバーにて、以下を実行してもらいます。

```powershell
# Inquira を動かしているサーバーの IP を確認 (Inquira サーバー上で実行)
ipconfig | findstr IPv4
# → 出力された IP を控える (= <INQUIRA_SERVER_IP>)

# AD サーバー上で A レコード作成
Add-DnsServerResourceRecordA -ZoneName "<CUSTOMER_DOMAIN>" -Name "<INQUIRA_HOST>" -IPv4Address "<INQUIRA_SERVER_IP>"
```

⚠ **重要**: `IPv4Address` は **Inquira サーバーの IP** を指定 (AD サーバーの IP ではない)。間違えるとブラウザから到達できません。

確認:
```powershell
Resolve-DnsName <INQUIRA_HOST>.<CUSTOMER_DOMAIN>
# → IPAddress が Inquira サーバーの IP と一致すれば OK
```

### 2.5-2. IIS リバプロ自動セットアップ実行

Inquira サーバー上の **管理者 PowerShell** で:

```powershell
mkdir C:\Temp -Force | Out-Null
(New-Object System.Net.WebClient).DownloadFile(
  "https://raw.githubusercontent.com/zashii5793/faq_platform/claude/add-roadmap-docs-RmQNp/scripts/setup_iis_reverse_proxy.ps1",
  "C:\Temp\setup_iis_reverse_proxy.ps1"
)
cd C:\Temp
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup_iis_reverse_proxy.ps1 -Hostname "<INQUIRA_HOST>.<CUSTOMER_DOMAIN>"
```

スクリプトが以下を全部自動でやります:

1. IIS 役割インストール
2. URL Rewrite / ARR モジュール (winget 経由)
3. 自己署名 SSL 証明書発行 (有効期限 5 年)
4. IIS サイト「Inquira」作成 (80/443 バインド)
5. リバプロ設定 (`http://127.0.0.1:8000` への転送)
6. **ARR の Location 書き換え無効化** (OAuth 互換)
7. iisreset
8. 動作確認

詳細は [`scripts/setup_iis_reverse_proxy_README.md`](../../scripts/setup_iis_reverse_proxy_README.md)。

### 2.5-3. `.env` の REDIRECT_URI を HTTPS に変更

```powershell
notepad "$env:USERPROFILE\Inquira\.env"
```

```env
GOOGLE_REDIRECT_URI=https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/auth/callback
```

### 2.5-4. Google Cloud Console にリダイレクト URI 追加

OAuth 2.0 クライアント → 承認済みリダイレクト URI に以下を追加:

```
https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/auth/callback
```

→ 保存。5〜10 分待つ (Google 側の伝搬時間)。

### 2.5-5. Inquira 再起動

```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
& "$env:USERPROFILE\Inquira\start_inquira.bat"
```

### 2.5-6. 動作確認

```powershell
# バックエンドが応答するか
Invoke-WebRequest http://127.0.0.1:8000/healthz -UseBasicParsing

# HTTPS 経由で応答するか
curl.exe -ks https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/healthz
# → {"ok":true}

# OAuth リダイレクト先が正しいか (重要)
curl.exe -ksi https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/auth/login | Select-String "Location"
# → Location: https://accounts.google.com/o/oauth2/v2/auth?... が出れば正常
```

最後にブラウザで `https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/` を開き、Google ログインから管理画面に入れたら完了。

---

## Part 3. A社 管理者の作業（ナレッジ投入、20 分）

### 3-1. ブラウザで管理画面にアクセス

顧客サーバー上 (もしくは社内 LAN の PC) のブラウザで:

```
https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/admin/upload
```

(HTTPS 化前は `http://localhost:8000/admin/upload` でも可)

⚠ 自己署名証明書のため、初回アクセス時にブラウザの警告が出ます。「詳細設定」→「アクセスする」で進めてください。AD のグループポリシーで証明書を社員 PC に配布すれば、警告は出なくなります。

### 3-2. Google ログイン

[Google でログイン] ボタンを押し、**事前にテストユーザー登録された Gmail**（提供側が Part 1-1 で登録した4名のいずれか）でログインしてください。

> ⚠ 「アクセスがブロックされました」と出る場合：
> - そのアカウントが Part 1-1 のテストユーザー登録に含まれていない可能性
> - 提供側に追加登録を依頼してください

### 3-3. ナレッジ投入

「📁 ファイル取り込み」タブで、社内マニュアル・FAQ・規程をドラッグ&ドロップ → 「取り込み確定」。

推奨投入順：
1. 人事・労務（休暇 / 経費 / 勤怠）
2. IT / 情シス（VPN / PC / SaaS）
3. 業務マニュアル

### 3-4. 社員に URL を告知

ナレッジ投入が完了したら、社員に以下を共有：

- 利用 URL: `https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/`
- 利用ガイド PDF: `docs/a_company_user_quickstart.pdf`（提供側からお渡し済）

---

## Part 4. A社 社員の利用開始

社員は `https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/` を開いて、会社の Gmail でログイン → 質問。

⚠ **デフォルト設定では、Part 1-1 でテストユーザー登録された Gmail のみログイン可** です。
全社員に開放したい場合は、提供側に「ALLOWED_DOMAIN に A社ドメインを追加」を依頼してください。

---

## 困ったとき (よくあるトラブル)

### 「アクセスがブロックされました」（Google ログイン時）

最も多いトラブル。原因：
- そのアカウントが OAuth テストユーザーに登録されていない → Part 1-1 で追加
- Redirect URI が登録されていない → Part 1-2 で追加

### `Python 3.11+ が見つかりません`

Python 未インストール、またはインストール時に「Add to PATH」を忘れた → Part 2-1 再実行。

### 文字化けする（`縺瑚ｦ九▽縺九ｊ縺ｾ縺帙ｓ` 等）

install.ps1 が UTF-8 BOM 付きでない可能性。GitHub から再ダウンロードしてやり直し（Part 2-3）。

### `Test-Path` が False / `net use` で「ネットワーク名が見つかりません」

共有フォルダへのアクセス権がない、もしくは共有名/パスが間違っている。A社 IT 部門の社内インフラ担当に確認。

### `healthcheck が通らない`

`%USERPROFILE%\Inquira\start_inquira.bat` をエクスプローラーから直接ダブルクリック → コンソールに出るエラーを確認。
よくあるのは `.env` の API キー綴りミスや SESSION_SECRET 未生成。

### スクリプト実行が拒否される（PowerShell）

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
を毎回先に叩く。これは「このターミナル限定で許可」する設定です。

### HTTPS URL がブラウザでタイムアウトする

DNS A レコードが Inquira サーバーと別マシンの IP を指している可能性。

```powershell
# 解決される IP を確認
Resolve-DnsName <INQUIRA_HOST>.<CUSTOMER_DOMAIN>

# Inquira サーバーの実 IP と比較
ipconfig | findstr IPv4

# 違っていたら AD サーバーで修正
# (AD サーバー上で実行)
Remove-DnsServerResourceRecord -ZoneName "<CUSTOMER_DOMAIN>" -Name "<INQUIRA_HOST>" -RRType A -Force
Add-DnsServerResourceRecordA -ZoneName "<CUSTOMER_DOMAIN>" -Name "<INQUIRA_HOST>" -IPv4Address "<INQUIRA_SERVER_IP>"

# Inquira サーバーで再確認
ipconfig /flushdns
Resolve-DnsName <INQUIRA_HOST>.<CUSTOMER_DOMAIN>
```

### Google ログイン押下後に `{"detail":"Not Found"}` が出る

IIS ARR の Location ヘッダ書き換えが `accounts.google.com` を自ホストに書き換えてしまっています。

```powershell
# 現在値の確認
Get-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" `
    -Filter "system.webServer/proxy" -Name "reverseRewriteHostInResponseHeaders"

# False に変更
Set-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" `
    -Filter "system.webServer/proxy" -Name "reverseRewriteHostInResponseHeaders" -Value $false

iisreset
```

確認:
```powershell
curl.exe -ksi https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/auth/login | Select-String "Location"
# → Location: https://accounts.google.com/... が出れば正常
```

最新の `setup_iis_reverse_proxy.ps1` (v2 以降) は自動で `false` に設定済みです。

### `.env` が文字化けで起動できない

文字コード変換コマンドを 2 回かけてしまったケース。対話入力で再生成:

```powershell
(New-Object System.Net.WebClient).DownloadFile(
  "https://raw.githubusercontent.com/zashii5793/faq_platform/claude/add-roadmap-docs-RmQNp/scripts/recover_env.ps1",
  "C:\Temp\recover_env.ps1"
)
cd C:\Temp
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\recover_env.ps1
```

対話で 4 項目入力すれば、UTF-8 BOM 無しで正しい `.env` が生成されます。

---

## 運用コマンド（A社 IT 部門用）

```powershell
# 状態確認
Invoke-WebRequest http://127.0.0.1:8000/healthz

# 手動再起動
Get-Process python | Where-Object { $_.MainWindowTitle -like '*uvicorn*' } | Stop-Process
& "$env:USERPROFILE\Inquira\start_inquira.bat"

# ログ確認 (手動起動した時のコンソール出力で見る)
& "$env:USERPROFILE\Inquira\start_inquira.bat"
# (バックグラウンドではなくフォアグラウンドで起動し、エラーをその場で確認できる)
```

---

## バックアップ対象

- データ保存先（`-DataDir` で指定した UNC 共有）配下まるごと
- `%USERPROFILE%\Inquira\.env`（再構築用、暗号化保管）

データ保存先の中身：
- `faq_master/` — 取り込み済みナレッジ
- `audit/` — 質問履歴
- `raw/` — アップロード原本
- `feedback_scores.json` — フィードバックスコア
- `faq_candidates.json` — 自動 FAQ 候補
- `org_settings.json` — 組織情報
- `index.json` — 検索インデックス（自動再生成可）

---

## サポート窓口

導入時の不明点は提供側（弊社）まで。Slack / メール経由でご案内済みの連絡先へ。

---

## (参考) Linux サーバーの場合

`install.ps1` ではなく `install.sh` を使い、systemd で自動起動。リバースプロキシは nginx：

```bash
sudo ./install.sh
sudo systemctl status inquira
sudo journalctl -u inquira -f
```

nginx 設定例は別途お問い合わせください。
