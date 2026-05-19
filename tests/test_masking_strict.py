"""厳しめのマスキング検証。誤検知・取りこぼし・優先順位を炙り出す。

TDD的に「こうあってほしい」期待値で書いている。失敗するテストは仕様レビュー対象。
"""
from __future__ import annotations

import pytest

from app.masking import build_rules, mask


# ============================================================
# Email: 取りこぼし
# ============================================================
class TestEmailMasking:
    def test_basic_email(self):
        assert "[メール]" in mask("contact me at test@example.com please", build_rules("general"))

    def test_email_with_plus_alias(self):
        assert "[メール]" in mask("alice+work@example.co.jp", build_rules("general"))

    def test_email_with_subdomain(self):
        assert "[メール]" in mask("user@mail.example.co.jp", build_rules("general"))

    def test_email_with_dot_in_local(self):
        assert "[メール]" in mask("first.last@example.com", build_rules("general"))

    def test_japanese_local_part_email(self):
        """日本語ローカル部のメールアドレス（RFC 6532 準拠）はマスクされるべき。"""
        text = "宛先は 山田@example.com です"
        out = mask(text, build_rules("general"))
        assert "[メール]" in out, f"日本語ローカル部メールがマスクされていない: {out}"

    def test_email_in_url_should_not_double_mask(self):
        """URL の中に @ を含むケースは URL マスク優先で問題なし。"""
        text = "https://user@example.com/path"
        out = mask(text, build_rules("general"))
        assert "[URL]" in out or "[メール]" in out


# ============================================================
# 電話番号: 国際形式・全角の取りこぼし
# ============================================================
class TestPhoneMasking:
    def test_basic_jp_phone(self):
        assert "[電話番号]" in mask("お電話は 03-1234-5678 まで", build_rules("general"))

    def test_mobile_phone(self):
        assert "[電話番号]" in mask("携帯: 090-1234-5678", build_rules("general"))

    def test_international_format_plus_81(self):
        """+81 形式の国際電話番号もマスクされるべき。"""
        text = "国際: +81-3-1234-5678"
        out = mask(text, build_rules("general"))
        assert "[電話番号]" in out, f"+81形式がマスクされていない: {out}"

    def test_zenkaku_phone(self):
        """全角数字の電話番号もマスクされるべき。"""
        text = "電話：０３−１２３４−５６７８"
        out = mask(text, build_rules("general"))
        assert "[電話番号]" in out, f"全角電話がマスクされていない: {out}"

    def test_phone_with_zenkaku_paren(self):
        """全角括弧 （03）1234-5678 もマスクされるべき。"""
        text = "（03）1234-5678 まで"
        out = mask(text, build_rules("general"))
        assert "[電話番号]" in out, f"全角括弧電話がマスクされていない: {out}"


# ============================================================
# クレジットカード番号: 誤検知
# ============================================================
class TestCreditCardMasking:
    def test_basic_credit_card(self):
        assert "[カード番号]" in mask("VISA: 4111-1111-1111-1111", build_rules("general"))

    def test_credit_card_with_spaces(self):
        assert "[カード番号]" in mask("4111 1111 1111 1111", build_rules("general"))

    def test_credit_card_no_separator(self):
        assert "[カード番号]" in mask("4111111111111111", build_rules("general"))

    def test_phone_not_misdetected_as_credit_card(self):
        """13-19桁ルールで電話番号が誤ってカード判定されるべきではない。"""
        text = "電話は 03-1234-5678 です"
        out = mask(text, build_rules("general"))
        assert "[カード番号]" not in out, f"電話番号がカード扱いされた: {out}"

    def test_isbn_not_misdetected(self):
        """ISBN13 は Luhn を通過しないため誤検知されない。"""
        text = "ISBN: 978-4-12-345678-9"
        out = mask(text, build_rules("general"))
        assert "[カード番号]" not in out, f"ISBN が誤検知された: {out}"

    def test_timestamp_not_misdetected(self):
        """タイムスタンプ「2024-06-24 084412」を誤ってカード判定しない（Backlog データで報告済み）。"""
        text = "スクリーンショット 2024-06-24 084412.png"
        out = mask(text, build_rules("general"))
        assert "[カード番号]" not in out, f"タイムスタンプが誤検知された: {out}"

    def test_id_sequence_not_misdetected(self):
        """連番 ID（タイムスタンプ風）も誤検知しない。"""
        text = "ID: 42079622 / プロジェクトID: 48954 / キーID: 830"
        out = mask(text, build_rules("general"))
        assert "[カード番号]" not in out

    def test_real_visa_detected(self):
        """正しい VISA テスト番号は検出される。"""
        # VISA テスト番号 (Luhn 通過)
        text = "カード: 4111-1111-1111-1111"
        out = mask(text, build_rules("general"))
        assert "[カード番号]" in out

    def test_real_amex_detected(self):
        """AMEX テスト番号 (15桁・Luhn 通過) も検出される。"""
        text = "AMEX: 3782-822463-10005"
        out = mask(text, build_rules("general"))
        assert "[カード番号]" in out


