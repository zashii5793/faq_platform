"""FAQ 候補化機能の設定（しきい値・自動承認モード）。

`data/faq_candidate_settings.json` に永続化される。管理画面の「FAQ 候補」タブから
情シスが調整する想定。初回起動時はデフォルト値が使われる。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from threading import RLock
from typing import Any

from .config import settings


@dataclass
class FaqCandidateSettings:
    # --- 検出のしきい値 ---
    # 候補化される会話の最低確信度（/api/ask の confidence は 0-100）
    min_confidence: int = 70
    # 同類質問が過去 lookback_days 日でこの回数以上聞かれた場合に候補化
    min_asked_count: int = 3
    # 別ユーザーが何人聞いたか（属人的な質問を弾く）
    min_unique_users: int = 2
    # 質問クラスタリングの類似度しきい値（cosine 0-1）
    # char-2gram + 単語のトークン化で、表記揺れのある同義質問は 0.55+ に分布する想定。
    # 「VPN の接続方法」「VPN の繋ぎ方」は同一に、「VPN の接続方法」「有給の申請方法」は
    # 別クラスタになるバランス値。管理画面から調整可能。
    similarity_threshold: float = 0.55
    # 何日分の監査ログを見るか
    lookback_days: int = 30

    # --- 自動承認モード ---
    auto_approve_enabled: bool = False
    # 自動承認の追加条件（min_* より厳しめに）
    auto_approve_min_confidence: int = 85
    auto_approve_min_asked_count: int = 5
    auto_approve_min_unique_users: int = 3

    # --- 検出のトリガー ---
    # 起動時に検出バッチを実行するか
    auto_detect_on_startup: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FaqCandidateSettings":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


_lock = RLock()
_cache: FaqCandidateSettings | None = None


def load() -> FaqCandidateSettings:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        path = settings.faq_candidate_settings_path
        if not path.exists():
            _cache = FaqCandidateSettings()
            return _cache
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _cache = FaqCandidateSettings.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            _cache = FaqCandidateSettings()
        return _cache


def save(s: FaqCandidateSettings) -> None:
    global _cache
    with _lock:
        path = settings.faq_candidate_settings_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(s), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _cache = s


def update(**kwargs: Any) -> FaqCandidateSettings:
    current = load()
    data = asdict(current)
    for k, v in kwargs.items():
        if k in data:
            data[k] = v
    new = FaqCandidateSettings.from_dict(data)
    save(new)
    return new


def reset_cache() -> None:
    """テスト用にキャッシュをクリア。"""
    global _cache
    with _lock:
        _cache = None
