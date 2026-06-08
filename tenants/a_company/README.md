# Inquira — A株式会社 オンプレ導入パッケージ

> A社の社内サーバー（**Windows Server**）に Inquira を 1 コマンドで設置するための一式。
> Docker は使わず、Python venv + Windows タスクスケジューラ構成。
> Linux サーバー (Ubuntu/RHEL) でも `install.sh` で同じ手順が回ります。

## このディレクトリの中身

| ファイル | 役割 |
|---|---|
| `install.ps1` | **Windows サーバー用** PowerShell インストーラ（A社用はこれ） |
| `install.sh` | Linux サーバー用 (Ubuntu/RHEL 等) インストーラ |
| `.env.template` | 設定テンプレ（インストール直前に実値を埋める） |
| `inquira.service` | Linux 用 systemd の起動ユニット |
| `README.md` | この案内 |

## インストール側（提供側）の作業手順

### 1. `.env` の実値を埋める

`.env.template` をコピーして、提供側が持っているシークレットを埋める：

```bash
cp .env.template .env
# 編集する項目:
#   ANTHROPIC_API_KEY        ← 自分の Anthropic コンソール
#   GOOGLE_CLIENT_ID         ← 共通の OAuth クライアント
#   GOOGLE_CLIENT_SECRET     ← 同上
#   GOOGLE_REDIRECT_URI      ← https://faq.a-corp.jp/auth/callback (A社の公開 URL に合わせる)
```

A社の管理者 Gmail は**リポジトリには書きません**。`.env` を作る時に、
ローカル管理しているメモ（Slack DM や 1Password 等）から `ALLOWED_EMAILS=`
にカンマ区切りで貼り付けてください。

> ⚠ A社の **一般社員にも開放する場合**は `ALLOWED_DOMAIN=` 行に
> A社の Gmail Workspace ドメイン（例: `a-corp.jp`）を追記してください。
> 空のままだと、`ALLOWED_EMAILS` に列挙した人のみアクセス可。

> ⚠ **完成した `.env` はリポジトリにコミットしないでください** (`.gitignore` 済み)。
> 機密情報 (API キー / 管理者メール) を含むため、A社サーバーへ運搬する時のみ
> 一時的にローカルに置きます。

### 2. Google Cloud Console で リダイレクト URI を追加

OAuth クライアントの「認可済みリダイレクト URI」に
`https://faq.a-corp.jp/auth/callback` を追加して保存（数分で反映）。

### 3. パッケージを A社サーバーに配置

ZIP で固めて scp / S3 / USB 等で運搬：

```bash
cd /path/to/faq_platform
tar czf inquira-a_company.tar.gz \
    --exclude='.git' --exclude='__pycache__' --exclude='.venv' \
    --exclude='data' --exclude='tenants/a_company/.env' \
    app/ scripts/ pyproject.toml tenants/a_company/ tenants/a_company/.env
scp inquira-a_company.tar.gz a-admin@a-server:/tmp/
```

### 4. A社サーバーで実行

#### 🪟 Windows Server の場合（A社はこちら）

事前に Python 3.11 をインストール（https://www.python.org/downloads/ 、
[Add python.exe to PATH] にチェック必須）。

ZIP を解凍してから、**PowerShell を「管理者として実行」** で：

```powershell
cd C:\path\to\faq_platform\tenants\a_company
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

完了すると Windows タスクスケジューラに `Inquira` タスクが登録され、
サーバー起動時に自動で立ち上がるようになります。

#### 🐧 Linux Server の場合

```bash
ssh a-admin@a-server
sudo tar xzf /tmp/inquira-a_company.tar.gz -C /tmp/
cd /tmp/faq_platform/tenants/a_company
sudo ./install.sh
```

完了。`✅ Inquira 起動完了` が表示されれば OK。

### 5. リバースプロキシ（A社の IT 部門が既存設備で設定）

A社サーバー上の `localhost:8000` を `https://faq.a-corp.jp` で公開する設定を
既存の nginx / Apache / Caddy に追加してもらう。

簡易 nginx の例（A社 IT に渡す）：

```nginx
server {
    listen 443 ssl http2;
    server_name faq.a-corp.jp;

    ssl_certificate     /etc/ssl/certs/a-corp.jp.crt;
    ssl_certificate_key /etc/ssl/private/a-corp.jp.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # アップロード大きめ対応
        client_max_body_size 1024M;
    }
}
```

### 6. 動作確認 → A社管理者に案内

ブラウザで `https://faq.a-corp.jp/` を開いて Google ログインを確認。
管理者の Gmail でログインして `/admin/upload` が開ければ完了。

A社管理者には以下を送付：
- 公開 URL: `https://faq.a-corp.jp/admin/upload`
- 操作手順 PDF: `docs/a_company_admin_quickstart.pdf`

---

## トラブル対応

| 症状 | 原因と対処 |
|---|---|
| `Python 3.11 以上が見つかりません` | `sudo apt install python3.11 python3.11-venv` (Ubuntu/Debian) または `sudo dnf install python3.11` (RHEL/Rocky) |
| `healthcheck が通らない` | `journalctl -u inquira -n 100` でログ確認。よくあるのは Anthropic API キーの綴りミス |
| Google ログインで「アクセスがブロック」 | リダイレクト URI が Google Cloud Console に未登録、または反映待ち |
| ログイン後に「アクセス権がありません」 | `.env` の `ALLOWED_DOMAIN` / `ALLOWED_EMAILS` がユーザーの Gmail と合っていない |

## 運用コマンド

### 🪟 Windows

```powershell
# 状態確認
Get-ScheduledTask -TaskName Inquira
Invoke-WebRequest http://127.0.0.1:8000/healthz

# 再起動
Stop-ScheduledTask -TaskName Inquira
Start-ScheduledTask -TaskName Inquira

# 手動起動 (デバッグ時)
C:\Inquira\start_inquira.bat
```

### 🐧 Linux

```bash
systemctl status inquira         # 状態確認
systemctl restart inquira        # 再起動
journalctl -u inquira -f         # ログ追跡
sudo -u inquira /opt/inquira/.venv/bin/python -m pytest -q   # テスト実行
```

## バックアップ対象

A社の IT 部門に伝えるバックアップ対象：

- **Windows**: `C:\Inquira\data\` 配下まるごと + `C:\Inquira\.env`
- **Linux**: `/opt/inquira/data/` 配下まるごと + `/opt/inquira/.env`

`data/` にナレッジ・監査ログ・FAQ 候補・フィードバックスコアが入ります。
`.env` は再構築用ですが、機密を含むので暗号化して保管してください。
