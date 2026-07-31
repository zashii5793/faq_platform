#!/usr/bin/env python3
"""Markdown を note 貼り付け用テキストに変換する。

note のエディタは表組みに対応していないため、表を箇条書きへ落とす。
コードブロック内は一切変換しない（表に見える行があっても触らない）。
入れ子フェンス (````markdown の中の ```css) を正しく扱う。
"""
from __future__ import annotations

import re
import sys


class FenceTracker:
    """コードフェンスの開閉を追跡する。

    CommonMark に従い、閉じフェンスは開きフェンスと同じ文字で、
    かつ同じ長さ以上でなければならない。これにより
    ````markdown ... ```css ... ``` ... ```` が正しく 1 ブロックになる。
    """

    def __init__(self) -> None:
        self.char: str | None = None
        self.size = 0

    @property
    def inside(self) -> bool:
        return self.char is not None

    def feed(self, line: str) -> bool:
        """行を食わせ、その行がフェンス行なら True を返す。"""
        m = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if not m:
            return False
        tok, rest = m.group(1), m.group(2)
        char, size = tok[0], len(tok)
        if not self.inside:
            # 開きフェンス（info string に同じ文字は入れられない）
            if char == "`" and "`" in rest:
                return False
            self.char, self.size = char, size
            return True
        # 閉じフェンス: 同じ文字・同じ長さ以上・後続は空白のみ
        if char == self.char and size >= self.size and not rest.strip():
            self.char, self.size = None, 0
            return True
        return False


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_sep(line: str) -> bool:
    """|---|---| のような区切り行か。"""
    s = line.strip()
    if not s.startswith("|"):
        return False
    return bool(re.fullmatch(r"[\s|:\-]+", s)) and "-" in s


def _clean(text: str) -> str:
    """セル内の装飾を note で読める形に整える。"""
    text = text.replace("<br>", " / ").replace("<br/>", " / ")
    text = text.replace("\\|", "|")
    return text.strip()


def convert_table(header: list[str], rows: list[list[str]]) -> list[str]:
    """表 → 箇条書き。

    2 列表  : 「・左：右」
    3 列以上: 1 列目を見出しにし、2 列目以降を「・列名：値」でぶら下げる
    """
    out: list[str] = []

    if len(header) == 2:
        for r in rows:
            left = _clean(r[0]) if r else ""
            right = _clean(r[1]) if len(r) > 1 else ""
            if not left and not right:
                continue
            out.append(f"・{left}：{right}" if right else f"・{left}")
        return out

    for r in rows:
        if not any(_clean(c) for c in r):
            continue
        title = _clean(r[0]) if r else ""
        # 1 列目が連番だけの表は、2 列目を見出しに繰り上げる
        if re.fullmatch(r"[#\d\s.]*", title) and len(r) > 1:
            num = title.strip()
            label = (num + " " if num else "") + _clean(r[1])
            rest = list(zip(header[2:], r[2:]))
        else:
            label = title
            rest = list(zip(header[1:], r[1:]))

        items = [(_clean(n), _clean(v)) for n, v in rest]
        items = [(n, v) for n, v in items if v and v != "—"]

        # 値が短い表は 1 行にまとめる。3 行に分けると情報量に対して冗長になる
        joined = " / ".join(f"{n}：{v}" for n, v in items)
        if items and len(joined) <= 60:
            out.append(f"■ {label}　{joined}")
            out.append("")
            continue

        out.append(f"■ {label}")
        for name, val in items:
            # 列名は常に残す。落とすと「何の値か」が読み取れなくなる
            out.append(f"・{name}：{val}")
        out.append("")
    while out and out[-1] == "":
        out.pop()
    return out


def convert(text: str) -> str:
    lines = text.split("\n")

    # --- パス 1: 表を箇条書きに ---
    out: list[str] = []
    fence = FenceTracker()
    i = 0
    while i < len(lines):
        line = lines[i]
        if fence.feed(line) or fence.inside:
            out.append(line)
            i += 1
            continue

        if line.strip().startswith("|") and i + 1 < len(lines) and _is_sep(lines[i + 1]):
            header = _cells(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            out.extend(convert_table(header, rows))
            out.append("")
            continue

        out.append(line)
        i += 1

    # --- パス 2: 見出しを記号付き行に（note は # を解釈しない） ---
    result: list[str] = []
    fence = FenceTracker()
    for line in out:
        if fence.feed(line) or fence.inside:
            result.append(line)
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if h:
            title = h.group(2).strip()
            result.append(f"【{title}】" if len(h.group(1)) <= 2 else f"◆ {title}")
            continue
        result.append(line)

    return re.sub(r"\n{4,}", "\n\n\n", "\n".join(result))


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        body = f.read()
    with open(dst, "w", encoding="utf-8") as f:
        f.write(convert(body))
    print(f"wrote {dst}")
