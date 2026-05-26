"""RAG 検索エンジン。2つのバックエンドから選択可能。

バックエンド:
  - "tfidf": 文字bigram の TF-IDF（軽量・モデルDL不要・PoC向け）
  - "e5-small" / "e5-base" / "e5-large": multilingual-e5 (semantic search)
    初回起動時に HuggingFace から モデル DL（small=470MB / large=2.2GB）

切替:
  環境変数 EMBEDDING_BACKEND=e5-small で起動

学習機能（共通）:
  - 👍/👎 から各文書のスコアブーストを学習（±15%倍率）
  - 永続化: data/feedback_scores.json
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


FEEDBACK_PATH = settings.feedback_path

# フィードバックのファイル I/O は検索ホットパスで呼ばれるため、mtime ベースキャッシュで I/O を削減
_feedback_cache: tuple[float, dict[str, dict[str, int]]] | None = None


def _load_feedback() -> dict[str, dict[str, int]]:
    """source ごとの {"up": n, "down": n} を返す（mtime ベースキャッシュ付き）。"""
    global _feedback_cache
    if not FEEDBACK_PATH.exists():
        return {}
    try:
        mtime = FEEDBACK_PATH.stat().st_mtime
    except OSError:
        return {}
    if _feedback_cache is not None and _feedback_cache[0] == mtime:
        return _feedback_cache[1]
    try:
        data = json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    _feedback_cache = (mtime, data)
    return data


def _save_feedback(data: dict[str, dict[str, int]]) -> None:
    global _feedback_cache
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        _feedback_cache = (FEEDBACK_PATH.stat().st_mtime, data)
    except OSError:
        _feedback_cache = None


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


_E5_MODEL_NAMES = {
    "e5-small": "intfloat/multilingual-e5-small",
    "e5-base": "intfloat/multilingual-e5-base",
    "e5-large": "intfloat/multilingual-e5-large",
}


class _TfidfBackend:
    """文字bigram TF-IDF。モデルDL不要、起動高速。"""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        if not chunks:
            self.vectorizer = None
            self.matrix = None
            return
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3))
        self.matrix = self.vectorizer.fit_transform([c.text for c in chunks])

    def raw_search(self, query: str) -> np.ndarray:
        if self.vectorizer is None:
            return np.array([])
        q = self.vectorizer.transform([query])
        return (self.matrix @ q.T).toarray().ravel()


class _E5Backend:
    """multilingual-e5 semantic search。

    e5 系モデルは passage と query で異なるプレフィックスを使うのが推奨:
      - encode passage: "passage: <text>"
      - encode query:   "query: <text>"
    """

    def __init__(self, chunks: list[Chunk], model_name: str):
        self.chunks = chunks
        if not chunks:
            self.model = None
            self.embeddings = None
            return
        # 遅延 import（embedding 不要環境では import エラーを起こさない）
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        # キャッシュから読み込み or 新規計算
        self.embeddings = self._load_or_encode(chunks)

    def _load_or_encode(self, chunks: list[Chunk]) -> np.ndarray:
        """チャンク単位の差分キャッシュ。

        旧実装は全チャンクで1つのハッシュキーを作っていたため、1ファイル追加
        するだけで全件再エンコードが発生していた（200K chunks で 30分〜2h）。
        本実装は (chunk_id, text_hash) → vector をキャッシュし、追加/変更され
        たチャンクだけを再計算する。定期更新運用での初回以降のコストが激減。
        """
        cache_path = settings.embedding_cache_path
        cached: dict[str, tuple[str, np.ndarray]] = {}
        if cache_path.exists():
            try:
                data = np.load(cache_path, allow_pickle=False)
                # 新形式: chunk_ids / text_hashes / embeddings の3配列
                if "chunk_ids" in data.files and "text_hashes" in data.files:
                    ids = data["chunk_ids"]
                    hashes = data["text_hashes"]
                    vecs = data["embeddings"]
                    for i in range(len(ids)):
                        cached[str(ids[i])] = (str(hashes[i]), vecs[i])
                # 旧形式 (key + embeddings) は無視して再構築。後方互換のため
                # 例外は出さずに通す
            except Exception:  # noqa: BLE001
                pass

        text_hashes = [self._text_hash(c.text) for c in chunks]
        out_vecs: list[np.ndarray | None] = [None] * len(chunks)
        to_encode_idx: list[int] = []
        for i, c in enumerate(chunks):
            entry = cached.get(c.chunk_id)
            if entry is not None and entry[0] == text_hashes[i]:
                out_vecs[i] = entry[1]
            else:
                to_encode_idx.append(i)

        n_hit = len(chunks) - len(to_encode_idx)
        n_new = len(to_encode_idx)
        print(
            f"[embedding] cache hit: {n_hit} chunks, recompute: {n_new} chunks",
            flush=True,
        )

        if to_encode_idx:
            passages = [f"passage: {chunks[i].text}" for i in to_encode_idx]
            # 大量エンコード時は進捗表示（サーバー起動が止まって見えるのを防ぐ）
            show_progress = n_new > 200
            new_vecs = self.model.encode(
                passages,
                normalize_embeddings=True,
                show_progress_bar=show_progress,
                batch_size=32,
            ).astype(np.float32)
            for k, i in enumerate(to_encode_idx):
                out_vecs[i] = new_vecs[k]

        embeddings = np.stack(out_vecs, axis=0)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            cache_path,
            chunk_ids=np.array([c.chunk_id for c in chunks]),
            text_hashes=np.array(text_hashes),
            embeddings=embeddings,
        )
        return embeddings

    @staticmethod
    def _text_hash(text: str) -> str:
        """チャンク本文のハッシュ（差分検出用・短縮版）。"""
        import hashlib

        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def raw_search(self, query: str) -> np.ndarray:
        if self.model is None or self.embeddings is None:
            return np.array([])
        q_vec = self.model.encode(
            [f"query: {query}"], normalize_embeddings=True, show_progress_bar=False
        ).astype(np.float32)[0]
        # コサイン類似度（既に L2 正規化済みなので内積でOK）
        return self.embeddings @ q_vec


def _make_backend(chunks: list[Chunk]):
    """設定に応じて検索バックエンドを構築。"""
    backend = settings.embedding_backend.lower()
    if backend in _E5_MODEL_NAMES:
        try:
            return _E5Backend(chunks, _E5_MODEL_NAMES[backend])
        except Exception as e:  # noqa: BLE001
            import warnings
            warnings.warn(
                f"Embedding バックエンド初期化失敗 ({e}), TF-IDF にフォールバック",
                stacklevel=2,
            )
    return _TfidfBackend(chunks)


class FaqIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.backend = _make_backend(chunks)

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        """検索 + フィードバック学習によるスコアブースト。"""
        if not self.chunks:
            return []
        raw_scores = self.backend.raw_search(query)
        if len(raw_scores) == 0:
            return []
        # フィードバック学習: フィードバックがあるときだけ boost 計算（多くの本番環境では空）
        fb = _load_feedback()
        if fb:
            boosted = np.fromiter(
                (raw_scores[i] * _boost_factor(self.chunks[i].source, fb)
                 for i in range(len(self.chunks))),
                dtype=np.float64, count=len(self.chunks),
            )
        else:
            boosted = raw_scores
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
    # FAQ が変わったら質問キャッシュを破棄（古い回答を返さないため）
    from . import llm  # 遅延 import で循環参照を回避

    llm.clear_answer_cache()
    return _index
