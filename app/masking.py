"""送信前マスキング。汎用 PII パターンを業界別に拡張可能。

実装ポリシー:
- 完全な PII 除去は保証しない（深層モデル必須レベル）。"見落とし時の被害を減らす"目的の防御層
- 業界・組織ごとに `EXTRA_PATTERNS` を追加して拡張する想定
- マスクトークンは LLM がそのまま尊重するよう、構造化された記法 [カテゴリ] を使う
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass
class MaskRule:
    name: str
    pattern: re.Pattern[str]
    replacement: str


# --- 汎用パターン（どの業界でも共通） ---
GENERIC_RULES: list[MaskRule] = [
    MaskRule(
        "email",
        re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
        "[メール]",
    ),
    MaskRule(
        "phone_intl",
        # +81-3-1234-5678 / +1 (212) 555-1234 など国際電話
        re.compile(r"\+\d{1,3}[\s\-(]*\d{1,4}[\s\-)]*\d{1,4}[\s\-]*\d{3,4}"),
        "[電話番号]",
    ),
    MaskRule(
        "phone_jp",
        # 半角: 03-1234-5678 / 090-1234-5678 / 0312345678
        # 全角括弧: （03）1234-5678
        re.compile(r"[(（]?\b0\d{1,4}[)）]?[-\s]?\d{1,4}[-\s]?\d{3,4}\b"),
        "[電話番号]",
    ),
    MaskRule(
        "phone_jp_zenkaku",
        # 全角数字: ０３−１２３４−５６７８
        re.compile(r"[(（]?０[０-９]{1,4}[)）]?[\-−ー－\s]?[０-９]{1,4}[\-−ー－\s]?[０-９]{3,4}"),
        "[電話番号]",
    ),
    MaskRule(
        "credit_card",
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        "[カード番号]",
    ),
    MaskRule(
        "my_number",
        re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"),
        "[マイナンバー]",
    ),
    MaskRule(
        "ipv6",
        # IPv6 (フル形式 + 省略形 ::）— 先に評価して IPv4 と競合させない
        re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b|::[0-9a-fA-F:]+|[0-9a-fA-F:]+::[0-9a-fA-F:]*"),
        "[IPアドレス]",
    ),
    MaskRule(
        "ip_address",
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        "[IPアドレス]",
    ),
    MaskRule(
        "url",
        # 末尾の日本語句読点（。、）と半角句読点（.,;!?）が URL に含まれないようにする
        re.compile(r"https?://[^\s。、，．！？]+"),
        "[URL]",
    ),
]


# --- 業界別パターン ---
EDUCATION_RULES: list[MaskRule] = [
    MaskRule(
        "school_name",
        # 漢字・ひらがな・カタカナ・全角英数字（Ａ-Ｚ Ａ-ｚ ０-９）・記号 ＋ 校種
        re.compile(
            r"[一-鿿ぁ-んァ-ヶー々〇○Ａ-Ｚａ-ｚ０-９]+"
            r"(?:学園|学院|高校|中学校|中学|小学校|大学|短大|専門学校)"
        ),
        "[学校名]",
    ),
]

HEALTHCARE_RULES: list[MaskRule] = [
    MaskRule(
        "medical_record_number",
        re.compile(r"\bMRN[-_]?\d{4,}\b", re.IGNORECASE),
        "[診療番号]",
    ),
]

FINANCE_RULES: list[MaskRule] = [
    MaskRule(
        "bank_account",
        re.compile(r"\b\d{7}\b"),
        "[口座番号]",
    ),
]

INDUSTRY_PRESETS: dict[str, list[MaskRule]] = {
    "education": EDUCATION_RULES,
    "healthcare": HEALTHCARE_RULES,
    "finance": FINANCE_RULES,
    "general": [],
}


def build_rules(industry: str = "general", extra: Iterable[MaskRule] = ()) -> list[MaskRule]:
    rules = list(GENERIC_RULES)
    rules.extend(INDUSTRY_PRESETS.get(industry, []))
    rules.extend(extra)
    return rules


def mask(text: str, rules: list[MaskRule] | None = None) -> str:
    if rules is None:
        # config から industry を読む（循環import回避のため遅延）
        from .config import settings

        rules = build_rules(settings.masking_industry)
    out = text
    for r in rules:
        out = r.pattern.sub(r.replacement, out)
    return out
