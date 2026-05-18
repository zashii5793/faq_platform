"""Google OAuth 2.0 認証。許可ドメイン or 明示メールリストでアクセス制御する。"""
from __future__ import annotations

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request, status

from .config import settings

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def is_email_allowed(email: str) -> bool:
    email = email.strip().lower()
    # 最低限のメール形式バリデーション: ローカル部 + @ + ドメイン部
    # 空ローカル部 (@example.com) や 二重@ (a@@b.com) を弾く
    if email.count("@") != 1:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain:
        return False
    if settings.allowed_emails and email in settings.allowed_email_set:
        return True
    if settings.allowed_domain and email.endswith("@" + settings.allowed_domain.lower()):
        return True
    return False


def require_user(request: Request) -> dict:
    if settings.demo_mode:
        return {"email": "demo@local", "name": "Demo User"}
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not signed in")
    if not is_email_allowed(user.get("email", "")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    return user
