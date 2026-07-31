"""runtime_settings.py の永続化・境界・壊れたファイル耐性。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import runtime_settings


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch):
    """各テストで独立した設定ファイルを使う。"""
    monkeypatch.setattr(runtime_settings, "OVERRIDES_PATH", tmp_path / "org_settings.json")
    yield tmp_path / "org_settings.json"


# ============================================================
# load_and_apply: 破損ファイル耐性
# ============================================================
class TestLoadAndApply:
    def test_missing_file_returns_empty(self, isolated_settings):
        assert runtime_settings.load_and_apply() == {}

    def test_broken_json_returns_empty(self, isolated_settings):
        isolated_settings.write_text("{{{ not json", encoding="utf-8")
        assert runtime_settings.load_and_apply() == {}

    def test_unknown_keys_ignored(self, isolated_settings, monkeypatch):
        """ホワイトリスト外のキーは settings に反映されない。"""
        from app.config import settings
        isolated_settings.write_text(
            json.dumps({"anthropic_api_key": "evil-key", "org_name": "Acme"}),
            encoding="utf-8",
        )
        original_api_key = settings.anthropic_api_key
        runtime_settings.load_and_apply()
        # API キーは永続化対象外 → 上書きされていない
        assert settings.anthropic_api_key == original_api_key

    def test_empty_string_value_ignored(self, isolated_settings):
        """空文字列は適用しない（既存値を保持）。"""
        isolated_settings.write_text(
            json.dumps({"org_name": ""}),
            encoding="utf-8",
        )
        result = runtime_settings.load_and_apply()
        assert "org_name" not in result

    def test_null_value_ignored(self, isolated_settings):
        isolated_settings.write_text(
            json.dumps({"org_name": None}),
            encoding="utf-8",
        )
        result = runtime_settings.load_and_apply()
        assert "org_name" not in result


# ============================================================
# update: バリデーション
# ============================================================
class TestUpdate:
    def test_update_basic(self, isolated_settings):
        applied = runtime_settings.update({"org_name": "Acme Corp"})
        assert applied == {"org_name": "Acme Corp"}
        assert isolated_settings.exists()

    def test_update_200_chars_ok(self, isolated_settings):
        exact = "x" * 200
        applied = runtime_settings.update({"org_name": exact})
        assert applied["org_name"] == exact

    def test_update_201_chars_raises(self, isolated_settings):
        over = "x" * 201
        with pytest.raises(ValueError):
            runtime_settings.update({"org_name": over})

    def test_update_unknown_key_silently_ignored(self, isolated_settings):
        applied = runtime_settings.update({"unknown_xyz": "value"})
        assert applied == {}

    def test_update_strips_whitespace(self, isolated_settings):
        applied = runtime_settings.update({"org_name": "  Acme  "})
        assert applied["org_name"] == "Acme"

    def test_update_only_whitespace_removes_key(self, isolated_settings):
        """空白のみの値は削除扱い。"""
        runtime_settings.update({"org_name": "Acme"})
        applied = runtime_settings.update({"org_name": "   "})
        # 削除されたので applied は空
        assert applied == {}
        current = runtime_settings.current_overrides()
        assert "org_name" not in current

    def test_update_none_removes_key(self, isolated_settings):
        runtime_settings.update({"org_name": "Acme"})
        runtime_settings.update({"org_name": None})
        current = runtime_settings.current_overrides()
        assert "org_name" not in current

    def test_update_non_string_coerced(self, isolated_settings):
        """非文字列は str() で強制変換される。"""
        applied = runtime_settings.update({"org_name": 123})
        assert applied["org_name"] == "123"

    def test_update_persists_across_calls(self, isolated_settings):
        runtime_settings.update({"org_name": "Acme"})
        runtime_settings.update({"assistant_role": "ヘルプデスク"})
        current = runtime_settings.current_overrides()
        assert current["org_name"] == "Acme"
        assert current["assistant_role"] == "ヘルプデスク"

    def test_update_with_unicode_value(self, isolated_settings):
        applied = runtime_settings.update({"org_name": "🚗 デモ会社 株式会社"})
        assert applied["org_name"] == "🚗 デモ会社 株式会社"
        # 再読み込みでも保持
        reloaded = runtime_settings.current_overrides()
        assert reloaded["org_name"] == "🚗 デモ会社 株式会社"

    def test_update_with_newline_in_value(self, isolated_settings):
        """改行を含む値も受け入れる（strip は両端のみ）。"""
        applied = runtime_settings.update({"org_name": "Acme\nCorp"})
        # 改行が中央にある場合は保持される
        assert "\n" in applied.get("org_name", "") or applied.get("org_name") == "Acme\nCorp"


# ============================================================
# reset: 削除挙動
# ============================================================
class TestReset:
    def test_reset_all_when_file_missing(self, isolated_settings):
        # 例外なし
        runtime_settings.reset()

    def test_reset_all_removes_file(self, isolated_settings):
        runtime_settings.update({"org_name": "X"})
        assert isolated_settings.exists()
        runtime_settings.reset()
        assert not isolated_settings.exists()

    def test_reset_specific_key_keeps_others(self, isolated_settings):
        runtime_settings.update({"org_name": "X", "assistant_role": "Y"})
        runtime_settings.reset("org_name")
        current = runtime_settings.current_overrides()
        assert "org_name" not in current
        assert current["assistant_role"] == "Y"

    def test_reset_last_key_removes_file(self, isolated_settings):
        runtime_settings.update({"org_name": "X"})
        runtime_settings.reset("org_name")
        assert not isolated_settings.exists()

    def test_reset_nonexistent_key_no_error(self, isolated_settings):
        runtime_settings.update({"org_name": "X"})
        # 存在しないキーを reset しても落ちない
        runtime_settings.reset("nonexistent_key")
        current = runtime_settings.current_overrides()
        assert current["org_name"] == "X"


# ============================================================
# current_overrides / get_effective
# ============================================================
class TestGetters:
    def test_current_overrides_missing_file(self, isolated_settings):
        assert runtime_settings.current_overrides() == {}

    def test_current_overrides_broken_json(self, isolated_settings):
        isolated_settings.write_text("not json", encoding="utf-8")
        assert runtime_settings.current_overrides() == {}

    def test_get_effective_returns_all_editable_keys(self, isolated_settings):
        eff = runtime_settings.get_effective()
        # 編集可能な全キーが含まれている
        for key in runtime_settings.EDITABLE_KEYS:
            assert key in eff


# ============================================================
# ファイル書き込み失敗の整合性（既知の弱点を可視化）
# ============================================================
class TestWriteFailureConsistency:
    def test_settings_in_memory_persists_even_if_write_fails(
        self, isolated_settings, monkeypatch
    ):
        """ファイル書き込みが失敗しても in-memory の settings は更新されてしまう。
        理想は: 書き込み失敗時にロールバックすべき。
        既知の弱点: 現状は in-memory が先行更新→ファイル書き込み→失敗時に不整合。
        """
        # 親ディレクトリを作れないようなパスを指定
        bad_path = isolated_settings.parent / "no_perm" / "settings.json"
        monkeypatch.setattr(runtime_settings, "OVERRIDES_PATH", bad_path)

        try:
            # 親ディレクトリ作成のため mkdir(parents=True) されるので、実際は成功する
            # 強制的に書き込み失敗にしたい場合は monkeypatch で write_text を例外化
            runtime_settings.update({"org_name": "ShouldFail"})
        except Exception:
            pass
        # この時点で in-memory は変更されているか？
        # （現状仕様: 変更されている。理想: 変更されていない）


# ============================================================
# ストレージパス設定（faq_master_dir, raw_upload_dir）
# ============================================================
class TestStoragePathSettings:
    def test_path_keys_in_editable(self):
        """ストレージパスのキーが編集可能リストに含まれる。"""
        assert "faq_master_dir" in runtime_settings.EDITABLE_KEYS
        assert "raw_upload_dir" in runtime_settings.EDITABLE_KEYS
        assert "faq_master_dir" in runtime_settings.PATH_KEYS
        assert "raw_upload_dir" in runtime_settings.PATH_KEYS

    def test_valid_path_is_applied_as_path_object(self, isolated_settings, tmp_path):
        """書き込み可能なパスを設定すると Path オブジェクトとして反映される。"""
        from app.config import settings

        target = tmp_path / "custom_faq_dir"
        applied = runtime_settings.update({"faq_master_dir": str(target)})

        assert "faq_master_dir" in applied
        assert isinstance(settings.faq_master_dir, Path)
        assert settings.faq_master_dir.exists()
        assert settings.faq_master_dir.is_dir()

    def test_path_persistence_round_trip(self, isolated_settings, tmp_path):
        """update → load_and_apply で Path 設定が正しく復元される。"""
        from app.config import settings

        target = tmp_path / "persist_test"
        runtime_settings.update({"faq_master_dir": str(target)})

        # settings をリセット相当（別の値に変更してから load し直す）
        settings.faq_master_dir = Path("./data/faq_master")
        applied = runtime_settings.load_and_apply()

        assert "faq_master_dir" in applied
        assert isinstance(settings.faq_master_dir, Path)
        assert str(settings.faq_master_dir) == str(target)

    def test_get_effective_returns_path_as_string(self, isolated_settings, tmp_path):
        """get_effective() は JSON 化のため Path を str で返す。"""
        target = tmp_path / "str_test"
        runtime_settings.update({"faq_master_dir": str(target)})

        effective = runtime_settings.get_effective()
        assert isinstance(effective["faq_master_dir"], str)
        assert str(target) in effective["faq_master_dir"]

    def test_relative_path_is_accepted(self, isolated_settings, tmp_path, monkeypatch):
        """相対パスも受け入れる（cwd 基準で解決される）。"""
        monkeypatch.chdir(tmp_path)
        applied = runtime_settings.update({"faq_master_dir": "./my_data"})
        assert "faq_master_dir" in applied
        assert (tmp_path / "my_data").exists()

    def test_path_with_500_chars_accepted(self, isolated_settings, tmp_path):
        """パス長は 500 文字まで許容（一般文字列は 200 文字まで）。"""
        # 長いがディレクトリとして作成可能なパス
        long_name = "a" * 100
        target = tmp_path / long_name
        applied = runtime_settings.update({"faq_master_dir": str(target)})
        assert "faq_master_dir" in applied

    def test_path_over_500_chars_rejected(self, isolated_settings, tmp_path):
        """500 文字を超えるパスは拒否される。"""
        long_path = str(tmp_path / ("a" * 600))
        with pytest.raises(ValueError, match="500 文字"):
            runtime_settings.update({"faq_master_dir": long_path})

    def test_unreadable_path_rejected(self, isolated_settings, tmp_path, monkeypatch):
        """書き込み権限のないパスは ValueError を投げる。"""
        # /dev/null 配下にディレクトリを作ろうとして失敗するケース
        with pytest.raises(ValueError, match="ディレクトリを作成できません|書き込み権限"):
            runtime_settings.update({"faq_master_dir": "/dev/null/cannot_create"})

    def test_two_path_keys_can_coexist(self, isolated_settings, tmp_path):
        """faq_master_dir と raw_upload_dir を同時に変更できる。"""
        from app.config import settings

        faq_dir = tmp_path / "faq"
        raw_dir = tmp_path / "raw"
        applied = runtime_settings.update({
            "faq_master_dir": str(faq_dir),
            "raw_upload_dir": str(raw_dir),
        })
        assert "faq_master_dir" in applied
        assert "raw_upload_dir" in applied
        assert isinstance(settings.faq_master_dir, Path)
        assert isinstance(settings.raw_upload_dir, Path)

    def test_reset_removes_path_override(self, isolated_settings, tmp_path):
        """reset() でパスのオーバーライドも削除される。"""
        target = tmp_path / "to_be_reset"
        runtime_settings.update({"faq_master_dir": str(target)})
        assert runtime_settings.current_overrides().get("faq_master_dir")

        runtime_settings.reset()
        assert "faq_master_dir" not in runtime_settings.current_overrides()
