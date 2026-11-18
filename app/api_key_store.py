"""Anthropic API キーの保管（お客さまが管理画面から自分のキーを登録する方式・BYOK）。

SaaS で提供するとき、AI の利用料はお客さまの Anthropic アカウントに直接かかる形にしたい。
そのため、キーは `.env` に運営側が書くのではなく、お客さまの管理者が画面から登録する。

- 保存先は `settings.api_key_path`（既定 `./data/api_key.enc`）。中身は暗号化して置く
- 暗号鍵は `KEY_ENCRYPTION_SECRET`（無ければ `SESSION_SECRET`）から作る。
  データフォルダだけが漏れても、キーは読めない
- 画面に返すのは末尾4文字だけ。平文のキーは API の応答にも監査ログにも出さない
- 画面で登録したキーが無いときは、従来どおり `.env` の `ANTHROPIC_API_KEY` を使う
  （オンプレ導入の既存の運用を壊さない）

`runtime_settings.py` が「機密は画面で扱わない」としているのは、平文の JSON に
書くと漏れるから。ここは暗号化と管理者限定で、その理由を満たしたうえで扱う。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

DEFAULT_SESSION_SECRET = "dev-secret-change-me"
# Anthropic のキーの形。形が違うものは、問い合わせる前に断る
KEY_PATTERN = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,200}$")


class KeyStoreError(ValueError):
    """画面にそのまま出してよい理由を持つ例外。"""


def _fernet() -> Fernet:
    secret = settings.key_encryption_secret or settings.session_secret
    if not settings.demo_mode and (not secret or secret == DEFAULT_SESSION_SECRET):
        # 既定の合言葉で暗号化すると、誰でも復号できる。暗号化したふりになるので保存させない
        raise KeyStoreError(
            "暗号化の合言葉が既定値のままです。.env に KEY_ENCRYPTION_SECRET（または SESSION_SECRET）を設定してから登録してください。"
        )
    digest = hashlib.sha256(("inquira-api-key:" + secret).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _read() -> dict | None:
    path = settings.api_key_path
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def stored_key() -> str:
    """画面で登録したキー（復号済み）。無い・読めないときは空文字。"""
    data = _read()
    if not data or "token" not in data:
        return ""
    try:
        return _fernet().decrypt(data["token"].encode("ascii")).decode("utf-8")
    except (InvalidToken, KeyStoreError, ValueError):
        # 合言葉が変わった等で読めない。黙って .env に戻ると、どのキーで動いているか分からなくなるので
        # 状態は status() で「読めない」と出す
        return ""


def effective_key() -> str:
    """実際に使うキー。画面で登録したもの → `.env` の順。"""
    return stored_key() or settings.anthropic_api_key


def mask(key: str) -> str:
    return f"sk-ant-…{key[-4:]}" if key else ""


def status() -> dict:
    data = _read()
    stored = stored_key()
    if stored:
        source = "ui"
    elif data:
        source = "unreadable"  # ファイルはあるが復号できない
    elif settings.anthropic_api_key:
        source = "env"
    else:
        source = "none"
    key = stored or settings.anthropic_api_key
    return {
        "source": source,
        "masked": mask(key) if source in ("ui", "env") else "",
        "updated_at": (data or {}).get("updated_at", ""),
        "updated_by": (data or {}).get("updated_by", ""),
    }


def validate_format(key: str) -> str:
    key = (key or "").strip()
    if not KEY_PATTERN.match(key):
        raise KeyStoreError("Anthropic の API キーの形ではありません（sk-ant- で始まる文字列です）。")
    return key


def save(key: str, user_email: str) -> dict:
    key = validate_format(key)
    token = _fernet().encrypt(key.encode("utf-8")).decode("ascii")
    path = settings.api_key_path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "token": token,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "updated_by": user_email,
    }
    tmp = path.with_suffix(".tmp")
    # 本人（アプリの実行ユーザー）だけが読めるように作ってから中身を書く
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)
    return status()


def clear() -> dict:
    try:
        settings.api_key_path.unlink()
    except FileNotFoundError:
        pass
    return status()


def can_manage(user: dict) -> bool:
    """キーを登録・削除できるのは管理者だけ。

    管理画面の他の操作は「ログインできる人」なら誰でもできるが、キーは請求先そのものなので、
    `ADMIN_EMAILS` に書かれた人に限る。未設定なら誰にも変えさせない（安全側に倒す）。
    """
    if settings.demo_mode:
        return True
    email = (user or {}).get("email", "").strip().lower()
    return bool(email) and email in settings.admin_email_set
