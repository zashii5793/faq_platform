# Inquira リリース運用ガイド

> 提供側がバージョンを切って、顧客が `update_inquira.ps1` で取りに行けるようにするまでの手順。

---

## バージョニング規約 (SemVer)

`MAJOR.MINOR.PATCH` 形式 (例: `1.2.3`)

| 数字 | 上げる条件 | 例 |
|---|---|---|
| **MAJOR** | 後方互換を破壊する変更 | `.env` の必須項目追加、API エンドポイントの URL 変更、データ JSON のスキーマ非互換変更 |
| **MINOR** | 後方互換を保ったまま機能追加 | 新タブ追加、新 API、新設定 (既定値ありの) 追加 |
| **PATCH** | バグ修正のみ、機能追加なし | 文字化け修正、誤動作の修正、UI 表記修正 |

### 0.x 期間中の例外運用

現状 `0.8.0`。1.0 リリース前は **MINOR を「機能追加」、PATCH を「修正全般」** として運用する。
1.0 以降は厳密 SemVer に切り替え。

---

## リリースフロー

### 1. 開発ブランチで開発

```bash
git checkout -b feature/xxx
# コードを書く
git commit -m "..."
git push -u origin feature/xxx
```

### 2. PR レビュー → main にマージ

```bash
git checkout main
git pull origin main
```

### 3. バージョン番号を上げる

2 か所を同時に更新:

```toml
# pyproject.toml
version = "0.9.0"
```

```python
# app/__init__.py
__version__ = "0.9.0"
```

> 既存の `pyproject.toml` のコメントに「app/__init__.py の __version__ と同期させること」と書いてある。

### 4. CHANGELOG.md にエントリ追加

`Keep a Changelog` 形式:

```markdown
## [0.9.0] - 2026-06-20

### Added — XXX 機能
- 説明...

### Changed
- 説明...

### Fixed
- 説明...

### Breaking
- ⚠ 説明... (MAJOR 上げ時のみ)

### Migration (Breaking がある場合)
- `.env` に `NEW_KEY=...` を追加してください
- `python scripts/migrate_X.py` を実行してください

---
```

### 5. 全テスト通す

```bash
pytest -q
```

全グリーンが必須。1 つでも fail があればリリース不可。

### 6. コミットしてタグを切る

```bash
git add pyproject.toml app/__init__.py CHANGELOG.md
git commit -m "Release v0.9.0"
git tag -a v0.9.0 -m "Release v0.9.0"
git push origin main --tags
```

### 7. リリースノートを GitHub Releases に投稿 (任意)

GitHub の Releases から `v0.9.0` タグに対して Release を作成し、CHANGELOG.md の該当セクションをコピペ。

---

## 顧客への通知テンプレート

```
Subject: [Inquira] バージョン v0.9.0 をリリースしました

A社 IT 部門ご担当者様

Inquira の新バージョン v0.9.0 をリリースしましたのでお知らせします。

更新方法 (約 3 分):
  1. 管理者 PowerShell で:
       cd "$env:USERPROFILE\Inquira\scripts"
       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
       .\update_inquira.ps1 -Version v0.9.0

  2. 自動でバックアップ → 入れ替え → ヘルスチェックが走ります
  3. 失敗時は自動ロールバックされ、旧バージョンに戻ります

このリリースで何が変わったか:
  ・(CHANGELOG の Added/Changed/Fixed 箇所をコピペ)

メンテナンス時間:
  ・約 30 秒〜2 分間、社員からアクセスできない時間が発生します
  ・夜間の実施を推奨

ご不明点は提供側までご連絡ください。
```

---

## Breaking change を含む場合の特別対応

MAJOR を上げるリリース (例: `0.8.0 → 1.0.0`) では:

1. **事前にユーザー通知** (`.env` 変更が必要等) を 2 週間前から告知
2. **マイグレーションスクリプト** を `scripts/migrate_X_to_Y.py` として用意
3. **CHANGELOG に `### Migration` セクション** を必ず記述
4. **顧客サーバーで先に DryRun** を実行してもらう:
   ```powershell
   .\update_inquira.ps1 -Version v1.0.0 -DryRun
   ```
5. リリース後 24h は監視を厚めに

---

## ホットフィックスの流れ (本番障害時)

1. 障害確認 → `main` から `hotfix/X` ブランチを切る
2. 最小修正のみコミット (機能追加禁止)
3. PATCH バージョンを上げる (`0.9.0 → 0.9.1`)
4. CHANGELOG に `### Fixed` で記載
5. main にマージ → タグ → push
6. 顧客に即時通知:
   ```
   .\update_inquira.ps1 -Version v0.9.1
   ```

---

## ロールバック方針 (リリース後に問題発覚)

### Step 1: 影響範囲を確認

- 監査ログ (`<UNC_SHARE>\audit\`) で異常クエリの数を確認
- 顧客の管理者に状況ヒアリング

### Step 2: 顧客側でロールバック

```powershell
.\update_inquira.ps1 -Version v0.8.0  # 一つ前のタグを指定
```

(`update_inquira.ps1` は「同バージョンならスキップ」ロジックがあるが、明示指定すれば上書きできる)

### Step 3: GitHub 側のタグを差し戻し

問題のあるタグを **削除しない** (履歴は残す)。代わりに:

- `v0.9.0-broken` の注釈をリリースノートに追記
- 修正版 `v0.9.1` を即座にリリース

---

## チェックリスト (リリース前)

リリース直前に以下を全てチェック:

- [ ] `pyproject.toml` の version を更新したか
- [ ] `app/__init__.py` の `__version__` を更新したか
- [ ] `CHANGELOG.md` にエントリを追加したか
- [ ] `pytest -q` でテストが全部通るか
- [ ] Breaking change がある場合、`### Migration` を書いたか
- [ ] 顧客向け通知テンプレートを用意したか
- [ ] タグを `v` 付きで切ったか (`v0.9.0` であって `0.9.0` ではない)
- [ ] `git push origin main --tags` でタグも push したか
- [ ] (任意) GitHub Releases に投稿したか

---

## 関連ドキュメント

- [`CHANGELOG.md`](../CHANGELOG.md)
- [`scripts/update_inquira_README.md`](../scripts/update_inquira_README.md) — 顧客側の更新手順
- [`docs/deployment_lessons_learned.md`](deployment_lessons_learned.md)
