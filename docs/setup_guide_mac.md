# Mac で動かす：詰まらない設定手順

> 想定読者: Mac でターミナル操作の経験はあるが、Python の細かい仕様は分からない方
> 所要時間: 5〜10分（初回）

---

## ステップ0：自分のMac で何が必要か確認

ターミナル（`Terminal.app` または `iTerm`）を開いて、以下を順番に実行：

```bash
# 1) Python 3.11 以上があるか
python3 --version
```

| 結果 | 次にやること |
|---|---|
| `Python 3.11.x` 以上 | → ステップ1へ進む（**方法A**を推奨） |
| `Python 3.10` 以下 / コマンドが無い | → **方法B（Docker）** が一番ラク |

```bash
# 2) git があるか
git --version
```

無ければ Xcode Command Line Tools が必要：
```bash
xcode-select --install
```
（10分くらいかかります）

---

## ステップ1：リポジトリを取得

```bash
cd ~/Documents          # 好きな場所でOK
git clone https://github.com/zashii5793/faq_platform.git
cd faq_platform
git checkout claude/add-roadmap-docs-RmQNp
```

> ⚠ `main` ブランチではなく `claude/add-roadmap-docs-RmQNp` です。
> （まだ main にマージしていないため）

---

## ステップ2：起動方法を選ぶ

下のどれか **1つ** を選んで実行してください。

### 方法A：Python 3.11+ がある場合（一番速い）

```bash
./scripts/demo.sh
```

これだけ。スクリプトが自動で：
1. Python 仮想環境（`.venv`）を作る
2. 必要なパッケージをインストール（fastapi, anthropic, openpyxl 等）
3. **41件の自動テストを実行**（失敗したら起動しない）
4. サーバを起動

成功すると以下が表示されます：
```
🧪 統合テストを実行中…
.........................................                                [100%]
41 passed, 1 warning in 4s

✅ テスト全 PASS

🚀 Inquira を起動します
   ┌──────────────────────────────────────────────────┐
   │ チャット画面: http://127.0.0.1:8000/                  │
   │ ナレッジ追加: http://127.0.0.1:8000/admin/upload      │
   └──────────────────────────────────────────────────┘
```

ブラウザで **http://127.0.0.1:8000/** を開けば触れます。

---

### 方法B：Docker を使う（環境を完全に隔離）

Python のバージョン違いで詰まるのが嫌なら **これが一番確実**。

#### 前提：Docker Desktop がインストールされていること
```bash
docker --version    # 確認
```
無ければ：
```bash
brew install --cask docker
# その後 Docker Desktop を起動（メニューバーにクジラのアイコンが出る）
```

#### 起動：1コマンド
```bash
docker compose up --build
```

初回ビルドで 2〜4分（Python イメージのダウンロード + 依存インストール）。
2回目以降はキャッシュされて10秒ほど。

ブラウザで **http://127.0.0.1:8000/** を開く。

#### 停止
別のターミナルで：
```bash
docker compose down
```
または起動中のターミナルで `Ctrl+C` → `docker compose down`。

---

### 方法C：uv を使う（最速・Python に詳しい人向け）

[uv](https://docs.astral.sh/uv/) は Rust 製で pyenv より約10倍速い。

```bash
brew install uv
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
DEMO_MODE=1 FAQ_MASTER_DIR=./data/demo_faq SESSION_SECRET=demo \
  uvicorn app.main:app --host 127.0.0.1 --port 8000
```

---

## ステップ3：携帯から触りたい場合

```bash
# 普通の demo.sh を Ctrl+C で止めてから
HOST=0.0.0.0 ./scripts/demo.sh
```

スクリプトが Mac の LAN IP を自動検出して表示します：
```
📱 携帯/タブレット: http://192.168.1.42:8000/  ← 同じWiFi内から
```

iPhone を Mac と **同じ WiFi** に繋いで、Safari でこの URL を開く。

> ⚠ DEMO_MODE は認証なしで LAN 全体に公開されます。
> 社内 WiFi など信頼できるネットワーク内でのみ使用してください。

---

## ステップ4：どんな機能が動くか確認

ブラウザで http://127.0.0.1:8000/ を開いた状態で：

### A. 質問してみる
1. 下部の入力欄に「VPN繋がらない時の対処法」と入力 → 送信
2. 確信度バッジ（緑=高 / 黄=中 / 赤=該当なし）を確認
3. 「📎 参照ドキュメント」を展開して出典を確認
4. 👍 / 👎 ボタンを押すとサイドバーのフィードバック数が更新

### B. 関係ない質問でハルシネーション抑制を確認
1. 「宇宙ロケットの打ち上げ手順」と入力 → 送信
2. **「該当情報が見つかりませんでした」** が返ってくる
3. これは AI を呼ばずに止めている（ハルシネーション抑制）

### C. ファイルを取り込む
1. 左サイドバー → **「📁 ファイルを追加」** をクリック
2. `/admin/upload` 画面に遷移
3. 適当な PDF / Excel / Markdown ファイルをドラッグ&ドロップ
4. 解析結果カード（🟢 取り込み可 / 🟡 確認必要 / 🔴 取り込み非推奨）が出る
5. 下部の **「選択を確定して取り込む(N件)」** ボタンで一括取り込み
6. 戻ってからその文書について質問できる

### D. 機密データの拒否を確認
1. マイナンバー（13桁）を含む CSV を作って投入
2. 🔴 「取り込み非推奨」と判定され、取り込みボタンが無効化される

---

## トラブルシューティング

### 「`port 8000` is already in use」エラー
別ポートで起動：
```bash
PORT=8080 ./scripts/demo.sh
```

### 「`No module named ...`」エラー
古い `.venv` が残っている可能性。完全リセット：
```bash
rm -rf .venv
./scripts/demo.sh
```

### Docker でビルドが終わらない / 失敗する
Docker Desktop の **Resources** で割り当てメモリを 4GB 以上に。
それでもダメなら方法A（uv なし）を試す。

### `pyenv install 3.11` が終わらない
**pyenv は使わなくて大丈夫です。** 代わりに：
- Mac の標準 Python が 3.11+ ならそのまま方法A
- 古い場合は方法B（Docker）か方法C（uv）

---

## 本番運用へ進む場合の追加設定

デモモードではなく本番設定にする場合は `.env` ファイルを作成：

```bash
cp .env.example .env
# 以下を編集
```

```env
# Anthropic API（学習に使われない商用契約）
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxx

# Google OAuth（社内アカウントログイン）
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxxx
GOOGLE_REDIRECT_URI=https://your-domain.com/auth/callback
ALLOWED_DOMAIN=your-company.co.jp

# セッション暗号化キー（適当な長い文字列）
SESSION_SECRET=$(openssl rand -hex 32)

# 業界マスキング（学校名等を追加で除去）
MASKING_INDUSTRY=education

# DEMO_MODE は本番では必ず false（または環境変数自体を削除）
DEMO_MODE=false
```

その後：
```bash
# 普通の uvicorn 起動（DEMO_MODE 環境変数を渡さない）
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## さいごに：何かおかしい時のチェックリスト

```bash
# 1) ブランチ確認
git branch --show-current
# → claude/add-roadmap-docs-RmQNp になっているか

# 2) 最新を取得
git pull origin claude/add-roadmap-docs-RmQNp

# 3) クリーンスタート
rm -rf .venv data/audit data/index.json data/feedback_scores.json
./scripts/demo.sh
```

3 で直らない場合は **エラーメッセージ全文** をコピーして相談してください。