# ============================================================
# マイナンバー
# ============================================================
class TestMyNumberMasking:
    def test_basic_my_number_dash(self):
        assert "[マイナンバー]" in mask("マイナンバー: 1234-5678-9012", build_rules("general"))

    def test_my_number_no_separator(self):
        assert "[マイナンバー]" in mask("番号 123456789012 を提示", build_rules("general"))

    def test_my_number_with_spaces(self):
        assert "[マイナンバー]" in mask("1234 5678 9012", build_rules("general"))


# ============================================================
# IP アドレス
# ============================================================
class TestIPMasking:
    def test_ipv4(self):
        assert "[IPアドレス]" in mask("接続先: 192.168.1.1", build_rules("general"))

    def test_invalid_ip_still_matches_by_regex(self):
        """範囲外（999.999.999.999）でも regex はマッチする想定（現状仕様）。"""
        text = "999.999.999.999"
        out = mask(text, build_rules("general"))
        # 仕様: 単純な regex なので範囲チェックなし→マッチする
        assert "[IPアドレス]" in out

    def test_ipv6_should_be_masked(self):
        """IPv6 アドレスもマスク対象にすべき。"""
        text = "サーバ: 2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        out = mask(text, build_rules("general"))
        assert "[IPアドレス]" in out, f"IPv6がマスクされていない: {out}"


# ============================================================
# URL
# ============================================================
class TestURLMasking:
    def test_http_url(self):
        assert "[URL]" in mask("見て: http://example.com/x", build_rules("general"))

    def test_https_url(self):
        assert "[URL]" in mask("https://example.com/x", build_rules("general"))

    def test_url_strips_trailing_punctuation(self):
        """文末の句読点を URL に含めない方が望ましい。"""
        text = "https://example.com/x。次の文"
        out = mask(text, build_rules("general"))
        # 望ましい: 「。次の文」が残る
        # 現状: 「[URL]次の文」になる（句読点まで貪欲マッチ）
        assert "[URL]" in out
        assert "次の文" in out, f"句読点まで貪欲マッチで本文が失われた: {out}"


# ============================================================
# 学校名（教育業界プリセット）
# ============================================================
class TestSchoolMasking:
    def test_basic_university(self):
        assert "[学校名]" in mask("東京大学に通っています", build_rules("education"))

    def test_basic_gakuen(self):
        assert "[学校名]" in mask("○○学園の件で", build_rules("education"))

    def test_zenkaku_alphabet_school_name(self):
        """全角英字の校名（例: ＡＢＣ大学）もマスクすべき。"""
        text = "ＡＢＣ大学に在籍"
        out = mask(text, build_rules("education"))
        assert "[学校名]" in out, f"全角英字校名がマスクされていない: {out}"

    def test_no_school_in_general_industry(self):
        assert "[学校名]" not in mask("東京大学", build_rules("general"))


# ============================================================
# 業界プリセット切替
# ============================================================
class TestIndustryPreset:
    def test_unknown_industry_falls_back_to_generic(self):
        """未知の industry 名でも generic ルールは適用される。"""
        rules = build_rules("nonexistent_industry")
        assert "[メール]" in mask("test@example.com", rules)

    def test_finance_bank_account(self):
        """金融業界では 7桁口座番号をマスク。"""
        rules = build_rules("finance")
        out = mask("口座番号: 1234567", rules)
        assert "[口座番号]" in out

    def test_healthcare_mrn(self):
        """医療業界では MRN-1234 形式をマスク。"""
        rules = build_rules("healthcare")
        out = mask("診療番号 MRN-12345", rules)
        assert "[診療番号]" in out


# ============================================================
# マスキング順序の安定性
# ============================================================
class TestMaskingOrder:
    def test_no_double_masking(self):
        """既にマスク済みの [メール] が再度マッチして二重マスクされない。"""
        text = "前回マスク済み: [メール] 今回: new@example.com"
        out = mask(text, build_rules("general"))
        # [メール] が2つ以上ある（前回分 + 今回分）
        assert out.count("[メール]") == 2

    def test_pii_in_url_handling(self):
        """URL 内の PII（メールアドレス含む URL）の扱いを定義。"""
        text = "https://internal.example.com/users?email=user@example.com"
        out = mask(text, build_rules("general"))
        # URL マスクが先にマッチするので、内部の email はマスクされない可能性
        # 仕様: URL 全体が [URL] になればOK
        assert "[URL]" in out or "[メール]" in out
