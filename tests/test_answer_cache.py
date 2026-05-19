"""質問キャッシュ (llm.answer の TTL キャッシュ) のテスト。

同じ質問が TTL 内に来たら Claude API を呼ばず前回回答を返す。
FAQ 再インデックス時にキャッシュは全消去される。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import llm
from app.config import settings


class FakeClient:
    """messages.create の呼び出し回数を数えるダミー Anthropic クライアント。"""

    def __init__(self):
        self.calls = 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=f"回答#{self.calls}")],
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=20,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            ),
        )


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "answer_cache_ttl", 300)
    monkeypatch.setattr(settings, "audit_log_dir", tmp_path / "audit")
    client = FakeClient()
    monkeypatch.setattr(llm, "_client", lambda: client)
    llm.clear_answer_cache()
    yield client
    llm.clear_answer_cache()


class TestAnswerCache:
    def test_second_identical_question_skips_api(self, fake):
        a1 = llm.answer("経費精算の締め日は?", [])
        a2 = llm.answer("経費精算の締め日は?", [])
        assert fake.calls == 1  # 2回目は API を呼ばない
        assert a1 == a2

    def test_different_questions_each_call_api(self, fake):
        llm.answer("質問A", [])
        llm.answer("質問B", [])
        assert fake.calls == 2

    def test_question_normalized_before_caching(self, fake):
        """前後の空白・大小文字差はキャッシュ上は同一扱い。"""
        llm.answer("  VPN設定  ", [])
        llm.answer("VPN設定", [])
        assert fake.calls == 1

    def test_reference_mode_cached_separately(self, fake):
        """通常モードと参考情報モードは別キャッシュ。"""
        llm.answer("同じ質問", [], reference_mode=False)
        llm.answer("同じ質問", [], reference_mode=True)
        assert fake.calls == 2

    def test_ttl_expiry_triggers_new_api_call(self, fake, monkeypatch):
        llm.answer("期限切れテスト", [])
        assert fake.calls == 1
        # キャッシュ済みエントリのタイムスタンプを TTL より過去に巻き戻す
        with llm._answer_cache_lock:
            for k, (text, _) in list(llm._answer_cache.items()):
                llm._answer_cache[k] = (text, 0.0)
        llm.answer("期限切れテスト", [])
        assert fake.calls == 2

    def test_ttl_zero_disables_cache(self, fake, monkeypatch):
        monkeypatch.setattr(settings, "answer_cache_ttl", 0)
        llm.answer("無効化テスト", [])
        llm.answer("無効化テスト", [])
        assert fake.calls == 2

    def test_clear_answer_cache_forces_refetch(self, fake):
        llm.answer("クリアテスト", [])
        assert fake.calls == 1
        llm.clear_answer_cache()
        llm.answer("クリアテスト", [])
        assert fake.calls == 2

    def test_local_mode_not_cached(self, monkeypatch, tmp_path):
        """API キー未設定（ローカルモード）はキャッシュ対象外。"""
        monkeypatch.setattr(settings, "anthropic_api_key", "")
        llm.clear_answer_cache()
        llm.answer("ローカル質問", [])
        with llm._answer_cache_lock:
            assert llm._answer_cache == {}


class TestReindexClearsCache:
    def test_reload_index_clears_answer_cache(self, fake, monkeypatch, tmp_path):
        from app import rag

        monkeypatch.setattr(settings, "faq_master_dir", tmp_path / "faq")
        (tmp_path / "faq").mkdir()
        llm.answer("再インデックステスト", [])
        assert fake.calls == 1
        rag.reload_index()  # FAQ 更新を模擬 → キャッシュ消去されるはず
        llm.answer("再インデックステスト", [])
        assert fake.calls == 2
