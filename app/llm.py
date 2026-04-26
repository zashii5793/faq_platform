"""Anthropic Claude 呼び出しのラッパー。"""
from __future__ import annotations

from anthropic import Anthropic

from .config import settings
from .rag import Chunk

SYSTEM_PROMPT_TEMPLATE = """あなたは{org_name}の{role}アシスタントです。
以下のルールを厳守してください:

1. 提供された [参考情報] のみを根拠に回答する
2. [参考情報] に答えが無い場合は推測せず「該当情報が見つかりませんでした」と伝える
3. 回答末尾に出典（ドキュメント名やID）を必ず明記する
4. マスキング済みのトークン（[氏名][メール]等）は復元せずそのまま使う
5. 簡潔・正確に。冗長な前置きは避ける。
"""


def system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        org_name=settings.org_name, role=settings.assistant_role
    )


def _client() -> Anthropic:
    return Anthropic(api_key=settings.anthropic_api_key)


def build_user_prompt(question: str, chunks: list[tuple[Chunk, float]]) -> str:
    if not chunks:
        return f"質問: {question}\n\n[参考情報]\n（参考情報なし）"
    refs = "\n\n".join(
        f"[出典: {c.chunk_id}]\n{c.text}" for c, _ in chunks
    )
    return f"[参考情報]\n{refs}\n\n質問: {question}"


def answer(question: str, chunks: list[tuple[Chunk, float]]) -> str:
    if not settings.anthropic_api_key:
        return (
            "（ローカルモード：APIキー未設定）\n\n"
            f"質問: {question}\n"
            f"参考: {[c.chunk_id for c, _ in chunks]}"
        )
    msg = _client().messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=system_prompt(),
        messages=[{"role": "user", "content": build_user_prompt(question, chunks)}],
    )
    return "".join(block.text for block in msg.content if block.type == "text")
