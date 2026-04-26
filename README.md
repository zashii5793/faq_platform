# Inquira — 社内問い合わせを"自己解決"に変えるFAQプラットフォーム

> どの企業にもある「**同じ質問が何度も来る**」「**ナレッジが個人と紙とチケットに散在する**」問題を、
> 既存ドキュメントを根拠に Claude が回答するセルフサービス FAQ で解決します。

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
- [docs/specification.md](./docs/specification.md) — 技術仕様書
- [docs/business_analysis.md](./docs/business_analysis.md) — ビジネス用途分析
- [docs/requirements_demo_education.md](./docs/requirements_demo_education.md) — 教育系A社様 導入事例

## セキュリティ要点

- **Anthropic 商用 API のみ使用**（個人プラン禁止 / 学習に使われない）
- API ログ保持 7日（標準）。必要なら ZDR 契約検討
- Google Workspace SSO + 許可ドメイン/メール
- 質問は送信前に `app/masking.py` でマスキング
- 全アクセスを `data/audit/audit-YYYY-MM-DD.jsonl` に記録
