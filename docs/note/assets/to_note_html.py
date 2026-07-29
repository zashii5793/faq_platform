#!/usr/bin/env python3
"""Markdown を「note に貼り付けるための HTML」に変換する。

なぜ HTML なのか:
    note のエディタは Markdown 記法を解釈しない。テキストのまま貼ると
    `##` や `**` が文字として残り、レイアウトが崩れる。
    一方、**ブラウザ上の書式付きテキストをコピーして貼ると、note は
    見出し・太字・リスト・引用を保持する**。
    そのため「ブラウザで開く → 全選択 → コピー → note に貼る」が最も崩れない。

使い方:
    python3 to_note_html.py 入力.md 出力.html
    → 出力.html をブラウザで開き、Cmd/Ctrl + A → Cmd/Ctrl + C → note に貼る

変換方針:
    - 表は note に機能が無いため、見出し + 箇条書きに展開する
    - コードブロックの中身は一切変更しない（入れ子フェンスにも対応）
    - フォントは CJK フォールバック事故を防ぐため IPA 系を明示する
"""
from __future__ import annotations

import html
import re
import sys

FONT_STACK = (
    '"Hiragino Kaku Gothic ProN", "Hiragino Sans", '
    '"Yu Gothic", YuGothic, Meiryo, "IPAPGothic", "IPAGothic", sans-serif'
)

STYLE = f"""
body {{
  font-family: {FONT_STACK};
  line-height: 1.9;
  max-width: 720px;
  margin: 0 auto;
  padding: 32px 20px 120px;
  color: #1a1a1a;
}}
h1 {{ font-size: 1.8em; margin: 1.8em 0 .6em; line-height: 1.5; }}
h2 {{ font-size: 1.45em; margin: 2em 0 .6em; line-height: 1.5;
     border-bottom: 2px solid #e5e5e5; padding-bottom: .3em; }}
h3 {{ font-size: 1.15em; margin: 1.8em 0 .5em; line-height: 1.6; }}
h4 {{ font-size: 1.02em; margin: 1.4em 0 .4em; }}
p {{ margin: .9em 0; }}
ul, ol {{ margin: .8em 0; padding-left: 1.6em; }}
li {{ margin: .35em 0; }}
blockquote {{ margin: 1.2em 0; padding: .6em 1em; border-left: 4px solid #ccc;
              background: #fafafa; }}
pre {{ background: #f5f5f5; padding: 14px 16px; overflow-x: auto;
       border-radius: 4px; line-height: 1.6; }}
pre, code {{ font-family: "SFMono-Regular", Consolas, "Courier New", monospace;
             font-size: .88em; }}
code {{ background: #f0f0f0; padding: .1em .35em; border-radius: 3px; }}
pre code {{ background: none; padding: 0; }}
hr {{ border: none; border-top: 1px solid #ddd; margin: 2.4em 0; }}
strong {{ font-weight: 700; }}
.row-title {{ margin: 1.1em 0 .2em; }}
"""


class FenceTracker:
    """コードフェンスの開閉を追跡する（入れ子フェンス対応）。"""

    def __init__(self) -> None:
        self.char: str | None = None
        self.size = 0

    @property
    def inside(self) -> bool:
        return self.char is not None

    def feed(self, line: str) -> bool:
        m = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if not m:
            return False
        tok, rest = m.group(1), m.group(2)
        char, size = tok[0], len(tok)
        if not self.inside:
            if char == "`" and "`" in rest:
                return False
            self.char, self.size = char, size
            return True
        if char == self.char and size >= self.size and not rest.strip():
            self.char, self.size = None, 0
            return True
        return False


def inline(text: str) -> str:
    """行内の Markdown 記法を HTML に変換する。"""
    # コードスパンを先に退避（中身を他の変換から守る）
    spans: list[str] = []

    def stash(m: re.Match[str]) -> str:
        spans.append(m.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)

    # Markdown のバックスラッシュエスケープ (\_ \* \| 等) を解除する。
    # 残すと日本語フォントで円記号として描画されてしまう。
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|])", r"\1", text)

    def pop(m: re.Match[str]) -> str:
        return "<code>" + html.escape(spans[int(m.group(1))], quote=False) + "</code>"

    return re.sub(r"\x00(\d+)\x00", pop, text)


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_sep(line: str) -> bool:
    s = line.strip()
    return (
        s.startswith("|")
        and bool(re.fullmatch(r"[\s|:\-]+", s))
        and "-" in s
    )


def _clean(text: str) -> str:
    return text.replace("<br>", " / ").replace("<br/>", " / ").replace("\\|", "|").strip()


