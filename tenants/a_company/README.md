# Inquira 導入手順 — A株式会社 全工程ガイド

> 想定読者: A社 IT 部門ご担当者様 / 提供側オペレーター
> 想定環境: Windows Server 2019 / 2022（Linux も末尾に併記）
> 所要時間: 提供側 15 分 + A社作業 30 分〜1 時間

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

## Part 3. A社 管理者の作業（ナレッジ投入、20 分）

### 3-1. ブラウザで管理画面にアクセス

A社サーバー上のブラウザで以下の URL を開きます：

```
http://localhost:8000/admin/upload
```

社内 LAN の別 PC から開く場合は、A社 IT 部門にサーバーの IP を聞いて：

```
http://<サーバーのIPアドレス>:8000/admin/upload
```

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

- 利用 URL: `http://<サーバーのIPアドレス>:8000/`
- 利用ガイド PDF: `docs/a_company_user_quickstart.pdf`（提供側からお渡し済）

---

## Part 4. A社 社員の利用開始

社員は `http://<サーバーのIPアドレス>:8000/` を開いて、会社の Gmail でログイン → 質問。

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
