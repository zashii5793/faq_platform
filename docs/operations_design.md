# Inquira 運用設計書（Docker 標準形）

> 想定読者: Inquira 提供元（運営）の運用担当・営業担当・サポート担当
> 目的: 新規クライアント導入から平常運用・障害対応・撤退までの「運営側の動き方」を1か所にまとめる。
> 関連: [deploy/README.md](../deploy/README.md) — Compose 構成 / [docs/billing_design.md](./billing_design.md) — 課金 / [docs/data_storage_guide.md](./data_storage_guide.md) — データ仕様

---

## 0. 設計の前提

Inquira は **完全ローカル保存型** の社内 FAQ プラットフォームです。
データはクライアントサーバー内に閉じ、Anthropic API への送信のみが外部通信となります。

- **標準導入形態は onpremise（1社=1サーバー）**。データ実体はクライアント側、運営からは物理アクセス不可。
- **共有ホスティング（multi-tenant）はオプション**。自社サーバーを用意できないクライアント向け。
- **データ主権は UI 上にも常時表示** されます（`app/main.py` の `_data_storage_info_html` / `_data_trust_line_html`）。
- 1社追加に要する作業時間は **約 30 分**（DNS 反映待ちを除く）。

---

## 1. 導入形態の選択

クライアントとの初回打合せで決めます。判断材料は以下：

| 質問 | onpremise を選ぶ | multi-tenant を選ぶ |
|---|---|---|
| 社内データを社外サーバーに置く規程はあるか | ❌ NG → onpremise | 制限なし |
| 自社で Linux サーバー (VPS/オンプレ) を運用できる情シスがいるか | ✅ いる | いない |
| Inquira 運営に物理アクセスを許容するか | 許容しない | 契約で許容 |
| 月の質問数規模 | どちらでも | 1,000問/月以下なら効率的 |

迷ったら **onpremise を案内** してください。データ主権の説明がシンプルで、契約後のトラブルも少なくなります。

---

## 2. 新規クライアント導入の標準手順（onpremise）

### 2.1 タイムライン

| フェーズ | 作業 | 所要 | 担当 |
|---|---|---|---|
| **事前準備** | ヒアリング、サーバー要件提示、DNS 委任 or サブドメイン発行 | 1〜3日 | 営業 |
| **クライアント側準備** | VPS 契約 or オンプレ準備、Docker インストール、SSH 鍵交換 | 1〜3日 | クライアント情シス |
| **デプロイ** | `.env` 構築、`docker compose up -d`、DNS 切り替え、動作確認 | **30分** | 運営 |
| **初期データ投入** | クライアント文書の取り込み、しきい値調整 | 0.5〜2日 | 運営 + クライアント情シス |
| **テスト運用** | 5〜10名で試用、フィードバック収集 | 1〜2週 | クライアント |
| **本番リリース** | 全社展開、運用引き継ぎ | 半日 | 運営 → クライアント |

### 2.2 必要な事前情報チェックリスト

クライアントから受け取るもの：

- [ ] サーバーの SSH 接続情報（IP・ユーザー・鍵）
- [ ] 公開ホスト名（例: `a-company.inquira.app` または `inquira.a-company.co.jp`）
- [ ] 表示組織名（`ORG_NAME`）と AI の役割表記（`ASSISTANT_ROLE`）
- [ ] 許可ドメイン or 許可メール一覧（Google SSO）
- [ ] データ保管先パス（既定: `/srv/inquira/data`）
- [ ] バックアップ先（任意。NAS or 別 VPS）

運営側で用意するもの：

- [ ] Anthropic API キー（弊社マスター or クライアント子キー — [billing_design.md](./billing_design.md) 参照）
- [ ] Google OAuth クライアント ID/Secret（弊社共通 or クライアント発行）
- [ ] `SESSION_SECRET` 生成（`openssl rand -hex 32`）

### 2.3 デプロイの実作業（30分）

[`deploy/onpremise/README.md`](../deploy/onpremise/README.md) の手順通り。要点だけ抜粋：

```bash
# クライアントサーバーで実行
sudo mkdir -p /srv/inquira/data && sudo chown 1000:1000 /srv/inquira/data
sudo mkdir -p /srv/inquira-deploy && cd /srv/inquira-deploy
# deploy/onpremise/ 一式を scp で送る
cp .env.example .env && vi .env
docker compose up -d
docker compose logs -f caddy   # HTTPS 取得を確認
```

