"""工数削減レポート — Inquira がどれだけ人的工数を削減したかを可視化。

集計ロジックは監査ログのみに依存し、軽量。
管理者は1質問あたりの想定削減時間と時給を調整できる（保存先: impact_settings_path）。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from . import audit
from .config import settings


@dataclass
class ImpactSettings:
    # 1質問あたりの「資料を探す or 人に聞く」想定削減時間（分）
    minutes_saved_per_answered_query: int = 8
    # 共有回答（ユーザー提供 FAQ）1件あたりの整備時間削減（分）
    minutes_saved_per_faq_shared: int = 20
    # 平均時給（円）。削減コスト換算用
    hourly_rate_yen: int = 3500


def load_settings() -> ImpactSettings:
    path = settings.impact_settings_path
    if not path.exists():
        return ImpactSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ImpactSettings()
    known = ImpactSettings.__dataclass_fields__
    return ImpactSettings(**{k: v for k, v in data.items() if k in known})


def save_settings(s: ImpactSettings) -> None:
    path = settings.impact_settings_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def update_settings(**kwargs: Any) -> ImpactSettings:
    current = load_settings()
    data = asdict(current)
    for k, v in kwargs.items():
        if k in data and v is not None:
            data[k] = v
    new = ImpactSettings(**data)
    save_settings(new)
    return new


def _month(ts: str) -> str:
    return ts[:7] if ts else ""


def _to_ts(iso: str) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def compute(days: int = 365) -> dict[str, Any]:
    """工数削減サマリを計算。デフォルトで直近1年。

    Returns:
        サマリ・月次推移・直近30日 vs 前30日 などをまとめた dict。
    """
    s = load_settings()
    entries = audit.read_range(days=days)

    answered: list[dict] = []
    not_answered: list[dict] = []
    faq_shared: list[dict] = []
    for e in entries:
        ev = e.get("event")
        if ev == "query":
            (answered if e.get("answered") else not_answered).append(e)
        elif ev == "faq_request":
            faq_shared.append(e)

    monthly: dict[str, dict[str, int]] = {}

    def bucket(month: str) -> dict[str, int]:
        return monthly.setdefault(
            month,
            {"answered": 0, "not_answered": 0, "faq_shared": 0, "minutes_saved": 0},
        )

    for e in answered:
        m = _month(e.get("ts", ""))
        if m:
            b = bucket(m)
            b["answered"] += 1
            b["minutes_saved"] += s.minutes_saved_per_answered_query
    for e in not_answered:
        m = _month(e.get("ts", ""))
        if m:
            bucket(m)["not_answered"] += 1
    for e in faq_shared:
        m = _month(e.get("ts", ""))
        if m:
            b = bucket(m)
            b["faq_shared"] += 1
            b["minutes_saved"] += s.minutes_saved_per_faq_shared

    total_answered = len(answered)
    total_not_answered = len(not_answered)
    total_queries = total_answered + total_not_answered
    total_faq_shared = len(faq_shared)
    minutes_saved = (
        total_answered * s.minutes_saved_per_answered_query
        + total_faq_shared * s.minutes_saved_per_faq_shared
    )
    hours_saved = minutes_saved / 60
    cost_saved = int(hours_saved * s.hourly_rate_yen)
    unique_users = len({e.get("user") for e in answered if e.get("user")})
    answer_rate = round(100 * total_answered / total_queries) if total_queries else 0

    # 直近 30 日 / 前 30 日
    now_ts = datetime.now(timezone.utc).timestamp()
    last30 = 0
    prev30 = 0
    for e in answered:
        t = _to_ts(e.get("ts", ""))
        if t is None:
            continue
        if t > now_ts - 30 * 86400:
            last30 += 1
        elif t > now_ts - 60 * 86400:
            prev30 += 1
    growth_pct = (
        round((last30 - prev30) / prev30 * 100) if prev30 > 0 else (100 if last30 > 0 else 0)
    )

    return {
        "settings": asdict(s),
        "summary": {
            "total_queries": total_queries,
            "total_answered": total_answered,
            "total_faq_shared": total_faq_shared,
            "answer_rate_pct": answer_rate,
            "unique_users": unique_users,
            "minutes_saved": minutes_saved,
            "hours_saved": round(hours_saved, 1),
            "days_saved": round(hours_saved / 8, 1),  # 8 時間 = 1人日
            "cost_saved_yen": cost_saved,
        },
        "monthly": [{"month": k, **v} for k, v in sorted(monthly.items())],
        "last_30_days": {
            "answered": last30,
            "vs_previous_30_days": last30 - prev30,
            "growth_pct": growth_pct,
        },
    }
