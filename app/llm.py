"""Anthropic Claude 呼び出しのラッパー（プロンプトキャッシュ対応）。"""
from __future__ import annotations

from anthropic import Anthropic

from . import audit
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
8. 出力フォーマット（読みやすさ重視）:
   - 冒頭に「## 回答」「### 結論」のような無意味な見出しは**付けない**
   - 見出しは内容を区切る場合に限り「## 」または「### 」を使う（最大深さ ###）
   - 強調は **太字** とリスト「- 」を活用
   - 短い回答（1〜3文で済む場合）は見出し・リスト不要で平文だけで返す
   - **出典は本文と**1行空けて**から「**出典:** ファイル名 #ID」の形で1行に整理**
   - 複数チャンク参照時は「**出典:** Foo.md #12, #45, #88」のようにまとめる

出力例:
  良い: 「経費精算の締め日は毎月25日です。提出期限は翌営業日17時まで。
         出典: 経費精算.md」
  悪い: 「## 回答\n\n### 締め日について\n\n経費精算は…」（← 過剰な見出し）
"""

REFERENCE_PROMPT_TEMPLATE = """あなたは{org_name}の{role}アシスタントです。

このリクエストは「参考情報モード」です。[参考情報] には質問への直接の答えは
明示的に書かれていない可能性がありますが、可能な範囲で関連性の高い内容を
**そのまま引用または要約** して提示してください。

ルール（厳守）:
1. [参考情報] に書かれている内容を**そのまま引用または要約** するに留める
2. 推測・想像・事前知識による補完は**絶対に禁止**
3. 回答冒頭で「以下は関連しそうな情報です」「直接の答えではありませんが」など、
   公式回答ではないことを明示する
4. 該当情報が部分的でも、出典を必ず明記する
5. もし [参考情報] に質問と関連する内容が全くない場合は:
   「関連する情報も見つかりませんでした。」とだけ返す
6. マスキング済みのトークン（[氏名][メール][学校名]等）は復元せずそのまま使う

出力例:
  良い: 「直接の答えは見つかりませんが、関連情報として「経費精算は毎月25日締め」
         との記載があります（出典: 経費精算.md）。担当部署にご確認ください。」
  悪い: 「経費精算は通常月末頃が一般的です」（← 推測禁止）
"""


def system_prompt(reference_mode: bool = False) -> str:
    template = REFERENCE_PROMPT_TEMPLATE if reference_mode else SYSTEM_PROMPT_TEMPLATE
    return template.format(
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


def answer(question: str, chunks: list[tuple[Chunk, float]], reference_mode: bool = False) -> str:
    if not settings.anthropic_api_key:
        prefix = "（ローカルモード：APIキー未設定／参考情報モード）" if reference_mode else "（ローカルモード：APIキー未設定）"
        return (
            f"{prefix}\n\n"
            f"質問: {question}\n"
            f"参考: {[c.chunk_id for c, _ in chunks]}"
        )

    # プロンプトキャッシュ: system を構造化（テキストブロック）して cache_control を付与
    # Anthropic のキャッシュは最小トークン数（Haiku 4.5 は 2048 tok）に満たない場合は
    # 自動的にキャッシュ対象外になる（エラーにはならない）。
    system_blocks = [
        {
            "type": "text",
            "text": system_prompt(reference_mode=reference_mode),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    msg = _client().messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=system_blocks,
        messages=[{"role": "user", "content": build_user_prompt(question, chunks)}],
    )

    # キャッシュヒット状況を監査ログに記録（コスト最適化の可視化用）
    try:
        usage = getattr(msg, "usage", None)
        if usage is not None:
            audit.record(
                "llm_usage",
                model=settings.claude_model,
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
                cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                reference_mode=reference_mode,
            )
    except Exception:
        # 監査記録が失敗しても主処理は止めない（フォールバック）
        pass

    return "".join(block.text for block in msg.content if block.type == "text")
