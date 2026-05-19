"""最低限の動作確認。Anthropic API キー無しでも通るよう設計している。"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

import app
from app.main import app as fastapi_app
from app.masking import build_rules, mask
from app.rag import FaqIndex, load_chunks


def test_healthz():
    client = TestClient(fastapi_app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_version_format_is_semver():
    """app.__version__ が SemVer (MAJOR.MINOR.PATCH) 形式。"""
    assert re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?$", app.__version__), (
        f"バージョン形式が SemVer 違反: {app.__version__}"
    )


def test_version_matches_pyproject():
    """app/__init__.py の __version__ と pyproject.toml の version が一致する。"""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "pyproject.toml に version 行が見つからない"
    pyproject_ver = m.group(1)
    assert pyproject_ver == app.__version__, (
        f"バージョン不一致: pyproject.toml={pyproject_ver} / app.__version__={app.__version__}"
    )


def test_version_appears_in_chat_page(monkeypatch):
    """チャット画面の HTML にバージョンバッジが含まれる（DEMO_MODE で確認）。"""
    from app.config import settings
    monkeypatch.setattr(settings, "demo_mode", True)
    client = TestClient(fastapi_app)
    r = client.get("/")
    assert r.status_code == 200
    assert f"v{app.__version__}" in r.text, "チャット画面にバージョン表示なし"


def test_version_api_returns_changelog():
    """/api/version は CHANGELOG を含む HTML を返す（認証不要）。"""
    client = TestClient(fastapi_app)
    r = client.get("/api/version")
    assert r.status_code == 200
    assert f"v{app.__version__}" in r.text
    # CHANGELOG の見出しが含まれる
    assert "Changelog" in r.text or "0.6.0" in r.text


def test_ask_requires_auth():
    client = TestClient(fastapi_app)
    r = client.post("/api/ask", json={"question": "テスト"})
    assert r.status_code == 401


def test_masking_generic_pii():
    text = "連絡先は test@example.com / 03-1234-5678 / https://internal.example.com/x です"
    out = mask(text, rules=build_rules("general"))
    assert "[メール]" in out
    assert "[電話番号]" in out
    assert "[URL]" in out


def test_masking_education_industry():
    text = "○○学園の生徒情報について教えてください"
    out = mask(text, rules=build_rules("education"))
    assert "[学校名]" in out


def test_masking_general_does_not_match_school():
    text = "○○学園の件で"
    out = mask(text, rules=build_rules("general"))
    assert "[学校名]" not in out  # general industry では学校名は対象外


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
