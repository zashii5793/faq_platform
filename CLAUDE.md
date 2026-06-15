# CLAUDE.md

このリポジトリで Claude Code が作業する際の遵守事項。

## ドキュメント / HTML / PDF 全般

### 日本語フォント (中華フォントへのフォールバック防止)

PDF 化される HTML や、社員・顧客に渡す HTML には、必ず以下の font-family を使用すること。weasyprint で生成する PDF が中国語フォントにフォールバックする事故を防ぐため、IPA フォントを明示的に末尾に含める。

```css
font-family:
  "Hiragino Kaku Gothic ProN",
  "Hiragino Sans",
  "Yu Gothic",
  YuGothic,
  Meiryo,
  "IPAPGothic",
  "IPAGothic",
  sans-serif;
```

- Mac → Hiragino 系が優先される
- Windows → Yu Gothic / Meiryo が優先される
- Linux (weasyprint) → IPAPGothic / IPAGothic が使用される (これを書かないと weasyprint が CJK フォントから中国語フォントを選ぶ事故が起きる)

### 顧客固有情報の取扱

- 顧客名、社内ドメイン、社内 IP、UNC パス、SSL 証明書 Thumbprint 等は **絶対にコミットしない**
- 例示する場合は `<CUSTOMER_DOMAIN>`, `example.local`, `10.0.0.x`, `\\fileserver\share\inquira` のような一般的な値を使用
- 実値は `.private/` 配下で管理 (.gitignore 済み)
- コミット前に下記のチェックを実行することを推奨:
  ```bash
  git diff --cached | grep -iE 'svn-corp|file2025|192\.168\.|@gmail\.com|sk-ant-|GOCSPX-'
  ```

### 「情シス」「弊社」「A 社」等の表現

- 「不明点は社内情シスへ」のような **押しつけがましい表現は使わない** (顧客側の組織構造を勝手に決めつけることになる)
- 「弊社」「A 社」のような **特定の組織を指す表現は使わない** (汎用テンプレートとして使えなくなる)
- 推奨表現: 「サービス提供元」「Inquira を導入された管理者の方」「サービスご利用元」

### PDF 生成

新たに PDF を作る、または更新する場合:

```bash
python3 -c "
from weasyprint import HTML
HTML(filename='docs/<name>.html').write_pdf('docs/<name>.pdf')
"
```

生成後、必ず以下を確認:
1. PDF を開いて中文化していないか目視 (Linux で生成した場合は特に)
2. レイアウトが意図通りに収まっているか

## コミット / リリース

### バージョニング

`pyproject.toml` と `app/__init__.py` の `__version__` を同期させる。Semantic Versioning (`MAJOR.MINOR.PATCH`) を遵守。

### CHANGELOG

機能追加・修正は `CHANGELOG.md` の `[Unreleased]` セクションに記録。リリース時に日付付きセクションに昇格させる。

### 命名

- ブランチ: `feature/<name>`, `fix/<name>`, `hotfix/<name>`
- タグ: `v0.9.0` (vプレフィックス付き)
