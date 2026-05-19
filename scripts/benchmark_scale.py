"""大規模インデックスのリアル実測ベンチマーク。

`tests/test_scale.py` の通過ラインは「許容ライン」だが、これは「実測値」を出す。
docs/scale_benchmark.md に転記して顧客説明用の数値として使う。

実行:
  .venv/bin/python scripts/benchmark_scale.py
"""
from __future__ import annotations

import gc
import statistics
import time
import tracemalloc
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.masking import build_rules, mask
from app.rag import Chunk, FaqIndex, record_feedback


def _make_chunks(n: int) -> list[Chunk]:
    keywords = [
        "VPN", "経費", "勤怠", "有給", "車検", "整備", "保証", "部品",
        "緊急", "顧客対応", "セキュリティ", "パスワード", "メール", "出張",
    ]
    chunks: list[Chunk] = []
    for i in range(n):
        kw = keywords[i % len(keywords)]
        text = (
            f"# {kw}関連のセクション {i}\n\n"
            f"これは{kw}に関する解説です。手順は以下の通り：\n"
            f"1. 申請フォームに記入\n"
            f"2. 承認者に提出\n"
            f"3. 期限内に処理完了\n"
            f"その他の留意事項は別途マニュアル参照。"
        )
        chunks.append(Chunk(chunk_id=f"doc{i//5}.md#{i%5}", source=f"doc{i//5}.md", text=text))
    return chunks


def fmt_ms(seconds: float) -> str:
    return f"{seconds*1000:7.1f} ms"


def fmt_s(seconds: float) -> str:
    return f"{seconds:6.2f} s "


def bench_index_build():
    print("\n## インデックス構築時間\n")
    print(f"{'チャンク数':>10} | {'時間':>10} | {'1チャンクあたり':>15}")
    print(f"{'-'*10} | {'-'*10} | {'-'*15}")
    for n in [100, 500, 1000, 2500, 5000]:
        chunks = _make_chunks(n)
        gc.collect()
        start = time.time()
        FaqIndex(chunks)
        elapsed = time.time() - start
        per_chunk = elapsed / n * 1000
        print(f"{n:>10,} | {fmt_s(elapsed)} | {per_chunk:>10.2f} ms")


def bench_search_latency():
    print("\n## 単一検索のレイテンシ（10回平均、warm）\n")
    print(f"{'チャンク数':>10} | {'平均':>10} | {'中央値':>10} | {'p95':>10}")
    print(f"{'-'*10} | {'-'*10} | {'-'*10} | {'-'*10}")
    for n in [100, 500, 1000, 2500, 5000]:
        idx = FaqIndex(_make_chunks(n))
        # ウォームアップ
        for _ in range(3):
            idx.search("VPN 接続", top_k=5)
        # 計測
        samples = []
        for _ in range(20):
            start = time.time()
            idx.search("VPN 接続 手順", top_k=5)
            samples.append(time.time() - start)
        avg = statistics.mean(samples)
        med = statistics.median(samples)
        p95 = sorted(samples)[int(len(samples) * 0.95)]
        print(f"{n:>10,} | {fmt_ms(avg)} | {fmt_ms(med)} | {fmt_ms(p95)}")


def bench_throughput():
    print("\n## 連続検索スループット（100件連続実行）\n")
    print(f"{'チャンク数':>10} | {'総時間':>10} | {'平均/件':>10} | {'QPS':>8}")
    print(f"{'-'*10} | {'-'*10} | {'-'*10} | {'-'*8}")
    queries = ["VPN", "経費", "勤怠", "有給", "車検", "整備", "保証", "部品", "緊急", "セキュリティ"] * 10
    for n in [500, 1000, 2500, 5000]:
        idx = FaqIndex(_make_chunks(n))
        for _ in range(3):
            idx.search("warm", top_k=5)
        start = time.time()
        for q in queries:
            idx.search(q, top_k=5)
        elapsed = time.time() - start
        avg = elapsed / len(queries)
        qps = len(queries) / elapsed
        print(f"{n:>10,} | {fmt_s(elapsed)} | {fmt_ms(avg)} | {qps:>5.1f}")


def bench_masking():
    print("\n## マスキング処理（10回平均）\n")
    print(f"{'テキストサイズ':>15} | {'時間':>10}")
    print(f"{'-'*15} | {'-'*10}")
    base = "社員 yamada@example.com は 03-1234-5678 まで連絡可能。"
    rules = build_rules("general")
    for repeats, label in [(10, "0.5KB"), (30, "1.5KB"), (300, "15KB"), (3000, "150KB")]:
        text = base * repeats
        # ウォームアップ
        mask(text, rules)
        samples = []
        for _ in range(10):
            start = time.time()
            mask(text, rules)
            samples.append(time.time() - start)
        print(f"{label:>15} | {fmt_ms(statistics.mean(samples))}")


def bench_feedback():
    print("\n## フィードバック書き込み（既存件数別）\n")
    print(f"{'既存件数':>10} | {'書き込み時間':>12}")
    print(f"{'-'*10} | {'-'*12}")
    import tempfile
    from app import rag

    for n_existing in [0, 100, 1000, 10_000]:
        with tempfile.TemporaryDirectory() as tmp:
            fb_path = Path(tmp) / "fb.json"
            rag.FEEDBACK_PATH = fb_path
            # 既存件数を蓄積
            if n_existing > 0:
                import json
                data = {f"doc{i}.md": {"up": i, "down": 0} for i in range(n_existing)}
                fb_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            # 計測（5回平均）
            samples = []
            for i in range(5):
                start = time.time()
                record_feedback([f"new{i}.md"], "up")
                samples.append(time.time() - start)
            print(f"{n_existing:>10,} | {fmt_ms(statistics.mean(samples))}")


def bench_memory():
    print("\n## メモリ使用量（インデックス構築後＋1検索後）\n")
    print(f"{'チャンク数':>10} | {'ピーク':>10}")
    print(f"{'-'*10} | {'-'*10}")
    for n in [500, 1000, 2500, 5000]:
        gc.collect()
        tracemalloc.start()
        idx = FaqIndex(_make_chunks(n))
        idx.search("VPN", top_k=5)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mb = peak / (1024 * 1024)
        print(f"{n:>10,} | {peak_mb:>7.1f} MB")


if __name__ == "__main__":
    print("=" * 60)
    print("Inquira スケーラビリティ・ベンチマーク")
    print(f"プラットフォーム: {sys.platform} / Python {sys.version.split()[0]}")
    print("=" * 60)
    bench_index_build()
    bench_search_latency()
    bench_throughput()
    bench_masking()
    bench_feedback()
    bench_memory()
    print("\n" + "=" * 60)
    print("完了")
    print("=" * 60)
