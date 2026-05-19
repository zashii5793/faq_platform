#!/usr/bin/env bash
# クライアント評価用デモ起動（中立名スクリプト）
#
# 使い方:
#   1. データを data/client_eval/faq_master/ に置く
#   2. ./scripts/demo_client_eval.sh
#
# テナント分離:
#   - FAQ:      ./data/client_eval/faq_master/
#   - 監査ログ: ./data/client_eval/audit/
#   - 学習:     ./data/client_eval/feedback_scores.json
#   - 設定:     ./data/client_eval/org_settings.json
#   - 生データ: ./data/client_eval/raw/
#   - キャッシュ: ./data/client_eval/embeddings.npz
#
# デモ会社用デモ (demo_company.sh) のデータには一切影響しません。

set -e
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
EVAL_DIR="./data/client_eval"

# データディレクトリの存在チェック
if [ ! -d "${EVAL_DIR}/faq_master" ] || [ -z "$(ls -A ${EVAL_DIR}/faq_master 2>/dev/null)" ]; then
  echo "❌ ${EVAL_DIR}/faq_master/ にデータが置かれていません。"
  echo ""
  echo "   📁 データをこのフォルダにコピーしてから再実行してください:"
  echo "      ${EVAL_DIR}/faq_master/"
  echo ""
  echo "   例（受領した zip を解凍する場合）:"
  echo "      mkdir -p ${EVAL_DIR}/faq_master"
  echo "      unzip ~/Downloads/受領データ.zip -d ${EVAL_DIR}/faq_master/"
  echo ""
  echo "   対応フォーマット: .md / .txt / .pdf / .xlsx / .docx / .pptx / .csv"
  exit 1
fi

N_FILES=$(find "${EVAL_DIR}/faq_master" -type f | wc -l | tr -d ' ')

# venv チェック（既存があれば再利用）
if [ ! -d .venv ]; then
  echo "❌ .venv がありません。先に ./scripts/demo_company.sh を1度実行して .venv を作成してください。"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# LAN IP
LAN_IP=""
if command -v ipconfig >/dev/null 2>&1; then
  LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")
elif command -v hostname >/dev/null 2>&1; then
  LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
fi

echo ""
echo "🧪 クライアント評価環境 — 社内ヘルプデスク"
echo ""
echo "   データ:    ${EVAL_DIR}/faq_master/ (${N_FILES} ファイル)"
echo "   組織名:    [評価環境]"
echo "   役割:      社内ヘルプデスク"
echo ""
if [ "$HOST" = "0.0.0.0" ] && [ -n "$LAN_IP" ]; then
  echo "   ┌─────────────────────────────────────────────────────────┐"
  echo "   │ 💻 PC:           http://127.0.0.1:${PORT}/                      │"
  echo "   │ 📱 LAN内端末:    http://${LAN_IP}:${PORT}/                      │"
  echo "   │ 📁 アップロード: http://${LAN_IP}:${PORT}/admin/upload          │"
  echo "   └─────────────────────────────────────────────────────────┘"
  echo "   ⚠ 認証なしモード。社内 WiFi 内のみで使ってください"
else
  echo "   ┌──────────────────────────────────────────────────┐"
  echo "   │ チャット:     http://127.0.0.1:${PORT}/                  │"
  echo "   │ アップロード: http://127.0.0.1:${PORT}/admin/upload      │"
  echo "   └──────────────────────────────────────────────────┘"
fi
echo ""
echo "   ⚠ クライアントデータは ${EVAL_DIR}/ に隔離されています（.gitignore済）"
echo "   (Ctrl+C で停止)"
echo ""

# 全保存先を client_eval/ に分離 + APIキーは .env のものを使う
DEMO_MODE=1 \
  FAQ_MASTER_DIR="${EVAL_DIR}/faq_master" \
  AUDIT_LOG_DIR="${EVAL_DIR}/audit" \
  FEEDBACK_PATH="${EVAL_DIR}/feedback_scores.json" \
  ORG_SETTINGS_PATH="${EVAL_DIR}/org_settings.json" \
  RAW_UPLOAD_DIR="${EVAL_DIR}/raw" \
  EMBEDDING_CACHE_PATH="${EVAL_DIR}/embeddings.npz" \
  SESSION_SECRET="client-eval-demo-secret" \
  PRODUCT_NAME="Inquira" \
  ORG_NAME="[評価環境]" \
  ASSISTANT_ROLE="社内ヘルプデスク" \
  uvicorn app.main:app --host "${HOST}" --port "${PORT}"
