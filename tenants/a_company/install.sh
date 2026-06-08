#!/usr/bin/env bash
# A株式会社 オンプレサーバー向け Inquira インストールスクリプト
#
# 想定: Ubuntu 22.04+ / Debian 12+ / RHEL 9+ / Rocky 9 / AlmaLinux 9 等
#       systemd + Python 3.11 が利用可能であること
#
# 使い方 (root もしくは sudo 権限で):
#   sudo ./install.sh
#
# 事前に同階層の .env ファイルを編集して
#   ANTHROPIC_API_KEY / GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI
# を実値で埋めてください (提供側の機密。リポジトリに含めない値)。
set -euo pipefail

APP_DIR=/opt/inquira
SERVICE_USER=inquira
PYTHON_BIN=""
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "==> 0/7  事前チェック"
if [[ $EUID -ne 0 ]]; then
  echo "❌ root 権限が必要です (sudo ./install.sh で実行してください)"
  exit 1
fi

for cand in python3.11 python3.12 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver=$("$cand" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if [[ "$(printf '%s\n%s\n' "3.11" "$ver" | sort -V | head -1)" == "3.11" ]]; then
      PYTHON_BIN="$(command -v "$cand")"
      break
    fi
  fi
done
if [[ -z "$PYTHON_BIN" ]]; then
  echo "❌ Python 3.11 以上が見つかりません。先に Python 3.11+ をインストールしてください。"
  echo "    Ubuntu/Debian:  sudo apt install python3.11 python3.11-venv"
  echo "    RHEL/Rocky:     sudo dnf install python3.11"
  exit 1
fi
echo "    Python: $PYTHON_BIN ($("$PYTHON_BIN" --version))"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "❌ systemd が必要です (このスクリプトは systemd デーモン化を前提)"
  exit 1
fi

if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo "❌ $SCRIPT_DIR/.env が見つかりません。.env.template をコピーして実値を埋めてください。"
  exit 1
fi
if grep -q "__FILL_FROM_PROVIDER_SECRETS__" "$SCRIPT_DIR/.env"; then
  echo "❌ .env に未設定の項目があります (__FILL_FROM_PROVIDER_SECRETS__)。"
  echo "    ANTHROPIC_API_KEY / GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET を埋めてから再実行してください。"
  exit 1
fi

echo "==> 1/7  サービスユーザー作成"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --shell /usr/sbin/nologin --home-dir "$APP_DIR" --no-create-home "$SERVICE_USER"
  echo "    $SERVICE_USER ユーザーを作成"
else
  echo "    $SERVICE_USER は既に存在 (スキップ)"
fi

echo "==> 2/7  アプリ配置 ($APP_DIR)"
mkdir -p "$APP_DIR"
# プロジェクトソースをコピー (tenants/ と docs/ は除外してサイズ削減)
rsync -a --delete \
  --exclude '.git' --exclude '__pycache__' --exclude '.venv' \
  --exclude 'tenants' --exclude 'docs' --exclude 'data' \
  "$PROJECT_DIR/" "$APP_DIR/"
mkdir -p "$APP_DIR/data"

echo "==> 3/7  Python venv 作成 + 依存インストール"
sudo -u "$SERVICE_USER" "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet -e "$APP_DIR"

echo "==> 4/7  .env 配置 (SESSION_SECRET をランダム生成 + パス置換)"
SESSION_SECRET="$(openssl rand -hex 32)"
sed -e "s|__GENERATED_BY_INSTALL_SH__|$SESSION_SECRET|" \
    -e "s|__APP_DIR__|$APP_DIR|g" \
    "$SCRIPT_DIR/.env" > "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"
chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"

echo "==> 5/7  所有権の調整"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

echo "==> 6/7  systemd unit 配置"
cp "$SCRIPT_DIR/inquira.service" /etc/systemd/system/inquira.service
systemctl daemon-reload
systemctl enable inquira.service
systemctl restart inquira.service

echo "==> 7/7  起動確認"
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
    echo ""
    echo "✅ Inquira 起動完了"
    echo ""
    echo "管理画面: https://faq.a-corp.jp/admin/upload"
    echo "一般画面: https://faq.a-corp.jp/"
    echo ""
    echo "ログ:    journalctl -u inquira -f"
    echo "再起動:  systemctl restart inquira"
    echo "停止:    systemctl stop inquira"
    exit 0
  fi
  sleep 2
done
echo "⚠ 10秒待っても healthcheck が通りませんでした。ログを確認してください:"
echo "    journalctl -u inquira -n 50"
exit 1
