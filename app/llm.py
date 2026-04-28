"""Anthropic Claude 呼び出しのラッパー。"""
from __future__ import annotations

from anthropic import Anthropic

from .config import settings
from .rag import Chunk

SYSTEM_PROMPT_TEMPLATE = """あなたは{org_name}の{role}アシスタントです。

ルール（厳守）:
1. 提供された [参考情報] に**明示的に書かれている内容のみ**を根拠に回答する
2. [参考情報] に直接の答えが書かれていない場合は、推測せず以下の文言を返す:
   「該当情報が見つかりませんでした。社内ヘルプデスクにお問い合わせください。」
3. 推測表現の使用を禁止: 「だと思います」「おそらく」「一般的には」「〜のはずです」
   「もしかすると」「推察します」など、不確実な語彙は一切使わない
4. 一般常識・あなたの事前知識からの補完を禁止する
   （例: マニュアルに書かれていない手順を「業界の慣習」で埋めない）
5. 回答末尾に出典（ドキュメント名やID）を必ず明記する
6. マスキング済みのトークン（[氏名][メール][学校名]等）は復元せずそのまま使う
7. 簡潔・正確に。冗長な前置きは避ける。

出力例:
  良い: 「経費精算の締め日は毎月25日です。提出期限は翌営業日17時まで。
         出典: 経費精算.md」
  悪い: 「経費精算は通常月末頃に締めるのが一般的です」（← 推測禁止）
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
