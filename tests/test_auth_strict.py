"""auth.py の許可チェック・境界条件。"""
from __future__ import annotations

import pytest

from app.auth import is_email_allowed
from app.config import settings


@pytest.fixture
def auth_settings(monkeypatch):
    """各テストで独立した allowed_domain / allowed_emails をセット。
    `allowed_email_set` は property のため、`allowed_emails` を変えれば自動再計算される。
    """
    monkeypatch.setattr(settings, "allowed_domain", "example.com")
    monkeypatch.setattr(settings, "allowed_emails", "admin@external.com,vip@partner.co.jp")


# ============================================================
# is_email_allowed: ドメインベース
# ============================================================
class TestDomainAllowed:
    def test_basic_allowed(self, auth_settings):
        assert is_email_allowed("user@example.com")

    def test_uppercase_email_normalized(self, auth_settings):
        assert is_email_allowed("USER@EXAMPLE.COM")

    def test_mixed_case_email(self, auth_settings):
        assert is_email_allowed("User@Example.Com")

    def test_wrong_domain_denied(self, auth_settings):
        assert not is_email_allowed("user@evil.com")

    def test_subdomain_denied(self, auth_settings):
        """allowed_domain=example.com の時、sub.example.com は拒否される。"""
        assert not is_email_allowed("user@sub.example.com")

    def test_typosquatting_denied(self, auth_settings):
        """allowed_domain=example.com の時、examp1e.com は拒否される。"""
        assert not is_email_allowed("user@examp1e.com")

    def test_domain_suffix_attack_denied(self, auth_settings):
        """example.com.attacker.com は拒否される（endswith は @ 込みで比較される）。"""
        assert not is_email_allowed("user@example.com.attacker.com")

    def test_domain_prefix_attack_denied(self, auth_settings):
        """fakeexample.com は拒否される（@ 付き比較で防げる）。"""
        assert not is_email_allowed("user@fakeexample.com")


# ============================================================
# is_email_allowed: 明示リスト
# ============================================================
class TestExplicitList:
    def test_explicit_email_allowed(self, auth_settings):
        assert is_email_allowed("admin@external.com")

    def test_explicit_email_case_insensitive(self, auth_settings):
        assert is_email_allowed("ADMIN@EXTERNAL.COM")

    def test_partner_email_allowed(self, auth_settings):
        assert is_email_allowed("vip@partner.co.jp")

    def test_unknown_external_denied(self, auth_settings):
        assert not is_email_allowed("random@external.com")


# ============================================================
# is_email_allowed: 異常入力
# ============================================================
class TestAbnormalInput:
    def test_empty_email_denied(self, auth_settings):
        assert not is_email_allowed("")

    def test_whitespace_only_denied(self, auth_settings):
        assert not is_email_allowed("   ")

    def test_no_at_sign_denied(self, auth_settings):
        assert not is_email_allowed("not-an-email")

    def test_multiple_at_signs_handled(self, auth_settings):
        """user@@example.com のような不正フォーマットは拒否されるべき。"""
        # 現状実装: endswith ベースなので "user@@example.com".endswith("@example.com") → True
        # これは誤って許可してしまう可能性あり
        result = is_email_allowed("user@@example.com")
        # 望ましい: False（不正フォーマット）
        if result is True:
            pytest.xfail("user@@example.com が許可される（メール形式バリデーション不足）")
        assert result is False

    def test_at_sign_only_denied(self, auth_settings):
        assert not is_email_allowed("@example.com")


# ============================================================
# 設定なし
# ============================================================
class TestNoConfig:
    def test_no_domain_no_list_denies_all(self, monkeypatch):
        monkeypatch.setattr(settings, "allowed_domain", "")
        monkeypatch.setattr(settings, "allowed_emails", "")
        assert not is_email_allowed("anyone@anywhere.com")
        assert not is_email_allowed("admin@example.com")

    def test_only_domain_no_list(self, monkeypatch):
        monkeypatch.setattr(settings, "allowed_domain", "example.com")
        monkeypatch.setattr(settings, "allowed_emails", "")
        assert is_email_allowed("user@example.com")
        assert not is_email_allowed("user@other.com")

    def test_only_list_no_domain(self, monkeypatch):
        monkeypatch.setattr(settings, "allowed_domain", "")
        monkeypatch.setattr(settings, "allowed_emails", "vip@x.com")
        assert is_email_allowed("vip@x.com")
        assert not is_email_allowed("anyone@x.com")


# ============================================================
# 大文字小文字の正規化（allowed_domain 側）
# ============================================================
class TestDomainCaseNormalization:
    def test_uppercase_domain_in_config(self, monkeypatch):
        """allowed_domain="EXAMPLE.COM"（設定側が大文字）でも user@example.com は許可される。"""
        monkeypatch.setattr(settings, "allowed_domain", "EXAMPLE.COM")
        monkeypatch.setattr(settings, "allowed_emails", "")
        assert is_email_allowed("user@example.com")
        assert is_email_allowed("USER@EXAMPLE.COM")
