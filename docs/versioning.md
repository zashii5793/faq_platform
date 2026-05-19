# バージョニング方針

Inquira は [Semantic Versioning 2.0.0](https://semver.org/lang/ja/) に厳密に従う。

---

## 📐 ナンバリング規則

```
MAJOR . MINOR . PATCH
  ↑       ↑       ↑
  │       │       └─ バグ修正のみ（後方互換あり）
  │       └───────── 機能追加（後方互換あり）
  └───────────────── 後方互換を破壊する変更
```

### バージョンを上げるタイミング

| 種類 | 例 | バンプ |
|---|---|---|
| 致命的なセキュリティ修正 | XSS / 認証バイパス修正 | **PATCH** |
| 通常のバグ修正 | UI のレイアウト崩れ修正 | **PATCH** |
| 文言・色・余白の微調整 | フォント拡大、テキスト修正 | **PATCH** |
| 新機能追加 (API互換) | 回答協力機能、新エンドポイント | **MINOR** |
| ドキュメント整備 | CHANGELOG、ガイド追加 | **MINOR** か **PATCH** |
| API レスポンス構造変更 | `Source` モデルにフィールド追加 | **MINOR**（追加のみ） / **MAJOR**（削除・改名） |
| データ保存形式の変更 | JSON → SQLite | **MAJOR** |
| 環境変数の名前変更 | `FAQ_DIR` → `FAQ_MASTER_DIR` | **MAJOR** |

---

## 🔢 現在のバージョン

`app/__init__.py` の `__version__` が **正のバージョン**（Source of Truth）。

```python
# app/__init__.py
__version__ = "0.6.0"
```

`pyproject.toml` の `version` フィールドも同じ値に保つ。
`tests/test_smoke.py::test_version_matches_pyproject` が CI で同期を強制する。

---

## 🚀 リリースフロー

新しいバージョンを切るとき:

1. **CHANGELOG.md** の `[Unreleased]` セクションを `[X.Y.Z] - YYYY-MM-DD` に変える
2. **`app/__init__.py`** の `__version__` を更新
3. **`pyproject.toml`** の `version` を同じ値に
4. テスト実行: `.venv/bin/python -m pytest -q`
5. コミット: `chore(release): vX.Y.Z`
6. Git タグ: `git tag -a vX.Y.Z -m "Release X.Y.Z"`
7. プッシュ: `git push origin <branch> --tags`

---

## 🎯 マイルストーン

| バージョン | 内容 | ETA |
|---|---|---|
| **0.6.x** | UI/UX 改善、回答協力機能、バージョン管理整備 ✅現在 | — |
| 0.7.x | 検索精度改善（Embedding デフォルト化）、複数ファイル横断検索強化 | 1-2 ヶ月 |
| 0.8.x | Slack/Teams 通知連携、月次レポート自動配信 | 2-3 ヶ月 |
| 0.9.x | チャット履歴の永続化、複数会話セッション | 3-4 ヶ月 |
| **1.0.0** | マルチテナント対応、SQLite 化、Stripe 課金 (ROADMAP Phase 2) | 4-6 ヶ月 |

---

## 📝 旧バージョンとの互換性

破壊的変更（**MAJOR** バンプ）の際は:
1. CHANGELOG に **Breaking Changes** セクションを目立たせる
2. 移行ガイド (`docs/migrations/X.Y.Z-to-A.B.C.md`) を用意
3. 旧版 API も 1 マイナーリリース分は残し、Deprecation 警告を出す

`0.x.y` 系の現在はマイナーアップグレードでも軽微な変更がある可能性あり。
**`1.0.0` 以降は厳密にセマンティックに従う**。

---

## 🔗 関連

- [Semantic Versioning 2.0.0](https://semver.org/lang/ja/)
- [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)
- [`CHANGELOG.md`](../CHANGELOG.md)
- [`ROADMAP.md`](../ROADMAP.md)
