"""簡易 RAG。FAQマスター（テキスト/Markdown/CSV）を読み込み、TF-IDF で検索する PoC 実装。

本番では Embedding（multilingual-e5-large 等）に差し替える前提（ROADMAP Task 1.1）。
"""
from __future__ import annotations

import json
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
        if not self.chunks or self.vectorizer is None:
            return []
        q = self.vectorizer.transform([query])
        scores = (self.matrix @ q.T).toarray().ravel()
        idx = np.argsort(-scores)[:top_k]
        return [(self.chunks[i], float(scores[i])) for i in idx if scores[i] > 0]

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
