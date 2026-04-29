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

# ──────────────────────────────────────────
# 0. 環境チェック
# ──────────────────────────────────────────
echo "🔍 環境チェック…"

# Python バージョン (3.11 以上)
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

# ポート使用中チェック
if command -v lsof >/dev/null 2>&1 && lsof -i ":${PORT}" >/dev/null 2>&1; then
  echo "⚠ ポート ${PORT} は既に使用中です。"
  echo "   既存プロセスを止めるか、PORT=8080 ./scripts/demo.sh のように別ポートで起動してください。"
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
# 2. 依存インストール（毎回実行 — 高速、新規依存も必ず入る）
# ──────────────────────────────────────────
# 必須依存をすべてチェック（今後 deps が増えてもここを更新）
REQUIRED_MODULES="fastapi anthropic openpyxl pypdf pptx authlib sklearn pandas pydantic_settings starlette"
NEED_INSTALL=0
for m in $REQUIRED_MODULES; do
  if ! python -c "import $m" 2>/dev/null; then
    NEED_INSTALL=1
    break
  fi
done

if [ $NEED_INSTALL -eq 1 ]; then
  echo "📦 依存パッケージをインストール中（初回 or 更新があるため）…"
  pip install --quiet --upgrade pip
  pip install --quiet -e ".[dev]"
fi

# ──────────────────────────────────────────
# 3. 全テスト実行（失敗したら起動しない）
# ──────────────────────────────────────────
echo ""
echo "🧪 統合テストを実行中…"
if ! pytest -q --tb=short; then
  echo ""
  echo "❌ テスト失敗。起動を中止します。"
  echo "   依存を更新するなら: rm -rf .venv && ./scripts/demo.sh"
  exit 1
fi
echo ""
echo "✅ テスト全 PASS"

# ──────────────────────────────────────────
# 4. サーバ起動
# ──────────────────────────────────────────
echo ""
echo "🚀 Inquira を起動します"
echo ""
echo "   ┌──────────────────────────────────────────────────┐"
echo "   │ チャット画面: http://127.0.0.1:${PORT}/                  │"
echo "   │ ナレッジ追加: http://127.0.0.1:${PORT}/admin/upload      │"
echo "   │ ヘルスチェック: http://127.0.0.1:${PORT}/healthz         │"
echo "   └──────────────────────────────────────────────────┘"
echo ""
echo "   (Ctrl+C で停止)"
echo ""

DEMO_MODE=1 \
  FAQ_MASTER_DIR=./data/demo_faq \
  SESSION_SECRET=demo-secret \
  ORG_NAME="貴社" \
  ASSISTANT_ROLE="社内ヘルプデスク" \
  uvicorn app.main:app --host 127.0.0.1 --port "${PORT}"
