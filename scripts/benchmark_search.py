#!/usr/bin/env python3
"""タカヤモーター実データで検索精度をベンチマーク。

各質問について：
  - 正解とされる文書（expected）が top1 に来ているか
  - top1 のスコア
  - has_answer 判定（NO ANSWER で止まっていないか）
を測定し、サマリを出力する。

使い方:
    python scripts/benchmark_search.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.rag import FaqIndex, load_chunks


# 想定質問と正解の文書（期待される top1）
TEST_CASES: list[tuple[str, str]] = [
    ("車検の必須交換項目チェックリスト", "車検手順.md"),
    ("車検の法定費用はいくら", "車検手順.md"),
    ("自賠責保険料", "車検手順.md"),
    ("車検の流れ", "車検手順.md"),
    ("リフト作業の安全ルール", "作業安全マニュアル.md"),
    ("火災発生時の対応", "作業安全マニュアル.md"),
    ("引火物の保管場所", "作業安全マニュアル.md"),
    ("有給を当日朝に取りたい", "勤怠・有給.md"),
    ("勤怠の打刻方法", "勤怠・有給.md"),
    ("計画年休とは", "勤怠・有給.md"),
    ("ロードサービスの夜間対応", "緊急ロードサービス.md"),
    ("バッテリー上がりの対応", "緊急ロードサービス.md"),
    ("クレーム対応の流れ", "顧客対応マニュアル.md"),
    ("電話応対の名乗り方", "顧客対応マニュアル.md"),
    ("部品発注の締め時間", "部品発注ルール.md"),
    ("廃番品の処分方法", "部品発注ルール.md"),
    ("整備保証の期間", "保証規定.md"),
    ("保証適用外のケース", "保証規定.md"),
    ("整備受付の流れ", "整備受付マニュアル.md"),
    ("代車利用時に必要な書類", "整備受付マニュアル.md"),
    ("タカヤCarEditにログインできない", "タカヤCarEdit操作.md"),
    ("二要素認証アプリを再インストール", "タカヤCarEdit操作.md"),
    ("トルクレンチの校正", "工具管理ルール.md"),
    ("工具を紛失した時", "工具管理ルール.md"),
    # ハルシネーション抑制用（NO ANSWER期待）
    ("今日の東京の天気", "__no_answer__"),
    ("野球の試合結果", "__no_answer__"),
    ("料理のレシピを教えて", "__no_answer__"),
]

NO_ANSWER_THRESHOLD = settings.min_score_threshold


def _compute_confidence(scored):
    """main.py の _compute_confidence と同期。"""
    if not scored:
        return 0
    top = scored[0][1]
    if top < NO_ANSWER_THRESHOLD:
        return 0
    if top < 0.12 and len(scored) >= 2:
        second = scored[1][1]
        if second / top < 0.3:
            return 0
    base = min(95, int(30 + top * 250))
    relevant = sum(1 for _, s in scored if s >= NO_ANSWER_THRESHOLD)
    return min(98, base + max(0, relevant - 1) * 3)


def main() -> int:
    faq_dir = Path("./data/takaya_faq")
    if not faq_dir.exists():
        print(f"❌ {faq_dir} がありません")
        return 1

    chunks = load_chunks(faq_dir)
    print(f"📚 取り込み済み: {len(set(c.source for c in chunks))} 文書 / {len(chunks)} チャンク")
    print(f"🔧 検索バックエンド: {settings.embedding_backend}")
    if settings.embedding_backend in ("e5-small", "e5-base", "e5-large"):
        print("   （初回は HuggingFace からモデル DL されます）")
    print()
    index = FaqIndex(chunks)

    headers = ("質問", "期待文書", "top1文書", "score", "確信度", "判定")
    rows = []
    correct = 0
    no_answer_correct = 0
    no_answer_total = 0
    answer_total = 0
    answered = 0

    for query, expected in TEST_CASES:
        results = index.search(query, top_k=5)
        confidence = _compute_confidence(results)
        if expected == "__no_answer__":
            no_answer_total += 1
            ok = confidence == 0
            if ok:
                no_answer_correct += 1
            top_doc = results[0][0].source if results else "-"
            top_score = results[0][1] if results else 0.0
            rows.append((query, "(NO ANSWER)", top_doc, f"{top_score:.3f}", f"{confidence}%",
                         "✅" if ok else "❌"))
        else:
            answer_total += 1
            if confidence > 0:
                answered += 1
            if results and confidence > 0 and results[0][0].source == expected:
                correct += 1
                ok = "✅"
            elif confidence == 0:
                ok = "🟡 NO_ANS"
            else:
                ok = "❌"
            top_doc = results[0][0].source if results else "-"
            top_score = results[0][1] if results else 0.0
            rows.append((query, expected, top_doc, f"{top_score:.3f}", f"{confidence}%", ok))

    # 表示
    widths = [max(len(str(r[i])) for r in (rows + [headers])) for i in range(len(headers))]
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*headers))
    print("-" * (sum(widths) + 2 * len(widths)))
    for row in rows:
        print(fmt.format(*row))
    print()

    # サマリ
    print("=" * 70)
    print("📊 ベンチマークサマリ")
    print(f"  関連質問:           {answer_total} 件")
    print(f"    回答できた:       {answered} 件 ({answered/answer_total*100:.0f}%)")
    print(f"    正解 (top1一致):  {correct} 件 ({correct/answer_total*100:.0f}%)")
    print(f"    NO_ANS 誤発動:    {answer_total - answered} 件")
    print()
    print(f"  ノイズ抑制テスト:    {no_answer_total} 件")
    print(f"    正しく NO_ANS:    {no_answer_correct} 件 ({no_answer_correct/no_answer_total*100:.0f}%)")
    print()
    overall = (correct + no_answer_correct) / len(TEST_CASES) * 100
    print(f"🎯 総合精度: {correct + no_answer_correct} / {len(TEST_CASES)} ({overall:.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
