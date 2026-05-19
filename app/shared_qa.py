"""共有Q&A (user-shared-*.md) のメタ情報管理。

各共有回答ごとに以下を蓄積:
  - votes_up / votes_down: 役立った/役に立たなかった投票数
  - resolved_count: 「解決しました」と押した人数

保存先: settings.shared_qa_meta_path (デフォルト ./data/shared_qa_meta.json)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import settings

# 共有Q&A ファイル名の正規パターン: user-shared-{YYYYMMDD-HHMMSS}-{prefix}.md
SHARED_PREFIX = "user-shared-"
SHARED_PATTERN = re.compile(r"^user-shared-(\d{8}-\d{6})-(.+)\.md$")


@dataclass
class SharedQA:
    file_id: str  # ファイル名（拡張子なし）
    source: str  # 「user-shared-XXX.md」
    question: str  # 質問本文（# 見出しから）
    answer: str  # 回答本文（「## 回答」セクション以下）
    contributor: str  # 共有者のメール
    shared_at: str  # ISO 形式の共有日時
    votes_up: int = 0
    votes_down: int = 0
    resolved_count: int = 0


def _load_meta() -> dict[str, dict]:
    p = settings.shared_qa_meta_path
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_meta(data: dict[str, dict]) -> None:
    p = settings.shared_qa_meta_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_shared_file(path: Path) -> SharedQA | None:
    """user-shared-*.md を読んで SharedQA を構築する。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    file_id = path.stem
    m = SHARED_PATTERN.match(path.name)
    if not m:
        return None
    ts_part = m.group(1)
    # 形式 "20260519-143000" → "2026-05-19T14:30:00"
    shared_at = (
        f"{ts_part[0:4]}-{ts_part[4:6]}-{ts_part[6:8]}T"
        f"{ts_part[9:11]}:{ts_part[11:13]}:{ts_part[13:15]}"
    )
    # 質問本文: 最初の "# " の行
    question = ""
    contributor = ""
    answer = ""
    lines = text.split("\n")
    in_answer = False
    for line in lines:
        if line.startswith("# ") and not question:
            question = line[2:].strip()
            continue
        if "ユーザー提供回答" in line and "@" in line:
            email_m = re.search(r"([\w.+-]+@[\w.-]+)", line)
            if email_m:
                contributor = email_m.group(1)
            continue
        if line.startswith("## 回答"):
            in_answer = True
            continue
        if in_answer:
            answer += line + "\n"
    answer = answer.strip()

    meta = _load_meta().get(file_id, {})
    return SharedQA(
        file_id=file_id,
        source=path.name,
        question=question,
        answer=answer,
        contributor=contributor,
        shared_at=shared_at,
        votes_up=int(meta.get("votes_up", 0)),
        votes_down=int(meta.get("votes_down", 0)),
        resolved_count=int(meta.get("resolved_count", 0)),
    )


def list_shared_qas() -> list[SharedQA]:
    """すべての共有Q&A を新しい順で返す。"""
    qas: list[SharedQA] = []
    if not settings.faq_master_dir.exists():
        return qas
    for path in settings.faq_master_dir.glob(f"{SHARED_PREFIX}*.md"):
        qa = _parse_shared_file(path)
        if qa:
            qas.append(qa)
    qas.sort(key=lambda q: q.shared_at, reverse=True)
    return qas


def get_shared_qa(file_id: str) -> SharedQA | None:
    """単一の共有Q&A を取得。"""
    path = settings.faq_master_dir / f"{file_id}.md"
    if not path.exists():
        return None
    return _parse_shared_file(path)


def vote(file_id: str, kind: str) -> dict:
    """投票を記録。kind は 'up' / 'down' / 'resolved' のいずれか。"""
    if kind not in ("up", "down", "resolved"):
        raise ValueError(f"invalid vote kind: {kind}")
    data = _load_meta()
    entry = data.setdefault(file_id, {"votes_up": 0, "votes_down": 0, "resolved_count": 0})
    if kind == "up":
        entry["votes_up"] = int(entry.get("votes_up", 0)) + 1
    elif kind == "down":
        entry["votes_down"] = int(entry.get("votes_down", 0)) + 1
    else:
        entry["resolved_count"] = int(entry.get("resolved_count", 0)) + 1
    _save_meta(data)
    return entry


def search(query: str, limit: int = 50) -> list[SharedQA]:
    """質問本文・回答本文に対する部分一致検索（簡易）。"""
    q = (query or "").strip().lower()
    qas = list_shared_qas()
    if not q:
        return qas[:limit]
    matched = [
        x for x in qas
        if q in x.question.lower() or q in x.answer.lower()
    ]
    return matched[:limit]
