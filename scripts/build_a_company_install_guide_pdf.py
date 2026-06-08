"""A社IT部門向けインストールガイドの PDF を生成。

tenants/a_company/README.md を Markdown から HTML 化し、weasyprint で PDF 化。

使い方:
    pip install weasyprint markdown
    python scripts/build_a_company_install_guide_pdf.py

出力:
    docs/a_company_install_guide.pdf
"""
from __future__ import annotations

from pathlib import Path

import markdown
from weasyprint import HTML

ROOT = Path(__file__).resolve().parents[1]
SRC_MD = ROOT / "tenants" / "a_company" / "README.md"
OUT_PDF = ROOT / "docs" / "a_company_install_guide.pdf"

CSS = """
@page {
  size: A4;
  margin: 18mm 16mm 18mm 16mm;
  @bottom-right {
    content: "Inquira インストール手順 (A社IT部門向け)  —  " counter(page) " / " counter(pages);
    font-size: 8pt;
    color: #9ca3af;
  }
}
* { box-sizing: border-box; }
body {
  font-family: "IPAPGothic", "IPAGothic", "Hiragino Sans", "Yu Gothic", sans-serif;
  color: #1f2937;
  font-size: 9.5pt;
  line-height: 1.7;
}
h1 {
  font-size: 18pt;
  color: #0f766e;
  border-bottom: 3px solid #14b8a6;
  padding-bottom: 6px;
  margin-bottom: 10px;
}
h2 {
  font-size: 13pt;
  color: #0f766e;
  border-left: 4px solid #14b8a6;
  padding-left: 8px;
  margin: 18px 0 8px;
  page-break-after: avoid;
}
h3 {
  font-size: 11pt;
  color: #134e4a;
  margin: 12px 0 6px;
  page-break-after: avoid;
}
blockquote {
  background: #fffbeb;
  border-left: 4px solid #f59e0b;
  padding: 6px 12px;
  margin: 8px 0;
  font-size: 9pt;
  color: #78350f;
}
blockquote p { margin: 0; }
code {
  background: #f3f4f6;
  color: #be185d;
  padding: 1px 4px;
  border-radius: 3px;
  font-family: "IPAGothic", monospace;
  font-size: 8.5pt;
}
pre {
  background: #0f172a;
  color: #e0f2fe;
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 8pt;
  line-height: 1.55;
  overflow-x: auto;
  margin: 8px 0;
  page-break-inside: avoid;
}
pre code {
  background: transparent;
  color: inherit;
  padding: 0;
  font-size: 8pt;
}
table {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  font-size: 8.5pt;
  page-break-inside: avoid;
}
th {
  background: #ccfbf1;
  color: #134e4a;
  padding: 5px 8px;
  text-align: left;
  border: 1px solid #99f6e4;
  font-weight: 700;
}
td {
  padding: 5px 8px;
  border: 1px solid #e5e7eb;
  vertical-align: top;
}
tr:nth-child(even) td { background: #fafafa; }
ul, ol { margin: 6px 0 6px 20px; }
li { margin: 2px 0; }
hr {
  border: 0;
  border-top: 1px dashed #d1d5db;
  margin: 14px 0;
}
strong { color: #0f766e; }
a { color: #1a73e8; text-decoration: none; }
"""


def main() -> None:
    md_text = SRC_MD.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc"],
    )
    full_html = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>Inquira インストール手順 — A株式会社 IT 部門向け</title>
<style>{CSS}</style>
</head><body>
{html_body}
</body></html>
"""
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=full_html).write_pdf(str(OUT_PDF))
    print(f"OK: {OUT_PDF}")


if __name__ == "__main__":
    main()
