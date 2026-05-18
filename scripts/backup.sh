#!/usr/bin/env bash
# Inquira バックアップスクリプト
#
# 使い方:
#   ./scripts/backup.sh                       # ./backups/ に tar.gz 作成
#   ./scripts/backup.sh /path/to/backup-dir   # 任意の出力先
#
# 取得対象:
#   - data/faq_master/  または DATA_DIR で指定したディレクトリ
#   - data/audit/       監査ログ
#   - data/feedback_scores.json  フィードバック学習データ
#   - .env              （API キーは含まれるため取り扱い注意）
#
# 復元方法:
#   ./scripts/restore.sh ./backups/inquira-backup-YYYYMMDD-HHMMSS.tar.gz

set -euo pipefail
cd "$(dirname "$0")/.."

OUT_DIR="${1:-./backups}"
mkdir -p "$OUT_DIR"

TS=$(date +%Y%m%d-%H%M%S)
ARCHIVE="$OUT_DIR/inquira-backup-$TS.tar.gz"

# バックアップ対象（存在するものだけ）
ITEMS=()
[ -d "data/faq_master" ] && ITEMS+=("data/faq_master")
[ -d "data/demo_company_faq" ] && ITEMS+=("data/demo_company_faq")
[ -d "data/demo_faq" ] && ITEMS+=("data/demo_faq")
[ -d "data/audit" ] && ITEMS+=("data/audit")
[ -f "data/feedback_scores.json" ] && ITEMS+=("data/feedback_scores.json")
[ -f ".env" ] && ITEMS+=(".env")

if [ ${#ITEMS[@]} -eq 0 ]; then
  echo "❌ バックアップ対象が見つかりません（data/ ディレクトリが空）"
  exit 1
fi

echo "🗄  Inquira バックアップ開始..."
echo ""
echo "   対象:"
for item in "${ITEMS[@]}"; do
  size=$(du -sh "$item" 2>/dev/null | cut -f1)
  echo "     • $item  ($size)"
done
echo ""

# tar.gz 作成
tar -czf "$ARCHIVE" "${ITEMS[@]}"

ARCHIVE_SIZE=$(du -h "$ARCHIVE" | cut -f1)
echo "✅ 完了"
echo ""
echo "   出力: $ARCHIVE"
echo "   サイズ: $ARCHIVE_SIZE"
echo ""

# .env が含まれる場合は注意喚起
if [[ " ${ITEMS[*]} " =~ " .env " ]]; then
  echo "⚠  .env が含まれています。ANTHROPIC_API_KEY など機密情報があるため、"
  echo "   バックアップファイルの保管・共有には十分ご注意ください。"
  echo ""
fi

# 古いバックアップの整理ガイド
NUM_BACKUPS=$(find "$OUT_DIR" -name 'inquira-backup-*.tar.gz' 2>/dev/null | wc -l | tr -d ' ')
if [ "$NUM_BACKUPS" -gt 10 ]; then
  echo "💡 バックアップが $NUM_BACKUPS 個あります。古いものを整理推奨:"
  echo "   find $OUT_DIR -name 'inquira-backup-*.tar.gz' -mtime +30 -delete"
fi

echo ""
echo "📋 復元するには:"
echo "   ./scripts/restore.sh $ARCHIVE"
