#!/usr/bin/env bash
# Inquira リストアスクリプト
#
# 使い方:
#   ./scripts/restore.sh ./backups/inquira-backup-YYYYMMDD-HHMMSS.tar.gz
#
# 注意:
#   - 既存の data/ や .env を **上書き** します
#   - 実行前に現状の状態をもう一度バックアップすることを推奨
#   - 復元後は ./scripts/demo_company.sh を再起動してください

set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -eq 0 ]; then
  echo "使い方: $0 <backup-file.tar.gz>"
  echo ""
  echo "利用可能なバックアップ:"
  ls -lh ./backups/inquira-backup-*.tar.gz 2>/dev/null || echo "  （./backups/ にバックアップなし）"
  exit 1
fi

ARCHIVE="$1"

if [ ! -f "$ARCHIVE" ]; then
  echo "❌ ファイルが見つかりません: $ARCHIVE"
  exit 1
fi

echo "🔄 Inquira リストア準備"
echo ""
echo "   復元元: $ARCHIVE"
echo "   復元先: $(pwd)"
echo ""
echo "   📋 アーカイブの内容:"
tar -tzf "$ARCHIVE" | sed 's/^/     /'
echo ""

# 既存ファイルの上書き確認
echo "⚠  以下が上書きされる可能性があります:"
echo "     • data/ 配下のFAQ・監査ログ・フィードバック学習データ"
echo "     • .env  （API キーが入れ替わります）"
echo ""
read -p "   復元を続行しますか？ (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
  echo "中止しました。"
  exit 0
fi

# 念のため現状をスナップショット（同名で実行された場合の保険）
SAFETY_DIR="./backups/_pre-restore-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$SAFETY_DIR"
echo ""
echo "🛟 復元前のスナップショットを保存中: $SAFETY_DIR"
for item in data .env; do
  if [ -e "$item" ]; then
    cp -R "$item" "$SAFETY_DIR/" 2>/dev/null || true
  fi
done

# 復元実行
echo "📥 復元中..."
tar -xzf "$ARCHIVE"

echo ""
echo "✅ 復元完了"
echo ""
echo "   復元前のスナップショット: $SAFETY_DIR"
echo "   （問題なければ削除可: rm -rf $SAFETY_DIR）"
echo ""
echo "📝 次のステップ:"
echo "   1. サーバが起動中なら Ctrl+C で停止"
echo "   2. ./scripts/demo_company.sh で再起動"
echo "   3. ブラウザで /admin/upload を開き、文書一覧と監査ログを確認"
