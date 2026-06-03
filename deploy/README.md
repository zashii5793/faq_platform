# Inquira デプロイ構成集

導入形態に応じて2種類の Docker Compose 構成を提供しています。

## どちらを使うか

| | [`onpremise/`](./onpremise/README.md) **(標準)** | [`multi-tenant/`](./multi-tenant/README.md) (オプション) |
|---|---|---|
| 想定 | クライアントが自社サーバーを用意できる | 自社サーバーを用意できない／したくない |
| サーバー | クライアントの VPS / オンプレ | 弊社共有ホスト |
| データ実体 | クライアントサーバー内 (`/srv/inquira/data`) | 弊社サーバー内 (`/srv/inquira/clients/<slug>/data`) |
| Inquira 運営の物理アクセス | ❌ なし（SSH 権限を持たない） | ⚠ あり（契約・運用で「触らない」を担保） |
| 新規 1 社あたりの作業 | サーバー準備 + `docker compose up -d` (約 30 分) | テンプレ展開 + Caddy reload (約 10 分) |
| 料金モデル適合性 | クライアントが API キーを持つ場合に最適 | 弊社マスター API キーで提供する場合に最適 |

**迷ったら `onpremise/` を案内してください。** データ主権がクライアント側にあり、
営業説明もシンプルです。

## 共通する設計原則

両構成とも以下は共通です:

- Inquira 本体 + Caddy (SSL 終端) の 2 コンテナ構成
- データは Docker volume ではなく **ホスト側ディレクトリにマウント**（バックアップ容易）
- Caddy が Let's Encrypt から自動で TLS 証明書を取得
- 環境変数で全データパスを上書き可能
- UI 上に「データ保管場所と直接アクセス不可」の明示が常時表示される
  （詳細は `app/main.py` の `_data_storage_info_html` / `_data_trust_line_html`）

## 関連ドキュメント

- [docs/data_storage_guide.md](../docs/data_storage_guide.md) — データ保存仕様
- [docs/deployment_guide.md](../docs/deployment_guide.md) — 既存デプロイ手順
- [docs/api_key_setup.md](../docs/api_key_setup.md) — Anthropic API キー取得
- [docs/google_oauth_setup.md](../docs/google_oauth_setup.md) — OAuth 設定
