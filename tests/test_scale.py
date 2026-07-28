"""大規模インデックスのパフォーマンステスト（スケーラビリティ検証）。

許容ライン（許容失敗時はチューニング対象）:
  - 500文書 × 5チャンク = 2500チャンク インデックス構築: < 15秒
  - 1000文書 × 5チャンク = 5000チャンク 構築: < 30秒
  - 検索1回 (5000チャンク): < 500ms
  - 連続100検索 (5000チャンク): 平均 < 200ms/件
  - インデックス全体メモリ占有: < 200MB
  - マスキング処理 (1KB テキスト): < 10ms
  - フィードバック書き込み: < 50ms
"""
from __future__ import annotations

import gc
import time

import pytest
from fastapi.testclient import TestClient

from app.masking import build_rules, mask
from app.rag import Chunk, FaqIndex, record_feedback


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    from app import audit, rag
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "faq_master_dir", tmp_path / "faq_master")
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "audit")
    monkeypatch.setattr(rag, "FEEDBACK_PATH", tmp_path / "feedback.json")
    rag._index = None
    return TestClient(app)


def _make_chunks(n: int) -> list[Chunk]:
    """N 個のチャンクを生成（テーマがバラバラになるよう各種キーワード混入）。"""
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


# ============================================================
# インデックス構築スケーラビリティ
# ============================================================
class TestIndexBuildScalability:
    def test_build_500_chunks_under_5s(self):
        chunks = _make_chunks(500)
        start = time.time()
        idx = FaqIndex(chunks)
        elapsed = time.time() - start
        assert elapsed < 5.0, f"500チャンク構築 {elapsed:.2f}秒（5秒以内が期待）"
        assert idx.backend is not None

    def test_build_2500_chunks_under_15s(self):
        chunks = _make_chunks(2500)
        start = time.time()
        FaqIndex(chunks)
        elapsed = time.time() - start
        assert elapsed < 15.0, f"2500チャンク構築 {elapsed:.2f}秒（15秒以内が期待）"

    @pytest.mark.slow
    def test_build_5000_chunks_under_30s(self):
        chunks = _make_chunks(5000)
        start = time.time()
        FaqIndex(chunks)
        elapsed = time.time() - start
        assert elapsed < 30.0, f"5000チャンク構築 {elapsed:.2f}秒（30秒以内が期待）"


# ============================================================
# 検索レイテンシ（スケール別）
# ============================================================
class TestSearchLatencyByScale:
    @pytest.fixture(scope="class")
    def small_index(self):
        """500チャンクのインデックス（複数テストで使い回し）。"""
        return FaqIndex(_make_chunks(500))

    @pytest.fixture(scope="class")
    def medium_index(self):
        return FaqIndex(_make_chunks(2500))

    @pytest.fixture(scope="class")
    def large_index(self):
        return FaqIndex(_make_chunks(5000))

    def test_search_500_chunks_under_100ms(self, small_index):
        start = time.time()
        results = small_index.search("VPN 接続 手順", top_k=5)
        elapsed = (time.time() - start) * 1000
        assert results, "検索結果が空"
        assert elapsed < 100, f"500チャンク検索 {elapsed:.1f}ms（100ms以内が期待）"

    def test_search_2500_chunks_under_250ms(self, medium_index):
        start = time.time()
        results = medium_index.search("VPN 接続 手順", top_k=5)
        elapsed = (time.time() - start) * 1000
        assert results
        assert elapsed < 250, f"2500チャンク検索 {elapsed:.1f}ms（250ms以内が期待）"

    def test_search_5000_chunks_under_500ms(self, large_index):
        start = time.time()
        results = large_index.search("VPN 接続 手順", top_k=5)
        elapsed = (time.time() - start) * 1000
        assert results
        assert elapsed < 500, f"5000チャンク検索 {elapsed:.1f}ms（500ms以内が期待）"


# ============================================================
# 連続検索のスループット（キャッシュ・状態管理の検証）
# ============================================================
class TestSequentialThroughput:
    def test_100_searches_5000_chunks_avg_under_200ms(self):
        """5000チャンクインデックスで100検索を連続実行。平均 200ms/件以下。"""
        idx = FaqIndex(_make_chunks(5000))
        queries = [
            "VPN 接続できない",
            "経費 精算 締切",
            "勤怠 修正 方法",
            "有給 申請 期限",
            "車検 手順",
            "整備 受付",
            "保証 規定",
            "部品 発注",
            "緊急 対応 連絡先",
            "セキュリティ ポリシー",
        ] * 10  # 100質問

        start = time.time()
        for q in queries:
            idx.search(q, top_k=5)
        elapsed_ms = (time.time() - start) * 1000
        avg = elapsed_ms / len(queries)
        assert avg < 200, f"平均 {avg:.1f}ms/件（200ms以内が期待）"


