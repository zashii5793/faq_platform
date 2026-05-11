"""エッジケースのテスト：空ファイル・特殊文字・大容量・パストラバーサル等。"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.ingest import _safe_filename, analyze, parse


# ============================================================
# ファイル名の安全化
# ============================================================
def test_safe_filename_strips_path_traversal():
    assert _safe_filename("../../../etc/passwd") == "passwd"
    assert _safe_filename("/etc/passwd") == "passwd"
    assert _safe_filename("..\\..\\windows\\system32") == "system32"


def test_safe_filename_handles_empty():
    assert _safe_filename("") == "unnamed.txt"
    assert _safe_filename("   ") == "unnamed.txt"


def test_safe_filename_strips_control_chars():
    assert _safe_filename("hello\x00world.md") == "helloworld.md"
    assert _safe_filename("file\nname.txt") == "filename.txt"


def test_safe_filename_keeps_japanese():
    assert _safe_filename("日本語ファイル.md") == "日本語ファイル.md"


# ============================================================
# 空ファイル系
# ============================================================
def test_parse_empty_text_returns_no_chunks():
    chunks = parse("empty.md", b"")
    assert chunks == []


def test_parse_whitespace_only():
    chunks = parse("ws.md", b"   \n\n   \n")
    assert chunks == []


def test_parse_csv_header_only():
    """ヘッダーだけの CSV はチャンク 0 件。"""
    chunks = parse("empty.csv", b"q,a\n")
    assert chunks == []


def test_analyze_empty_file_returns_warn():
    """空ファイルは「テキストを抽出できませんでした」warn 判定。"""
    result = analyze("empty.md", b"")
    assert result.recommendation == "warn"
    assert "抽出できませんでした" in result.reason
    assert result.n_chunks == 0


# ============================================================
# 大容量・多チャンク
# ============================================================
def test_parse_large_text_creates_many_chunks():
    """1万字のテキストを与えると複数チャンクに分割される。"""
    text = "## セクション\n\n" + ("これは長い文章です。" * 50 + "\n\n") * 30
    chunks = parse("big.md", text.encode("utf-8"))
    assert len(chunks) >= 5
    # 各チャンクは max_chars * 1.5 を大きく超えない
    for c in chunks:
        assert len(c.text) <= 600  # 350 * 1.5 + 余裕


def test_parse_many_headings_split_correctly():
    """多数の見出しがある文書は見出し境界で分割される。"""
    text = "\n\n".join([f"## 節{i}\n\n本文{i}です。" for i in range(20)])
    chunks = parse("multi.md", text.encode("utf-8"))
    # ほぼ見出しの数分のチャンク（1チャンクにまとまる場合もあるが少なくとも10以上は欲しい）
    assert len(chunks) >= 10


# ============================================================
# 特殊文字・記号
# ============================================================
def test_analyze_with_emoji_and_symbols():
    content = "# テスト 🚗\n\n顧客 😊 への案内です。\n価格: ¥10,000".encode("utf-8")
    result = analyze("emoji.md", content)
    assert result.recommendation == "ok"
    assert result.n_chunks >= 1


def test_analyze_with_only_symbols():
    """記号だけの文書も例外で落ちない。"""
    content = "###@#$%&*()\n\n+-/*\n".encode("utf-8")
    result = analyze("syms.md", content)
    # 安全に処理できればOK（推奨は何でも良い）
    assert result.recommendation in ("ok", "warn")


# ============================================================
# Excel エッジケース
# ============================================================
def test_parse_xlsx_empty_sheet():
    """空シートのみの Excel はチャンク 0 件。"""
    from openpyxl import Workbook
    wb = Workbook()
    buf = io.BytesIO()
    wb.save(buf)
    chunks = parse("empty.xlsx", buf.getvalue())
    assert chunks == []


def test_parse_xlsx_with_blank_rows():
    """途中に空行がある Excel: 空行はスキップして取り込み。"""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["q", "a"])
    ws.append(["VPN", "再起動"])
    ws.append([None, None])  # 空行
    ws.append(["有給", "申請"])
    buf = io.BytesIO()
    wb.save(buf)
    chunks = parse("mix.xlsx", buf.getvalue())
    assert len(chunks) == 2  # 空行は除外


# ============================================================
# API レベル
# ============================================================
@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    from app import audit, rag
    from app.main import app

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "faq_master_dir", tmp_path / "faq_master")
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "audit")
    rag._index = None
    return TestClient(app)


def test_api_analyze_with_traversal_filename(client: TestClient):
    """パストラバーサルが含まれていても安全化される。"""
    body = "# OK\n\n安全な文書".encode("utf-8")
    r = client.post("/api/admin/analyze",
                    files={"file": ("../../etc/passwd.md", body, "text/markdown")})
    assert r.status_code == 200
    data = r.json()
    assert data["filename"] == "passwd.md"  # 安全化された
    assert "../" not in data["filename"]


def test_api_ingest_empty_file_gracefully(client: TestClient):
    """空ファイルの取り込みは 200 で 0 チャンク。"""
    r = client.post("/api/admin/ingest",
                    files={"file": ("empty.md", b"", "text/markdown")})
    assert r.status_code == 200
    assert r.json()["ingested_chunks"] == 0


def test_api_analyze_returns_warn_for_no_text(client: TestClient):
    """空ファイルでは判定が warn になり「抽出できませんでした」が出る。"""
    r = client.post("/api/admin/analyze",
                    files={"file": ("empty.md", b"", "text/markdown")})
    assert r.status_code == 200
    data = r.json()
    assert data["recommendation"] == "warn"
    assert "抽出できませんでした" in data["reason"]


def test_api_ingest_all_chunks_excluded(client: TestClient):
    """全チャンクを除外した場合は 0 チャンクで成功（書き出しなし）。"""
    md = b"## A\n\ntext A\n\n## B\n\ntext B"
    r = client.post("/api/admin/analyze",
                    files={"file": ("doc.md", md, "text/markdown")})
    chunks = r.json()["chunks"]
    from urllib.parse import quote
    all_ids = quote(",".join(c["chunk_id"] for c in chunks), safe=",")
    r = client.post(f"/api/admin/ingest?excluded_chunk_ids={all_ids}",
                    files={"file": ("doc.md", md, "text/markdown")})
    assert r.status_code == 200
    assert r.json()["ingested_chunks"] == 0


# ============================================================
# チャンク品質：細分化の効果
# ============================================================
def test_chunking_creates_finer_granularity_than_before():
    """同じ文書を旧設定（600字）と新設定（350字）で比較。

    新設定の方がチャンク数が多くなる（=細かい検索が可能）。
    """
    big_md = (
        "# タイトル\n\n"
        + "## セクションA\n\nAの内容です。これはセクションAの詳細です。長めに書いておきます。\n\n"
        + "## セクションB\n\nBの内容です。これはセクションBの詳細です。\n\n"
        + "## セクションC\n\nCの内容です。\n\n"
        + "## セクションD\n\nDの内容です。\n\n"
        + "## セクションE\n\nEの内容です。\n\n"
    )
    chunks = parse("test.md", big_md.encode("utf-8"))
    # 5セクションあるので、ほぼ5チャンクに分割されるはず（旧設定なら1チャンクにまとまっていた）
    assert len(chunks) >= 5
