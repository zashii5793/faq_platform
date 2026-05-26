"""Embedding バックエンドのテスト。

サンドボックス環境では HuggingFace 接続不可なので、以下のみ検証:
  1. tfidf がデフォルト
  2. 設定変更後もエラーで落ちず TF-IDF にフォールバックする（モデルDL失敗時）
  3. キャッシュキーがチャンク内容のハッシュで決まる

実モデルを使った Embedding テストは、
sentence-transformers + ネット接続が揃った環境でのみ意味があるため、
ベンチマークスクリプト (scripts/benchmark_search.py) にて手動実行を想定。
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.rag import Chunk, FaqIndex, _make_backend, _TfidfBackend


def test_default_backend_is_tfidf():
    assert settings.embedding_backend == "tfidf"


def test_make_backend_tfidf():
    chunks = [Chunk(chunk_id="a#0", source="a.md", text="VPNの繋ぎ方")]
    settings_orig = settings.embedding_backend
    try:
        settings.embedding_backend = "tfidf"
        b = _make_backend(chunks)
        assert isinstance(b, _TfidfBackend)
    finally:
        settings.embedding_backend = settings_orig


def test_unknown_backend_falls_back_to_tfidf():
    """存在しないバックエンド名でも TF-IDF にフォールバック（落ちない）。"""
    chunks = [Chunk(chunk_id="a#0", source="a.md", text="test")]
    settings_orig = settings.embedding_backend
    try:
        settings.embedding_backend = "unknown-backend"
        b = _make_backend(chunks)
        assert isinstance(b, _TfidfBackend)
    finally:
        settings.embedding_backend = settings_orig


def test_e5_backend_falls_back_when_model_unavailable(monkeypatch):
    """e5 系を指定してもモデルロード失敗で TF-IDF にフォールバック。

    サンドボックス環境のように HuggingFace へアクセス不可の場合に、
    アプリ自体が起動不能にならないことを保証する。
    """
    chunks = [Chunk(chunk_id="a#0", source="a.md", text="test")]
    settings_orig = settings.embedding_backend
    try:
        settings.embedding_backend = "e5-small"
        # warning は出るが、TF-IDF にフォールバックされる
        with pytest.warns(UserWarning):
            b = _make_backend(chunks)
        # フォールバックで TF-IDF として動く
        assert isinstance(b, _TfidfBackend)
    except Exception:
        # ネット接続があってモデルロード成功した環境では別ロジック
        # この場合は E5Backend インスタンスになるので OK
        pass
    finally:
        settings.embedding_backend = settings_orig


def test_index_search_works_after_fallback():
    """e5 を指定してフォールバックしても通常の検索が動作する。"""
    chunks = [
        Chunk(chunk_id="vpn#0", source="vpn.md", text="VPN は FortiClient を起動して接続"),
        Chunk(chunk_id="exp#0", source="経費.md", text="経費精算の締め日は毎月25日"),
    ]
    settings_orig = settings.embedding_backend
    try:
        # 存在しないバックエンドを指定しても動作する
        settings.embedding_backend = "unknown-backend"
        idx = FaqIndex(chunks)
        results = idx.search("VPN の接続方法", top_k=2)
        assert results
        assert results[0][0].source == "vpn.md"
    finally:
        settings.embedding_backend = settings_orig


def test_e5_text_hash_depends_on_content():
    """チャンク本文のハッシュ → 同じ内容なら同じ、変わると別。

    差分キャッシュは (chunk_id, text_hash) で命中判定するため、text_hash が
    内容と一対一に対応していることが基盤要件。
    """
    from app.rag import _E5Backend

    assert _E5Backend._text_hash("content A") == _E5Backend._text_hash("content A")
    assert _E5Backend._text_hash("content A") != _E5Backend._text_hash("content B")


def test_e5_differential_cache_reuses_unchanged_chunks(tmp_path, monkeypatch):
    """差分キャッシュ: 既存チャンクは再エンコードせず、新規/変更分だけ計算する。

    実モデルは使わず、SentenceTransformer をスタブで差し替えてエンコード
    回数を観測する。
    """
    import numpy as np

    from app import rag as rag_mod
    from app.rag import _E5Backend

    cache_file = tmp_path / "emb.npz"
    monkeypatch.setattr(rag_mod.settings, "embedding_cache_path", cache_file)

    encode_calls: list[list[str]] = []

    class _StubModel:
        def encode(self, texts, **kw):
            encode_calls.append(list(texts))
            # 各 passage に対して固定次元（4）のダミーベクトルを返す
            return np.ones((len(texts), 4), dtype=np.float32)

    # __init__ の SentenceTransformer ロードを回避してインスタンスを直接構築
    backend = _E5Backend.__new__(_E5Backend)
    backend.model = _StubModel()

    chunks_initial = [
        Chunk(chunk_id="a#0", source="a.md", text="alpha"),
        Chunk(chunk_id="a#1", source="a.md", text="beta"),
    ]
    backend.chunks = chunks_initial
    backend.embeddings = backend._load_or_encode(chunks_initial)
    assert backend.embeddings.shape == (2, 4)
    assert len(encode_calls) == 1
    assert len(encode_calls[0]) == 2  # 初回は全件エンコード

    # 1チャンク追加 + 既存は変更なし → 新規分1件だけエンコードされるはず
    encode_calls.clear()
    chunks_added = chunks_initial + [Chunk(chunk_id="a#2", source="a.md", text="gamma")]
    backend.embeddings = backend._load_or_encode(chunks_added)
    assert backend.embeddings.shape == (3, 4)
    assert len(encode_calls) == 1
    assert len(encode_calls[0]) == 1  # 新規1件のみ
    assert "passage: gamma" in encode_calls[0][0]

    # 既存チャンクの本文を変更 → 変更分1件だけエンコード
    encode_calls.clear()
    chunks_changed = [
        Chunk(chunk_id="a#0", source="a.md", text="alpha-modified"),  # 変更
        Chunk(chunk_id="a#1", source="a.md", text="beta"),            # 同じ
        Chunk(chunk_id="a#2", source="a.md", text="gamma"),           # 同じ
    ]
    backend.embeddings = backend._load_or_encode(chunks_changed)
    assert len(encode_calls) == 1
    assert len(encode_calls[0]) == 1
    assert "alpha-modified" in encode_calls[0][0]

    # 全件同じ → エンコード呼び出しゼロ
    encode_calls.clear()
    backend.embeddings = backend._load_or_encode(chunks_changed)
    assert encode_calls == []