### 2.4 引き渡し時のチェックリスト

- [ ] `https://${CLIENT_HOST}/healthz` が 200
- [ ] Google ログインが通り、許可外メールは弾かれる
- [ ] チャット画面下部に「🔒 データは貴社サーバー内 …」が常時表示されている
- [ ] サイドバー「💾 データの保管場所」に正しいパスが表示されている
- [ ] テスト質問1件で回答 + 出典が返る
- [ ] `/admin/upload` から文書1本を取り込んで再質問できる
- [ ] バックアップ cron が動作している（初回 rsync 完了）

---

## 3. 平常運用

### 3.1 監視

最低限の監視項目：

| 監視対象 | 方法 | 閾値 | 通報先 |
|---|---|---|---|
| `/healthz` | 外形監視 (UptimeRobot 等) | 5分間 NG で通報 | 運営 Slack #inquira-ops |
| Anthropic API 残高 | Anthropic Console アラート | 月予算の 80% で通報 | 運営 Slack |
| ディスク使用率 | サーバー側 (df) | 80% で通報 | クライアント情シス |
| Caddy 証明書期限 | Caddy ログ | 30日前から確認 | 自動更新前提・失敗時のみ |

外形監視は `https://${CLIENT_HOST}/healthz` を全クライアント分登録します。

### 3.2 ログ確認

```bash
# 直近のアプリログ
docker compose logs --tail 100 inquira

# 監査ログ（質問・操作の履歴）
sudo tail -f /srv/inquira/data/audit/audit-$(date +%Y-%m-%d).jsonl

# Caddy アクセスログ
docker compose logs --tail 100 caddy
```

### 3.3 バックアップ

クライアントサーバー側に cron で仕掛けます（[deploy/onpremise/README.md](../deploy/onpremise/README.md) 参照）：

```cron
0 3 * * *  rsync -a --delete /srv/inquira/data/ /backup/inquira/$(date +\%Y\%m\%d)/
0 4 * * 0  find /backup/inquira -maxdepth 1 -type d -mtime +30 -exec rm -rf {} \;
```

- 必須対象: `faq_master/`, `audit/`, `feedback_scores.json`, `org_settings.json`, `.env`
- 再生成可（不要）: `index.json`, `embeddings.npz`

> 運営側ではバックアップ実体は保持しません（データ主権の原則）。ただし
> `.env` の値（特に `SESSION_SECRET` と OAuth/API キー）の管理は運営側でも
> 1Password 等にコピーを保持し、サーバー喪失時の再構築に備えます。

### 3.4 アップデート

新バージョンを GHCR に push → 各クライアントの compose のタグを書き換え：

```bash
ssh inquira@${CLIENT_HOST}
cd /srv/inquira-deploy
sed -i 's/inquira:v1.2.3/inquira:v1.2.4/' .env
docker compose pull inquira
docker compose up -d inquira
docker compose logs --tail 50 inquira | grep -i error || echo "OK"
```

破壊的変更がないリリースは Slack 通知のみ、ある場合はクライアント情シスに事前連絡。

---

## 4. 障害対応

### 4.1 一次切り分け

| 症状 | 確認 | 原因の典型 |
|---|---|---|
| HTTP 502/503 | `docker compose ps` | Inquira コンテナ停止 / 起動中 |
| HTTPS 証明書失効 | `docker compose logs caddy` | DNS 変更後の再取得失敗 |
| ログインできない | `docker compose logs inquira \| grep auth` | OAuth 設定ずれ / 許可ドメイン外 |
| 回答精度が低下 | `/api/admin/stats` | 文書追加後の再取り込み未実施 |
| 「該当情報なし」が多い | `EMBEDDING_BACKEND` | tfidf → e5-small への切替検討 |

### 4.2 復旧手順

データを失わない順序で：

```bash
# 1. アプリだけ再起動（データに触れない）
docker compose restart inquira

# 2. それでもダメなら一度落として起動
docker compose down
docker compose up -d

# 3. データ破損の疑いがあるとき
cp -r /srv/inquira/data /srv/inquira/data.broken.$(date +%s)
# バックアップから戻す
rsync -a --delete /backup/inquira/YYYYMMDD/ /srv/inquira/data/
docker compose up -d
```

