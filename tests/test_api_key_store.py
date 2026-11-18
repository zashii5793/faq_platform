"""お客さまが自分の Anthropic API キーを登録する（BYOK）ことの検証。

守りたいこと:
  - 平文のキーが、保存ファイル・API の応答・監査ログのどこにも出ない
  - キーを変えられるのは ADMIN_EMAILS の人だけ。未設定なら誰も変えられない
  - 既定の合言葉では保存させない（暗号化したふりにしない）
  - 画面で登録したキーが無ければ、従来どおり .env のキーで動く
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

GOOD = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 3
OTHER = "sk-ant-api03-" + "Z9y8X7w6V5u4T3s2R1q0" * 3


@pytest.fixture
def store(tmp_path, monkeypatch):
    from app import api_key_store
    from app.config import settings

    monkeypatch.setattr(settings, "api_key_path", tmp_path / "api_key.enc")
    monkeypatch.setattr(settings, "session_secret", "test-session-secret-0123456789")
    monkeypatch.setattr(settings, "key_encryption_secret", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "admin_emails", "boss@example.com")
    return api_key_store


def _client(tmp_path, monkeypatch, email: str | None):
    """本番モード（DEMO_MODE=False）で、指定したメールでログインしている状態の TestClient。"""
    from app import audit, rag
    from app.auth import require_user
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "faq_master_dir", tmp_path / "faq_master")
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "audit")
    rag._index = None
    if email:
        app.dependency_overrides[require_user] = lambda: {"email": email, "name": "x"}
    client = TestClient(app)
    return client


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    from app.main import app
    app.dependency_overrides.clear()


class TestStore:
    def test_falls_back_to_env_when_nothing_stored(self, store, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "anthropic_api_key", OTHER)
        assert store.effective_key() == OTHER
        assert store.status()["source"] == "env"

    def test_none_when_no_key_anywhere(self, store):
        assert store.effective_key() == ""
        assert store.status() == {"source": "none", "masked": "", "updated_at": "", "updated_by": ""}

    def test_saved_key_wins_over_env_and_is_not_plaintext_on_disk(self, store, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "anthropic_api_key", OTHER)
        store.save(GOOD, "boss@example.com")
        assert store.effective_key() == GOOD
        raw = settings.api_key_path.read_text(encoding="utf-8")
        assert GOOD not in raw and GOOD[-12:] not in raw
        assert store.status()["source"] == "ui"
        assert store.status()["masked"] == "sk-ant-…" + GOOD[-4:]

    def test_file_is_private(self, store):
        from app.config import settings
        store.save(GOOD, "boss@example.com")
        assert oct(settings.api_key_path.stat().st_mode & 0o777) == "0o600"

    def test_clear_returns_to_env(self, store, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "anthropic_api_key", OTHER)
        store.save(GOOD, "boss@example.com")
        store.clear()
        assert store.effective_key() == OTHER
        store.clear()  # 2回目も落ちない

    def test_unreadable_after_secret_changes(self, store, monkeypatch):
        from app.config import settings
        store.save(GOOD, "boss@example.com")
        monkeypatch.setattr(settings, "session_secret", "another-secret-9876543210")
        assert store.effective_key() == ""
        assert store.status()["source"] == "unreadable"

    @pytest.mark.parametrize("bad", ["", "   ", "sk-proj-abc", "sk-ant-short", "sk-ant-" + "a" * 19, "x" + GOOD, GOOD + " extra"])
    def test_rejects_malformed_keys(self, store, bad):
        with pytest.raises(store.KeyStoreError):
            store.save(bad, "boss@example.com")

    def test_refuses_default_secret_outside_demo(self, store, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "session_secret", store.DEFAULT_SESSION_SECRET)
        with pytest.raises(store.KeyStoreError):
            store.save(GOOD, "boss@example.com")
        assert not settings.api_key_path.exists()

    def test_key_encryption_secret_is_preferred(self, store, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "key_encryption_secret", "dedicated-secret-abcdef")
        store.save(GOOD, "boss@example.com")
        # session_secret が変わっても、専用の合言葉が同じなら読める
        monkeypatch.setattr(settings, "session_secret", "rotated-session-secret-xyz")
        assert store.effective_key() == GOOD


class TestCanManage:
    def test_admin_only(self, store):
        assert store.can_manage({"email": "Boss@Example.com"})
        assert not store.can_manage({"email": "staff@example.com"})
        assert not store.can_manage({})

    def test_nobody_when_admins_not_configured(self, store, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "admin_emails", "")
        assert not store.can_manage({"email": "boss@example.com"})

    def test_demo_mode_allows(self, store, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "demo_mode", True)
        assert store.can_manage({"email": "demo@local"})


class TestEndpoints:
    def test_get_never_returns_plaintext(self, store, tmp_path, monkeypatch):
        store.save(GOOD, "boss@example.com")
        c = _client(tmp_path, monkeypatch, "staff@example.com")
        r = c.get("/api/admin/api-key")
        assert r.status_code == 200
        assert GOOD not in r.text
        body = r.json()
        assert body["source"] == "ui" and body["can_manage"] is False

    def test_non_admin_cannot_set_or_clear(self, store, tmp_path, monkeypatch):
        c = _client(tmp_path, monkeypatch, "staff@example.com")
        assert c.put("/api/admin/api-key", json={"key": GOOD, "verify": False}).status_code == 403
        assert c.delete("/api/admin/api-key").status_code == 403
        assert store.effective_key() == ""

    def test_signed_out_is_rejected(self, store, tmp_path, monkeypatch):
        c = _client(tmp_path, monkeypatch, None)
        assert c.get("/api/admin/api-key").status_code == 401
        assert c.put("/api/admin/api-key", json={"key": GOOD, "verify": False}).status_code == 401

    def test_admin_sets_and_clears(self, store, tmp_path, monkeypatch):
        c = _client(tmp_path, monkeypatch, "boss@example.com")
        r = c.put("/api/admin/api-key", json={"key": GOOD, "verify": False})
        assert r.status_code == 200, r.text
        assert GOOD not in r.text and r.json()["source"] == "ui"
        assert store.effective_key() == GOOD
        r = c.delete("/api/admin/api-key")
        assert r.status_code == 200 and r.json()["source"] == "none"

    def test_malformed_key_is_400(self, store, tmp_path, monkeypatch):
        c = _client(tmp_path, monkeypatch, "boss@example.com")
        assert c.put("/api/admin/api-key", json={"key": "sk-proj-xyz", "verify": False}).status_code == 400

    def test_verify_rejects_invalid_key(self, store, tmp_path, monkeypatch):
        import anthropic
        import httpx
        from app import main

        class FakeModels:
            def list(self, **kw):
                req = httpx.Request("GET", "https://api.anthropic.com/v1/models")
                raise anthropic.AuthenticationError("bad", response=httpx.Response(401, request=req), body=None)

        class FakeClient:
            def __init__(self, api_key):
                self.models = FakeModels()

        monkeypatch.setattr(main, "Anthropic", FakeClient)
        c = _client(tmp_path, monkeypatch, "boss@example.com")
        r = c.put("/api/admin/api-key", json={"key": GOOD, "verify": True})
        assert r.status_code == 400
        assert store.effective_key() == ""  # 確かめられなかったキーは保存しない

    def test_verify_accepts_valid_key(self, store, tmp_path, monkeypatch):
        from app import main

        class FakeClient:
            def __init__(self, api_key):
                assert api_key == GOOD
                self.models = type("M", (), {"list": lambda self, **kw: []})()

        monkeypatch.setattr(main, "Anthropic", FakeClient)
        c = _client(tmp_path, monkeypatch, "boss@example.com")
        assert c.put("/api/admin/api-key", json={"key": GOOD, "verify": True}).status_code == 200
        assert store.effective_key() == GOOD

    def test_audit_log_has_no_plaintext(self, store, tmp_path, monkeypatch):
        c = _client(tmp_path, monkeypatch, "boss@example.com")
        c.put("/api/admin/api-key", json={"key": GOOD, "verify": False})
        logs = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "audit").rglob("*") if p.is_file())
        assert "api_key_set" in logs
        assert GOOD not in logs

    def test_setting_key_clears_answer_cache(self, store, tmp_path, monkeypatch):
        from app import llm
        llm._answer_cache["k"] = ("old answer", 9e18)
        c = _client(tmp_path, monkeypatch, "boss@example.com")
        c.put("/api/admin/api-key", json={"key": GOOD, "verify": False})
        assert "k" not in llm._answer_cache


def test_llm_uses_stored_key(store, monkeypatch):
    """回答時に使うキーが、画面で登録したものになっていること。"""
    from app import llm
    store.save(GOOD, "boss@example.com")
    seen = {}

    class FakeAnthropic:
        def __init__(self, api_key):
            seen["key"] = api_key

    monkeypatch.setattr(llm, "Anthropic", FakeAnthropic)
    llm._client()
    assert seen["key"] == GOOD


def test_status_json_serializable(store):
    json.dumps(store.status())
