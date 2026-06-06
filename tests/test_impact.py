"""工数削減レポートのユニットテスト。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import impact


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    from app import audit
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "audit_log_dir", tmp_path / "audit")
    monkeypatch.setattr(_settings, "impact_settings_path", tmp_path / "impact_settings.json")
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "audit")
    return tmp_path


def _write_log(tmp_path: Path, entries: list[dict]) -> None:
    log_dir = tmp_path / "audit"
    log_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = log_dir / f"audit-{today}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _query(answered: bool = True, user: str = "a@x.jp") -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "query",
        "user": user,
        "answered": answered,
    }


def test_default_settings(tmp_data):
    s = impact.load_settings()
    assert s.minutes_saved_per_answered_query == 8
    assert s.hourly_rate_yen == 3500


def test_update_settings(tmp_data):
    s = impact.update_settings(minutes_saved_per_answered_query=15, hourly_rate_yen=5000)
    assert s.minutes_saved_per_answered_query == 15
    assert s.hourly_rate_yen == 5000
    # 永続化される
    s2 = impact.load_settings()
    assert s2.minutes_saved_per_answered_query == 15


def test_compute_empty(tmp_data):
    r = impact.compute()
    assert r["summary"]["total_queries"] == 0
    assert r["summary"]["hours_saved"] == 0


def test_compute_basic(tmp_data):
    # 10 件回答済み + 2 件未回答
    entries = [_query(answered=True) for _ in range(10)] + [_query(answered=False) for _ in range(2)]
    _write_log(tmp_data, entries)

    r = impact.compute()
    s = r["summary"]
    assert s["total_queries"] == 12
    assert s["total_answered"] == 10
    assert s["answer_rate_pct"] == 83
    # デフォルト 8分/件 * 10件 = 80分 = 1.3時間
    assert s["minutes_saved"] == 80
    assert s["hours_saved"] == 1.3
    # ¥3500 * 1.3 = ¥4550
    assert s["cost_saved_yen"] == int(1.3333333333 * 3500)  # 1.33hours from 80/60


def test_compute_with_settings_change(tmp_data):
    impact.update_settings(minutes_saved_per_answered_query=15, hourly_rate_yen=5000)
    entries = [_query() for _ in range(10)]
    _write_log(tmp_data, entries)

    r = impact.compute()
    s = r["summary"]
    assert s["minutes_saved"] == 150
    assert s["hours_saved"] == 2.5
    assert s["cost_saved_yen"] == int(2.5 * 5000)


def test_compute_includes_faq_shared(tmp_data):
    entries = [_query() for _ in range(5)] + [
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "faq_request",
            "user": "a@x.jp",
        }
        for _ in range(2)
    ]
    _write_log(tmp_data, entries)

    r = impact.compute()
    s = r["summary"]
    # 5*8 + 2*20 = 40+40 = 80
    assert s["minutes_saved"] == 80
    assert s["total_faq_shared"] == 2


def test_compute_unique_users(tmp_data):
    entries = (
        [_query(user="a@x.jp") for _ in range(5)]
        + [_query(user="b@x.jp") for _ in range(3)]
        + [_query(user="c@x.jp") for _ in range(2)]
    )
    _write_log(tmp_data, entries)

    r = impact.compute()
    assert r["summary"]["unique_users"] == 3


def test_compute_monthly_buckets(tmp_data):
    """同一月の質問は1バケットにまとまる。"""
    entries = [_query() for _ in range(3)]
    _write_log(tmp_data, entries)
    r = impact.compute()
    assert len(r["monthly"]) == 1
    m = r["monthly"][0]
    assert m["answered"] == 3