def render_table(header: list[str], rows: list[list[str]]) -> list[str]:
    """表 → 見出し + 箇条書き（note に表機能が無いため）。"""
    out: list[str] = []
    if len(header) == 2:
        out.append("<ul>")
        for r in rows:
            left = _clean(r[0]) if r else ""
            right = _clean(r[1]) if len(r) > 1 else ""
            if not (left or right):
                continue
            # 元セルが既に **太字** の場合、二重に <strong> を巻かない
            head = inline(left) if left.startswith("**") and left.endswith("**") \
                else f"<strong>{inline(left)}</strong>"
            out.append(f"<li>{head}：{inline(right)}</li>" if right else f"<li>{head}</li>")
        out.append("</ul>")
        return out

    for r in rows:
        if not any(_clean(c) for c in r):
            continue
        title = _clean(r[0]) if r else ""
        if re.fullmatch(r"[#\d\s.]*", title) and len(r) > 1:
            num = title.strip()
            label = (num + " " if num else "") + _clean(r[1])
            rest = list(zip(header[2:], r[2:]))
        else:
            label = title
            rest = list(zip(header[1:], r[1:]))
        out.append(f'<p class="row-title"><strong>■ {inline(label)}</strong></p>')
        items = [(n, _clean(v)) for n, v in rest]
        items = [(n, v) for n, v in items if v and v != "—"]
        if items:
            out.append("<ul>")
            for name, val in items:
                out.append(f"<li>{inline(_clean(name))}：{inline(val)}</li>")
            out.append("</ul>")
    return out


def convert(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    fence = FenceTracker()
    i = 0
    para: list[str] = []
    list_stack: list[str] = []

    def flush_para() -> None:
        if para:
            out.append("<p>" + "<br>".join(inline(x) for x in para) + "</p>")
            para.clear()

    def close_lists() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    while i < len(lines):
        line = lines[i]

        # --- コードブロック（中身は無変換） ---
        if fence.feed(line):
            flush_para()
            close_lists()
            if fence.inside:  # 開いた
                buf: list[str] = []
                i += 1
                while i < len(lines):
                    if fence.feed(lines[i]) and not fence.inside:
                        break
                    buf.append(lines[i])
                    i += 1
                body = "\n".join(html.escape(b, quote=False) for b in buf)
                out.append(f"<pre><code>{body}</code></pre>")
            i += 1
            continue

        stripped = line.strip()

        # --- HTML コメントは落とす ---
        if stripped.startswith("<!--"):
            flush_para()
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue

        # --- 表 ---
        if stripped.startswith("|") and i + 1 < len(lines) and _is_sep(lines[i + 1]):
            flush_para()
            close_lists()
            header = _cells(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            out.extend(render_table(header, rows))
            continue

        # --- 見出し ---
        h = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if h:
            flush_para()
            close_lists()
            level = min(len(h.group(1)), 4)
            out.append(f"<h{level}>{inline(h.group(2).strip())}</h{level}>")
            i += 1
            continue

        # --- 水平線 ---
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            flush_para()
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        # --- 引用 ---
        if stripped.startswith(">"):
            flush_para()
            close_lists()
            quote: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            body = "<br>".join(inline(q) for q in quote if q.strip() or True)
            out.append(f"<blockquote>{body}</blockquote>")
            continue

        # --- リスト ---
        li = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if li:
            flush_para()
            indent, marker, body = len(li.group(1)), li.group(2), li.group(3)
            tag = "ul" if marker in "-*+" else "ol"
            depth = indent // 2 + 1
            while len(list_stack) > depth:
                out.append(f"</{list_stack.pop()}>")
            while len(list_stack) < depth:
                out.append(f"<{tag}>")
                list_stack.append(tag)
            # チェックボックスは記号に置換（note にチェックリスト機能が無いため）
            body = re.sub(r"^\[ \]\s*", "☐ ", body)
            body = re.sub(r"^\[[xX]\]\s*", "☑ ", body)
            out.append(f"<li>{inline(body)}</li>")
            i += 1
            continue

        # --- 空行 / 本文 ---
        if not stripped:
            flush_para()
            close_lists()
        else:
            if list_stack:
                close_lists()
            para.append(stripped)
        i += 1

    flush_para()
    close_lists()
    return "\n".join(out)


TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{style}</style>
</head>
<body>
{body}
</body>
</html>
"""


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        md = f.read()
    m = re.search(r"^#\s+(.*)$", md, re.M)
    title = m.group(1).strip() if m else "note 記事"
    with open(dst, "w", encoding="utf-8") as f:
        f.write(TEMPLATE.format(title=html.escape(title), style=STYLE, body=convert(md)))
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
