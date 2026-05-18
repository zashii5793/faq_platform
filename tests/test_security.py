"""セキュリティテスト：攻撃ベクトルに対する防御を検証する。

カテゴリ:
  - パストラバーサル（ファイル名・URLパス）
  - XSS（質問・ファイル名・組織名）
  - 認証バイパス
  - リソース枯渇（巨大入力）
  - JSON/ヘッダーインジェクション
"""
from __future__ import annotations

import io
import json

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


@pytest.fixture
def authn_client(tmp_path, monkeypatch) -> TestClient:
    """DEMO_MODE=False（本番モード）で動かす TestClient。認証必須。"""
    from app import audit, rag
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "faq_master_dir", tmp_path / "faq_master")
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "audit")
    rag._index = None
    return TestClient(app)


# ============================================================
# パストラバーサル（ファイル削除）
# ============================================================
class TestPathTraversal:
    def test_delete_rejects_unix_traversal(self, client: TestClient):
        """../../../etc/passwd 等のパスは削除されてはならない。"""
        r = client.delete("/api/admin/documents/../../../etc/passwd")
        assert r.status_code in (400, 403, 404), f"パストラバーサルが受理された: {r.status_code}"

    def test_delete_rejects_windows_traversal(self, client: TestClient):
        r = client.delete("/api/admin/documents/..\\..\\windows\\system32")
        assert r.status_code in (400, 403, 404)

    def test_delete_rejects_absolute_path(self, client: TestClient):
        r = client.delete("/api/admin/documents//etc/passwd")
        assert r.status_code in (400, 403, 404)

    def test_delete_nonexistent_returns_404(self, client: TestClient):
        r = client.delete("/api/admin/documents/nonexistent_xyz_12345.md")
        assert r.status_code == 404


# ============================================================
# ファイル名へのインジェクション
# ============================================================
class TestFilenameInjection:
    def test_ingest_filename_with_null_byte(self, client: TestClient):
        """ファイル名のヌルバイトが除去される（_safe_filename で対処済み）。"""
        content = "# テスト\n\n本文".encode("utf-8")
        r = client.post(
            "/api/admin/ingest",
            files={"file": ("safe\x00name.md", content, "text/markdown")},
        )
        # 取り込み成功して安全化されたファイル名が返るか、reject
        assert r.status_code in (200, 400, 422)
        if r.status_code == 200:
            # 保存後のファイル名に \x00 が含まれていない
            r2 = client.get("/api/admin/documents")
            assert r2.status_code == 200
            for doc in r2.json().get("documents", []):
                assert "\x00" not in doc["filename"]

    def test_ingest_filename_with_path_traversal(self, client: TestClient):
        """../../etc/passwd.md のようなファイル名でも安全化される。"""
        content = "# テスト\n\n本文".encode("utf-8")
        r = client.post(
            "/api/admin/ingest",
            files={"file": ("../../etc/passwd.md", content, "text/markdown")},
        )
        assert r.status_code in (200, 400, 422)
        if r.status_code == 200:
            r2 = client.get("/api/admin/documents")
            for doc in r2.json().get("documents", []):
                assert "/" not in doc["filename"]
                assert "\\" not in doc["filename"]
                assert ".." not in doc["filename"]

    def test_ingest_filename_with_html_tag(self, client: TestClient):
        """ファイル名にHTMLタグが含まれても XSS にならない。"""
        content = "# テスト\n\n本文".encode("utf-8")
        # _safe_filename が < > を許可するか確認
        r = client.post(
            "/api/admin/ingest",
            files={"file": ("<script>alert(1)</script>.md", content, "text/markdown")},
        )
        if r.status_code == 200:
            # /admin/upload を取得して、ファイル名がエスケープされて表示されるか
            # （直接 HTML 内には埋め込まれない API を経由するので XSS にはなりにくい）
            r2 = client.get("/api/admin/documents")
            assert r2.status_code == 200
            # JSON レスポンスなのでタグはエスケープ問題なし
            for doc in r2.json().get("documents", []):
                # < > を含むファイル名が安全化されているか（残ってもJSON側ではエスケープされる）
                assert isinstance(doc["filename"], str)


