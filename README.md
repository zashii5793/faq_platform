# Inquira — 社内問い合わせを"自己解決"に変えるFAQプラットフォーム

[![Test](https://github.com/zashii5793/faq_platform/actions/workflows/test.yml/badge.svg)](https://github.com/zashii5793/faq_platform/actions/workflows/test.yml)

> どの企業にもある「**同じ質問が何度も来る**」「**ナレッジが個人と紙とチケットに散在する**」問題を、
> 既存ドキュメントを根拠に Claude が回答するセルフサービス FAQ で解決します。

---

## 🚀 自分で動かす（Mac 向け 3 通り）

### 方法A: uv ★最速・推奨

[uv](https://docs.astral.sh/uv/) は Rust 製の Python パッケージマネージャ。pyenv のビルドより **10倍速い**。

```bash
brew install uv
git clone https://github.com/zashii5793/faq_platform.git
cd faq_platform
git checkout claude/add-roadmap-docs-RmQNp

uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"

DEMO_MODE=1 FAQ_MASTER_DIR=./data/demo_faq SESSION_SECRET=demo \
  uvicorn app.main:app --host 127.0.0.1 --port 8000
```

→ ブラウザで http://127.0.0.1:8000/

### 方法B: Docker ★ゼロ設定

Python のバージョン違いやビルド失敗を**完全に避けたい**ならこれ。

```bash
git clone https://github.com/zashii5793/faq_platform.git
cd faq_platform
git checkout claude/add-roadmap-docs-RmQNp

docker compose up --build
```

初回ビルド 2〜4分（Python イメージ DL + 依存インストール）。
2回目以降はキャッシュが効いて 10秒以内で起動。

→ ブラウザで http://127.0.0.1:8000/

停止: `docker compose down`

### 方法C: 既存 Python 3.11+ がある場合

`python3 --version` で 3.11 以上なら、最も軽量に動く。

```bash
git clone https://github.com/zashii5793/faq_platform.git
cd faq_platform
git checkout claude/add-roadmap-docs-RmQNp
./scripts/demo.sh
```

スクリプトが venv 作成・依存インストール・テスト実行・サーバ起動まで自動でやります。

---

## 📱 携帯で試す（同じ WiFi 内から）

**Mac で起動 → iPhone から触る** の手順：

```bash
# Mac 側でサーバを LAN 公開モードで起動
HOST=0.0.0.0 ./scripts/demo.sh
```

起動メッセージに **LAN IP** が自動表示されます：

```
🚀 Inquira を起動します
   ┌──────────────────────────────────────────────────────────┐
   │ 💻 PC ブラウザ:   http://127.0.0.1:8000/                      │
   │ 📱 携帯/タブレット: http://192.168.1.42:8000/  ← 同じWiFi内から  │
   │ 📁 ナレッジ追加:   http://192.168.1.42:8000/admin/upload         │
   └──────────────────────────────────────────────────────────┘
```

**iPhone で**：
1. Mac と同じ WiFi に接続されていることを確認
2. Safari で表示された LAN IP を開く（例: `http://192.168.1.42:8000/`）
3. サイドバーは左上の **☰ ボタン** で開閉

> ⚠ DEMO_MODE は認証なしで動きます。**社内 WiFi など信頼できるネットワークでのみ使用** してください。
> 自宅の WiFi でも他端末からは見えますが、ゲストネットワーク等は注意。

### モバイル UI のポイント

| 機能 | モバイル時の挙動 |
|---|---|
| サイドバー | ☰ で開く・スクリーン外タップで閉じる |
| チャットバブル | 幅 90% に拡張 |
| 入力欄 | iOS 自動ズーム防止（`font-size: 16px`） |
| アップロード画面 | 1カラム表示・フッターボタン全幅 |

---

---

## 🔬 検索精度を上げる（Embedding 切替・任意）

デフォルトは TF-IDF（モデルDL不要・軽量）ですが、精度を上げたい場合は **multilingual-e5** に切替可能：

```bash
# 1. embedding 用の依存をインストール
pip install -e ".[embedding]"

# 2. 環境変数で指定して起動（小: 470MB / 大: 2.2GB）
EMBEDDING_BACKEND=e5-small ./scripts/demo_takaya.sh
# または
EMBEDDING_BACKEND=e5-large ./scripts/demo_takaya.sh
```

| バックエンド | モデルサイズ | 精度 | 起動時間 | メモリ |
|---|---|---|---|---|
| `tfidf` (デフォルト) | 0 | 中 (74%) | 即時 | 軽量 |
| `e5-small` | 470MB | 高 | 初回30秒 | 1〜2GB |
| `e5-large` | 2.2GB | 最高 | 初回2〜5分 | 4〜6GB |

> 初回起動時のみ HuggingFace からモデルがダウンロードされます（以降キャッシュ）。
> ベクトル化結果は `data/embeddings.npz` に保存され、文書追加時のみ再計算されます。

---

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `port 8000` 使用中 | `PORT=8080 ./scripts/demo.sh` のように変えて起動 |
| 古い venv で起動失敗 | `rm -rf .venv && ./scripts/demo.sh` |
| pyenv のビルドが終わらない | 案A (uv) または案B (Docker) を使う |
| Docker が無い | `brew install --cask docker` で Docker Desktop を入れる |

---

## なぜ作るか

- 社内ヘルプデスク／情報システム部門の問い合わせ工数の **40〜60%** は同種反復質問
- 既存のチャットボット製品はテンプレ運用で構築コストが高い
- LLM × RAG なら **既存ドキュメントを学習なしで回答ソース化** でき、保守も軽い
- 学習に使われない商用 API + 社内ホストで **データ主権を維持** できる

## 主要機能（PoC）

| 機能 | 内容 |
|---|---|
| 自然言語 Q&A | 社員が自由記述で質問 → Claude が関連チャンクを参照して回答 |
| 出典必須 | 回答には必ず「どのドキュメントを参照したか」を明示 |
| Google SSO | 許可ドメイン／メールリストで社内アクセスを制限 |
| マスキング | 業界別 PII パターンで送信前にトークン化（汎用 + 教育/医療/金融プリセット） |
| 監査ログ | 全クエリを JSONL で記録 |
| デモモード | 認証・APIキー無しでローカル動作確認可能 |

## 構成

```
app/
  main.py        FastAPI + Google SSO + RAG エンドポイント
  auth.py        Google OAuth・許可ドメイン/メール判定
  rag.py         FAQマスター読み込み + TF-IDF 検索
  llm.py         Anthropic Claude 呼び出し（システムプロンプトは設定駆動）
  masking.py     汎用PII + 業界別パターンによるマスキング
  audit.py       JSONL 形式の監査ログ
  config.py      環境変数読み込み
data/
  faq_master/    FAQ正本（顧客ごとの実データ。Git 管理外）
  demo_faq/      デモ用サンプル（教育系想定）
  raw/           元データ置き場（チケットCSV 等、Git 管理外）
scripts/
  classify_tickets.py  チケットCSV を Claude で自動分類するデモ
docs/
  specification.md           技術仕様書
  requirements_demo_education.md 教育系A社様向け導入事例（要件）
  business_analysis.md       ビジネス用途分析
tests/                      pytest
```

## 🎬 30秒で見る（ブラウザだけで動く）

サーバ・APIキー・依存インストール **すべて不要**。ブラウザで開くだけ：

```
docs/demo.html
```

クライアントサイドで FAQ 検索・スコアリング・マスキングをシミュレートします。
業界プリセット切替（汎用 / 教育 / 金融 / 医療）も動作確認可能。

スクリーンショット：
- [`docs/demo_interactive_initial.png`](./docs/demo_interactive_initial.png) — 初期画面
- [`docs/demo_interactive_session.png`](./docs/demo_interactive_session.png) — 4問やり取り＋マスキング適用

## クイックスタート（デモ）

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 認証バイパスのデモモードで起動
DEMO_MODE=1 FAQ_MASTER_DIR=./data/demo_faq SESSION_SECRET=demo \
  uvicorn app.main:app --host 127.0.0.1 --port 8000

# 別ターミナル:
curl -s -X POST http://127.0.0.1:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"出席の保存ボタンが効かない"}' | python -m json.tool
```

## 本番セットアップ

1. `cp .env.example .env` で環境変数を設定
2. `ORG_NAME` / `ASSISTANT_ROLE` で導入企業に合わせたペルソナを定義
3. `MASKING_INDUSTRY` で業界別マスキング (`general` / `education` / `healthcare` / `finance`)
4. `data/faq_master/` に正本ドキュメントを配置（`.md` / `.txt`）
5. `uvicorn app.main:app --host 0.0.0.0 --port 8000`

## テスト

```bash
pytest
```

## ロードマップ・関連文書

- [ROADMAP.md](./ROADMAP.md) — 全体ロードマップ（Phase 1〜3）
- **[docs/setup_guide_mac.md](./docs/setup_guide_mac.md) — Mac セットアップ詳細手順（初心者向け）**
- **[docs/api_key_setup.md](./docs/api_key_setup.md) — Anthropic API キーの取得・確認・テスト**
- **[docs/product_assessment.md](./docs/product_assessment.md) — プロダクト評価（使えるか？の正直な答え）**
- [docs/architecture_report.md](./docs/architecture_report.md) — アーキテクチャ解説（非エンジニア向け）
- [docs/specification.md](./docs/specification.md) — 技術仕様書
- [docs/ui_specification.md](./docs/ui_specification.md) — UI設計仕様
- [docs/business_analysis.md](./docs/business_analysis.md) — ビジネス用途分析
- [docs/requirements_demo_education.md](./docs/requirements_demo_education.md) — 教育系A社様 導入事例

## セキュリティ要点

- **Anthropic 商用 API のみ使用**（個人プラン禁止 / 学習に使われない）
- API ログ保持 7日（標準）。必要なら ZDR 契約検討
- Google Workspace SSO + 許可ドメイン/メール
- 質問は送信前に `app/masking.py` でマスキング
- 全アクセスを `data/audit/audit-YYYY-MM-DD.jsonl` に記録
