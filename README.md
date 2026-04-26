# FAQ Platform

教育系A社様 社内FAQツール（PoC）。詳細は以下を参照。

- ロードマップ全体像： [`ROADMAP.md`](./ROADMAP.md)
- 教育系A社案件 要件定義（ドラフト）： [`docs/requirements_demo_education.md`](./docs/requirements_demo_education.md)

## 構成（PoC）

```
app/
  main.py        FastAPI + Google SSO + RAG エンドポイント
  auth.py        Google OAuth・許可ドメイン/メール判定
  rag.py         FAQマスター読み込み + TF-IDF 検索（本番では Embedding に差し替え）
  llm.py         Anthropic Claude 呼び出し
  masking.py     学校名・メール・電話番号の簡易マスキング
  audit.py       JSONL 形式の監査ログ
  config.py      環境変数読み込み
data/
  faq_master/    FAQ正本（Markdown / テキスト）
  raw/           元データ置き場（チケットCSV 等、Git 管理外）
scripts/
  classify_tickets.py  チケットCSV を Claude で自動分類するデモ
tests/           pytest
```

## セットアップ

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # 値を埋める
uvicorn app.main:app --reload
```

## テスト

```bash
pytest
```

## チケット分類デモ

```bash
python scripts/classify_tickets.py data/raw/DBチケット履歴.csv --out data/raw/classified.csv
```

詳細は `scripts/classify_tickets.py --help` を参照。

## セキュリティ要点

- **Anthropic 商用 API のみ使用**（個人プラン禁止 / 学習に使われない）
- API ログ保持 7日（標準）。必要なら ZDR 契約検討
- Google Workspace SSO + 許可ドメイン/メール
- 質問は送信前に `app/masking.py` でマスキング
- 全アクセスを `data/audit/audit-YYYY-MM-DD.jsonl` に記録
