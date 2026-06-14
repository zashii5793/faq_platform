# Inquira アップデート手順

`scripts/update_inquira.ps1` を使うと、稼働中の Inquira を **1 コマンドで新しいバージョンに更新** できます。
失敗時は自動的に旧コードへロールバックします。

---

## 何をやるか / 何をやらないか

| | 操作 |
|---|---|
| ✅ 更新する | `app/` `scripts/` `pyproject.toml` `README.md` `ROADMAP.md` `CHANGELOG.md` `LICENSE` |
| 🚫 触らない | `.env` (認証情報) / `.venv` (Python 環境は再インストールするが入れ替えはしない) / データ保存先 (UNC 共有) |
| 💾 バックアップ先 | `%USERPROFILE%\Inquira_backups\<timestamp>-v<旧バージョン>\` |
| 📝 ログ | `%USERPROFILE%\Inquira_Update.log` |

---

## 使い方

### 1. 最新版 (main ブランチの tip) に更新

```powershell
cd "$env:USERPROFILE\Inquira\scripts"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\update_inquira.ps1
```

所要時間: 2〜3 分。途中で社員が `/healthz` を叩いてる場合、一瞬 502 が出ます。

### 2. 特定のタグに固定

```powershell
.\update_inquira.ps1 -Version v1.2.3
```

リリースタグ運用をしているなら、本番では必ずタグ指定がおすすめです。

### 3. ダウンロードして検証だけ (本体には触らない)

```powershell
.\update_inquira.ps1 -DryRun
```

実環境に影響を与えず、ZIP の取得と展開・新バージョン番号の表示まで行います。
リリース前の動作確認に便利。

### 4. インストール先を変えている場合

```powershell
.\update_inquira.ps1 -AppDir "D:\Inquira"
```

---

## 自動ロールバック

以下のどちらかが発生すると、自動的に旧コードに戻して再起動します:

1. `pip install -e .` が失敗 (依存解決エラー / 新しい requirement の解決失敗 等)
2. 起動後 30 秒以内に `/healthz` が 200 を返さない

調査のためロールバックさせたくない場合は:

```powershell
.\update_inquira.ps1 -NoRollback
```

→ 失敗してもそのまま停止状態にします。`%USERPROFILE%\Inquira_Update.log` を読んで手動対処。

---

## 手動ロールバック

何らかの理由で自動ロールバックが効かなかった場合:

```powershell
# 最新のバックアップを探す
$latest = Get-ChildItem "$env:USERPROFILE\Inquira_backups" -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$AppDir = "$env:USERPROFILE\Inquira"

# 停止
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# 旧コードに戻す
Copy-Item "$($latest.FullName)\*" $AppDir -Recurse -Force

# 依存も戻す
& "$AppDir\.venv\Scripts\python.exe" -m pip install --quiet -e $AppDir

# 起動
& "$AppDir\start_inquira.bat"

# 確認
Invoke-WebRequest http://127.0.0.1:8000/healthz -UseBasicParsing
```

---

## バックアップの自動削除

何度もアップデートするとバックアップが溜まります。古いものを定期削除:

```powershell
# 30 日より古いバックアップを削除
Get-ChildItem "$env:USERPROFILE\Inquira_backups" -Directory |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Recurse -Force
```

タスクスケジューラに月次で登録しておくのが楽。

---

## トラブルシューティング

### `-Version` 指定でダウンロード失敗

- ブランチ名 / タグ名のスペルミス
- ブランチ名にスラッシュが含まれる場合 (例: `feature/foo`) はそのまま指定
- リポジトリが Private で資格情報が必要な場合は `Personal Access Token` 経由の URL に変更必要

### `pip install` で失敗 (ロールバック発動)

- 新バージョンが新しい Python パッケージに依存
- ネットワーク経由で PyPI に到達できない (社内プロキシ)
- ログ: `%USERPROFILE%\Inquira_Update.log` の `[ERR]` 行を確認

### ヘルスチェック失敗 (ロールバック発動)

- `.env` のフォーマットが新バージョンと非互換
- 設定値追加が必要 → リリースノート (`CHANGELOG.md`) を確認
- 起動時例外: `start_inquira.bat` を**フォアグラウンドで手動起動**して例外を確認

### ロールバック後も起動しない

旧 venv が新バージョンの依存で汚染された可能性。venv 再作成:

```powershell
Remove-Item "$env:USERPROFILE\Inquira\.venv" -Recurse -Force
py -3.11 -m venv "$env:USERPROFILE\Inquira\.venv"
& "$env:USERPROFILE\Inquira\.venv\Scripts\python.exe" -m pip install -e "$env:USERPROFILE\Inquira"
& "$env:USERPROFILE\Inquira\start_inquira.bat"
```

---

## 関連ドキュメント

- [`docs/release_guide.md`](../docs/release_guide.md) — 提供側のリリース手順 (タグ作成 / CHANGELOG 更新)
- [`CHANGELOG.md`](../CHANGELOG.md) — リリースノート
- [`tenants/<slug>/README.md`](../tenants/) — 各テナントの導入手順
