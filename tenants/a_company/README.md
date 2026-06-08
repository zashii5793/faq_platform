# Inquira — A株式会社 オンプレ導入パッケージ

> A社の社内サーバーに Inquira を1コマンドで設置するための一式。
> Docker は使わず、Python venv + systemd 構成。

## このディレクトリの中身

| ファイル | 役割 |
|---|---|
| `install.sh` | A社サーバーで叩く全自動セットアップスクリプト |
| `.env.template` | 設定テンプレ（インストール直前に実値を埋める） |
| `inquira.service` | systemd の起動ユニット |
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

A社の管理者 Gmail は既に埋め済み：
- `admin1_redacted@gmail.com`
- `admin2_redacted@gmail.com`
- `admin3_redacted@gmail.com`

> ⚠ A社の **一般社員にも開放する場合**は `ALLOWED_DOMAIN=` 行に
> A社の Gmail Workspace ドメイン（例: `a-corp.jp`）を追記してください。
> 空のままだと、上の3名のみアクセス可。

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

### 4. A社サーバーで実行（root 権限で）

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

```bash
systemctl status inquira         # 状態確認
systemctl restart inquira        # 再起動
journalctl -u inquira -f         # ログ追跡
sudo -u inquira /opt/inquira/.venv/bin/python -m pytest -q   # テスト実行
```

## バックアップ対象

A社の IT 部門に伝えるバックアップ対象：

- `/opt/inquira/data/` 配下まるごと（ナレッジ・監査ログ・FAQ 候補・フィードバックスコア）
- `/opt/inquira/.env`（再構築用、ただし機密なので暗号化保管）
