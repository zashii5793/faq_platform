#!/usr/bin/env bash
# テナント追加スクリプト — 新規顧客向け Inquira インスタンスを 1 コマンドで立ち上げる
#
# 使い方:
#   ./scripts/add_tenant.sh <slug>
#
# 例:
#   ./scripts/add_tenant.sh a_company
#
# やること:
#   1. tenants/<slug>/ ディレクトリ + 専用 data/ + .env を生成（対話で値を入力）
#   2. docker-compose.<slug>.yml を生成（ポート分離 + 専用ボリューム）
#   3. 起動コマンドを表示
#
# 前提:
#   - 提供側の ANTHROPIC_API_KEY / GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET を
#     ~/.inquira_provider_secrets に書いておく（テナント毎に貼り直す手間を省く）
#   - リバースプロキシ (caddy 等) は別途設定済みで、サブドメイン → ポート転送ができる
#
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <slug>"
  echo "Example: $0 a_company"
  exit 1
fi

SLUG="$1"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TENANT_DIR="$ROOT_DIR/tenants/$SLUG"
COMPOSE_FILE="$ROOT_DIR/docker-compose.$SLUG.yml"
SECRETS_FILE="${INQUIRA_PROVIDER_SECRETS:-$HOME/.inquira_provider_secrets}"

if [[ -d "$TENANT_DIR" ]]; then
  echo "❌ tenants/$SLUG は既に存在します。別の slug を指定してください。"
  exit 1
fi

# 提供側シークレット（API キー・OAuth クライアント）の読み込み
if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "⚠ $SECRETS_FILE が見つかりません。"
  echo "  以下の内容で作成してください:"
  echo ""
  echo "    ANTHROPIC_API_KEY=sk-ant-..."
  echo "    GOOGLE_CLIENT_ID=...apps.googleusercontent.com"
  echo "    GOOGLE_CLIENT_SECRET=..."
  echo ""
  exit 1
fi
# shellcheck disable=SC1090
source "$SECRETS_FILE"

# 対話で必要項目を聞く（テナント固有の値だけ）
echo "=== テナント追加: $SLUG ==="
read -rp "組織名 (例: A株式会社) : " ORG_NAME
read -rp "許可ドメイン (例: a-corp.jp) : " ALLOWED_DOMAIN
read -rp "管理者の Gmail (カンマ区切り可) : " ALLOWED_EMAILS
read -rp "公開 URL (例: https://faq-a.inquira.app) : " PUBLIC_URL
read -rp "ホスト側ポート (例: 8011) : " HOST_PORT

# 入力チェック
for var in ORG_NAME ALLOWED_DOMAIN ALLOWED_EMAILS PUBLIC_URL HOST_PORT; do
  if [[ -z "${!var}" ]]; then
    echo "❌ $var が空です。中断しました。"
    exit 1
  fi
done

# データディレクトリ・.env を生成
mkdir -p "$TENANT_DIR/data"

cat > "$TENANT_DIR/.env" <<EOF
# === $ORG_NAME 専用テナント ($(date '+%Y-%m-%d' 生成)) ===
PRODUCT_NAME=Inquira
ORG_NAME=$ORG_NAME
ASSISTANT_ROLE=社内ヘルプデスク

ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
CLAUDE_MODEL=claude-sonnet-4-6

GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI=$PUBLIC_URL/auth/callback

ALLOWED_DOMAIN=$ALLOWED_DOMAIN
ALLOWED_EMAILS=$ALLOWED_EMAILS

SESSION_SECRET=$(openssl rand -hex 32)

DEMO_MODE=false
HOST=0.0.0.0
PORT=8000
EOF

# docker-compose を生成（ポート + ボリュームをテナント分離）
cat > "$COMPOSE_FILE" <<EOF
# $ORG_NAME 専用テナント
# 起動: docker compose -f docker-compose.$SLUG.yml up -d
services:
  inquira_$SLUG:
    build: .
    image: inquira:latest
    container_name: inquira-$SLUG
    restart: unless-stopped
    env_file: tenants/$SLUG/.env
    ports:
      - "$HOST_PORT:8000"
    volumes:
      - ./tenants/$SLUG/data:/app/data
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8000/healthz"]
      interval: 30s
      timeout: 3s
      retries: 5
      start_period: 30s
EOF

echo ""
echo "✅ テナント生成完了: $SLUG"
echo ""
echo "次の作業:"
echo "  1. Google Cloud Console の OAuth クライアントに以下のリダイレクト URI を追加:"
echo "       $PUBLIC_URL/auth/callback"
echo ""
echo "  2. リバースプロキシで $PUBLIC_URL → localhost:$HOST_PORT を設定"
echo ""
echo "  3. 起動:"
echo "       docker compose -f docker-compose.$SLUG.yml up -d"
echo ""
echo "  4. 動作確認:"
echo "       curl -fsS http://localhost:$HOST_PORT/healthz"
echo ""
echo "  5. A社管理者に PDF (docs/a_company_admin_quickstart.pdf) と"
echo "     URL ($PUBLIC_URL/admin/upload) を送付"
