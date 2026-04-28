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


def test_parse_xlsx():
    """openpyxl でシート×行をチャンク化できる。"""
    from openpyxl import Workbook
    import io

    wb = Workbook()
    ws = wb.active
    ws.title = "FAQ"
    ws.append(["question", "answer"])
    ws.append(["VPN繋がらない", "FortiClientを再起動"])
    ws.append(["有給申請", "KING OF TIMEから"])
    buf = io.BytesIO()
    wb.save(buf)

    chunks = parse("faq.xlsx", buf.getvalue())
    assert len(chunks) == 2
    assert "VPN" in chunks[0].text
    assert "FAQ!r2" in chunks[0].chunk_id  # シート名+行番号


def test_parse_pdf():
    """pypdf でページごとにチャンク化できる。"""
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, TextStringObject
    import io

    # シンプルなPDFを作成（pypdfで読める最小フォーマット）
    # pypdf の AddBlankPage では text 抽出できないので reportlab があれば使うが、
    # ここでは pypdf 自身で書き込む形で代替。
    pdf_bytes = _make_minimal_pdf("Hello PDF\nThis is page one.")
    chunks = parse("doc.pdf", pdf_bytes)
    assert chunks
    assert "PDF" in chunks[0].text or "page" in chunks[0].text.lower()


def _make_minimal_pdf(text: str) -> bytes:
    """テスト用の最小PDF生成（手書き）。"""
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >> endobj\n"
        b"4 0 obj << /Length 60 >> stream\n"
        b"BT /F1 12 Tf 50 700 Td ("
        + text.encode("latin-1", errors="replace") + b") Tj ET\n"
        b"endstream endobj\n"
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        b"xref\n0 6\n0000000000 65535 f\n"
        b"0000000009 00000 n\n0000000058 00000 n\n0000000111 00000 n\n"
        b"0000000226 00000 n\n0000000316 00000 n\n"
        b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n388\n%%EOF\n"
    )
    return pdf


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