`data.broken.*` を消すのは原因究明後。

### 4.3 サーバー喪失からの再構築（DR）

クライアントサーバーが完全喪失した場合の手順：

1. 新サーバーを準備（同 OS・同スペック）
2. `deploy/onpremise/` を再配置
3. `.env` を運営側 1Password から復元
4. バックアップから `/srv/inquira/data` をリストア
5. `docker compose up -d`
6. DNS の A レコードを新サーバー IP に向ける
7. HTTPS 再取得まで数分待機

`SESSION_SECRET` を保持していれば、ユーザーのログインセッションも維持されます。

---

## 5. アクセス権の設計

| 役割 | データ実体 | UI 一般機能 | UI 管理機能 | 備考 |
|---|---|---|---|---|
| クライアント一般スタッフ | ❌ | ✅ | ❌ | UI 上でのみ閲覧 |
| クライアント情シス（サーバー管理者） | ✅ (SSH) | ✅ | ✅ | 全権限 |
| 運営（提供元）通常時 | ❌ | ❌ | ❌ | 一切のアクセス不可 |
| 運営（提供元）サポート時 | ⚠ | ✅ | ✅ | 情シスから SSH 鍵を一時発行された場合のみ |
| 運営（提供元）作業後 | ❌ | ❌ | ❌ | SSH 鍵を返却 |

サポート対応で SSH 権限を借りた場合は、作業完了後に鍵を破棄し、情シスから鍵失効を確認します。

---

## 6. インシデント対応

### 6.1 セキュリティインシデント

| 事象 | 一次対応 | 二次対応 |
|---|---|---|
| API キー漏洩疑い | Anthropic Console で即時失効 → 新キー発行 → クライアント `.env` 更新 | 漏洩経路調査・再発防止 |
| OAuth Secret 漏洩疑い | Google Cloud Console で Secret 再発行 → 全クライアント `.env` 更新 | 同上 |
| 不正アクセスログ検知 | `/srv/inquira/data/audit/` を保全 → クライアント情シスに通知 | フォレンジック支援 |
| 文書誤公開 | `/admin/documents/{name}` で削除 → 監査ログ確認 | アクセスログから影響範囲特定 |

### 6.2 連絡フロー

```
インシデント発生
  ↓
運営側で検知 ─→ 24時間以内に当該クライアント情シスへ第一報
  ↓
事実関係の整理（48時間以内）
  ↓
詳細報告書（5営業日以内）
```

---

## 7. クライアント解約・撤退手順

```bash
# 1. クライアント情シスに最終バックアップを依頼
ssh inquira@${CLIENT_HOST}
tar czf /backup/inquira-final-$(date +%Y%m%d).tar.gz /srv/inquira/data

# 2. コンテナ停止
cd /srv/inquira-deploy
docker compose down -v

# 3. データ削除（クライアント許可後）
sudo rm -rf /srv/inquira

# 4. 運営側でクライアント情報を 1Password から削除
# 5. DNS レコードの削除（弊社管理ドメインの場合）
```

最終バックアップは **クライアントに引き渡し**、運営側では保持しません。

---

## 8. SLA の目安

参考値。契約により上下します。

| 項目 | 目安 |
|---|---|
| 月間稼働率 | 99.5%（onpremise はクライアント側設備依存） |
| 一次応答 | 平日 9-18時 4時間以内 |
| 緊急障害復旧着手 | 平日 9-18時 1時間以内 |
| バージョンアップ通知 | 破壊的変更は2週間前 |
| データ保全 | クライアント側責任、運営は復旧支援のみ |

---

## 9. 関連ドキュメント

- [deploy/README.md](../deploy/README.md) — Docker 構成の選択
- [deploy/onpremise/README.md](../deploy/onpremise/README.md) — 1社=1サーバー導入手順
- [deploy/multi-tenant/README.md](../deploy/multi-tenant/README.md) — 共有ホスト導入手順
- [docs/billing_design.md](./billing_design.md) — API 計量と請求設計
- [docs/data_storage_guide.md](./data_storage_guide.md) — データ保存の詳細
- [docs/api_cost_analysis.md](./api_cost_analysis.md) — API コスト試算
