# HTTPS デプロイ手順

> 顧客に提供する URL は **必ず HTTPS** が必要です（Google OAuth の要件 + ブラウザのセキュリティ要件）。
> 本ガイドでは 3つのデプロイパターンを案内します。

---

## デプロイ先の選び方

| 選択肢 | 月額 | 設定難易度 | 向いている顧客 |
|---|---|---|---|
| **A. Render** | $0〜$25 | 🟢 易（30分） | PoC・小規模・初導入 |
| **B. Railway** | $0〜$20 | 🟢 易（30分） | 開発者向け・PoC |
| **C. AWS / 自社サーバ** | サーバ代 + 運用工数 | 🔴 難（半日〜） | 大企業・データ主権重視 |

**推奨**: 第1〜2号顧客は **Render** で楽をする。3社目以降で AWS/オンプレを必要とする顧客が出てきたら C へ。

---

## A. Render でデプロイ（推奨・最速）

[Render](https://render.com/) は無料枠あり・自動 HTTPS・Git push で再デプロイの SaaS。

### A-1. Render アカウント作成

1. [https://render.com/](https://render.com/) で **「Get Started」**
2. GitHub 連携 OR Email 登録

### A-2. Web Service を作成

1. Dashboard → **New** → **Web Service**
2. **「Build and deploy from a Git repository」** を選択
3. リポジトリを選択（`zashii5793/faq_platform` を connect）
4. ブランチ: `main`（または現在の開発ブランチ）

### A-3. ビルド設定

| 項目 | 値 |
|---|---|
| Name | `inquira-edu-demo` |
| Region | `Singapore`（日本に近い）|
| Branch | `main` |
| Runtime | **Docker**（Dockerfile を自動検出） |
| Plan | **Free** で開始（後で Standard $25/月 にアップ可能） |

> Dockerfile は既にリポジトリに存在するので Render が自動認識します。

### A-4. 環境変数を設定

Render の **Environment** タブで以下を追加：

```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxx
CLAUDE_MODEL=claude-sonnet-4-6

GOOGLE_CLIENT_ID=123456-abcdef.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxx
GOOGLE_REDIRECT_URI=https://inquira-edu-demo.onrender.com/auth/callback
ALLOWED_DOMAIN=example-edu.co.jp

SESSION_SECRET=（openssl rand -hex 32 の出力）

PRODUCT_NAME=Inquira
ORG_NAME=導入企業
ASSISTANT_ROLE=社内ヘルプデスク
MASKING_INDUSTRY=education
EMBEDDING_BACKEND=tfidf  # 最初は軽量設定で

# DEMO_MODE は **設定しない**（または DEMO_MODE=false）
```

### A-5. デプロイ

「**Create Web Service**」をクリック。
ビルドログを眺めて 2〜4分待つと、`https://inquira-edu-demo.onrender.com/` でアクセス可能になります。

### A-6. Google OAuth 側のリダイレクト URI 更新

Render が払い出した URL を Google Cloud Console の OAuth 設定に登録：

```
https://inquira-edu-demo.onrender.com/auth/callback
```

[docs/google_oauth_setup.md](./google_oauth_setup.md) を参照。

### A-7. カスタムドメイン（任意）

顧客固有のドメインを使いたい場合：

1. Render の **Settings** → **Custom Domains** → **Add**
2. `inquira.example-edu.co.jp` を入力
3. 表示される CNAME を顧客 DNS に登録
4. Let's Encrypt で自動 HTTPS 化（数分）

---

## B. Railway でデプロイ

[Railway](https://railway.app/) も Render と似た SaaS。Dockerfile から自動デプロイ。

```bash
# CLI 利用
brew install railwayapp/railway/railway
railway login
railway link  # プロジェクト紐付け
railway up    # デプロイ
```

または Web UI で GitHub から連携。環境変数の設定は同じ。

公開 URL は `https://xxxx.up.railway.app/` 形式。

---

## C. 自社サーバ / AWS にデプロイ

データ主権が重要な顧客向け。

### C-1. インフラ準備

| リソース | 選択肢 |
|---|---|
| サーバ | EC2 / GCE / 自社オンプレ Linux |
| Python | 3.11+ |
| Web サーバ | nginx (リバプロ) |
| 証明書 | Let's Encrypt (certbot) |
| プロセス管理 | systemd / Docker |

### C-2. アプリ配置（Docker 推奨）

```bash
git clone https://github.com/zashii5793/faq_platform.git
cd faq_platform
git checkout main

# .env を作成（前述の手順）
cp .env.example .env
vim .env

# docker compose で起動
docker compose up -d --build
```

ポート 8000 でアプリが立ち上がる。

### C-3. nginx でリバースプロキシ + HTTPS

`/etc/nginx/sites-available/inquira.conf`:

```nginx
server {
    listen 80;
    server_name inquira.example-edu.co.jp;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name inquira.example-edu.co.jp;

    ssl_certificate     /etc/letsencrypt/live/inquira.example-edu.co.jp/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/inquira.example-edu.co.jp/privkey.pem;

    # セキュリティヘッダ
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    client_max_body_size 1100M;  # アプリの MAX_UPLOAD_MB（既定1024）以上に設定する

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/inquira.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Let's Encrypt 取得
sudo certbot --nginx -d inquira.example-edu.co.jp
```

### C-4. systemd サービス化（Docker 不使用の場合）

`/etc/systemd/system/inquira.service`:

```ini
[Unit]
Description=Inquira FAQ Platform
After=network.target

[Service]
Type=simple
User=inquira
WorkingDirectory=/opt/inquira
EnvironmentFile=/opt/inquira/.env
ExecStart=/opt/inquira/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable inquira
sudo systemctl start inquira
sudo systemctl status inquira
```

### C-5. ファイアウォール

- 80, 443 のみ外部開放
- 8000 (uvicorn) は localhost のみ
- IP 制限が必要なら nginx で `allow / deny`

---

## 共通: デプロイ後の確認チェックリスト

```bash
# 1. ヘルスチェック
curl https://inquira.example-edu.co.jp/healthz
# → {"ok":true}

# 2. ログイン画面表示
curl -I https://inquira.example-edu.co.jp/
# → 200 OK

# 3. SSL 検証
curl -v https://inquira.example-edu.co.jp/healthz 2>&1 | grep -i "SSL\|TLS"

# 4. 認証なしで /api/ask は弾かれるか
curl -X POST https://inquira.example-edu.co.jp/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"test"}'
# → 401 not signed in
```

---

## ログとモニタリング

### Render
- ダッシュボードの **Logs** タブで stdout 確認可能
- 監視は別途 UptimeRobot 等を併用推奨

### 自社サーバ
```bash
# uvicorn ログ
journalctl -u inquira -f

# 監査ログ（業務上重要）
tail -f /opt/inquira/data/audit/audit-$(date +%F).jsonl

# nginx アクセスログ
tail -f /var/log/nginx/access.log
```

---

## 容量とコスト試算

| 項目 | Render Free | Render Standard | 自社サーバ |
|---|---|---|---|
| 月額 | $0 | $25 | サーバ代次第 |
| ストレージ | 1GB | 1GB（永続化に注意） | サーバ容量分 |
| メモリ | 512MB | 2GB | サーバ仕様次第 |
| Sleep | 15分非アクティブで停止 | 常時稼働 | 常時稼働 |
| 用途 | PoC・社内デモ | 35〜100名 | 100名以上・機密重視 |

> ⚠ Render Free は 15分操作なしでスリープ → 再起動に30秒かかります。本番運用は Standard 以上推奨。
> ⚠ Render の永続ディスクは別途 $0.25/GB/月。FAQ・監査ログを保持するなら設定。

---

## バックアップ計画

毎日：
- `data/faq_master/` （FAQマスター）
- `data/audit/` （監査ログ）
- `.env` （オンプレなら）

**Render** ではディスクスナップショット（有料プランのみ）。
**自社** では cron + S3 へ rclone などで cloud バックアップ。

---

## 関連
- [docs/google_oauth_setup.md](./google_oauth_setup.md) — Google OAuth 設定
- [docs/api_key_setup.md](./api_key_setup.md) — Anthropic API キー
- [docs/setup_guide_mac.md](./setup_guide_mac.md) — Mac 開発環境
- [Dockerfile](../Dockerfile) — Docker ビルド
- [docker-compose.yml](../docker-compose.yml) — ローカル Docker 起動
