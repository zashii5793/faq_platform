#!/usr/bin/env bash
# デモ会社株式会社 想定デモ起動
#
# 使い方: ./scripts/demo_company.sh
#   通常版: ./scripts/demo.sh と同じ流れで venv 作成・テスト・起動
#   組織名・FAQ 文書だけデモ会社用に切り替えます

set -e
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8000}"

echo "🚗 デモ会社株式会社 — 社内ヘルプデスク 起動"
echo ""

# 既存の .venv が Python 3.11+ ならそれを優先利用（システム python3 が 3.9 でも OK）
USE_EXISTING_VENV=0
if [ -d .venv ] && [ -x .venv/bin/python ]; then
  VENV_VER=$(.venv/bin/python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
  VENV_MAJ=$(echo "$VENV_VER" | cut -d. -f1)
  VENV_MIN=$(echo "$VENV_VER" | cut -d. -f2)
  if [ "$VENV_MAJ" -ge 3 ] 2>/dev/null && [ "$VENV_MIN" -ge 11 ] 2>/dev/null; then
    echo "   既存 .venv (Python ${VENV_VER}) を使用 ✓"
    USE_EXISTING_VENV=1
  fi
fi

if [ "$USE_EXISTING_VENV" -eq 0 ]; then
  # 環境チェック（最低限）
  if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "❌ ${PYTHON} が見つかりません。"
    echo "   方法A: brew install python@3.11"
    echo "   方法B: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
  fi

  # Python バージョンチェック (3.11+)
  PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  PY_MAJ=$(echo "$PY_VER" | cut -d. -f1)
  PY_MIN=$(echo "$PY_VER" | cut -d. -f2)
  if [ "$PY_MAJ" -lt 3 ] || { [ "$PY_MAJ" -eq 3 ] && [ "$PY_MIN" -lt 11 ]; }; then
    echo "❌ Python ${PY_VER} は古すぎます。3.11+ が必要です（faq-platform の依存条件）。"
    echo ""
    echo "💡 既に .venv を Python 3.11 で作成済みの場合:"
    echo "   ls -la .venv/bin/python が Python 3.11+ を指していれば、"
    echo "   このスクリプトを更新版（git pull）にしてから再実行してください"
    echo ""
    echo "解決策（一番ラクなのは uv）:"
    echo ""
    echo "  方法A: uv で Python 3.11 を自動 DL"
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "    # 新しいターミナルで:"
    echo "    cd $(pwd)"
    echo "    rm -rf .venv"
    echo "    uv venv --python 3.11"
    echo "    source .venv/bin/activate"
    echo "    uv pip install -e \".[dev]\""
    echo "    DEMO_MODE=1 FAQ_MASTER_DIR=./data/demo_company_faq SESSION_SECRET=demo \\"
    echo "      ORG_NAME=\"デモ会社株式会社\" ASSISTANT_ROLE=\"整備工場サポート\" \\"
    echo "      uvicorn app.main:app --host 127.0.0.1 --port 8000"
    echo ""
    echo "  方法B: brew install python@3.11 してから"
    echo "    rm -rf .venv && PYTHON=python3.11 ./scripts/demo_company.sh"
    echo ""
    echo "  方法C: Docker"
    echo "    docker compose up --build"
    exit 1
  fi
  echo "   Python ${PY_VER} ✓"
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
echo "🚗 デモ会社 社内ヘルプデスク 起動準備完了"
echo ""
echo "   組織名:    デモ会社株式会社"
echo "   役割:      整備工場サポート"
echo "   取り込み済み: data/demo_company_faq/ の 10 文書"
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
    echo "      HOST=0.0.0.0 ./scripts/demo_company.sh"
  fi
fi
echo ""
echo "   試してみる質問例:"
echo "     ・「車検の法定費用はいくら？」"
echo "     ・「部品発注の締め時間は？」"
echo "     ・「ロードサービスの夜間対応どうするの」"
echo "     ・「リフト作業の安全ルール」"
echo "     ・「デモ会社CarEditにログインできない時」"
echo ""
echo "   (Ctrl+C で停止)"
echo ""

# テナント分離: 監査ログ・フィードバックもデモ会社専用ディレクトリに
DEMO_MODE=1 \
  FAQ_MASTER_DIR=./data/demo_company_faq \
  SESSION_SECRET=demo_company-demo-secret \
  PRODUCT_NAME=Inquira \
  ORG_NAME="デモ会社株式会社" \
  ASSISTANT_ROLE="整備工場サポート" \
  uvicorn app.main:app --host "${HOST}" --port "${PORT}"
