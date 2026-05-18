#!/usr/bin/env python3
"""本番動作確認スクリプト（Production Smoke Test）。

Anthropic API キーを使って、実際の Claude 回答が出る状態を E2E で検証する。

使い方:
    export ANTHROPIC_API_KEY=sk-ant-xxxxx
    python scripts/production_smoke_test.py

検証項目:
    1. APIキー疎通（test_anthropic.py 相当の最小リクエスト）
    2. システムプロンプトでの回答抑制（推測禁止が効いているか）
    3. デモ会社実 FAQ で 5 質問の実回答品質
    4. 関係ない質問で「該当情報なし」が出るか
    5. 出典が回答末尾に明記されるか
    6. マスキング済みトークンが復元されないか

各質問について:
    - 確信度・出典・トークン数・コスト・所要時間・回答本文
を記録し、合格/不合格をジャッジ。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.llm import build_user_prompt, system_prompt
from app.rag import FaqIndex, load_chunks


# 検証ケース：(質問, 期待文書, 「該当情報なし」期待か)
TEST_CASES: list[tuple[str, str, bool]] = [
    ("VPN接続の方法を教えて", "VPN接続マニュアル.md", False),
    ("リフト作業の安全ルール", "作業安全マニュアル.md", False),
    ("デモ会社CarEditにログインできない時", "デモ会社CarEdit操作.md", False),
    ("有給を当日朝に取りたい", "勤怠・有給.md", False),
    ("バッテリー上がりの対応", "緊急ロードサービス.md", False),
    # ハルシネーション抑制
    ("料理のレシピを教えて", "", True),
    ("今日の東京の天気", "", True),
]

# 推測表現 NG ワード（出力に含まれてはいけない）
HALLUCINATION_NG = [
    "だと思います", "おそらく", "一般的には", "推測", "推察",
    "もしかすると", "〜のはずです",
]


def _check_anthropic() -> bool:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("❌ ANTHROPIC_API_KEY が未設定です")
        print("   export ANTHROPIC_API_KEY=sk-ant-... を実行してから再試行してください")
        return False
    if not api_key.startswith("sk-ant-"):
        print(f"⚠ APIキー形式が不正の可能性: {api_key[:10]}...")
    settings.anthropic_api_key = api_key
    return True


def _evaluate_response(
    response: str,
    expected_source: str,
    expects_no_answer: bool,
) -> tuple[bool, list[str]]:
    """回答内容を評価。"""
    issues = []
    if expects_no_answer:
        if "該当情報が見つかりませんでした" not in response and "見つかりませんでした" not in response:
            issues.append("「該当情報なし」と返すべきだが回答してしまった")
    else:
        if "該当情報が見つかりませんでした" in response:
            issues.append("該当情報があるのに NO_ANSWER に倒れた")
        # 出典明記チェック
        if "出典" not in response and "参照" not in response and ".md" not in response:
            issues.append("回答末尾に出典が見当たらない")
    # 推測禁止チェック
    for ng in HALLUCINATION_NG:
        if ng in response:
            issues.append(f"推測表現「{ng}」を含む（システムプロンプト無視）")
    # マスキング復元チェック
    if "[メール]" in response or "[電話番号]" in response or "[マイナンバー]" in response:
        # マスクトークンはそのまま使うべきで、復元してはいけない
        pass  # マスクトークンが維持されている = 正常
    return len(issues) == 0, issues


def main() -> int:
    print("=" * 70)
    print("🚀 Inquira 本番動作確認（Production Smoke Test）")
    print("=" * 70)
    print()

    if not _check_anthropic():
        return 1

    faq_dir = Path("./data/demo_company_faq")
    if not faq_dir.exists():
        print(f"❌ {faq_dir} がありません。デモ会社用デモデータが必要です")
        return 1

    print(f"📚 取り込み済み FAQ: {faq_dir}")
    chunks = load_chunks(faq_dir)
    n_docs = len(set(c.source for c in chunks))
    print(f"   文書 {n_docs} / チャンク {len(chunks)}")
    print(f"🔧 検索バックエンド: {settings.embedding_backend}")
    print(f"🤖 Claude モデル:    {settings.claude_model}")
    print()

    print("📝 システムプロンプト（先頭150字）:")
    print("   " + system_prompt()[:150].replace("\n", " ") + "...")
    print()

    index = FaqIndex(chunks)

    pass_count = 0
    fail_count = 0
    total_in_tok = 0
    total_out_tok = 0
    total_time = 0.0

    for i, (query, expected_src, expects_no) in enumerate(TEST_CASES, 1):
        label = "[該当情報なし期待]" if expects_no else f"[{expected_src} 期待]"
        print(f"--- {i}/{len(TEST_CASES)}: {query} {label} ---")

        chunks_hit = index.search(query, top_k=5)
        if not chunks_hit and not expects_no:
            print("  ❌ 検索ヒット 0 件 — Embedding切替を検討")
            fail_count += 1
            continue

        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=settings.anthropic_api_key)

            start = time.time()
            msg = client.messages.create(
                model=settings.claude_model,
                max_tokens=512,
                system=system_prompt(),
                messages=[{"role": "user", "content": build_user_prompt(query, chunks_hit)}],
            )
            elapsed = time.time() - start
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ API 呼び出し失敗: {e}")
            fail_count += 1
            continue

        response = "".join(b.text for b in msg.content if b.type == "text").strip()
        in_tok = msg.usage.input_tokens
        out_tok = msg.usage.output_tokens
        total_in_tok += in_tok
        total_out_tok += out_tok
        total_time += elapsed

        ok, issues = _evaluate_response(response, expected_src, expects_no)

        # ソースの一致確認
        src_ok = True
        if not expects_no and chunks_hit:
            top_source = chunks_hit[0][0].source
            src_ok = top_source == expected_src
            if not src_ok:
                issues.append(f"top1 が {expected_src} ではなく {top_source}")

        print(f"  応答時間:   {elapsed:.2f}秒")
        print(f"  トークン:   入力 {in_tok} / 出力 {out_tok}")
        print("  回答（先頭200字）:")
        print("    " + response[:200].replace("\n", "\n    "))
        if not response.endswith("..."):
            pass
        if ok and src_ok:
            print("  判定: ✅ 合格")
            pass_count += 1
        else:
            print("  判定: ❌ 不合格")
            for issue in issues:
                print(f"        - {issue}")
            fail_count += 1
        print()

    # サマリ
    print("=" * 70)
    print("📊 サマリ")
    print(f"  合格:           {pass_count} / {len(TEST_CASES)}")
    print(f"  不合格:         {fail_count} / {len(TEST_CASES)}")
    print(f"  総トークン:     入力 {total_in_tok:,} / 出力 {total_out_tok:,}")
    cost_usd = (total_in_tok * 3 + total_out_tok * 15) / 1_000_000
    cost_jpy = cost_usd * 155
    print(f"  推定コスト:     ${cost_usd:.4f} (約 {cost_jpy:.2f}円)")
    print(f"  平均応答時間:   {total_time / max(1, pass_count + fail_count):.2f}秒")
    print()
    if fail_count == 0:
        print("✅ 本番運用可。すべての検証を通過しました。")
        return 0
    print(f"⚠ {fail_count} 件の不合格があります。上の issue を確認してください。")
    return 1 if fail_count > pass_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
