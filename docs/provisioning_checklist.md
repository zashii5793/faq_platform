# Inquira テナント提供チェックリスト（提供側オペ用）

> 想定読者: 自分（提供側）／ Inquira を顧客に SaaS 提供するときの作業手順
> 所要時間: 1 テナントあたり **30 分〜1 時間**
> 前提: APIキー・OAuth クライアントは提供側持ち（顧客負担ゼロ）

---

## 0. 初回のみ — 提供側シークレットの保管

ホームに `~/.inquira_provider_secrets` を作成して、全テナントで共通の値を書く：

```bash
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
```

`chmod 600 ~/.inquira_provider_secrets` でパーミッション絞っておく。

---

## 1. 顧客情報のヒアリング（5 分・メール or 商談で）

聞くのはこれだけ：

| 項目 | 例 |
|---|---|
| 組織名 | A株式会社 |
| 許可するメールドメイン | a-corp.jp |
| 管理者の Gmail（カンマ区切り） | admin@a-corp.jp, ishizashi@a-corp.jp |
| 希望するサブドメイン | faq-a |

---

## 2. テナント生成（1 コマンド・3 分）

```bash
./scripts/add_tenant.sh a_company
```

対話で 5 項目入力するだけで以下が自動生成される：
- `tenants/a_company/.env`（テナント固有設定 + SESSION_SECRET ランダム生成）
- `tenants/a_company/data/`（永続化ボリューム）
- `docker-compose.a_company.yml`（ポート分離 + コンテナ名分離）

---

## 3. Google OAuth リダイレクト URI 追加（5 分）

[Google Cloud Console](https://console.cloud.google.com/apis/credentials) で
既存の OAuth クライアントを開いて、以下を「認可済みリダイレクト URI」に追加：

```
https://faq-a.inquira.app/auth/callback
```

保存して数分待つ（反映までラグあり）。

---

## 4. リバースプロキシ設定（5 分）

caddy の場合（`Caddyfile` に追記）：

```caddyfile
faq-a.inquira.app {
    reverse_proxy localhost:8011
}
```

`systemctl reload caddy` で反映。

nginx の場合は `proxy_pass http://localhost:8011;` + Let's Encrypt。

---

## 5. 起動 + 動作確認（5 分）

```bash
docker compose -f docker-compose.a_company.yml up -d
docker logs -f inquira-a_company   # 起動ログを観察、テストが通ってから uvicorn が立つ
curl -fsS https://faq-a.inquira.app/healthz   # {"ok": true} が返ればOK
```

ブラウザで `https://faq-a.inquira.app/` を開いて、Google ログイン画面が出ることを確認。
管理者の Gmail でログインして `/admin/upload` が開ければ完了。

---

## 6. 顧客への引き渡し（5 分）

以下をメール or Slack で送る：

```
件名: Inquira ご利用案内 — A株式会社様

A株式会社 ご担当者様

Inquira のご利用準備が整いました。以下より早速ご利用ください。

▼ 管理画面（ナレッジ投入）
https://faq-a.inquira.app/admin/upload

▼ 一般利用
https://faq-a.inquira.app/

▼ 操作手順（A4 1ページ）
docs/a_company_admin_quickstart.pdf を添付

ナレッジ投入後、すぐに社員の方の利用を開始いただけます。
ご不明点があればお気軽にご連絡ください。
```

PDF 添付: `docs/a_company_admin_quickstart.pdf`

---

## 7. ローンチ後のフォロー（運用ルーチン）

| 頻度 | やること |
|---|---|
| 翌営業日 | `docker logs inquira-a_company` で初日のエラーチェック |
| 1 週間後 | 利用統計 (`/admin/upload#analytics`) を見て、未回答質問の傾向を顧客にフィードバック |
| 月次 | `📈 削減効果` のスクショを顧客に送る（営業フォロー） |
| 月次 | `🌱 FAQ 候補` の承認状況を確認、貯まっていたら「これ承認しといてください」と Slack |

---

## トラブル対応

### Google ログインで「アクセスがブロックされました」
→ リダイレクト URI が Google Cloud Console に未登録、または反映待ち。5 分待って再試行。

### ログイン後に「アクセス権がありません」
→ `.env` の `ALLOWED_DOMAIN` か `ALLOWED_EMAILS` が顧客側のメールと合っていない。`tenants/<slug>/.env` を修正して `docker compose -f docker-compose.<slug>.yml restart`。

### コンテナがすぐ落ちる
→ 起動時に pytest が走る設計。`docker logs` でテスト失敗箇所を確認。

### ポート競合
→ `docker-compose.<slug>.yml` の `ports:` のホスト側を別のポートに変更。`add_tenant.sh` 実行時の選択を間違えた場合、`tenants/<slug>/` ごと消して再実行で OK。

---

## テナント削除

```bash
docker compose -f docker-compose.a_company.yml down -v
rm -rf tenants/a_company/ docker-compose.a_company.yml
```

⚠ `tenants/<slug>/data/` には顧客のナレッジが入っているので、削除前に顧客に確認すること。
