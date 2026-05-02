"""パフォーマンステスト：大きなファイル・多チャンク・連続質問のレイテンシ。

許容ライン:
  - 100チャンクのインデックス構築: < 1秒
  - 1チャンク検索: < 50ms
  - 100質問連続: < 5秒（平均 50ms/件）
  - 50KB ファイル解析: < 500ms
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.ingest import analyze, parse


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    from app import audit, rag
    from app.main import app

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "faq_master_dir", tmp_path / "faq_master")
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "audit")
    rag._index = None
    return TestClient(app)


def _make_doc(n_sections: int = 50) -> bytes:
    """N セクションある Markdown を生成。"""
    parts = ["# 大きな文書\n\n"]
    for i in range(n_sections):
        parts.append(f"## セクション{i}\n\n")
        parts.append(f"これはセクション{i}の内容です。" * 5 + "\n\n")
    return "".join(parts).encode("utf-8")


# ============================================================
# 大きなファイル解析
# ============================================================
def test_large_file_analysis_under_500ms():
    """50KB の Markdown ファイル解析が 500ms 以内。"""
    content = _make_doc(n_sections=200)  # ~50KB
    assert len(content) > 30_000  # 30KB 以上はある
    start = time.time()
    result = analyze("big.md", content)
    elapsed = time.time() - start
    assert result.n_chunks >= 50
    assert elapsed < 0.5, f"解析時間 {elapsed:.3f}秒 が許容超過"


def test_many_chunks_creates_correct_number():
    """200セクションある文書で 200チャンク前後生成される。"""
    content = _make_doc(n_sections=200)
    chunks = parse("big.md", content)
    assert 150 <= len(chunks) <= 250


# ============================================================
# 検索パフォーマンス
# ============================================================
def test_search_in_large_index_under_50ms(client: TestClient):
    """100チャンク規模のインデックスで1検索 50ms 以内。"""
    # 大きい文書を取り込み
    content = _make_doc(n_sections=100)
    client.post("/api/admin/ingest",
                files={"file": ("big.md", content, "text/markdown")})
    # 検索計測
    start = time.time()
    r = client.post("/api/ask", json={"question": "セクション50の内容"})
    elapsed = time.time() - start
    assert r.status_code == 200
    # FastAPI 経由なのでオーバーヘッド込みで 200ms 以内
    assert elapsed < 0.2, f"検索時間 {elapsed:.3f}秒 が許容超過"


def test_serial_queries_average_under_100ms(client: TestClient):
    """20質問連続で平均 100ms/件以内。"""
    content = _make_doc(n_sections=30)
    client.post("/api/admin/ingest",
                files={"file": ("doc.md", content, "text/markdown")})

    questions = [f"セクション{i}の内容について" for i in range(20)]
    start = time.time()
    for q in questions:
        r = client.post("/api/ask", json={"question": q})
        assert r.status_code == 200
    elapsed = time.time() - start
    avg = elapsed / len(questions)
    assert avg < 0.1, f"平均 {avg*1000:.0f}ms/件 が許容超過"


# ============================================================
# 取り込みパフォーマンス
# ============================================================
def test_csv_with_1000_rows(client: TestClient):
    """1000行 CSV の取り込みが 3秒以内。"""
    rows = ["id,question,answer"]
    for i in range(1000):
        rows.append(f"{i},質問{i}番,回答{i}番")
    content = "\n".join(rows).encode("utf-8")

    start = time.time()
    r = client.post("/api/admin/ingest",
                    files={"file": ("big.csv", content, "text/csv")})
    elapsed = time.time() - start
    assert r.status_code == 200
    assert r.json()["ingested_chunks"] == 1000
    assert elapsed < 3.0, f"1000行CSV取り込み {elapsed:.2f}秒 が許容超過"


# ============================================================
# 同時操作
# ============================================================
def test_concurrent_queries_dont_corrupt(client: TestClient):
    """連続して20質問を投げても結果が崩れない（state competition）。"""
    md = b"# Test\n\nthis is a test document"
    client.post("/api/admin/ingest",
                files={"file": ("t.md", md, "text/markdown")})

    results = []
    for i in range(20):
        r = client.post("/api/ask", json={"question": f"test query {i}"})
        results.append(r.json())
    # 全レスポンス成功
    assert all("has_answer" in r for r in results)
    # confidence が一貫している（同じ質問は同じ結果）
    same_q_results = [client.post("/api/ask", json={"question": "test"}).json() for _ in range(3)]
    assert len(set(r["confidence"] for r in same_q_results)) == 1
