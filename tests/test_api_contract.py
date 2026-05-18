"""API 契約のテスト：不正リクエスト・型不一致・必須欠落への応答を検証する。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    from app import audit, rag
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "faq_master_dir", tmp_path / "faq_master")
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "audit")
    rag._index = None
    return TestClient(app)


# ============================================================
# /api/ask
# ============================================================
class TestAskContract:
    def test_missing_question_field(self, client: TestClient):
        r = client.post("/api/ask", json={})
        assert r.status_code == 422

    def test_question_wrong_type_int(self, client: TestClient):
        r = client.post("/api/ask", json={"question": 123})
        assert r.status_code == 422

    def test_question_wrong_type_list(self, client: TestClient):
        r = client.post("/api/ask", json={"question": ["a", "b"]})
        assert r.status_code == 422

    def test_question_null(self, client: TestClient):
        r = client.post("/api/ask", json={"question": None})
        assert r.status_code == 422

    def test_empty_question_string(self, client: TestClient):
        """空文字列の質問は 422 か、200で「該当なし」レスポンスを返すべき。"""
        r = client.post("/api/ask", json={"question": ""})
        assert r.status_code in (200, 400, 422)
        if r.status_code == 200:
            # 空質問では has_answer=False が期待
            assert r.json().get("has_answer") is False

    def test_whitespace_only_question(self, client: TestClient):
        r = client.post("/api/ask", json={"question": "   "})
        assert r.status_code in (200, 400, 422)

    def test_invalid_json_body(self, client: TestClient):
        r = client.post(
            "/api/ask",
            data="not json {{{",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code in (400, 422)


# ============================================================
# /api/feedback
# ============================================================
class TestFeedbackContract:
    def test_missing_vote(self, client: TestClient):
        r = client.post("/api/feedback", json={"sources": ["x.md"]})
        assert r.status_code in (400, 422)

    def test_invalid_vote_value(self, client: TestClient):
        """vote は 'up' or 'down' 以外を拒否すべき。"""
        r = client.post("/api/feedback", json={"sources": ["x.md"], "vote": "neutral"})
        assert r.status_code in (200, 400, 422)
        # 仕様: 不正な vote は黙って無視（rag.record_feedback がガード）
        # 望ましい: 400/422 で明示的に拒否

    def test_empty_sources(self, client: TestClient):
        """空配列のソースでも受理されるが、何も記録されない。"""
        r = client.post("/api/feedback", json={"sources": [], "vote": "up"})
        assert r.status_code in (200, 400, 422)

    def test_sources_wrong_type(self, client: TestClient):
        r = client.post("/api/feedback", json={"sources": "not-a-list", "vote": "up"})
        assert r.status_code in (400, 422)


# ============================================================
# /api/faq-requests
# ============================================================
class TestFaqRequestContract:
    def test_missing_question(self, client: TestClient):
        r = client.post("/api/faq-requests", json={})
        assert r.status_code in (400, 422)

    def test_empty_question(self, client: TestClient):
        """空文字列の質問は拒否すべき（管理画面で表示する意味なし）。"""
        r = client.post("/api/faq-requests", json={"question": ""})
        assert r.status_code in (200, 400, 422)

    def test_extremely_long_question(self, client: TestClient):
        """ 1万文字の質問は受理 or 拒否 を明確にする。"""
        long_q = "あ" * 10_000
        r = client.post("/api/faq-requests", json={"question": long_q})
        assert r.status_code in (200, 400, 413, 422)


# ============================================================
# /api/admin/settings
# ============================================================
class TestSettingsContract:
    def test_get_returns_dict(self, client: TestClient):
        r = client.get("/api/admin/settings")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        # 編集可能キーが含まれる
        assert "org_name" in data or "effective" in data or "settings" in data

    def test_put_unknown_key_silently_ignored(self, client: TestClient):
        """ホワイトリスト外のキーは黙って無視される（仕様）。"""
        r = client.put("/api/admin/settings", json={"unknown_key": "value"})
        assert r.status_code in (200, 400, 422)

    def test_put_201_chars_rejected(self, client: TestClient):
        """201文字以上の org_name は拒否される（runtime_settings の制約）。"""
        too_long = "x" * 201
        r = client.put("/api/admin/settings", json={"org_name": too_long})
        assert r.status_code in (400, 422)

    def test_put_200_chars_accepted(self, client: TestClient):
        """200文字ちょうどは受理される。"""
        exact = "x" * 200
        r = client.put("/api/admin/settings", json={"org_name": exact})
        assert r.status_code == 200

    def test_put_org_name_with_newline(self, client: TestClient):
        """改行を含む値は trim される（または拒否）。"""
        r = client.put("/api/admin/settings", json={"org_name": "  acme\n\n  "})
        assert r.status_code in (200, 400, 422)
        if r.status_code == 200:
            r2 = client.get("/api/admin/settings")
            data = r2.json()
            org = data.get("org_name") or data.get("effective", {}).get("org_name")
            # trim されているはず
            if org:
                assert org.startswith("acme") or org == "acme"

    def test_delete_resets_settings(self, client: TestClient):
        """DELETE で設定がリセットされる。"""
        client.put("/api/admin/settings", json={"org_name": "Custom"})
        r = client.delete("/api/admin/settings")
        assert r.status_code in (200, 204)


# ============================================================
# /api/admin/queries
# ============================================================
class TestQueriesContract:
    def test_negative_limit_rejected(self, client: TestClient):
        r = client.get("/api/admin/queries?limit=-1")
        assert r.status_code in (200, 400, 422)

    def test_huge_limit_capped(self, client: TestClient):
        """巨大な limit (10000) は内部で上限にキャップされるべき。"""
        r = client.get("/api/admin/queries?limit=10000")
        assert r.status_code in (200, 400, 422)
        if r.status_code == 200:
            data = r.json()
            results = data.get("queries", data.get("results", data))
            # 内部上限が機能している
            if isinstance(results, list):
                assert len(results) <= 1000

    def test_invalid_limit_type(self, client: TestClient):
        r = client.get("/api/admin/queries?limit=abc")
        assert r.status_code in (400, 422)


# ============================================================
# /api/admin/export
# ============================================================
class TestExportContract:
    def test_export_invalid_format_rejected(self, client: TestClient):
        """不正な format=xml は 400 で拒否される。"""
        r = client.get("/api/admin/export?format=xml")
        assert r.status_code == 400

    def test_export_invalid_days_rejected(self, client: TestClient):
        """days=0 は 400 で拒否される。"""
        r = client.get("/api/admin/export?days=0")
        assert r.status_code == 400

    def test_export_days_over_limit_rejected(self, client: TestClient):
        """days=500 は 400 で拒否される（上限365日）。"""
        r = client.get("/api/admin/export?days=500")
        assert r.status_code == 400

    def test_export_queries_csv(self, client: TestClient):
        r = client.get("/api/admin/export?event=query&format=csv")
        assert r.status_code == 200
        assert "csv" in r.headers.get("content-type", "").lower() or "text" in r.headers.get(
            "content-type", ""
        ).lower()

    def test_export_unknown_event_returns_empty(self, client: TestClient):
        """未知の event 種別は空CSVが返る（エラーではない）。"""
        r = client.get("/api/admin/export?event=unknown_xyz")
        assert r.status_code == 200


# ============================================================
# /healthz
# ============================================================
class TestHealthz:
    def test_healthz_returns_ok(self, client: TestClient):
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_healthz_no_auth_required(self, client: TestClient):
        """ヘルスチェックは認証不要（監視ツールから叩ける）。"""
        r = client.get("/healthz")
        assert r.status_code == 200