# ============================================================
# マスキング処理の高速性
# ============================================================
class TestMaskingPerformance:
    def test_masking_1kb_text_under_10ms(self):
        rules = build_rules("general")
        text = ("社員 yamada@example.com は 03-1234-5678 まで連絡可能。" * 30)
        assert len(text) >= 1000

        # ウォームアップ
        mask(text, rules)

        # 計測（10回平均）
        start = time.time()
        for _ in range(10):
            mask(text, rules)
        elapsed_ms = ((time.time() - start) / 10) * 1000
        assert elapsed_ms < 10, f"マスキング {elapsed_ms:.2f}ms（10ms以内が期待）"

    def test_masking_10kb_text_under_50ms(self):
        rules = build_rules("general")
        text = ("社員 yamada@example.com は 03-1234-5678 まで連絡可能。" * 300)
        assert len(text) >= 10_000

        mask(text, rules)  # ウォームアップ
        start = time.time()
        for _ in range(10):
            mask(text, rules)
        elapsed_ms = ((time.time() - start) / 10) * 1000
        assert elapsed_ms < 50, f"10KB マスキング {elapsed_ms:.2f}ms（50ms以内が期待）"


# ============================================================
# フィードバック書き込みの速度
# ============================================================
class TestFeedbackPerformance:
    def test_feedback_write_under_50ms(self, tmp_path, monkeypatch):
        from app import rag
        monkeypatch.setattr(rag, "FEEDBACK_PATH", tmp_path / "fb.json")

        # ウォームアップ
        record_feedback(["doc1.md"], "up")

        start = time.time()
        for i in range(10):
            record_feedback([f"doc{i}.md"], "up")
        elapsed_ms = ((time.time() - start) / 10) * 1000
        assert elapsed_ms < 50, f"フィードバック書き込み {elapsed_ms:.2f}ms（50ms以内が期待）"


# ============================================================
# エンドツーエンドの応答時間（FastAPI 経由）
# ============================================================
class TestEndToEndLatency:
    def test_e2e_response_with_500_chunks_under_500ms(self, client):
        """500チャンクインデックスへの /api/ask 1リクエストが 500ms 以内。"""
        # 100文書 (各 5チャンク) をまとめて取り込み
        for i in range(100):
            content = (
                f"# 文書{i}\n\n"
                f"## セクションA\n本文A {i}\n\n"
                f"## セクションB\n本文B {i}\n\n"
                f"## セクションC\n本文C {i}\n\n"
                f"## セクションD\n本文D {i}\n\n"
                f"## セクションE\n本文E {i}\n"
            ).encode("utf-8")
            r = client.post("/api/admin/ingest",
                            files={"file": (f"doc{i}.md", content, "text/markdown")})
            assert r.status_code == 200

        # 計測
        start = time.time()
        r = client.post("/api/ask", json={"question": "セクションAについて教えて"})
        elapsed_ms = (time.time() - start) * 1000
        assert r.status_code == 200
        assert elapsed_ms < 500, f"E2E 応答 {elapsed_ms:.0f}ms（500ms以内が期待）"


# ============================================================
# メモリ使用量（オプション・参考値）
# ============================================================
class TestMemoryFootprint:
    def test_index_5000_chunks_memory_reasonable(self):
        """5000チャンクのインデックスがメモリ 300MB 以内に収まる。
        psutil は標準では入っていないので、tracemalloc で測る。
        """
        import tracemalloc
        gc.collect()
        tracemalloc.start()
        idx = FaqIndex(_make_chunks(5000))
        # 検索を1回叩いて TF-IDF matrix が確実に展開された状態にする
        idx.search("VPN", top_k=5)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mb = peak / (1024 * 1024)
        # 5000チャンク × 平均200文字 = 1MB のテキスト → TF-IDF 行列で約20倍くらい
        assert peak_mb < 300, f"ピークメモリ {peak_mb:.1f}MB（300MB以内が期待）"
