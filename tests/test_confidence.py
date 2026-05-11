"""確信度計算とハルシネーション抑制のテスト。"""
from fastapi.testclient import TestClient

from app.config import settings
from app.main import _compute_confidence, NO_ANSWER_TEXT, app
from app.rag import Chunk


def _scored(scores):
    """テスト用の (Chunk, score) タプルリスト生成。"""
    return [(Chunk(chunk_id=f"c{i}", source="x.md", text="t"), s) for i, s in enumerate(scores)]


def test_confidence_zero_when_empty():
    assert _compute_confidence([]) == 0


def test_confidence_zero_when_below_threshold():
    """top score が閾値未満なら 0 を返す。"""
    assert _compute_confidence(_scored([0.01])) == 0
    assert _compute_confidence(_scored([0.04, 0.03])) == 0


def test_confidence_high_for_strong_match():
    """top score 0.30+ なら 90% 以上。"""
    c = _compute_confidence(_scored([0.35, 0.20, 0.15]))
    assert c >= 90


def test_confidence_increases_with_supporting_chunks():
    """サポートチャンク数が増えるほど確信度が上がる。"""
    one = _compute_confidence(_scored([0.15]))
    three = _compute_confidence(_scored([0.15, 0.10, 0.08]))
    assert three > one


def test_confidence_capped_at_98():
    c = _compute_confidence(_scored([0.99, 0.99, 0.99, 0.99, 0.99]))
    assert c <= 98


def test_confidence_zero_for_isolated_noise():
    """top1が低め(<0.12)かつ2位以下が極端に低い → ノイズ扱いで NO ANSWER。

    実例: 「天気は？」のような無関係な質問が、共通の助詞で
    1つの文書だけに弱マッチする現象を弾く。
    """
    # top=0.10 (低め), second=0.02 → 比率0.2 で突出ノイズ
    assert _compute_confidence(_scored([0.10, 0.02, 0.01])) == 0


def test_confidence_passes_when_top_is_decent():
    """top1 が 0.12 以上なら、2位以下が低くても正解1件ヒットとみなす。

    実例: ニッチな質問で関連文書が1つしかないケースを救う。
    """
    # top=0.15, second=0.02 → 旧ロジックでは弾かれていたが新ロジックでは回答可
    c = _compute_confidence(_scored([0.15, 0.02, 0.01]))
    assert c > 0


def test_confidence_passes_when_multiple_supporting():
    """複数文書から関連情報が見つかれば回答可。"""
    # top=0.15, second=0.10 → 比率0.67 で正常
    c = _compute_confidence(_scored([0.15, 0.10, 0.08]))
    assert c > 0


def test_ask_returns_no_answer_when_score_too_low(monkeypatch, tmp_path):
    """関連性が低い場合 LLM を呼ばずに NO_ANSWER を返す（ハルシネーション抑制）。"""
    # 空のFAQマスターディレクトリ → 検索結果ゼロ → confidence=0
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "faq_master_dir", tmp_path)

    from app import rag
    rag._index = None  # キャッシュを無効化

    client = TestClient(app)
    r = client.post("/api/ask", json={"question": "存在しない情報について教えて"})
    assert r.status_code == 200
    data = r.json()
    assert data["has_answer"] is False
    assert data["confidence"] == 0
    assert "該当情報が見つかりませんでした" in data["answer"]
    assert data["sources"] == []


def test_ask_returns_confidence_with_answer(monkeypatch, tmp_path):
    """関連文書がある場合は has_answer=True で confidence>0 を返す。"""
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    (tmp_path / "vpn.md").write_text(
        "# VPN接続\n\nFortiClientを起動してログインしてください。",
        encoding="utf-8"
    )
    monkeypatch.setattr(settings, "faq_master_dir", tmp_path)

    from app import rag
    rag._index = None

    client = TestClient(app)
    r = client.post("/api/ask", json={"question": "VPN接続の方法"})
    assert r.status_code == 200
    data = r.json()
    assert data["has_answer"] is True
    assert data["confidence"] > 0
    assert data["sources"]


def test_no_answer_text_constant():
    """NO_ANSWER_TEXT に推測を促さない明確な文言が含まれる。"""
    assert "見つかりませんでした" in NO_ANSWER_TEXT
    assert "推測" not in NO_ANSWER_TEXT
