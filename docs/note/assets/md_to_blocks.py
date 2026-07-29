#!/usr/bin/env python3
"""Markdown を「ブロック構造の JSON」に変換する。

docx 生成 (to_note_docx.js) の入力になる中間表現。
HTML 版と同じ変換方針を使う:
  - 表は note に機能が無いため、見出し + 箇条書きに展開する
  - コードブロックの中身は一切変更しない（入れ子フェンス対応）

出力するブロック:
  {"t":"h",     "level":2, "runs":[...]}   見出し
  {"t":"p",     "runs":[...]}              段落
  {"t":"li",    "ordered":false, "level":1, "runs":[...]}  リスト項目
  {"t":"quote", "runs":[...]}              引用
  {"t":"code",  "text":"..."}              コードブロック
  {"t":"hr"}                               区切り線

run = {"text": "...", "b": true/false, "c": true/false}   b=太字, c=等幅
"""
from __future__ import annotations

import json
import re
import sys

from to_note_html import FenceTracker, _cells, _clean, _is_sep  # noqa: F401


def runs(text: str) -> list[dict]:
    """行内 Markdown を run のリストに分解する。"""
    # コードスパンを退避して他の変換から守る
    spans: list[str] = []

    def stash(m: re.Match[str]) -> str:
        spans.append(m.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Markdown のバックスラッシュエスケープを解除
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|])", r"\1", text)

    out: list[dict] = []
    for part in re.split(r"(\*\*.+?\*\*)", text):
        if not part:
            continue
        bold = part.startswith("**") and part.endswith("**") and len(part) > 4
        body = part[2:-2] if bold else part
        # 退避したコードスパンを個別の run として復元
        for piece in re.split(r"(\x00\d+\x00)", body):
            if not piece:
                continue
            m = re.fullmatch(r"\x00(\d+)\x00", piece)
            if m:
                out.append({"text": spans[int(m.group(1))], "b": bold, "c": True})
            else:
                out.append({"text": piece, "b": bold, "c": False})
    return out or [{"text": "", "b": False, "c": False}]


def table_blocks(header: list[str], rows: list[list[str]]) -> list[dict]:
    """表 → 見出し + 箇条書き。"""
    out: list[dict] = []
    if len(header) == 2:
        for r in rows:
            left = _clean(r[0]) if r else ""
            right = _clean(r[1]) if len(r) > 1 else ""
            if not (left or right):
                continue
            src = left if left.startswith("**") else f"**{left}**"
            out.append({"t": "li", "ordered": False, "level": 1,
                        "runs": runs(f"{src}：{right}" if right else src)})
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
        out.append({"t": "p", "rowTitle": True, "runs": runs(f"**■ {label}**")})
        for name, val in rest:
            val = _clean(val)
            if val and val != "—":
                out.append({"t": "li", "ordered": False, "level": 1,
                            "runs": runs(f"{_clean(name)}：{val}")})
    return out


def parse(md: str) -> list[dict]:
    lines = md.split("\n")
    blocks: list[dict] = []
    fence = FenceTracker()
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            blocks.append({"t": "p", "runs": runs(" ".join(para))})
            para.clear()

    while i < len(lines):
        line = lines[i]

        if fence.feed(line):
            flush()
            if fence.inside:
                buf: list[str] = []
                i += 1
                while i < len(lines):
                    if fence.feed(lines[i]) and not fence.inside:
                        break
                    buf.append(lines[i])
                    i += 1
                blocks.append({"t": "code", "text": "\n".join(buf)})
            i += 1
            continue

        s = line.strip()

        if s.startswith("<!--"):
            flush()
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue

        if s.startswith("|") and i + 1 < len(lines) and _is_sep(lines[i + 1]):
            flush()
            header = _cells(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            blocks.extend(table_blocks(header, rows))
            continue

        h = re.match(r"^(#{1,6})\s+(.*)$", s)
        if h:
            flush()
            blocks.append({"t": "h", "level": min(len(h.group(1)), 4),
                           "runs": runs(h.group(2).strip())})
            i += 1
            continue

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            flush()
            blocks.append({"t": "hr"})
            i += 1
            continue

        if s.startswith(">"):
            flush()
            quote: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]).strip())
                i += 1
            blocks.append({"t": "quote", "runs": runs(" ".join(q for q in quote if q))})
            continue

        li = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if li:
            flush()
            body = li.group(3)
            body = re.sub(r"^\[ \]\s*", "☐ ", body)
            body = re.sub(r"^\[[xX]\]\s*", "☑ ", body)
            blocks.append({
                "t": "li",
                "ordered": li.group(2) not in "-*+",
                "level": min(len(li.group(1)) // 2 + 1, 3),
                "runs": runs(body),
            })
            i += 1
            continue

        if not s:
            flush()
        else:
            para.append(s)
        i += 1

    flush()
    return blocks


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        md = f.read()
    m = re.search(r"^#\s+(.*)$", md, re.M)
    doc = {"title": m.group(1).strip() if m else "note 記事", "blocks": parse(md)}
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    print(f"wrote {sys.argv[2]} ({len(doc['blocks'])} blocks)")
