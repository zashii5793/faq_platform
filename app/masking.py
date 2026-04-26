"""送信前のマスキング。学校名・個人情報の検出を簡易で行う初期実装。"""
from __future__ import annotations

import re

# TBD: 実運用では辞書を社内で整備する
SCHOOL_PATTERNS = [
    re.compile(r"[一-鿿]+(?:学園|学院|高校|中学|小学校|大学|短大|専門学校)"),
]
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"\b0\d{1,4}[-(]?\d{1,4}[-)]?\d{3,4}\b")


def mask(text: str) -> str:
    out = text
    for p in SCHOOL_PATTERNS:
        out = p.sub("[学校名]", out)
    out = EMAIL_RE.sub("[メール]", out)
    out = PHONE_RE.sub("[電話番号]", out)
    return out
