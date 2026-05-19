"""共有Q&A (Phase A) 機能のテスト。

- /api/knowledge-base: 一覧 / 検索
- /api/knowledge-base/vote: 役立った / 解決した / 違うかも
- 共有された Q&A を入力サジェストで返す
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    from app import audit, rag, shared_qa as sqa
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "faq_master_dir", tmp_path / "faq_master")
    monkeypatch.setattr(settings, "audit_log_dir", tmp_path / "audit")
    monkeypatch.setattr(settings, "shared_qa_meta_path", tmp_path / "shared_qa_meta.json")
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "audit")
    rag._index = None
    return TestClient(app)


def _share_answer(client, question, answer, share=True):
    """faq-requests 経由で共有回答を1件登録するヘルパー。"""
    r = client.post("/api/faq-requests", json={
        "question": question,
        "answer": answer,
        "share": share,
    })
    assert r.status_code == 200
    return r.json()


# ============================================================
# /api/knowledge-base 一覧
# ============================================================
class TestKnowledgeBaseList:
    def test_empty_initially(self, client):
        r = client.get("/api/knowledge-base")
        assert r.status_code == 200
        assert r.json()["total"] == 0
        assert r.json()["items"] == []

    def test_shared_answer_appears_in_list(self, client):
        _share_answer(client, "VPN設定方法", "FortiClient を使ってください")
        r = client.get("/api/knowledge-base")
        data = r.json()
        assert data["total"] >= 1
        assert any(it["question"] == "VPN設定方法" for it in data["items"])

    def test_private_share_NOT_in_list(self, client):
        """share=False で送ると検索インデックスに乗らないので一覧にも出ない。"""
        _share_answer(client, "個人メモ", "これは秘密", share=False)
        r = client.get("/api/knowledge-base")
        questions = [it["question"] for it in r.json()["items"]]
        assert "個人メモ" not in questions

    def test_search_filter_by_query(self, client):
        _share_answer(client, "VPN設定方法", "FortiClient を使う")
        _share_answer(client, "経費精算", "毎月25日締め")
        r = client.get("/api/knowledge-base?q=VPN")
        questions = [it["question"] for it in r.json()["items"]]
        assert "VPN設定方法" in questions
        assert "経費精算" not in questions


# ============================================================
# /api/knowledge-base/vote
# ============================================================
class TestKnowledgeBaseVote:
    def test_vote_up_increments_count(self, client):
        _share_answer(client, "テスト質問", "テスト回答")
        items = client.get("/api/knowledge-base").json()["items"]
        file_id = items[0]["file_id"]

        r = client.post("/api/knowledge-base/vote", json={"file_id": file_id, "kind": "up"})
        assert r.status_code == 200
        assert r.json()["meta"]["votes_up"] == 1

        # もう一度押すと2に
        client.post("/api/knowledge-base/vote", json={"file_id": file_id, "kind": "up"})
        items = client.get("/api/knowledge-base").json()["items"]
        target = next(x for x in items if x["file_id"] == file_id)
        assert target["votes_up"] == 2

    def test_vote_resolved_increments_count(self, client):
        _share_answer(client, "解決テスト", "解決方法")
        file_id = client.get("/api/knowledge-base").json()["items"][0]["file_id"]
        client.post("/api/knowledge-base/vote", json={"file_id": file_id, "kind": "resolved"})
        client.post("/api/knowledge-base/vote", json={"file_id": file_id, "kind": "resolved"})
        target = next(
            x for x in client.get("/api/knowledge-base").json()["items"]
            if x["file_id"] == file_id
        )
        assert target["resolved_count"] == 2

    def test_invalid_vote_kind_rejected(self, client):
        _share_answer(client, "テスト", "テスト")
        file_id = client.get("/api/knowledge-base").json()["items"][0]["file_id"]
        r = client.post("/api/knowledge-base/vote", json={"file_id": file_id, "kind": "neutral"})
        assert r.status_code in (400, 422)

    def test_vote_for_unknown_file_404(self, client):
        r = client.post(
            "/api/knowledge-base/vote",
            json={"file_id": "user-shared-99999999-999999-nonexistent", "kind": "up"},
        )
        assert r.status_code == 404


# ============================================================
# /knowledge-base ページ
# ============================================================
class TestKnowledgeBasePage:
    def test_page_renders(self, client):
        r = client.get("/knowledge-base")
        assert r.status_code == 200
        assert "みんなのナレッジ" in r.text

    def test_page_shows_version_badge(self, client):
        from app import __version__
        r = client.get("/knowledge-base")
        assert f"v{__version__}" in r.text


# ============================================================
# 入力サジェスト経由（検索 API を流用）
# ============================================================
class TestInputSuggestion:
    def test_search_returns_matching_questions(self, client):
        _share_answer(client, "VPN 接続方法 詳細", "FortiClient で接続")
        r = client.get("/api/knowledge-base?q=VPN&limit=5")
        items = r.json()["items"]
        assert items
        assert "VPN" in items[0]["question"]
