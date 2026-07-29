#!/usr/bin/env node
/**
 * ブロック JSON (md_to_blocks.py の出力) から .docx を生成する。
 *
 * 目的:
 *   note のエディタは HTML 貼り付けで書式が落ちることがあるが、
 *   Word / Pages / Google ドキュメントからの貼り付けは安定して書式を保持する。
 *   そのため「実際の見出しスタイル」を持つ .docx を作る。
 *
 * 使い方:
 *   python3 md_to_blocks.py 記事.md blocks.json
 *   node to_note_docx.js blocks.json 出力.docx
 *
 * 注意:
 *   - 見出しは組み込みの HeadingLevel を使う（note 側が見出しとして解釈できる）
 *   - 箇条書きは numbering 設定を使う（「・」を直接書かない）
 *   - 日本語フォントは CJK フォールバック事故を防ぐため明示する
 */
const fs = require('fs');
const path = require('path');

const docxPath = ['docx', path.join(__dirname, 'node_modules', 'docx')]
  .map((p) => { try { return require.resolve(p); } catch { return null; } })
  .find(Boolean);
if (!docxPath) {
  console.error('docx モジュールが見つかりません。`npm install docx` を実行してください。');
  process.exit(1);
}
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel,
  AlignmentType, BorderStyle, LevelFormat, convertInchesToTwip,
} = require(docxPath);

const JP_FONT = 'Yu Gothic';
const MONO_FONT = 'Consolas';

const HEADING = {
  1: HeadingLevel.HEADING_1,
  2: HeadingLevel.HEADING_1, // note の大見出しに対応させる
  3: HeadingLevel.HEADING_2,
  4: HeadingLevel.HEADING_3,
};

/** run 配列 → TextRun 配列 */
function toRuns(runs, opts = {}) {
  return (runs || []).map((r) =>
    new TextRun({
      text: r.text,
      bold: !!r.b || !!opts.bold,
      font: r.c ? MONO_FONT : JP_FONT,
      size: opts.size,
      color: opts.color,
    })
  );
}

function build(blocks) {
  const out = [];
  for (const b of blocks) {
    switch (b.t) {
      case 'h':
        out.push(new Paragraph({
          heading: HEADING[b.level] || HeadingLevel.HEADING_3,
          spacing: { before: 320, after: 160 },
          children: toRuns(b.runs, { bold: true }),
        }));
        break;

      case 'p':
        out.push(new Paragraph({
          spacing: { after: 140, line: 320 },
          children: toRuns(b.runs),
        }));
        break;

      case 'li':
        out.push(new Paragraph({
          numbering: {
            reference: b.ordered ? 'num-list' : 'bullet-list',
            level: Math.max(0, (b.level || 1) - 1),
          },
          spacing: { after: 60, line: 300 },
          children: toRuns(b.runs),
        }));
        break;

      case 'quote':
        out.push(new Paragraph({
          indent: { left: convertInchesToTwip(0.3) },
          border: {
            left: { style: BorderStyle.SINGLE, size: 12, space: 12, color: 'BBBBBB' },
          },
          spacing: { before: 140, after: 140, line: 320 },
          children: toRuns(b.runs),
        }));
        break;

      case 'code':
        // 行ごとに段落を作る（\n は使えない）
        (b.text.split('\n')).forEach((line, idx, arr) => {
          out.push(new Paragraph({
            shading: { fill: 'F2F2F2' },
            spacing: {
              before: idx === 0 ? 140 : 0,
              after: idx === arr.length - 1 ? 140 : 0,
              line: 260,
            },
            children: [new TextRun({ text: line || ' ', font: MONO_FONT, size: 18 })],
          }));
        });
        break;

      case 'hr':
        out.push(new Paragraph({
          border: {
            bottom: { style: BorderStyle.SINGLE, size: 6, space: 1, color: 'CCCCCC' },
          },
          spacing: { before: 200, after: 200 },
          children: [],
        }));
        break;

      default:
        break;
    }
  }
  return out;
}

function main() {
  const [src, dst] = process.argv.slice(2);
  const doc = JSON.parse(fs.readFileSync(src, 'utf8'));

  const bulletLevels = [0, 1, 2].map((i) => ({
    level: i,
    format: LevelFormat.BULLET,
    text: ['●', '○', '▪'][i],
    alignment: AlignmentType.LEFT,
    style: {
      paragraph: {
        indent: {
          left: convertInchesToTwip(0.3 + i * 0.25),
          hanging: convertInchesToTwip(0.22),
        },
      },
    },
  }));
  const numberLevels = [0, 1, 2].map((i) => ({
    level: i,
    format: LevelFormat.DECIMAL,
    text: `%${i + 1}.`,
    alignment: AlignmentType.LEFT,
    style: {
      paragraph: {
        indent: {
          left: convertInchesToTwip(0.3 + i * 0.25),
          hanging: convertInchesToTwip(0.25),
        },
      },
    },
  }));

  const document = new Document({
    title: doc.title,
    styles: {
      default: {
        document: { run: { font: JP_FONT, size: 21 } },
      },
    },
    numbering: {
      config: [
        { reference: 'bullet-list', levels: bulletLevels },
        { reference: 'num-list', levels: numberLevels },
      ],
    },
    sections: [{ children: build(doc.blocks) }],
  });

  Packer.toBuffer(document).then((buf) => {
    fs.writeFileSync(dst, buf);
    console.log(`wrote ${dst} (${doc.blocks.length} blocks, ${buf.length} bytes)`);
  });
}

main();
