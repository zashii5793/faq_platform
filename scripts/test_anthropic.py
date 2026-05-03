#!/usr/bin/env python3
"""Anthropic API キーが使えるか確認するスクリプト。

使い方:
    export ANTHROPIC_API_KEY=sk-ant-xxxxx
    python scripts/test_anthropic.py

    # または
    ANTHROPIC_API_KEY=sk-ant-xxxxx python scripts/test_anthropic.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# プロジェクトルートを import path に追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if not api_key:
        print("❌ ANTHROPIC_API_KEY が設定されていません")
        print()
        print("以下のいずれかで設定してください:")
        print("  1. export ANTHROPIC_API_KEY=sk-ant-xxxxx")
        print("  2. ANTHROPIC_API_KEY=sk-ant-xxxxx python scripts/test_anthropic.py")
        print("  3. プロジェクトの .env ファイルに ANTHROPIC_API_KEY=sk-ant-xxxxx を記載")
        return 1

    if not api_key.startswith("sk-ant-"):
        print(f"⚠ APIキーの形式が違うかも: {api_key[:10]}...")
        print("   通常は 'sk-ant-' で始まる形式です。")
        print("   このまま試行します...")
        print()

    print(f"🔑 APIキー: {api_key[:12]}...{api_key[-4:]} (長さ: {len(api_key)}文字)")
    print()

    try:
        from anthropic import Anthropic
    except ImportError:
        print("❌ anthropic パッケージが入っていません")
        print("   pip install anthropic を実行してください（または ./scripts/demo.sh）")
        return 1

    client = Anthropic(api_key=api_key)

    # 接続テスト: 最小限のリクエスト
    print("📡 接続テスト中... (約2秒)")
    start = time.time()
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=64,
            messages=[{"role": "user", "content": "こんにちは。'OK'とだけ返答してください。"}],
        )
    except Exception as e:
        print(f"❌ 接続失敗: {e}")
        print()
        print("考えられる原因:")
        print("  - APIキーが無効・期限切れ・無効化されている")
        print("  - ネットワーク／プロキシの問題")
        print("  - Anthropic 側の障害")
        print("  - クレジット残高不足（Anthropic Console で確認）")
        return 1

    elapsed = time.time() - start
    answer = "".join(b.text for b in msg.content if b.type == "text").strip()

    print(f"✅ 接続成功（{elapsed:.2f}秒）")
    print(f"   モデル:     {msg.model}")
    print(f"   応答:       {answer}")
    print(f"   入力tokens:  {msg.usage.input_tokens}")
    print(f"   出力tokens:  {msg.usage.output_tokens}")
    print()

    # コスト試算
    in_tok = msg.usage.input_tokens
    out_tok = msg.usage.output_tokens
    cost_usd = (in_tok * 3.0 + out_tok * 15.0) / 1_000_000
    cost_jpy = cost_usd * 155  # 1 USD = 155円 想定
    print(f"💰 このリクエストの料金: ${cost_usd:.6f} (約 {cost_jpy:.4f}円)")
    print()
    print("📊 月額試算（参考）:")
    avg_tokens_per_query = 5000  # 平均1質問の入出力合計トークン
    for n_users, n_queries_per_day in [(5, 5), (35, 10), (100, 15)]:
        n_queries_per_month = n_users * n_queries_per_day * 22
        monthly_tokens = n_queries_per_month * avg_tokens_per_query
        monthly_cost_usd = monthly_tokens * (3 + 15) / 2 / 1_000_000  # 平均
        monthly_cost_jpy = monthly_cost_usd * 155
        print(f"   {n_users:3d}名 × {n_queries_per_day:2d}質問/日 × 22日 "
              f"= 月{n_queries_per_month:5,}質問 ≈ ${monthly_cost_usd:.2f} (約 {monthly_cost_jpy:,.0f}円)")
    print()
    print("✅ APIキーは正常に動作しています。本番モードで起動できます:")
    print()
    print(f"   ANTHROPIC_API_KEY={api_key[:12]}... \\")
    print("   FAQ_MASTER_DIR=./data/takaya_faq \\")
    print("   ORG_NAME='タカヤモーター株式会社' \\")
    print("   uvicorn app.main:app --host 127.0.0.1 --port 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