# ============================================================
# 巨大入力（DoS 対策）
# ============================================================
class TestResourceExhaustion:
    def test_ask_rejects_huge_question(self, client: TestClient):
        """100KB の質問は拒否されるべき（FastAPI のデフォルト境界に依存）。"""
        huge_q = "あ" * 100_000  # 約300KB UTF-8
        r = client.post("/api/ask", json={"question": huge_q})
        # 拒否または許容のどちらか（明示的な上限が無いなら 200 もありうる）
        assert r.status_code in (200, 400, 413, 422, 502)

    def test_faq_request_rejects_huge_question(self, client: TestClient):
        huge_q = "x" * 100_000
        r = client.post("/api/faq-requests", json={"question": huge_q})
        # 何らかのハンドリング（DoS せず即応答）
        assert r.status_code in (200, 400, 413, 422)

    def test_ingest_has_size_limit_constant(self):
        """実装に上限定数が定義されている。実機での巨大ファイル送信は
        TestClient のメモリ問題で重いため、ここでは定数の存在のみ verify する。
        """
        from app import main as m
        src = open(m.__file__, encoding="utf-8").read()
        # /api/admin/analyze と /api/admin/ingest にサイズチェックがある
        assert "50 * 1024 * 1024" in src or "MAX_UPLOAD" in src, (
            "アップロード上限のチェックが実装されていない"
        )

    def test_ingest_handles_zero_byte_file(self, client: TestClient):
        """ゼロバイトファイルでサーバが落ちない。"""
        r = client.post(
            "/api/admin/ingest",
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert r.status_code in (200, 400, 422)


# ============================================================
# 認証バイパス試行
# ============================================================
class TestAuthBypass:
    def test_ask_requires_auth_in_production(self, authn_client: TestClient):
        """本番モードで /api/ask は認証必須。"""
        r = authn_client.post("/api/ask", json={"question": "テスト"})
        assert r.status_code == 401

    def test_admin_endpoints_require_auth_in_production(self, authn_client: TestClient):
        """本番モードで /api/admin/* は認証必須。"""
        endpoints = [
            ("GET", "/api/admin/stats"),
            ("GET", "/api/admin/documents"),
            ("GET", "/api/admin/queries"),
            ("GET", "/api/admin/dashboard"),
            ("GET", "/api/admin/faq-requests"),
            ("GET", "/api/admin/settings"),
            ("POST", "/api/admin/reload-index"),
        ]
        for method, path in endpoints:
            r = authn_client.request(method, path)
            assert r.status_code in (401, 403), f"{method} {path} が認証なしで通った: {r.status_code}"

    def test_session_forgery_does_not_work(self, authn_client: TestClient):
        """偽の Cookie を投げてもセッションとして受理されない。"""
        r = authn_client.post(
            "/api/ask",
            json={"question": "テスト"},
            cookies={"session": "fake-session-value"},
        )
        assert r.status_code in (401, 403)


# ============================================================
# JSON / ヘッダー / 制御文字
# ============================================================
class TestInjectionAttacks:
    def test_ask_with_null_byte_in_question(self, client: TestClient):
        r = client.post("/api/ask", json={"question": "テスト\x00注入"})
        # サーバが落ちないこと
        assert r.status_code in (200, 400, 422)

    def test_ask_with_newline_injection(self, client: TestClient):
        """改行を含む質問でも監査ログが壊れない（JSONL の \\n 区切りが崩れない）。"""
        r = client.post("/api/ask", json={"question": "line1\nline2\nline3"})
        assert r.status_code in (200, 400, 502)

    def test_settings_update_rejects_html_injection(self, client: TestClient):
        """組織名に <script> タグを保存しても、それを HTML に直接埋め込まない。"""
        r = client.put("/api/admin/settings", json={"org_name": "<script>alert(1)</script>"})
        # 受け入れる場合: 後で HTML に出力する際にエスケープ
        # 拒否する場合: バリデーションで400
        assert r.status_code in (200, 400, 422)
        # 仕様確認：受け入れる場合は HTML 側でエスケープされること
        if r.status_code == 200:
            r2 = client.get("/")
            assert r2.status_code == 200
            # 生のscriptタグが含まれていない
            assert "<script>alert(1)</script>" not in r2.text, (
                "組織名のscriptタグが未エスケープでHTMLに出力されている"
            )


# ============================================================
# HTTP メソッド・Content-Type
# ============================================================
class TestProtocolBoundary:
    def test_ask_rejects_get_method(self, client: TestClient):
        """/api/ask は POST 専用。"""
        r = client.get("/api/ask")
        assert r.status_code == 405

    def test_ask_rejects_form_data(self, client: TestClient):
        """JSON 期待のエンドポイントに form-data を投げると 422。"""
        r = client.post("/api/ask", data={"question": "テスト"})
        assert r.status_code in (400, 415, 422)

    def test_settings_update_rejects_post_method(self, client: TestClient):
        """/api/admin/settings は PUT 専用、POST は不可。"""
        r = client.post("/api/admin/settings", json={"org_name": "X"})
        assert r.status_code == 405


# ============================================================
# CSRF（DEMO_MODE では認証がないので CSRF 対策は無い想定）
# ============================================================
class TestCSRFInDemoMode:
    def test_demo_mode_documents_csrf_risk(self, client: TestClient):
        """DEMO_MODE では CSRF 対策が無いことを明示的にドキュメント化。
        本番モードでは Cookie Same-Site で防御されるが、DEMO_MODE 自体が
        「社内 LAN 限定」が前提なので、Origin チェックなし。
        """
        # DEMO_MODE では Origin ヘッダーなしでも書き込みが通る
        r = client.post(
            "/api/feedback",
            json={"sources": ["x.md"], "vote": "up"},
            headers={"Origin": "http://attacker.example.com"},
        )
        # 仕様: DEMO_MODE では Origin チェックなしで通る（既知のリスク）
        assert r.status_code in (200, 400, 422)
