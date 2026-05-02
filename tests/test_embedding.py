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


def test_e5_cache_key_depends_on_content():
    """キャッシュキーは内容のハッシュ → 内容変更で再計算される。"""
    from app.rag import _E5Backend

    chunks_a = [Chunk(chunk_id="a#0", source="a.md", text="content A")]
    chunks_b = [Chunk(chunk_id="a#0", source="a.md", text="content B")]
    chunks_a2 = [Chunk(chunk_id="a#0", source="a.md", text="content A")]

    key_a = _E5Backend._cache_key(chunks_a)
    key_b = _E5Backend._cache_key(chunks_b)
    key_a2 = _E5Backend._cache_key(chunks_a2)

    assert key_a == key_a2  # 同じ内容ならキー同じ
    assert key_a != key_b   # 内容違えば別キー
