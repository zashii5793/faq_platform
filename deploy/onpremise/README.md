# Inquira 自社サーバー導入手順（標準）

クライアント企業（A社等）が自社サーバー（VPS or オンプレ Linux）に Inquira を
**1社分** デプロイする構成です。データはすべてクライアントサーバー内に残り、
Inquira 提供元（運営）はサーバーアクセス権を持たない限りデータに触れません。

> 複数クライアントを1台のサーバーに同居させたい場合は
> [`../multi-tenant/`](../multi-tenant/README.md) を参照。

---

## 前提

- Linux サーバー (Ubuntu 22.04+ / Debian 12+ / RHEL 9+)
- Docker Engine 24+ と docker compose plugin
- ポート 80 / 443 がインターネットから到達可能
- ルートドメイン (例: `a-company.inquira.app`) の DNS 権限

CPU 2 コア / RAM 4 GB / SSD 30 GB から開始可能。`EMBEDDING_BACKEND=e5-large`
を使う場合は RAM 8 GB 以上を推奨。

---

## 手順

### 1. データディレクトリの作成

```bash
sudo mkdir -p /srv/inquira/data
sudo chown 1000:1000 /srv/inquira/data
```

> 所有者を 1000:1000 にしているのは、コンテナ内の非 root ユーザーから
> 書き込めるようにするため。実運用では情シスのアクセス権限を別途設定。

### 2. このディレクトリを配置

```bash
sudo mkdir -p /srv/inquira-deploy
cd /srv/inquira-deploy
# このリポジトリの deploy/onpremise/ 配下のファイルをコピー
```

### 3. `.env` を埋める

```bash
cp .env.example .env
openssl rand -hex 32   # SESSION_SECRET 用
vi .env
```

最低限必須:
- `CLIENT_HOST` — 公開ホスト名
- `ANTHROPIC_API_KEY` — Anthropic Console で発行
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — Google Cloud Console
- `ALLOWED_DOMAIN` または `ALLOWED_EMAILS`
- `SESSION_SECRET` — 必ず固有値

### 4. DNS 設定

`CLIENT_HOST` をこのサーバーの IP に向ける A レコードを追加。

### 5. 起動

```bash
docker compose up -d
docker compose logs -f caddy   # Let's Encrypt の取得状況を確認
```

数十秒で `https://${CLIENT_HOST}` でログイン画面が表示されます。

---

## 動作確認

```bash
# ヘルスチェック
curl -sS https://${CLIENT_HOST}/healthz

# コンテナ状態
docker compose ps
```

ブラウザで `https://${CLIENT_HOST}` にアクセスして、Google ログインが
通ること、画面下部に「🔒 データは貴社サーバー内に保管されています …」が
表示されていることを確認。

---

## バックアップ

```bash
# 推奨: 毎日 03:00 に rsync を打つ cron
0 3 * * *  rsync -a /srv/inquira/data/ /backup/inquira/$(date +\%Y\%m\%d)/
```

詳細は [docs/data_storage_guide.md](../../docs/data_storage_guide.md)。

---

## アップデート

```bash
cd /srv/inquira-deploy
docker compose pull inquira
docker compose up -d inquira
```

イメージタグを `:vX.Y.Z` で固定しておけば、リリースノートを確認してから
タグを書き換える運用にできます。

---

## トラブル時

| 症状 | 確認 |
|---|---|
| HTTPS 証明書が取れない | DNS が正しく向いているか、ポート 80/443 が開いているか |
| 「このアプリは確認されていません」(Google) | 試験運用中は正常。本番では Google OAuth 認証取得を |
| `/healthz` が 503 | `docker compose logs inquira` でエラー確認 |
| 全文検索が遅い | `EMBEDDING_BACKEND` を `e5-small` に変更 |

---

## アクセス権の設計

| 役割 | データへのアクセス |
|---|---|
| クライアント情シス（サーバー管理者） | ✅ SSH 経由でフル |
| クライアント一般スタッフ | ❌ Inquira UI 経由でのみ閲覧（実体には届かない） |
| Inquira 運営（提供元） | ❌ SSH 権限を持たない（サポート時のみ情シスの許可で発行） |

この設計は UI 上にも常時表示されます（画面下部の「🔒 データは貴社サーバー内 …」）。
