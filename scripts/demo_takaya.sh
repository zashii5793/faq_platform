#!/usr/bin/env bash
# タカヤモーター株式会社 想定デモ起動
#
# 使い方: ./scripts/demo_takaya.sh
#   通常版: ./scripts/demo.sh と同じ流れで venv 作成・テスト・起動
#   組織名・FAQ 文書だけタカヤモーター用に切り替えます

set -e
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8000}"

echo "🚗 タカヤモーター株式会社 — 社内ヘルプデスク 起動"
echo ""

# 環境チェック（最低限）
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "❌ ${PYTHON} が見つかりません。Python 3.11+ をインストールしてください"
  exit 1
fi

# venv
if [ ! -d .venv ]; then
  echo "🔧 仮想環境を作成中…"
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 依存
REQUIRED="fastapi anthropic openpyxl pypdf pptx authlib sklearn pandas pydantic_settings starlette"
NEED_INSTALL=0
for m in $REQUIRED; do
  if ! python -c "import $m" 2>/dev/null; then NEED_INSTALL=1; break; fi
done
if [ $NEED_INSTALL -eq 1 ]; then
  echo "📦 依存パッケージをインストール中…"
  pip install --quiet --upgrade pip
  pip install --quiet -e ".[dev]"
fi

# テスト
echo ""
echo "🧪 統合テスト実行中…"
if ! pytest -q --tb=short; then
  echo "❌ テスト失敗。起動を中止します。"
  exit 1
fi
echo "✅ テスト全 PASS"

# LAN IP
LAN_IP=""
if command -v ipconfig >/dev/null 2>&1; then
  LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")
elif command -v hostname >/dev/null 2>&1; then
  LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
HOST="${HOST:-127.0.0.1}"

echo ""
echo "🚗 タカヤモーター 社内ヘルプデスク 起動準備完了"
echo ""
echo "   組織名:    タカヤモーター株式会社"
echo "   役割:      整備工場サポート"
echo "   取り込み済み: data/takaya_faq/ の 10 文書"
echo ""
if [ "$HOST" = "0.0.0.0" ] && [ -n "$LAN_IP" ]; then
  echo "   ┌─────────────────────────────────────────────────────────┐"
  echo "   │ 💻 PC:       http://127.0.0.1:${PORT}/                          │"
  echo "   │ 📱 携帯/タブ: http://${LAN_IP}:${PORT}/  ← 工場の iPhone から     │"
  echo "   │ 📁 アップロード: http://${LAN_IP}:${PORT}/admin/upload          │"
  echo "   └─────────────────────────────────────────────────────────┘"
  echo "   ⚠ 認証なしモード。社内 WiFi 内のみで使ってください"
else
  echo "   ┌──────────────────────────────────────────────────┐"
  echo "   │ チャット:     http://127.0.0.1:${PORT}/                  │"
  echo "   │ アップロード: http://127.0.0.1:${PORT}/admin/upload      │"
  echo "   └──────────────────────────────────────────────────┘"
  if [ -n "$LAN_IP" ]; then
    echo ""
    echo "   📱 工場のスマホから試したい場合:"
    echo "      HOST=0.0.0.0 ./scripts/demo_takaya.sh"
  fi
fi
echo ""
echo "   試してみる質問例:"
echo "     ・「車検の法定費用はいくら？」"
echo "     ・「部品発注の締め時間は？」"
echo "     ・「ロードサービスの夜間対応どうするの」"
echo "     ・「リフト作業の安全ルール」"
echo "     ・「タカヤCarEditにログインできない時」"
echo ""
echo "   (Ctrl+C で停止)"
echo ""

# テナント分離: 監査ログ・フィードバックもタカヤ専用ディレクトリに
DEMO_MODE=1 \
  FAQ_MASTER_DIR=./data/takaya_faq \
  SESSION_SECRET=takaya-demo-secret \
  PRODUCT_NAME=Inquira \
  ORG_NAME="タカヤモーター株式会社" \
  ASSISTANT_ROLE="整備工場サポート" \
  uvicorn app.main:app --host "${HOST}" --port "${PORT}"
