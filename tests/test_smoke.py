"""最低限の動作確認。Anthropic API キー無しでも通るよう設計している。"""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.masking import mask
from app.rag import FaqIndex, load_chunks


def test_healthz():
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_ask_requires_auth():
    client = TestClient(app)
    r = client.post("/api/ask", json={"question": "テスト"})
    assert r.status_code == 401


def test_masking_school_name():
    text = "○○学園の生徒情報について教えてください"
    out = mask(text)
    assert "[学校名]" in out


def test_masking_email_phone():
    text = "連絡先は test@example.com / 03-1234-5678 です"
    out = mask(text)
    assert "[メール]" in out
    assert "[電話番号]" in out


def test_rag_loads_and_searches(tmp_path: Path):
    (tmp_path / "faq1.md").write_text(
        "# 出席登録の仕方\n\n出席ボタンを押して保存してください。",
        encoding="utf-8",
    )
    (tmp_path / "faq2.md").write_text(
        "# 成績入力\n\n成績画面から学年とクラスを選び入力します。",
        encoding="utf-8",
    )
    chunks = load_chunks(tmp_path)
    assert len(chunks) >= 2
    idx = FaqIndex(chunks)
    results = idx.search("出席", top_k=2)
    assert results
    assert "出席" in results[0][0].text
