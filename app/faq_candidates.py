"""優良な質問→回答ペアを監査ログから検出し、FAQ 候補として管理。

検出: 過去 N 日分の query イベントを類似度クラスタリングし、
      asked_count / unique_users / confidence のしきい値を超えたものを候補化。
承認: FAQ マスター（settings.faq_master_dir）に Markdown として書き込み、検索インデックスを reload。
却下: ステータスを rejected に変更（次回 detect で同一クラスタが現れても再候補化はしない）。
自動承認モード: detect 時に厳しめのしきい値を超えたら、その場で approve まで進める。
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from . import audit, rag
from .config import settings
from .faq_candidate_settings import FaqCandidateSettings, load as load_settings


@dataclass
class FaqCandidate:
    id: str
    question_examples: list[str]
    answer: str
    sources: list[str]
    confidence: int
    support: dict[str, Any]
    first_seen: str
    last_seen: str
    status: str = "pending"  # pending | approved | rejected
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
    approved_doc_path: str | None = None


_lock = RLock()
_cache: dict[str, FaqCandidate] | None = None


def _path() -> Path:
    return settings.faq_candidates_path


def _load_all() -> dict[str, FaqCandidate]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        path = _path()
        if not path.exists():
            _cache = {}
            return _cache
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            _cache = {}
            return _cache
        _cache = {}
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            try:
                _cache[k] = FaqCandidate(**v)
            except TypeError:
                continue
        return _cache


def _save_all(cands: dict[str, FaqCandidate]) -> None:
    global _cache
    with _lock:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {k: asdict(v) for k, v in cands.items()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        _cache = cands


def reset_cache() -> None:
    """テスト用にキャッシュをクリア。"""
    global _cache
    with _lock:
        _cache = None


def list_all(status: str | None = None) -> list[FaqCandidate]:
    items = list(_load_all().values())
    if status:
        items = [c for c in items if c.status == status]
    items.sort(key=lambda c: c.last_seen, reverse=True)
    return items


def get(cid: str) -> FaqCandidate | None:
    return _load_all().get(cid)


def count_by_status() -> dict[str, int]:
    out = {"pending": 0, "approved": 0, "rejected": 0}
    for c in _load_all().values():
        if c.status in out:
            out[c.status] += 1
    return out


# --- 類似度 ---


def _tokenize(text: str) -> list[str]:
    """日本語混在の質問文を char-2gram + 単語の混合トークンに分解。

    char-1gram も入れると助詞や「教えて」等の共通語で類似度が吊り上がり、
    無関係質問の誤クラスタ化が増えるため、char-2gram + 単語のみとする。
    既定しきい値 0.55 程度で同義質問はまとまる想定（管理画面から調整可）。
    """
    text = text.lower().strip()
    chars2 = [text[i : i + 2] for i in range(len(text) - 1)]
    words = re.findall(r"\w+", text)
    return chars2 + words


def _bag(tokens: list[str]) -> dict[str, int]:
    bag: dict[str, int] = {}
    for t in tokens:
        bag[t] = bag.get(t, 0) + 1
    return bag


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# --- ログ走査 ---


@dataclass
class _QueryRecord:
    question: str
    answer: str
    sources: list[str]
    confidence: int
    user: str
    ts: str


def _scan_query_logs(days: int) -> list[_QueryRecord]:
    out: list[_QueryRecord] = []
    for entry in audit.read_range(days=days):
        if entry.get("event") != "query":
            continue
        if not entry.get("answered"):
            continue
        ans = entry.get("answer")
        q = entry.get("question") or ""
        if not ans or not q:
            continue
        out.append(
            _QueryRecord(
                question=q,
                answer=ans,
                sources=entry.get("sources") or [],
                confidence=int(entry.get("confidence") or 0),
                user=entry.get("user") or "",
                ts=entry.get("ts") or "",
            )
        )
    return out


def _existing_faq_titles() -> list[str]:
    out: list[str] = []
    for p in settings.faq_master_dir.glob("*.md"):
        try:
            first = p.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError):
            continue
        out.append(first.lstrip("# ").strip())
    return out


# --- クラスタリング ---


def _cluster(records: list[_QueryRecord], threshold: float) -> list[list[_QueryRecord]]:
    """Single-link クラスタリング: クラスタ内の「いずれか」と threshold 以上なら同一クラスタ。

    累積バッグ方式だと頻度が希釈されて類似度が下がるので、各要素の bag を全部保持し
    新規質問はクラスタ内の最も似た既存質問と比較する。O(N^2) だが、N=数百件までは実用範囲。
    """
    clusters: list[list[_QueryRecord]] = []
    cluster_bags: list[list[dict[str, int]]] = []  # 各クラスタの bag リスト
    for r in records:
        bag = _bag(_tokenize(r.question))
        best_i = -1
        best_sim = 0.0
        for i, bags in enumerate(cluster_bags):
            for cb in bags:
                sim = _cosine(bag, cb)
                if sim > best_sim:
                    best_sim = sim
                    best_i = i
        if best_sim >= threshold and best_i >= 0:
            clusters[best_i].append(r)
            cluster_bags[best_i].append(bag)
        else:
            clusters.append([r])
            cluster_bags.append([bag])
    return clusters


# --- しきい値 ---


def _meets(cluster: list[_QueryRecord], s: FaqCandidateSettings) -> bool:
    if len(cluster) < s.min_asked_count:
        return False
    if len({r.user for r in cluster}) < s.min_unique_users:
        return False
    avg_conf = sum(r.confidence for r in cluster) / len(cluster)
    if avg_conf < s.min_confidence:
        return False
    return True


def _meets_auto(cluster: list[_QueryRecord], s: FaqCandidateSettings) -> bool:
    if not s.auto_approve_enabled:
        return False
    if len(cluster) < s.auto_approve_min_asked_count:
        return False
    if len({r.user for r in cluster}) < s.auto_approve_min_unique_users:
        return False
    avg_conf = sum(r.confidence for r in cluster) / len(cluster)
    if avg_conf < s.auto_approve_min_confidence:
        return False
    return True


# --- 候補生成 ---


def _representative(cluster: list[_QueryRecord]) -> _QueryRecord:
    return sorted(cluster, key=lambda r: (r.confidence, len(r.answer)), reverse=True)[0]


def _make_candidate(cluster: list[_QueryRecord]) -> FaqCandidate:
    rep = _representative(cluster)
    questions = list(dict.fromkeys(r.question for r in cluster))[:5]
    sources = list(dict.fromkeys(s for r in cluster for s in r.sources))[:10]
    return FaqCandidate(
        id=str(uuid.uuid4()),
        question_examples=questions,
        answer=rep.answer,
        sources=sources,
        confidence=int(sum(r.confidence for r in cluster) / len(cluster)),
        support={
            "asked_count": len(cluster),
            "unique_users": len({r.user for r in cluster}),
        },
        first_seen=min(r.ts for r in cluster),
        last_seen=max(r.ts for r in cluster),
    )


def _matches_existing_candidate(
    question: str, candidates: list[FaqCandidate], threshold: float
) -> FaqCandidate | None:
    bag_q = _bag(_tokenize(question))
    for c in candidates:
        for ex in c.question_examples:
            if _cosine(bag_q, _bag(_tokenize(ex))) >= threshold:
                return c
    return None


def _matches_existing_faq(question: str, titles: list[str], threshold: float) -> bool:
    bag_q = _bag(_tokenize(question))
    for t in titles:
        if _cosine(bag_q, _bag(_tokenize(t))) >= threshold:
            return True
    return False


# --- FAQ マスターへの書き込み ---


def _slug(text: str) -> str:
    s = re.sub(r"[^\w一-鿿ぁ-んァ-ヶー]+", "_", text[:40]).strip("_")
    return s or "faq"


def _write_as_faq_doc(
    c: FaqCandidate,
    *,
    auto: bool,
    custom_question: str | None = None,
    custom_answer: str | None = None,
) -> str:
    q = custom_question or (c.question_examples[0] if c.question_examples else "（無題）")
    a = custom_answer or c.answer
    settings.faq_master_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = "faq-auto" if auto else "faq-promoted"
    out_path = settings.faq_master_dir / f"{prefix}-{ts}-{_slug(q)}.md"

    lines = [
        f"# {q}",
        "",
        f"> 🌱 **自動 FAQ 候補化** 由来の文書（{'自動承認' if auto else '管理者承認'}）",
        f"> 候補 ID: `{c.id}` ／ 観測期間: {c.first_seen[:10]} 〜 {c.last_seen[:10]}",
        f"> 観測: {c.support.get('asked_count')} 件の質問 ／ {c.support.get('unique_users')} 名のユーザー",
        "",
        "## 質問",
        "",
        q,
    ]
    other_qs = [oq for oq in c.question_examples if oq != q]
    if other_qs:
        lines.extend(["", "### 同類質問の例", ""])
        lines.extend(f"- {oq}" for oq in other_qs)
    lines.extend(["", "## 回答", "", a])
    if c.sources:
        lines.extend(["", "### 元の出典（参考）", ""])
        lines.extend(f"- `{src}`" for src in c.sources)

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out_path)


# --- 検出（メインエントリ） ---


def detect() -> dict[str, Any]:
    """監査ログを走査して新規候補を検出。自動承認モードが ON なら即昇格まで。

    Returns:
        統計: {"new": N, "auto_approved": M, "skipped_existing_faq": K,
              "skipped_existing_candidate": L, "below_threshold": Q}
    """
    s = load_settings()
    records = _scan_query_logs(s.lookback_days)
    clusters = _cluster(records, s.similarity_threshold)
    existing_cands = list_all()
    existing_titles = _existing_faq_titles()
    cands = _load_all()

    stats = {
        "new": 0,
        "auto_approved": 0,
        "skipped_existing_faq": 0,
        "skipped_existing_candidate": 0,
        "below_threshold": 0,
    }

    for cluster in clusters:
        if not _meets(cluster, s):
            stats["below_threshold"] += 1
            continue
        rep_q = _representative(cluster).question
        if _matches_existing_faq(rep_q, existing_titles, s.similarity_threshold):
            stats["skipped_existing_faq"] += 1
            continue
        existing = _matches_existing_candidate(rep_q, existing_cands, s.similarity_threshold)
        if existing:
            if existing.status == "pending":
                existing.support["asked_count"] = len(cluster)
                existing.support["unique_users"] = len({r.user for r in cluster})
                existing.last_seen = max(existing.last_seen, max(r.ts for r in cluster))
                cands[existing.id] = existing
            stats["skipped_existing_candidate"] += 1
            continue

        cand = _make_candidate(cluster)
        if _meets_auto(cluster, s):
            cand.status = "approved"
            cand.reviewed_by = "auto"
            cand.reviewed_at = datetime.now(timezone.utc).isoformat()
            cand.review_note = "自動承認モードによる昇格"
            cand.approved_doc_path = _write_as_faq_doc(cand, auto=True)
            stats["auto_approved"] += 1
        cands[cand.id] = cand
        stats["new"] += 1

    _save_all(cands)
    if stats["auto_approved"] > 0:
        rag.reload_index()
    return stats


# --- 承認 / 却下 ---


def approve(
    cid: str,
    reviewer: str,
    *,
    question: str | None = None,
    answer: str | None = None,
    note: str | None = None,
) -> FaqCandidate:
    cands = _load_all()
    c = cands.get(cid)
    if c is None:
        raise KeyError(cid)
    if c.status != "pending":
        raise ValueError(f"候補は既に {c.status} です")
    if question:
        c.question_examples = [question] + [q for q in c.question_examples if q != question]
    if answer:
        c.answer = answer
    c.approved_doc_path = _write_as_faq_doc(
        c, auto=False, custom_question=question, custom_answer=answer
    )
    c.status = "approved"
    c.reviewed_by = reviewer
    c.reviewed_at = datetime.now(timezone.utc).isoformat()
    c.review_note = note
    cands[cid] = c
    _save_all(cands)
    rag.reload_index()
    return c


def reject(cid: str, reviewer: str, note: str | None = None) -> FaqCandidate:
    cands = _load_all()
    c = cands.get(cid)
    if c is None:
        raise KeyError(cid)
    if c.status != "pending":
        raise ValueError(f"候補は既に {c.status} です")
    c.status = "rejected"
    c.reviewed_by = reviewer
    c.reviewed_at = datetime.now(timezone.utc).isoformat()
    c.review_note = note
    cands[cid] = c
    _save_all(cands)
    return c
