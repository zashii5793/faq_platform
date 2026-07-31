---
name: release-guard
description: リリース前の安全確認とバージョン同期を行う。「リリースして」「バージョンを上げて」「コミットして大丈夫か」と言われたときに使用する。秘密情報スキャン、バージョン同期、CHANGELOG 更新、テスト実行を含む。
---

# リリースガード

リリース前に、以下を **上から順に** 実行する。1 つでも失敗したら中断し、ユーザーに報告する。

## 1. 秘密情報スキャン（最優先・省略禁止）

```bash
git diff --cached | grep -inE 'sk-ant-|GOCSPX-|AIza[0-9A-Za-z_-]{35}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|password\s*=\s*["'"'"'][^"'"'"']{6,}|192\.168\.[0-9]|10\.[0-9]+\.[0-9]+\.[0-9]'
```

**ヒットした場合は、その時点で中断する。** 自己判断でコミットを進めない。
ヒット箇所を提示し、「これはプレースホルダですか、実値ですか」とユーザーに確認する。

追加で確認する:

```bash
git status --porcelain | grep -E '\.env$|\.pem$|\.key$|/\.private/'
```

## 2. バージョン同期

以下 2 箇所が一致しているか確認する。ずれていたら修正する。

- `pyproject.toml` の `version`
- `<package>/__init__.py` の `__version__`

バージョンの上げ方（Semantic Versioning）:

| 変更内容 | 上げる箇所 |
|---|---|
| 後方互換のないインターフェース変更 | MAJOR |
| 後方互換のある機能追加 | MINOR |
| バグ修正のみ | PATCH |

## 3. CHANGELOG

`CHANGELOG.md` の `[Unreleased]` セクションに、今回の変更が記載されているか確認する。
記載がない場合は、git diff から内容を要約して追記する。

リリース時は `[Unreleased]` を `[<version>] - YYYY-MM-DD` に昇格させ、
新しい空の `[Unreleased]` を上に作る。

## 4. テストと静的解析

```bash
ruff check <package> tests
pytest -q
```

**失敗している状態でリリースを進めない。**

## 5. 報告

以下の形式で報告する。

```
✅ 秘密情報スキャン: 検出なし
✅ バージョン同期: pyproject.toml / __init__.py ともに 0.9.0
✅ CHANGELOG: [0.9.0] - 2026-07-28 に昇格済み
✅ テスト: 377 passed
✅ Lint: エラーなし

次のコマンドでリリースできます:
git tag v0.9.0 && git push origin main --tags
```
