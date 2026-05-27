#!/usr/bin/env bash
# 本番／試験運用 用起動スクリプト
# 使い方: ./scripts/serve.sh
#
# demo.sh との違い:
#   - DEMO_MODE は強制せず、.env に従う（既定: false → Google SSO 必須）
#   - FAQ_MASTER_DIR をデモ用ディレクトリで上書きしない（本番データを使う）
#   - 起動前に Google OAuth に必要な環境変数の存在を検証
#   - テストは既定でスキップ（高速起動）。RUN_TESTS=1 で実行
#
# 環境変数:
#   PORT=8000              listen ポート
#   HOST=127.0.0.1         listen アドレス（Cloudflare Tunnel 経由なら 127 で OK）
#   RUN_TESTS=1            起動前にテストを実行する
#   PYTHON=python3.11      使用する Python

set -e
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"

# ──────────────────────────────────────────
# 0. 環境チェック
# ──────────────────────────────────────────
echo "🔍 環境チェック…"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "❌ ${PYTHON} が見つかりません。Python 3.11+ をインストールしてください"
  exit 1
fi
PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJ=$(echo "$PY_VER" | cut -d. -f1)
PY_MIN=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJ" -lt 3 ] || { [ "$PY_MAJ" -eq 3 ] && [ "$PY_MIN" -lt 11 ]; }; then
  echo "❌ Python ${PY_VER} は古すぎます。3.11+ が必要です"
  exit 1
fi
echo "   Python ${PY_VER} ✓"

if command -v lsof >/dev/null 2>&1 && lsof -i ":${PORT}" >/dev/null 2>&1; then
  echo "⚠ ポート ${PORT} は既に使用中です。"
  echo "   既存プロセスを止めるか、PORT=8080 ./scripts/serve.sh のように別ポートで起動してください。"
  exit 1
fi

# ──────────────────────────────────────────
# 1. venv 作成（初回のみ）
# ──────────────────────────────────────────
if [ ! -d .venv ]; then
  echo "🔧 仮想環境を作成中…"
  "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# ──────────────────────────────────────────
# 2. 依存インストール（必要なときだけ）
# ──────────────────────────────────────────
REQUIRED_MODULES="fastapi anthropic openpyxl pypdf pptx authlib sklearn pandas pydantic_settings starlette"
NEED_INSTALL=0
for m in $REQUIRED_MODULES; do
  if ! python -c "import $m" 2>/dev/null; then
    NEED_INSTALL=1
    break
  fi
done

if [ $NEED_INSTALL -eq 1 ]; then
  echo "📦 依存パッケージをインストール中…"
  pip install --quiet --upgrade pip
  pip install --quiet -e ".[dev]"
fi

# ──────────────────────────────────────────
# 3. .env の存在と必須設定の検証
# ──────────────────────────────────────────
if [ ! -f .env ]; then
  echo "❌ .env が見つかりません。.env.example をコピーして編集してください:"
  echo "   cp .env.example .env && open -e .env"
  exit 1
fi

# .env から値を読み出す簡易ヘルパー（コメント・空行はスキップ）
get_env() {
  local key="$1"
  grep -E "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- | sed 's/^"//; s/"$//; s/^[[:space:]]*//; s/[[:space:]]*$//'
}

API_KEY=$(get_env ANTHROPIC_API_KEY)
DEMO=$(get_env DEMO_MODE)
GOOGLE_ID=$(get_env GOOGLE_CLIENT_ID)
GOOGLE_SECRET=$(get_env GOOGLE_CLIENT_SECRET)
GOOGLE_REDIRECT=$(get_env GOOGLE_REDIRECT_URI)
ALLOWED_DOMAIN=$(get_env ALLOWED_DOMAIN)
ALLOWED_EMAILS=$(get_env ALLOWED_EMAILS)
SESSION_SECRET=$(get_env SESSION_SECRET)

# Anthropic API キー（プレースホルダのままなら拒否）
if [ -z "$API_KEY" ] || [ "$API_KEY" = "sk-ant-..." ]; then
  echo "❌ ANTHROPIC_API_KEY が .env に未設定 or プレースホルダのままです"
  exit 1
fi

# セッション秘密鍵（デフォルトのままなら拒否）
if [ -z "$SESSION_SECRET" ] || [ "$SESSION_SECRET" = "dev-secret-change-me" ]; then
  echo "❌ SESSION_SECRET が .env に未設定 or 既定値のままです"
  echo "   ランダム文字列を設定してください:"
  echo "     python -c 'import secrets; print(secrets.token_urlsafe(32))'"
  exit 1
fi

# DEMO_MODE が ON のときは認証スキップなので、ローカル以外なら強く警告
if [ "$DEMO" = "true" ] || [ "$DEMO" = "1" ]; then
  echo "⚠ DEMO_MODE=true で起動します（認証スキップ）。本番運用前に必ず false にしてください。"
else
  # DEMO_MODE オフなら Google OAuth 必須
  MISSING=""
  [ -z "$GOOGLE_ID" ] && MISSING="${MISSING}GOOGLE_CLIENT_ID "
  [ -z "$GOOGLE_SECRET" ] && MISSING="${MISSING}GOOGLE_CLIENT_SECRET "
  [ -z "$GOOGLE_REDIRECT" ] && MISSING="${MISSING}GOOGLE_REDIRECT_URI "
  if [ -n "$MISSING" ]; then
    echo "❌ Google SSO 用の環境変数が .env に未設定です: ${MISSING}"
    echo "   設定方法は docs/a_company_security_brief.md または docs/api_key_setup.md を参照"
    exit 1
  fi
  if [ -z "$ALLOWED_DOMAIN" ] && [ -z "$ALLOWED_EMAILS" ]; then
    echo "❌ ALLOWED_DOMAIN または ALLOWED_EMAILS のどちらかを .env に設定してください"
    echo "   （未指定だと「ログインさえできれば誰でも触れる」状態になります）"
    exit 1
  fi
  echo "   Google SSO 設定 ✓"
  echo "   許可ドメイン/メール: ${ALLOWED_DOMAIN:-（個別メールのみ）}"
fi

# ──────────────────────────────────────────
# 4. テスト（既定はスキップ、RUN_TESTS=1 で実行）
# ──────────────────────────────────────────
if [ "${RUN_TESTS:-0}" = "1" ]; then
  echo ""
  echo "🧪 テストを実行中…"
  if ! pytest -q --tb=short; then
    echo "❌ テスト失敗。起動を中止します。"
    exit 1
  fi
  echo "✅ テスト全 PASS"
fi

# ──────────────────────────────────────────
# 5. サーバ起動
# ──────────────────────────────────────────
echo ""
echo "🚀 Inquira を起動します"
echo "   ┌─────────────────────────────────────────────┐"
echo "   │ Listen: http://${HOST}:${PORT}/                   │"
if [ -n "$GOOGLE_REDIRECT" ]; then
  PUBLIC_URL=$(echo "$GOOGLE_REDIRECT" | sed 's|/auth/callback$||')
  echo "   │ 公開URL: ${PUBLIC_URL}/   │"
fi
echo "   └─────────────────────────────────────────────┘"
echo ""
echo "   (Ctrl+C で停止)"
echo ""

# .env は pydantic-settings 経由で自動ロードされるため、env を直接 export しない
exec uvicorn app.main:app --host "${HOST}" --port "${PORT}"
