#!/usr/bin/env bash
# ワンコマンドデモ起動スクリプト
# 使い方: ./scripts/demo.sh
#   - 必要なら venv を作って依存をインストール
#   - 統合テストを走らせる（失敗したら起動しない）
#   - DEMO_MODE で uvicorn を起動

set -e
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8000}"

# 1. venv 作成（初回のみ）
if [ ! -d .venv ]; then
  echo "🔧 仮想環境を作成中…"
  "$PYTHON" -m venv .venv
fi

# 2. 依存インストール（fastapi が無ければ）
# shellcheck disable=SC1091
source .venv/bin/activate
if ! python -c "import fastapi, anthropic, openpyxl, pypdf" 2>/dev/null; then
  echo "📦 依存パッケージをインストール中…"
  pip install --quiet --upgrade pip
  pip install --quiet -e ".[dev]"
fi

# 3. 全テスト実行（失敗したら起動しない）
echo ""
echo "🧪 統合テストを実行中…"
if ! pytest -q --tb=short; then
  echo ""
  echo "❌ テスト失敗。起動を中止します。"
  exit 1
fi
echo ""
echo "✅ テスト全 PASS"

# 4. サーバ起動
echo ""
echo "🚀 Inquira を起動します"
echo "   チャット画面: http://127.0.0.1:${PORT}/"
echo "   ナレッジ追加: http://127.0.0.1:${PORT}/admin/upload"
echo ""
echo "   (Ctrl+C で停止)"
echo ""

DEMO_MODE=1 \
  FAQ_MASTER_DIR=./data/demo_faq \
  SESSION_SECRET=demo-secret \
  ORG_NAME="貴社" \
  ASSISTANT_ROLE="社内ヘルプデスク" \
  uvicorn app.main:app --host 127.0.0.1 --port "${PORT}"
