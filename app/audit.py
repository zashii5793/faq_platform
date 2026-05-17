"""監査ログ。JSONL に追記。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path("./data/audit")


def _log_path() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return LOG_DIR / f"audit-{today}.jsonl"


def record(event: str, *, user: str | None = None, **fields: Any) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "user": user,
        **fields,
    }
    with _log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_recent(limit: int = 100) -> list[dict]:
    """直近の監査ログエントリを新しい順で返す（最大 limit 件、当日のファイルのみ）。"""
    path = _log_path()
    if not path.exists():
        return []
    entries: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return list(reversed(entries))[:limit]


def read_range(days: int = 30) -> list[dict]:
    """過去 days 日分の監査ログを古い順で返す（エクスポート・分析用）。

    日次ローテーションされた audit-YYYY-MM-DD.jsonl を全て読む。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    for path in sorted(LOG_DIR.glob("audit-*.jsonl")):
        if path.stat().st_mtime < cutoff:
            continue
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries
