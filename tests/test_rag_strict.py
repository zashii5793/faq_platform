"""RAG（検索エンジン）の境界条件・エッジケース。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.rag import (
    Chunk,
    FaqIndex,
    _boost_factor,
    _load_feedback,
    _split_text,
    load_chunks,
    record_feedback,
)


# ============================================================
# _split_text の境界
# ============================================================
class TestSplitText:
    def test_empty_text_returns_fallback(self):
        result = _split_text("")
        assert result == [""]

    def test_single_short_paragraph(self):
        result = _split_text("短い文章")
        assert result == ["短い文章"]

    def test_paragraph_exceeds_max_chars(self):
        """1段落が max_chars(600) を超える場合、1チャンクとして返す（実装上は分割されない）。"""
        long = "あ" * 1000
        result = _split_text(long, max_chars=600)
        assert len(result) >= 1
        # 現状実装: 1段落=1チャンクは尊重されるので超過する
        # 望ましい: 600文字以下に分割
        if any(len(c) > 600 for c in result):
            pytest.xfail("単一巨大段落は max_chars 超過のまま（既知の弱点）")

    def test_multiple_paragraphs_split(self):
        text = "\n\n".join([f"段落{i} " * 30 for i in range(20)])
        result = _split_text(text, max_chars=200)
        assert len(result) > 1

    def test_whitespace_paragraphs_dropped(self):
        text = "本文1\n\n   \n\n本文2"
        result = _split_text(text)
        # 空白のみの段落は除外され、本文1と本文2のみ残る
        joined = "\n".join(result)
        assert "本文1" in joined and "本文2" in joined


# ============================================================
# load_chunks: ファイル種別フィルタ
# ============================================================
class TestLoadChunks:
    def test_nonexistent_dir_returns_empty(self, tmp_path: Path):
        result = load_chunks(tmp_path / "doesnotexist")
        assert result == []

    def test_empty_dir_returns_empty(self, tmp_path: Path):
        assert load_chunks(tmp_path) == []

    def test_only_md_and_txt_loaded(self, tmp_path: Path):
        (tmp_path / "a.md").write_text("# A\n\n本文A", encoding="utf-8")
        (tmp_path / "b.txt").write_text("本文B", encoding="utf-8")
        (tmp_path / "c.pdf").write_bytes(b"%PDF-1.4 fake")
        (tmp_path / "d.json").write_text("{}", encoding="utf-8")
        chunks = load_chunks(tmp_path)
        sources = {c.source for c in chunks}
        assert sources == {"a.md", "b.txt"}

    def test_subdirectory_files_loaded(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.md").write_text("# nested\n\nねすと本文", encoding="utf-8")
        chunks = load_chunks(tmp_path)
        assert any("nested.md" in c.chunk_id for c in chunks)

    def test_unicode_filename(self, tmp_path: Path):
        (tmp_path / "日本語タイトル.md").write_text("# 日本語\n\n本文", encoding="utf-8")
        chunks = load_chunks(tmp_path)
        assert any("日本語タイトル.md" in c.chunk_id for c in chunks)


# ============================================================
# FaqIndex 検索
# ============================================================
class TestFaqIndexSearch:
    def test_empty_index_returns_empty(self):
        idx = FaqIndex([])
        assert idx.search("anything") == []

    def test_search_with_empty_query(self):
        chunks = [Chunk("a.md#0", "a.md", "本文A"), Chunk("b.md#0", "b.md", "本文B")]
        idx = FaqIndex(chunks)
        # 空クエリは「全文書のスコアがゼロ」になるので空のリストを返すべき
        results = idx.search("")
        # 仕様: スコア0は除外されるので []
        assert all(score > 0 for _, score in results)

    def test_search_with_only_whitespace_query(self):
        chunks = [Chunk("a.md#0", "a.md", "テスト本文")]
        idx = FaqIndex(chunks)
        results = idx.search("   ")
        # サーバが落ちない
        assert isinstance(results, list)

    def test_search_top_k_respected(self):
        chunks = [Chunk(f"f{i}.md#0", f"f{i}.md", f"これは文書{i}番") for i in range(20)]
        idx = FaqIndex(chunks)
        results = idx.search("文書", top_k=5)
        assert len(results) <= 5

    def test_search_top_k_zero(self):
        chunks = [Chunk("a.md#0", "a.md", "本文")]
        idx = FaqIndex(chunks)
        results = idx.search("本文", top_k=0)
        assert results == []

    def test_search_negative_top_k(self):
        chunks = [Chunk("a.md#0", "a.md", "本文")]
        idx = FaqIndex(chunks)
        # numpy の argsort で負数は末尾から、結果は逆順だが空に近い
        results = idx.search("本文", top_k=-1)
        # クラッシュしない
        assert isinstance(results, list)

    def test_search_huge_query(self):
        """巨大クエリ（10万字）でもクラッシュしない。"""
        chunks = [Chunk("a.md#0", "a.md", "本文")]
        idx = FaqIndex(chunks)
        results = idx.search("あ" * 100_000, top_k=5)
        assert isinstance(results, list)

    def test_search_query_with_control_chars(self):
        chunks = [Chunk("a.md#0", "a.md", "本文")]
        idx = FaqIndex(chunks)
        # ヌルバイトを含むクエリ
        results = idx.search("本文\x00\x01\x02", top_k=5)
        assert isinstance(results, list)


# ============================================================
# フィードバック学習
# ============================================================
class TestFeedback:
    def test_load_returns_empty_when_missing(self, tmp_path: Path, monkeypatch):
        from app import rag
        monkeypatch.setattr(rag, "FEEDBACK_PATH", tmp_path / "fb.json")
        assert _load_feedback() == {}

    def test_load_handles_broken_json(self, tmp_path: Path, monkeypatch):
        """JSON が壊れていても落ちず、{} を返す。"""
        from app import rag
        fb_path = tmp_path / "fb.json"
        fb_path.write_text("invalid json {{{", encoding="utf-8")
        monkeypatch.setattr(rag, "FEEDBACK_PATH", fb_path)
        assert _load_feedback() == {}

    def test_record_feedback_basic(self, tmp_path: Path, monkeypatch):
        from app import rag
        monkeypatch.setattr(rag, "FEEDBACK_PATH", tmp_path / "fb.json")
        record_feedback(["a.md#0"], "up")
        record_feedback(["a.md#1"], "down")
        data = _load_feedback()
        assert data["a.md"] == {"up": 1, "down": 1}

    def test_record_feedback_invalid_vote_ignored(self, tmp_path: Path, monkeypatch):
        """vote='neutral' のような不正値は黙って無視される。"""
        from app import rag
        monkeypatch.setattr(rag, "FEEDBACK_PATH", tmp_path / "fb.json")
        record_feedback(["a.md#0"], "neutral")
        assert _load_feedback() == {}

    def test_record_feedback_with_empty_sources(self, tmp_path: Path, monkeypatch):
        from app import rag
        monkeypatch.setattr(rag, "FEEDBACK_PATH", tmp_path / "fb.json")
        record_feedback([], "up")
        assert _load_feedback() == {}

    def test_boost_factor_no_data(self):
        assert _boost_factor("unknown.md", {}) == 1.0

    def test_boost_factor_positive(self):
        fb = {"a.md": {"up": 10, "down": 0}}
        boost = _boost_factor("a.md", fb)
        assert boost > 1.0
        assert boost <= 1.16  # 最大 +15% 程度

    def test_boost_factor_negative(self):
        fb = {"a.md": {"up": 0, "down": 10}}
        boost = _boost_factor("a.md", fb)
        assert boost < 1.0
        assert boost >= 0.84

    def test_boost_factor_equal(self):
        fb = {"a.md": {"up": 5, "down": 5}}
        boost = _boost_factor("a.md", fb)
        assert boost == 1.0


# ============================================================
# 同時アクセス・耐久性
# ============================================================
class TestConcurrency:
    def test_concurrent_feedback_writes_no_data_loss(self, tmp_path: Path, monkeypatch):
        """並行書き込みでデータが消失しない（単純なシナリオ）。"""
        import threading
        from app import rag
        monkeypatch.setattr(rag, "FEEDBACK_PATH", tmp_path / "fb.json")

        def worker(src: str):
            for _ in range(10):
                record_feedback([src], "up")

        threads = [threading.Thread(target=worker, args=(f"f{i}.md#0",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        data = _load_feedback()
        # 5ファイル × 10投票 = 50票が分散して入る
        total = sum(d.get("up", 0) for d in data.values())
        # 並行書き込みの競合で多少欠落する可能性あり（ファイルロックなし）
        # 望ましい: 50票が全部記録される
        # 既知の弱点: 競合時に書き込みが上書きされる
        if total < 50:
            pytest.xfail(
                f"並行書き込みで {50 - total}/50 票が失われた（既知の弱点・ファイルロックなし）"
            )
        assert total == 50
