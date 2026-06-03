# Inquira マルチテナント (弊社共有ホスティング) 構成

> **これはオプション構成です。** 標準形は [`../onpremise/`](../onpremise/README.md)
> （クライアント自社サーバー導入）。本構成は「自社サーバーを用意できない／
> 用意したくない」クライアント向けに、運営側が共有ホストで複数社をまとめて
> 動かすための雛形です。

## 構成イメージ

```
[Inquira 運営の1台のサーバー]
   ├ Caddy (proxy/) ── *.inquira.app のワイルドカード SSL 終端
   ├ inquira-a-company   (コンテナA + /srv/inquira/clients/a-company/data)
   ├ inquira-b-company   (コンテナB + /srv/inquira/clients/b-company/data)
   └ inquira-c-company   (コンテナC + /srv/inquira/clients/c-company/data)
```

クライアントごとに **コンテナ・データボリュームを完全分離** しますが、
物理サーバーは弊社管理下で同居するため、**データ主権は契約・運用で担保** します。
オンプレ希望のクライアントには `../onpremise/` を案内してください。

## 含まれるファイル

| ファイル | 用途 |
|---|---|
| `docker-compose.template.yml` | クライアント1社分の compose 定義テンプレート |
| `.env.template` | クライアント固有設定のテンプレート |
| `proxy/docker-compose.yml` | Caddy リバプロ（共通・最初に1度だけ起動） |
| `proxy/Caddyfile` | ホスト名 → コンテナの振り分け（クライアント追加時に追記） |

## 新規クライアント追加の流れ（手順サマリ）

```bash
# 初回のみ: 共通ネットワーク + Caddy を起動
docker network create inquira_net
cd proxy && docker compose up -d && cd ..

# 1社追加（例: c-company）
SLUG=c-company
mkdir -p clients/$SLUG
cp docker-compose.template.yml clients/$SLUG/docker-compose.yml
cp .env.template clients/$SLUG/.env
$EDITOR clients/$SLUG/.env

# Caddyfile に振り分けブロックを追記して reload
$EDITOR proxy/Caddyfile
docker exec inquira-proxy caddy reload --config /etc/caddy/Caddyfile

# 起動
cd clients/$SLUG && docker compose up -d
```

将来的には `provision-client.sh` で自動化予定。

## 注意

- 本構成では運営側に物理アクセスがあるため、UI 上の「Inquira 運営からも
  アクセス不可」表示は **契約上のコミットメント** として理解してください。
- クライアントごとに `SESSION_SECRET` は必ず別の値を使うこと。
- ワイルドカード証明書を使う場合は DNS-01 challenge の設定が別途必要
  （Caddyfile 冒頭のコメント参照）。
