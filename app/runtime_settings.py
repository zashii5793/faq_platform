"""ランタイムで編集可能な組織情報・ストレージパス設定。

`.env` の値を初期値として、UI から上書き可能。
変更は `data/org_settings.json` に保存され、次回起動時にも反映される。

Anthropic API キーや Google OAuth 認証情報のような機密性の高い設定は
ここでは扱わない（ファイル経由で誤って漏れるリスク回避のため）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import settings

OVERRIDES_PATH = settings.org_settings_path

# ランタイム編集を許可する設定キー（ホワイトリスト）
EDITABLE_KEYS = {
    "product_name",
    "org_name",
    "assistant_role",
    "masking_industry",
    # --- ストレージパス（A社オンプレ運用で利用者がディレクトリを切替できるよう公開） ---
    "faq_master_dir",
    "raw_upload_dir",
}

# Path 型として扱うキー（str から Path への変換が必要）
PATH_KEYS = {
    "faq_master_dir",
    "raw_upload_dir",
}


def load_and_apply() -> dict[str, Any]:
    """起動時呼び出し用：保存済みオーバーライドを settings に反映。"""
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    applied: dict[str, Any] = {}
    for key, value in data.items():
        if key in EDITABLE_KEYS and value:
            applied_value = Path(value) if key in PATH_KEYS else value
            setattr(settings, key, applied_value)
            applied[key] = value
    return applied


def current_overrides() -> dict[str, Any]:
    """ファイルに保存されているオーバーライド一覧を返す。"""
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def get_effective() -> dict[str, Any]:
    """編集可能キーの「現在有効な値」を返す（オーバーライド適用後）。

    Path 型は str に変換して返す（JSON 化のため）。
    """
    result: dict[str, Any] = {}
    for key in EDITABLE_KEYS:
        value = getattr(settings, key)
        result[key] = str(value) if isinstance(value, Path) else value
    return result


def _validate_path(key: str, value: str) -> Path:
    """ストレージパスの妥当性チェック。

    - 親ディレクトリが存在することを確認（無ければ作成試行）
    - 書き込み権限があることを確認
    """
    path = Path(value).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as e:
        raise ValueError(f"{key}: ディレクトリを作成できません ({e})") from e
    if not path.is_dir():
        raise ValueError(f"{key}: 指定パスはディレクトリではありません")
    # 書き込み権限テスト（一時ファイル作成 → 削除）
    test_file = path / ".inquira_write_test"
    try:
        test_file.touch()
        test_file.unlink()
    except (OSError, PermissionError) as e:
        raise ValueError(f"{key}: 書き込み権限がありません ({e})") from e
    return path


def update(updates: dict[str, Any]) -> dict[str, Any]:
    """設定を更新し、ファイルに保存し、settings に反映する。

    Args:
      updates: 更新する key/value（ホワイトリスト外は無視）

    Returns:
      適用された key/value
    """
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = current_overrides()
    applied: dict[str, Any] = {}
    for key, value in updates.items():
        if key not in EDITABLE_KEYS:
            continue
        if value is None:
            existing.pop(key, None)
            continue
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        if not value:
            existing.pop(key, None)
            continue
        max_len = 500 if key in PATH_KEYS else 200
        if len(value) > max_len:
            raise ValueError(f"{key} は {max_len} 文字以内にしてください")
        if key in PATH_KEYS:
            path = _validate_path(key, value)
            setattr(settings, key, path)
            existing[key] = str(path)
            applied[key] = str(path)
        else:
            existing[key] = value
            setattr(settings, key, value)
            applied[key] = value

    OVERRIDES_PATH.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return applied


def reset(key: str | None = None) -> None:
    """オーバーライドを削除して `.env` のデフォルトに戻す（ファイル削除のみ）。

    Args:
      key: 指定があればそのキーだけ削除、None なら全削除
    """
    if not OVERRIDES_PATH.exists():
        return
    if key is None:
        OVERRIDES_PATH.unlink()
        return
    existing = current_overrides()
    existing.pop(key, None)
    if existing:
        OVERRIDES_PATH.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        OVERRIDES_PATH.unlink()
