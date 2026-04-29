"""簡易 RAG。FAQマスター（テキスト/Markdown/CSV）を読み込み、TF-IDF で検索する PoC 実装。

本番では Embedding（multilingual-e5-large 等）に差し替える前提（ROADMAP Task 1.1）。

学習機能:
  - フィードバック（👍/👎）から各文書のスコアブーストを学習
  - 検索時に raw_score × (1 + 0.15 * tanh(net_votes / 5)) で再ランキング
  - 永続化は data/feedback_scores.json（簡易版）
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .config import settings


@dataclass
class Chunk:
    chunk_id: str
    source: str
    text: str


def _split_text(text: str, max_chars: int = 600) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = (buf + "\n\n" + p).strip()
        else:
            if buf:
                chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    return chunks or [text]


def load_chunks(faq_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    if not faq_dir.exists():
        return chunks
    for path in sorted(faq_dir.glob("**/*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8")
        for i, piece in enumerate(_split_text(text)):
            chunks.append(
                Chunk(chunk_id=f"{path.name}#{i}", source=str(path.name), text=piece)
            )
    return chunks


FEEDBACK_PATH = Path("./data/feedback_scores.json")


def _load_feedback() -> dict[str, dict[str, int]]:
    """source ごとの {"up": n, "down": n} を返す。"""
    if not FEEDBACK_PATH.exists():
        return {}
    try:
        return json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_feedback(data: dict[str, dict[str, int]]) -> None:
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record_feedback(sources: list[str], vote: str) -> None:
    """フィードバック投票を蓄積。vote は 'up' or 'down'。"""
    if vote not in ("up", "down"):
        return
    data = _load_feedback()
    for src in sources:
        # source からファイル名のみ抽出（"foo.md#0" → "foo.md"）
        key = src.split("#")[0]
        if key not in data:
            data[key] = {"up": 0, "down": 0}
        data[key][vote] += 1
    _save_feedback(data)


def _boost_factor(source: str, fb: dict[str, dict[str, int]]) -> float:
    """フィードバックに基づくブースト係数。
    ネット票数 (up - down) を tanh で滑らかにし、最大 ±15% の倍率に。
    例: net=+5 → ×1.114 / net=-5 → ×0.886 / net=0 → ×1.0
    """
    info = fb.get(source) or fb.get(source.split("#")[0])
    if not info:
        return 1.0
    net = info.get("up", 0) - info.get("down", 0)
    return 1.0 + 0.15 * math.tanh(net / 5.0)


class FaqIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        if chunks:
            self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3))
            self.matrix = self.vectorizer.fit_transform([c.text for c in chunks])
        else:
            self.vectorizer = None
            self.matrix = None

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        """検索 + フィードバック学習によるスコアブースト。"""
        if not self.chunks or self.vectorizer is None:
            return []
        q = self.vectorizer.transform([query])
        raw_scores = (self.matrix @ q.T).toarray().ravel()

        # フィードバック学習: source ごとのブースト適用
        fb = _load_feedback()
        boosted = np.array([
            raw_scores[i] * _boost_factor(self.chunks[i].source, fb)
            for i in range(len(self.chunks))
        ])
        idx = np.argsort(-boosted)[:top_k]
        return [(self.chunks[i], float(boosted[i])) for i in idx if boosted[i] > 0]

    def save_meta(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([asdict(c) for c in self.chunks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


_index: FaqIndex | None = None


def get_index() -> FaqIndex:
    global _index
    if _index is None:
        _index = FaqIndex(load_chunks(settings.faq_master_dir))
    return _index


def reload_index() -> FaqIndex:
    global _index
    _index = FaqIndex(load_chunks(settings.faq_master_dir))
    return _index
