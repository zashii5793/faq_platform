"""統合テスト：複数エンドポイントを跨ぐ実シナリオを検証する。

カバー範囲:
  1. アップロード → 取り込み → 質問 → 回答（完全フロー）
  2. 関連なし質問 → has_answer=False（ハルシネーション抑制）
  3. PIIマスキング → 監査ログのマスク済み記録
  4. 危険ファイルの取り込み拒否（HTTP 400）
  5. 複数フォーマット（CSV/Markdown/PowerPoint）の同時取り込み
  6. フィードバック投票 → サイドバー stats への反映
  7. 容量上限超過 → HTTP 413
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """各テストで独立した FAQマスターディレクトリを使う。"""
    from app import audit, rag
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "faq_master_dir", tmp_path / "faq_master")
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "audit")
    rag._index = None
    return TestClient(app)


def _xlsx_bytes(rows: list[list]) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pptx_bytes(slides: list[str]) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    blank = prs.slide_layouts[6]
    for text in slides:
        s = prs.slides.add_slide(blank)
        s.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(2)).text_frame.text = text
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ============================================================
# シナリオ1: 完全フロー（取り込み → 質問 → 回答 → 確信度）
# ============================================================
def test_full_workflow_upload_then_ask(client: TestClient):
    # Step 1: VPN手順マークダウンをアップロード&取り込み
    md = "# VPN\n\nFortiClientを起動してログイン後、OTP6桁を入力してください。".encode("utf-8")
    r = client.post("/api/admin/ingest", files={"file": ("vpn.md", md, "text/markdown")})
    assert r.status_code == 200
    assert r.json()["ingested_chunks"] >= 1

    # Step 2: 取り込んだ内容について質問
    r = client.post("/api/ask", json={"question": "VPNにログインする手順"})
    assert r.status_code == 200
    data = r.json()
    assert data["has_answer"] is True
    assert data["confidence"] > 0
    assert any(s["source"] == "vpn.md" for s in data["sources"])


# ============================================================
# シナリオ2: ハルシネーション抑制
# ============================================================
def test_no_answer_for_irrelevant_question(client: TestClient):
    # 1件だけ取り込んで関係ない質問をする
    md = "# 経費精算\n\n月次締めは毎月25日です。".encode("utf-8")
    client.post("/api/admin/ingest", files={"file": ("expense.md", md, "text/markdown")})

    r = client.post("/api/ask", json={"question": "宇宙ロケットの打ち上げ手順を教えて"})
    data = r.json()
    assert data["has_answer"] is False
    assert data["confidence"] == 0
    assert "見つかりませんでした" in data["answer"]


# ============================================================
# シナリオ3: PIIマスキングと監査ログ
# ============================================================
def test_pii_masked_in_audit_log(client: TestClient, tmp_path):
    md = "# FAQ\n\nVPN は FortiClient を使う".encode("utf-8")
    client.post("/api/admin/ingest", files={"file": ("vpn.md", md, "text/markdown")})

    # PII を含む質問
    client.post("/api/ask", json={
        "question": "test@example.com のユーザーが 03-1234-5678 でVPN接続できない"
    })

    # 監査ログを確認: マスク済みで記録されているはず
    log_dir = tmp_path / "audit"
    log_files = list(log_dir.glob("*.jsonl"))
    assert log_files
    entries = [json.loads(line) for line in log_files[0].read_text().splitlines() if line.strip()]
    query_entries = [e for e in entries if e.get("event") == "query"]
    assert query_entries
    last = query_entries[-1]
    assert "[メール]" in last["question"]
    assert "[電話番号]" in last["question"]
    assert "test@example.com" not in last["question"]
    assert "03-1234-5678" not in last["question"]


# ============================================================
# シナリオ4: 危険ファイル取り込み拒否
# ============================================================
def test_dangerous_file_rejected(client: TestClient):
    csv = b"\xef\xbb\xbfid,name,number\n1,foo,1234 5678 9012\n2,bar,9876 5432 1098\n"
    r = client.post("/api/admin/ingest", files={"file": ("staff.csv", csv, "text/csv")})
    assert r.status_code == 400
    assert "マイナンバー" in r.json()["detail"]


def test_dangerous_file_can_still_be_analyzed(client: TestClient):
    """analyze は danger 判定でも結果を返す（UIで判断するため）。"""
    csv = b"\xef\xbb\xbfid,name,number\n1,foo,1234 5678 9012\n"
    r = client.post("/api/admin/analyze", files={"file": ("staff.csv", csv, "text/csv")})
    assert r.status_code == 200
    assert r.json()["recommendation"] == "danger"


# ============================================================
# シナリオ5: 複数フォーマット同時取り込み
# ============================================================
def test_multi_format_ingest_and_query(client: TestClient):
    # Markdown
    client.post("/api/admin/ingest", files={
        "file": ("md.md", "# 出席\n\n出席ボタン押下".encode("utf-8"), "text/markdown")
    })
    # CSV
    client.post("/api/admin/ingest", files={
        "file": ("csv.csv", "q,a\nVPN,FortiClient起動\n".encode("utf-8"), "text/csv")
    })
    # Excel
    client.post("/api/admin/ingest", files={
        "file": ("xl.xlsx", _xlsx_bytes([["category", "answer"], ["有給", "KING OF TIME"]]),
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    })
    # PowerPoint
    client.post("/api/admin/ingest", files={
        "file": ("pp.pptx", _pptx_bytes(["経費精算は毎月25日"]),
                 "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    })

    # stats 確認: 4 文書取り込まれている
    r = client.get("/api/admin/stats")
    s = r.json()
    assert s["knowledge"]["n_documents"] == 4

    # 各フォーマットから検索できる（FAQマスターは .md に統一保存される仕様）
    for q, expected_src in [
        ("出席", "md.md"),
        ("VPN", "csv.md"),
        ("有給", "xl.md"),
        ("経費精算", "pp.md"),
    ]:
        r = client.post("/api/ask", json={"question": q})
        d = r.json()
        assert d["has_answer"] is True, f"{q} → {d}"
        assert any(s["source"] == expected_src for s in d["sources"]), \
            f"{q} の最上位が {expected_src} ではない: {d['sources']}"


# ============================================================
# シナリオ6: フィードバック投票 → stats 反映
# ============================================================
def test_feedback_updates_stats(client: TestClient):
    md = "# FAQ\n\n出席登録の方法".encode("utf-8")
    client.post("/api/admin/ingest", files={"file": ("a.md", md, "text/markdown")})
    client.post("/api/ask", json={"question": "出席登録"})

    # フィードバック投票
    r = client.post("/api/feedback", json={"question": "出席登録", "vote": "up", "sources": ["a.md"]})
    assert r.status_code == 200

    r = client.post("/api/feedback", json={"question": "出席登録", "vote": "down", "sources": ["a.md"]})
    assert r.status_code == 200

    # stats 反映確認
    s = client.get("/api/admin/stats").json()
    assert s["feedback"]["up"] == 1
    assert s["feedback"]["down"] == 1
    assert "出席登録" in s["feedback"]["down_questions"]


def test_feedback_validates_vote(client: TestClient):
    r = client.post("/api/feedback", json={"question": "x", "vote": "invalid"})
    assert r.status_code == 400


# ============================================================
# シナリオ7: 容量上限
# ============================================================
def test_oversized_file_rejected(client: TestClient):
    # 51MB のダミー
    big = b"x" * (51 * 1024 * 1024)
    r = client.post("/api/admin/analyze", files={"file": ("big.txt", big, "text/plain")})
    assert r.status_code == 413


# ============================================================
# シナリオ8: 未対応形式
# ============================================================
def test_unsupported_format(client: TestClient):
    r = client.post("/api/admin/analyze", files={"file": ("malware.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415


# ============================================================
# シナリオ9: stats が初期状態で動作する
# ============================================================
def test_stats_initial_state(client: TestClient):
    s = client.get("/api/admin/stats").json()
    assert s["knowledge"]["n_documents"] == 0
    assert s["analytics"]["n_queries_today"] == 0
    assert s["analytics"]["avg_confidence"] == 0
    assert s["feedback"]["up"] == 0
    assert s["history"] == []


# ============================================================
# シナリオ10: 確信度がトピックの種類で変わる
# ============================================================
def test_confidence_higher_for_specific_match(client: TestClient):
    md = "# VPN詳細\n\nFortiClient設定: corp-vpn / 社員番号 + AD パスワード + OTP".encode("utf-8")
    client.post("/api/admin/ingest", files={"file": ("vpn.md", md, "text/markdown")})

    specific = client.post("/api/ask", json={"question": "FortiClientの設定"}).json()
    vague = client.post("/api/ask", json={"question": "システムについて"}).json()

    # 具体的な質問の方が確信度が高い OR vague は no_answer
    if vague["has_answer"]:
        assert specific["confidence"] >= vague["confidence"]
    else:
        assert specific["has_answer"] is True
