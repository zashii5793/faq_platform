"""FAQ 候補化機能のユニットテスト。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import faq_candidate_settings, faq_candidates


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    """各テストで独立した data ディレクトリを使う。"""
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "faq_master_dir", tmp_path / "faq_master")
    monkeypatch.setattr(_settings, "audit_log_dir", tmp_path / "audit")
    monkeypatch.setattr(_settings, "faq_candidates_path", tmp_path / "faq_candidates.json")
    monkeypatch.setattr(
        _settings, "faq_candidate_settings_path", tmp_path / "faq_candidate_settings.json"
    )

    # audit モジュールの LOG_DIR も明示的に更新
    from app import audit

    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "audit")

    # キャッシュをクリア
    faq_candidates.reset_cache()
    faq_candidate_settings.reset_cache()

    # rag.reload_index を no-op に差し替え（テスト時はインデックス再構築不要）
    from app import rag

    monkeypatch.setattr(rag, "reload_index", lambda: None)
    return tmp_path


def _write_audit_log(tmp_path: Path, entries: list[dict]) -> None:
    log_dir = tmp_path / "audit"
    log_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = log_dir / f"audit-{today}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _query_entry(question: str, answer: str, *, user: str, confidence: int = 85) -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "query",
        "user": user,
        "question": question,
        "answer": answer,
        "sources": ["doc.md#0"],
        "confidence": confidence,
        "answered": True,
    }


# ----- 設定の保存/読み込み -----


def test_settings_default(tmp_data):
    s = faq_candidate_settings.load()
    assert s.min_confidence == 70
    assert s.auto_approve_enabled is False


def test_settings_update(tmp_data):
    s = faq_candidate_settings.update(min_confidence=80, auto_approve_enabled=True)
    assert s.min_confidence == 80
    assert s.auto_approve_enabled is True
    faq_candidate_settings.reset_cache()
    s2 = faq_candidate_settings.load()
    assert s2.min_confidence == 80
    assert s2.auto_approve_enabled is True


# ----- 検出 -----


def test_detect_empty_audit_log(tmp_data):
    stats = faq_candidates.detect()
    assert stats["new"] == 0
    assert faq_candidates.list_all() == []


def test_detect_promotes_eligible_cluster(tmp_data):
    # 3 ユーザーが似た質問を 3 回（min_asked_count=3, min_unique_users=2 を満たす）
    entries = [
        _query_entry("経費精算の期限はいつまでですか", "翌月5営業日以内です。", user="a@x.jp"),
        _query_entry("経費精算の期限はいつまでですか？", "翌月5営業日以内です。", user="b@x.jp"),
        _query_entry("経費精算の期限はいつまで？", "翌月5営業日以内です。", user="c@x.jp"),
    ]
    _write_audit_log(tmp_data, entries)
    stats = faq_candidates.detect()
    assert stats["new"] == 1
    assert stats["auto_approved"] == 0
    cands = faq_candidates.list_all("pending")
    assert len(cands) == 1
    c = cands[0]
    assert c.support["asked_count"] == 3
    assert c.support["unique_users"] == 3
    assert c.confidence == 85


def test_detect_skips_low_confidence(tmp_data):
    entries = [
        _query_entry("低確信度のテスト質問A", "回答X", user="a@x.jp", confidence=40),
        _query_entry("低確信度のテスト質問B", "回答X", user="b@x.jp", confidence=40),
        _query_entry("低確信度のテスト質問C", "回答X", user="c@x.jp", confidence=40),
    ]
    _write_audit_log(tmp_data, entries)
    stats = faq_candidates.detect()
    assert stats["new"] == 0
    assert stats["below_threshold"] >= 1


def test_detect_skips_single_user(tmp_data):
    # 同一ユーザーが繰り返し聞いても候補化しない
    entries = [
        _query_entry(f"同一ユーザーが繰り返し聞く質問パターン{i}", "回答X", user="a@x.jp")
        for i in range(5)
    ]
    _write_audit_log(tmp_data, entries)
    stats = faq_candidates.detect()
    assert stats["new"] == 0


def test_detect_clusters_similar_questions(tmp_data):
    entries = [
        _query_entry("VPN の接続方法を教えてください", "FortiClient を使います", user="a@x.jp"),
        _query_entry("VPN の接続方法を教えて", "FortiClient を使います", user="b@x.jp"),
        _query_entry("VPN の接続方法は", "FortiClient を使います", user="c@x.jp"),
        _query_entry("有給休暇の申請方法を教えてください", "WorkPort から申請します", user="a@x.jp"),
        _query_entry("有給休暇の申請方法を教えて", "WorkPort から申請します", user="b@x.jp"),
        _query_entry("有給休暇の申請方法は", "WorkPort から申請します", user="c@x.jp"),
    ]
    _write_audit_log(tmp_data, entries)
    stats = faq_candidates.detect()
    # 2 クラスタとも候補化される
    assert stats["new"] == 2


def test_detect_skips_existing_faq(tmp_data):
    # 既存 FAQ に同類のものがあればスキップ
    (tmp_data / "faq_master").mkdir(parents=True, exist_ok=True)
    (tmp_data / "faq_master" / "vpn.md").write_text(
        "# VPN の接続方法を教えてください\n\nFortiClient を使います\n", encoding="utf-8"
    )
    entries = [
        _query_entry("VPN の接続方法を教えてください", "FortiClient を使います", user="a@x.jp"),
        _query_entry("VPN の接続方法を教えて", "FortiClient を使います", user="b@x.jp"),
        _query_entry("VPN の接続方法は", "FortiClient を使います", user="c@x.jp"),
    ]
    _write_audit_log(tmp_data, entries)
    stats = faq_candidates.detect()
    assert stats["new"] == 0
    assert stats["skipped_existing_faq"] >= 1


# ----- 自動承認 -----


def test_auto_approve_mode(tmp_data):
    faq_candidate_settings.update(
        auto_approve_enabled=True,
        auto_approve_min_confidence=80,
        auto_approve_min_asked_count=3,
        auto_approve_min_unique_users=3,
    )
    entries = [
        _query_entry("自動承認テスト質問", "自動承認テスト回答", user="a@x.jp", confidence=90),
        _query_entry("自動承認テストです質問", "自動承認テスト回答", user="b@x.jp", confidence=90),
        _query_entry("自動承認テストの質問", "自動承認テスト回答", user="c@x.jp", confidence=90),
    ]
    _write_audit_log(tmp_data, entries)
    stats = faq_candidates.detect()
    assert stats["auto_approved"] == 1
    # 自動承認されると faq_master に Markdown が生成される
    files = list((tmp_data / "faq_master").glob("faq-auto-*.md"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "自動承認" in content
    assert "自動承認テスト回答" in content


# ----- 承認 / 却下 -----


def test_approve_writes_faq_doc(tmp_data):
    entries = [
        _query_entry("テスト質問A", "回答A", user="a@x.jp"),
        _query_entry("テスト質問B", "回答A", user="b@x.jp"),
        _query_entry("テスト質問C", "回答A", user="c@x.jp"),
    ]
    _write_audit_log(tmp_data, entries)
    faq_candidates.detect()
    cand = faq_candidates.list_all("pending")[0]

    approved = faq_candidates.approve(cand.id, reviewer="admin@x.jp", note="OK")
    assert approved.status == "approved"
    assert approved.reviewed_by == "admin@x.jp"
    assert approved.approved_doc_path
    assert Path(approved.approved_doc_path).exists()
    assert "管理者承認" in Path(approved.approved_doc_path).read_text(encoding="utf-8")


def test_approve_with_edit(tmp_data):
    entries = [
        _query_entry("元の質問A", "元の回答", user="a@x.jp"),
        _query_entry("元の質問B", "元の回答", user="b@x.jp"),
        _query_entry("元の質問C", "元の回答", user="c@x.jp"),
    ]
    _write_audit_log(tmp_data, entries)
    faq_candidates.detect()
    cand = faq_candidates.list_all("pending")[0]

    approved = faq_candidates.approve(
        cand.id,
        reviewer="admin@x.jp",
        question="編集後の質問",
        answer="編集後の回答",
    )
    content = Path(approved.approved_doc_path).read_text(encoding="utf-8")
    assert "編集後の質問" in content
    assert "編集後の回答" in content


def test_reject_keeps_status(tmp_data):
    entries = [
        _query_entry("拒否される質問A", "回答", user="a@x.jp"),
        _query_entry("拒否される質問B", "回答", user="b@x.jp"),
        _query_entry("拒否される質問C", "回答", user="c@x.jp"),
    ]
    _write_audit_log(tmp_data, entries)
    faq_candidates.detect()
    cand = faq_candidates.list_all("pending")[0]

    rejected = faq_candidates.reject(cand.id, reviewer="admin@x.jp", note="不適切")
    assert rejected.status == "rejected"
    assert faq_candidates.list_all("pending") == []
    assert len(faq_candidates.list_all("rejected")) == 1


def test_approve_twice_raises(tmp_data):
    entries = [
        _query_entry("二重承認テスト質問A", "回答", user="a@x.jp"),
        _query_entry("二重承認テスト質問B", "回答", user="b@x.jp"),
        _query_entry("二重承認テスト質問C", "回答", user="c@x.jp"),
    ]
    _write_audit_log(tmp_data, entries)
    faq_candidates.detect()
    cand = faq_candidates.list_all("pending")[0]
    faq_candidates.approve(cand.id, reviewer="admin@x.jp")
    with pytest.raises(ValueError):
        faq_candidates.approve(cand.id, reviewer="admin@x.jp")


def test_count_by_status(tmp_data):
    entries = [
        _query_entry("ステータス確認テストA", "回答", user="a@x.jp"),
        _query_entry("ステータス確認テストB", "回答", user="b@x.jp"),
        _query_entry("ステータス確認テストC", "回答", user="c@x.jp"),
    ]
    _write_audit_log(tmp_data, entries)
    faq_candidates.detect()
    counts = faq_candidates.count_by_status()
    assert counts["pending"] == 1
    assert counts["approved"] == 0
    assert counts["rejected"] == 0
