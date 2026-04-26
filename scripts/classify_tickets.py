"""DBチケット履歴.csv を Claude で自動分類するデモスクリプト。

入力CSVのカラム名は揺れがちなので、ヘッダーを自動推測する。明示したい場合は
--question-col / --answer-col / --id-col で上書きできる。

使い方:
    python scripts/classify_tickets.py data/raw/DBチケット履歴.csv \
        --out data/raw/classified.csv \
        --limit 50 \
        --batch-size 5

API キー未設定でも --dry-run で構造とプロンプトの確認だけはできる。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

# 親ディレクトリを import path に追加（app.config の読み込み用）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


CLASSIFY_SYSTEM = """あなたは教育系A社 社内のヘルプデスクチケットを分類する分析者です。
各チケットを以下の軸で分類し、JSON 形式のみで返答してください。

出力スキーマ:
{
  "results": [
    {
      "id": "チケットID",
      "category_pkg": "PKG | カスタム | 不明",
      "function": "出願 | 出席 | 成績 | 教務 | 設定 | その他 | 不明",
      "type": "不具合 | 操作方法 | 設定変更 | 要望 | その他",
      "urgency": "高 | 中 | 低 | 不明",
      "faq_suitability": "高 | 中 | 低 | 不適格",
      "reason": "FAQ適格度をそう判断した理由（30字以内）",
      "cluster_hint": "類似質問グループの短いラベル（例: 出席登録の操作）"
    }
  ]
}

判断基準:
- faq_suitability=高: 同種の質問が繰り返されそうで、回答も汎化できる
- faq_suitability=中: 一定条件下では使える（補足必要）
- faq_suitability=低: 個別事例性が強い
- faq_suitability=不適格: 解決策が無い／個人特定情報のみ／FAQ化不能
"""

USER_TEMPLATE = """以下のチケット {n} 件を分類してください。JSON のみ返答すること。

{tickets}
"""


def guess_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in cols:
            return cols[c.lower()]
    for col in df.columns:
        for c in candidates:
            if c.lower() in col.lower():
                return col
    return None


def format_tickets(rows: list[dict]) -> str:
    parts = []
    for r in rows:
        parts.append(
            f"--- ID: {r['id']} ---\n"
            f"[問い合わせ]\n{r['question']}\n\n"
            f"[回答]\n{r['answer'] or '(未記載)'}"
        )
    return "\n\n".join(parts)


def call_claude(rows: list[dict], model: str) -> list[dict]:
    from anthropic import Anthropic

    client = Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=CLASSIFY_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": USER_TEMPLATE.format(n=len(rows), tickets=format_tickets(rows)),
            }
        ],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    # ```json ... ``` で囲まれていたら剥がす
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:].lstrip()
        text = text.rsplit("```", 1)[0].strip()
    data = json.loads(text)
    return data.get("results", [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="入力CSVパス")
    ap.add_argument("--out", type=Path, default=Path("classified.csv"), help="出力CSV")
    ap.add_argument("--id-col", help="チケットID列名（自動推測可）")
    ap.add_argument("--question-col", help="問い合わせ列名（自動推測可）")
    ap.add_argument("--answer-col", help="回答列名（自動推測可）")
    ap.add_argument("--limit", type=int, default=0, help="先頭 N 件のみ処理（0=全件）")
    ap.add_argument("--batch-size", type=int, default=5, help="1リクエストあたり件数")
    ap.add_argument("--model", default=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"))
    ap.add_argument("--encoding", default="utf-8", help="入力CSVのエンコーディング (cp932 等)")
    ap.add_argument("--dry-run", action="store_true", help="API 呼び出しせずプロンプトだけ表示")
    args = ap.parse_args()

    if not args.input.exists():
        ap.error(f"入力ファイルが存在しません: {args.input}")

    df = pd.read_csv(args.input, encoding=args.encoding)
    print(f"[info] 読み込み: {len(df)} 件 / 列: {list(df.columns)}", file=sys.stderr)

    id_col = args.id_col or guess_column(df, ["id", "チケットid", "ticket_id", "番号", "no"])
    q_col = args.question_col or guess_column(
        df, ["問い合わせ", "依頼内容", "question", "subject", "件名", "本文"]
    )
    a_col = args.answer_col or guess_column(
        df, ["回答", "対応内容", "answer", "解決方法", "解決策", "対応"]
    )
    if not q_col:
        ap.error("問い合わせ列を特定できません。--question-col で指定してください。")
    print(f"[info] 列マッピング: id={id_col} / question={q_col} / answer={a_col}", file=sys.stderr)

    rows: list[dict] = []
    for i, row in df.iterrows():
        if args.limit and i >= args.limit:
            break
        rows.append(
            {
                "id": str(row[id_col]) if id_col else f"row-{i+1}",
                "question": str(row[q_col]) if pd.notna(row[q_col]) else "",
                "answer": str(row[a_col]) if a_col and pd.notna(row[a_col]) else "",
            }
        )

    if args.dry_run:
        sample = rows[: args.batch_size]
        print("=== SYSTEM ===")
        print(CLASSIFY_SYSTEM)
        print("=== USER (sample) ===")
        print(USER_TEMPLATE.format(n=len(sample), tickets=format_tickets(sample)))
        return 0

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("[error] ANTHROPIC_API_KEY が未設定です（--dry-run で確認可能）", file=sys.stderr)
        return 1

    all_results: list[dict] = []
    for start in range(0, len(rows), args.batch_size):
        batch = rows[start : start + args.batch_size]
        try:
            results = call_claude(batch, args.model)
        except Exception as e:
            print(f"[warn] batch {start} 失敗: {e}", file=sys.stderr)
            time.sleep(2)
            continue
        all_results.extend(results)
        print(f"[info] {start + len(batch)} / {len(rows)} 件完了", file=sys.stderr)

    out_df = pd.DataFrame(all_results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"[done] {len(out_df)} 件を {args.out} に出力", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
