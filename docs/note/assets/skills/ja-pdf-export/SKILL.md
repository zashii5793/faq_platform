---
name: ja-pdf-export
description: 日本語の HTML を PDF に変換する。中国語フォントへのフォールバックを防ぎ、A4 レイアウトを検証する。「PDF にして」「PDF 化」「資料を印刷用に」と言われたときに使用する。
---

# 日本語 PDF エクスポート

## 手順

### 1. HTML のフォント指定を確認する

対象 HTML の `font-family` に IPA フォントが含まれているかを確認する。
含まれていない場合は、**変換前に必ず修正する**。

```css
body {
  font-family:
    "Hiragino Kaku Gothic ProN", "Hiragino Sans",
    "Yu Gothic", YuGothic, Meiryo,
    "IPAPGothic", "IPAGothic", sans-serif;
}
```

理由: Linux 環境では、日本語フォントを明示しないと CJK 共通フォントから
**中国語書体が選択される**。Mac の開発機では正常に見えるため、
気づかずに社外へ配布する事故につながる。

### 2. 印刷用 CSS を確認する

以下が含まれていない場合は追加する。

```css
@page { size: A4; margin: 15mm; }
table { page-break-inside: avoid; }
h1, h2, h3 { page-break-after: avoid; }
.page-break { page-break-before: always; }
```

### 3. 変換を実行する

```bash
python3 -c "
from weasyprint import HTML
HTML(filename='docs/<name>.html').write_pdf('docs/<name>.pdf')
"
```

### 4. 生成後の検証（省略禁止）

以下を必ず報告する。

1. 生成された PDF のページ数とファイルサイズ
2. **「フォント指定に IPA フォントが含まれていることを確認済み」** の明示
3. ユーザーへの依頼:
   「PDF を開いて、**漢字の字形が日本語書体になっているか**を目視確認してください。
   特に『直』『経』『値』『骨』の字形を確認すると判別しやすいです」

### 5. 中文化していた場合の対処

システムに日本語フォントが入っていない可能性がある。

```bash
# Debian / Ubuntu
sudo apt-get install -y fonts-ipafont fonts-ipaexfont
fc-list | grep -i ipa   # 導入確認
```

## やってはいけないこと

- フォント指定を確認せずに変換すること
- 「PDF を生成しました」だけを報告して、目視確認の依頼を省略すること
