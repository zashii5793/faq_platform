"""ingest.py のテスト。"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.ingest import analyze, ingest, parse


def test_parse_markdown():
    content = "# 出席登録\n\n保存ボタンを押す。\n\nトラブル時はリロード。".encode("utf-8")
    chunks = parse("出席登録.md", content)
    assert chunks
    assert all(c.source == "出席登録.md" for c in chunks)


def test_parse_csv():
    content = b"id,question,answer\n1,VPN,FortiClient\n2,paid leave,king of time\n"
    chunks = parse("faq.csv", content)
    assert len(chunks) == 2
    assert "VPN" in chunks[0].text


def test_parse_unsupported():
    with pytest.raises(ValueError):
        parse("foo.exe", b"bin")


def test_analyze_clean_doc():
    content = "出席登録の保存ボタンが押せない場合、ブラウザを再起動してください。".encode("utf-8")
    result = analyze("clean.md", content)
    assert result.recommendation == "ok"
    assert result.findings.pii_counts == {}


def test_analyze_warn_pii():
    content = "# Q&A\ncontact@example.com まで連絡を。電話 03-1234-5678 でも可。\n".encode("utf-8")
    result = analyze("contacts.md", content)
    assert result.recommendation == "warn"
    assert result.findings.pii_counts.get("email", 0) >= 1
    assert result.findings.pii_counts.get("phone_jp", 0) >= 1


def test_analyze_danger_my_number():
    content = b"\xef\xbb\xbfid,name,number\n1,foo,1234 5678 9012\n"
    result = analyze("staff.csv", content)
    assert result.recommendation == "danger"
    assert "マイナンバー" in result.reason


def test_analyze_warn_confidential_marker():
    content = "# 内部メモ\n\nこの資料は社外秘です。閲覧注意。".encode("utf-8")
    result = analyze("memo.md", content)
    assert result.recommendation == "warn"
    assert "社外秘" in " ".join(result.findings.confidential_markers)


def test_ingest_writes_masked_text(tmp_path: Path):
    content = "問い合わせ: contact@example.com / 03-1234-5678".encode("utf-8")
    result = analyze("contact.md", content)
    n = ingest(result, tmp_path, apply_masking=True)
    assert n == result.n_chunks
    out = list(tmp_path.glob("*.md"))
    assert out
    body = out[0].read_text(encoding="utf-8")
    assert "[メール]" in body
    assert "[電話番号]" in body
    assert "contact@example.com" not in body


def test_api_analyze_requires_auth():
    from app.main import app
    client = TestClient(app)
    r = client.post("/api/admin/analyze", files={"file": ("a.md", b"hello", "text/plain")})
    assert r.status_code in (401, 403)


def test_api_analyze_returns_assessment(monkeypatch):
    """DEMO_MODE で認証バイパスして実際のレスポンスを確認。"""
    monkeypatch.setattr(settings, "demo_mode", True)
    from app.main import app
    client = TestClient(app)
    csv_body = b"q,a\nVPN connection,Restart FortiClient\n"
    r = client.post("/api/admin/analyze", files={"file": ("faq.csv", csv_body, "text/csv")})
    assert r.status_code == 200
    data = r.json()
    assert data["recommendation"] == "ok"
    assert data["n_chunks"] == 1
    assert data["format"] == "csv"
