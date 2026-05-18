# Windows で動かす：詰まらない設定手順

> 想定読者: Windows 10 / 11 を使用、PowerShell の基本操作は OK だが Python の細かい仕様は分からない方
> 所要時間: 5〜15分（初回）
> 前提: 管理者権限のあるアカウント

---

## ステップ0：自分の Windows で何が必要か確認

**PowerShell**（スタートメニューで `powershell` を検索 → 起動）を開いて、以下を順番に実行：

```powershell
# 1) Python 3.11 以上があるか
python --version
```

| 結果 | 次にやること |
|---|---|
| `Python 3.11.x` 以上 | → ステップ1へ進む（**方法A**を推奨） |
| `Python 3.10` 以下 / 「python は認識されません」 | → 下記「Python のインストール」 |

```powershell
# 2) git があるか
git --version
```

無ければ：[Git for Windows](https://git-scm.com/download/win) をダウンロード→インストール。
**インストール時に「Git Bash Here」にチェック**を入れること（後で使います）。

---

### Python のインストール（3.11 以下 or 未インストールの場合）

#### 方法1：Microsoft Store（一番簡単）

1. スタートメニュー → **「Microsoft Store」** を起動
2. 検索ボックスに **`Python 3.11`** と入力
3. 「Python 3.11」をインストール（無料）
4. インストール後、PowerShell を**閉じてから再度開いて** `python --version` で確認

#### 方法2：公式インストーラ

1. https://www.python.org/downloads/windows/ にアクセス
2. **Python 3.11.x** の Windows installer (64-bit) をダウンロード
3. インストール時に **「Add python.exe to PATH」にチェック必須**
4. インストール完了後、PowerShell 再起動 → `python --version` で確認

#### 方法3：winget（Windows 10/11 標準のパッケージマネージャ）

```powershell
winget install Python.Python.3.11
```

---

## ステップ1：リポジトリを取得

PowerShell で実行：

```powershell
cd $HOME\Documents          # 好きな場所でOK
git clone https://github.com/zashii5793/faq_platform.git
cd faq_platform
git checkout claude/add-roadmap-docs-RmQNp
```

> ⚠ `main` ブランチではなく `claude/add-roadmap-docs-RmQNp` です。

---

## ステップ2：起動方法を選ぶ

下のどれか **1つ** を選んで実行してください。

### 方法A：Git Bash で動かす（一番おすすめ／推奨）

`scripts/demo_company.sh` は bash スクリプトなので、**Git Bash**（Git for Windowsに含まれる）で動かすのが一番簡単です。

#### 手順

1. エクスプローラで `faq_platform` フォルダを開く
2. フォルダ内の何もない場所で **右クリック → 「Git Bash Here」**
3. Git Bash 上で：
   ```bash
   ./scripts/demo_company.sh
   ```

これで Mac と全く同じように動きます。スクリプトが自動で：
1. Python 仮想環境（`.venv`）を作る
2. 必要なパッケージをインストール
3. **120件の自動テストを実行**（失敗したら起動しない）
4. サーバを起動

成功すると以下が表示されます：
```
🧪 統合テストを実行中…
......................................................   [100%]
120 passed in 70s

✅ テスト全 PASS

🚀 Inquira を起動します
   ┌──────────────────────────────────────────────────┐
   │ チャット画面: http://127.0.0.1:8000/                  │
   │ ナレッジ追加: http://127.0.0.1:8000/admin/upload      │
   └──────────────────────────────────────────────────┘
```

ブラウザ（Edge / Chrome 推奨）で **http://127.0.0.1:8000/** を開けば触れます。

#### 停止
Git Bash 上で `Ctrl + C`

---

### 方法B：Docker Desktop を使う（環境を完全に隔離）

Python のバージョン違いで詰まるのが嫌なら **これが一番確実**。

#### 前提：Docker Desktop のインストール

1. https://www.docker.com/products/docker-desktop/ からダウンロード
2. インストーラ実行（途中で「WSL 2」のインストールを求められたら指示通りに）
3. インストール後、Windows 再起動
4. Docker Desktop を起動（タスクトレイにクジラのアイコンが出る）
5. **「Engine running」** になるのを待つ（初回は数分）

#### 起動：1コマンド

PowerShell で：
```powershell
docker compose up --build
```

初回ビルドで 3〜5分（Python イメージのダウンロード + 依存インストール）。
2回目以降はキャッシュされて10秒ほど。

ブラウザで **http://127.0.0.1:8000/** を開く。

#### 停止
別の PowerShell で：
```powershell
docker compose down
```
または起動中の PowerShell で `Ctrl + C` → `docker compose down`

---

### 方法C：PowerShell で手動起動（Pythonに慣れている人向け）

bash スクリプトを使わず、PowerShell から直接 uvicorn を起動：

```powershell
# 仮想環境を作成
python -m venv .venv

# 仮想環境を有効化
.\.venv\Scripts\Activate.ps1

# ※ 「このシステムではスクリプトの実行が無効になっています」エラーが出たら：
# Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
# を実行してから上記を再試行

# 依存パッケージのインストール
pip install -e ".[dev]"

# テスト実行（任意）
pytest -q

# サーバ起動（DEMO モード）
$env:DEMO_MODE = "1"
$env:FAQ_MASTER_DIR = ".\data\demo_company_faq"
$env:SESSION_SECRET = "demo-secret-please-change"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

ブラウザで **http://127.0.0.1:8000/** を開く。

#### 停止
PowerShell 上で `Ctrl + C`

#### 仮想環境の終了
```powershell
deactivate
```

---

### 方法D：WSL2 で Linux 環境を使う（開発者向け）

Windows で Linux 環境を直接動かせる WSL2 を使うと、Mac/Linuxの手順がそのまま使えます。

#### WSL2 インストール（管理者 PowerShell で）

```powershell
wsl --install
```

Windows 再起動後、Ubuntu のセットアップ画面が出ます。ユーザー名・パスワードを設定。

#### WSL2 内で実行

```bash
# Ubuntu 内
sudo apt update && sudo apt install -y python3.11 python3.11-venv git
git clone https://github.com/zashii5793/faq_platform.git
cd faq_platform
git checkout claude/add-roadmap-docs-RmQNp
./scripts/demo_company.sh
```

ブラウザは Windows 側の Edge / Chrome から **http://127.0.0.1:8000/** で開けます（WSL2 → Windows 自動転送）。

---

## ステップ3：携帯から触りたい場合（社内 LAN）

### Windows ファイアウォール許可

PowerShell（**管理者権限で起動**）で：
```powershell
New-NetFirewallRule -DisplayName "Inquira" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

### LAN 公開で起動

Git Bash で：
```bash
HOST=0.0.0.0 ./scripts/demo_company.sh
```

または PowerShell（方法C）で：
```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

PC の LAN IP を確認：
```powershell
ipconfig | findstr IPv4
```
表示された `192.168.x.x` を、iPhone の Safari で `http://192.168.x.x:8000/` として開く。

> ⚠ DEMO_MODE は認証なしで LAN 全体に公開されます。
> 社内 WiFi など信頼できるネットワーク内でのみ使用してください。

---

## ステップ4：どんな機能が動くか確認

ブラウザで http://127.0.0.1:8000/ を開いた状態で：

### A. 質問してみる
1. 下部の入力欄に「VPN繋がらない時の対処法」と入力 → 送信
2. 確信度バッジ（緑=高 / 黄=中 / 赤=該当なし）を確認
3. 「📎 参照ドキュメント」を展開して出典を確認
4. 👍 / 👎 ボタンを押すとサイドバーのフィードバック数が更新

### B. 関係ない質問でハルシネーション抑制を確認
1. 「宇宙ロケットの打ち上げ手順」と入力 → 送信
2. **「該当情報が見つかりませんでした」** が返ってくる
3. これは AI を呼ばずに止めている（ハルシネーション抑制）

### C. ファイルを取り込む
1. 左サイドバー → **「📁 ファイルを追加」** をクリック
2. `/admin/upload` 画面に遷移
3. 適当な PDF / Excel / Markdown ファイルをドラッグ&ドロップ
4. 解析結果カード（🟢 取り込み可 / 🟡 確認必要 / 🔴 取り込み非推奨）が出る
5. 下部の **「選択を確定して取り込む(N件)」** ボタンで一括取り込み
6. 戻ってからその文書について質問できる

### D. 機密データの拒否を確認
1. マイナンバー（13桁）を含む CSV を作って投入
2. 🔴 「取り込み非推奨」と判定され、取り込みボタンが無効化される

---

## トラブルシューティング

### 「`python` は認識されません」
- Python が PATH に入っていない可能性。再インストール時に「Add python.exe to PATH」にチェック
- または PowerShell を**閉じてから再度開く**（PATH 反映に再起動が必要）
- それでもダメなら絶対パス指定：`C:\Users\<ユーザー名>\AppData\Local\Programs\Python\Python311\python.exe`

### 「`./scripts/demo_company.sh` は認識されません」（PowerShell で実行した場合）
- これは bash スクリプトなので **Git Bash** で実行が必要
- または方法C（PowerShell で手動起動）か方法B（Docker）を選ぶ

### 「このシステムではスクリプトの実行が無効になっています」（PowerShell）
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
を実行してから再試行。

### `port 8000 is already in use` エラー
別のプロセスが 8000 を使っている可能性。確認：
```powershell
netstat -ano | findstr :8000
```
表示された PID（プロセスID）を強制終了：
```powershell
taskkill /PID <PID番号> /F
```
または別ポートで起動：
```bash
PORT=8080 ./scripts/demo_company.sh
```

### Docker でビルドが終わらない / 失敗する
- Docker Desktop の **Settings → Resources → Advanced** で割り当てメモリを 4GB 以上に
- WSL 2 backend が有効か確認（Settings → General → 「Use the WSL 2 based engine」にチェック）
- それでもダメなら方法A（Git Bash）を試す

### 「Microsoft Defender SmartScreen」警告でインストーラがブロックされる
- 「詳細情報」 → 「実行」 で許可（公式インストーラなら安全）

### ブラウザで `http://127.0.0.1:8000/` が開けない
- サーバ起動の PowerShell / Git Bash に **「Uvicorn running on ...」** が出ているか確認
- 出ていなければエラーログを確認
- 出ているのに開けない場合は、ブラウザのキャッシュをクリアか別ブラウザ（Edge → Chrome）で試す

### `git checkout` で「ローカル変更が上書きされる」エラー
```powershell
git stash
git checkout claude/add-roadmap-docs-RmQNp
git stash pop  # 必要なら
```

---

## 本番キー・OAuth情報の取得

本番運用には以下の2つが必要です。順番に取得してください。

### A. Anthropic API キー（必須・所要5分）

#### A-1. Anthropic Console にサインアップ

1. [https://console.anthropic.com/](https://console.anthropic.com/) にアクセス（Edge/Chromeなど）
2. 右上 **「Sign up」**
3. メールアドレス入力 → 認証メールから登録
4. 組織情報を入力（個人なら個人名でOK）
5. クレジットカード登録 OR プリペイドクレジット入金

> 💡 初回登録時に **無料クレジット $5** が付与されます（テスト用に十分）。

> ⚠ Claude Pro / Team サブスクリプションとは **別契約**です。APIプラン専用のアカウントが必要。

#### A-2. API キー生成

1. ログイン後 → 左メニュー **「API Keys」**
2. **「Create Key」** ボタン
3. キー名を入力（例: `inquira-prod`）
4. `sk-ant-api03-xxxxxxxxxx...` が表示される
5. **このキーは1回しか表示されません**。必ずコピーして保管
6. メモ帳やパスワードマネージャ（Bitwarden / 1Password 等）に保存

> 🔒 キーは **パスワードと同じ機密情報** です。リポジトリへのコミット禁止。`.env` ファイル経由でのみ使用（`.gitignore` 登録済み）。

#### A-3. 動作確認

PowerShell で：
```powershell
cd $HOME\Documents\faq_platform
.\.venv\Scripts\Activate.ps1
$env:ANTHROPIC_API_KEY = "sk-ant-api03-xxxxxxxxxx"
python scripts\test_anthropic.py
```

または Git Bash で：
```bash
cd ~/Documents/faq_platform
source .venv/Scripts/activate
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxx python scripts/test_anthropic.py
```

成功すると：
```
🔑 APIキー: sk-ant-api03...XXXX (長さ: 108文字)
📡 接続テスト中... (約2秒)
✅ 接続成功（1.85秒）
   モデル:     claude-sonnet-4-6
   応答:       OK
💰 このリクエストの料金: $0.000114 (約 0.0177円)
✅ APIキーは正常に動作しています。
```

> 詳細・料金体系・トラブルシュート → [`docs/api_key_setup.md`](./api_key_setup.md)

---

### B. Google OAuth クライアント ID / Secret（社内認証用・所要30〜60分）

社員ログインに Google Workspace アカウントを使うための設定です。
DEMO_MODE では不要ですが、**本番運用では必須**（認証なしで LAN 公開は危険）。

> 前提: 顧客が Google Workspace を契約していること

#### B-1. Google Cloud プロジェクトを作成

1. [https://console.cloud.google.com/](https://console.cloud.google.com/) にアクセス
2. 顧客 Google Workspace 管理者アカウントでログイン
3. 上部「プロジェクトの選択」→ **「新しいプロジェクト」**
4. プロジェクト名: `Inquira-<顧客名>` （例: `Inquira-AcmeCorp`）
5. 組織: 顧客の組織（Workspace 配下）を選択 ← **重要**
6. **作成** をクリック

#### B-2. OAuth 同意画面を構成

左メニュー → **API とサービス** → **OAuth 同意画面**

1. **ユーザータイプ: 内部 (Internal)** を選択 ← 必須
   - これにより Workspace 内のメンバーのみログイン可能になる
   - External だと Google の審査が必要になる

2. アプリ情報を入力：

   | 項目 | 入力例 |
   |---|---|
   | アプリ名 | `Inquira 社内ヘルプデスク` |
   | ユーザーサポートメール | `support@your-company.co.jp` |
   | 承認済みドメイン | `your-company.co.jp`（顧客ドメイン） |
   | デベロッパーの連絡先 | `support@your-company.co.jp` |

3. **保存して次へ**

4. スコープ画面で「**スコープを追加または削除**」→ 以下にチェック：
   - `.../auth/userinfo.email`
   - `.../auth/userinfo.profile`
   - `openid`

   > これだけで OK。**ファイル等のアクセス権は不要**。

5. **保存して次へ** → テストユーザーは内部アプリなのでスキップ可

#### B-3. OAuth クライアント ID を作成

左メニュー → **API とサービス** → **認証情報**

1. 上部 **+ 認証情報を作成** → **OAuth クライアント ID**
2. アプリケーションの種類: **ウェブアプリケーション**
3. 名前: `Inquira Web Client`

4. **承認済みの JavaScript 生成元** に以下を追加：
   ```
   https://inquira.your-company.co.jp
   http://localhost:8000
   http://127.0.0.1:8000
   ```

5. **承認済みのリダイレクト URI** に以下を追加：
   ```
   https://inquira.your-company.co.jp/auth/callback
   http://localhost:8000/auth/callback
   http://127.0.0.1:8000/auth/callback
   ```

   > ⚠ パス `/auth/callback` の末尾に **スラッシュを付けない**。Inquira のコードは正確にこのパスを期待します。

6. **作成** をクリック

7. ポップアップに表示される **2つの値を必ずコピー**：
   - **クライアント ID**: `123456789-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.apps.googleusercontent.com`
   - **クライアント シークレット**: `GOCSPX-xxxxxxxxxxxxxxxxxxxxxxxx`

> 詳細・チェックリスト・トラブルシュート → [`docs/google_oauth_setup.md`](./google_oauth_setup.md)

---

## 本番運用へ進む場合の追加設定

デモモードではなく本番設定にする場合は `.env` ファイルを作成：

```powershell
# .env.example をコピー
Copy-Item .env.example .env

# メモ帳で開いて編集
notepad .env
```

以下を編集：

```env
# Anthropic API（学習に使われない商用契約）
# → 上記「本番キー・OAuth情報の取得」§A で取得した値
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxx

# Google OAuth（社内アカウントログイン）
# → 上記「本番キー・OAuth情報の取得」§B で取得した値
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxxx
GOOGLE_REDIRECT_URI=https://your-domain.com/auth/callback
ALLOWED_DOMAIN=your-company.co.jp

# セッション暗号化キー（適当な長い文字列）
# PowerShell で生成: -join ((48..57)+(97..122) | Get-Random -Count 64 | ForEach-Object {[char]$_})
SESSION_SECRET=<生成した文字列>

# DEMO_MODE は本番では必ず false（または環境変数自体を削除）
DEMO_MODE=false
```

その後、PowerShell で：
```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Windows サービスとして常駐起動したい場合

社内サーバで「PC起動時に自動で立ち上がってほしい」場合は **NSSM (Non-Sucking Service Manager)** が便利：

1. https://nssm.cc/download から NSSM をダウンロード → 解凍
2. 管理者 PowerShell で：
   ```powershell
   cd C:\path\to\nssm-2.24\win64
   .\nssm.exe install Inquira
   ```
3. GUI が開くので以下を設定：
   - **Path**: `C:\Users\<ユーザー名>\Documents\faq_platform\.venv\Scripts\uvicorn.exe`
   - **Startup directory**: `C:\Users\<ユーザー名>\Documents\faq_platform`
   - **Arguments**: `app.main:app --host 0.0.0.0 --port 8000`
4. 「Install service」をクリック
5. サービス開始：
   ```powershell
   Start-Service Inquira
   ```

これで Windows 起動時に自動的に Inquira が立ち上がります。

---

## さいごに：何かおかしい時のチェックリスト

```powershell
# 1) 現在のブランチ確認
git branch --show-current
# → claude/add-roadmap-docs-RmQNp になっているか

# 2) 最新を取得
git pull origin claude/add-roadmap-docs-RmQNp

# 3) クリーンスタート（Git Bash で実行）
rm -rf .venv data/audit data/index.json data/feedback_scores.json
./scripts/demo_company.sh
```

3 で直らない場合は **エラーメッセージ全文** をコピーして相談してください。

---

## 関連ドキュメント

- [`docs/setup_for_admin.md`](./setup_for_admin.md) — 管理者向け全体ガイド（本番運用）
- [`docs/setup_guide_mac.md`](./setup_guide_mac.md) — Mac版
- [`docs/https_deployment.md`](./https_deployment.md) — HTTPS本番デプロイ
- [`docs/google_oauth_setup.md`](./google_oauth_setup.md) — Google OAuth設定
- [`docs/api_key_setup.md`](./api_key_setup.md) — Anthropic API キー取得

---

最終更新: 2026年5月18日
