# Inquira 許可ユーザー追加 手順書

`scripts/add_allowed_emails.ps1` を使うと、Inquira の `.env` の `ALLOWED_EMAILS` に新規ユーザーを安全に追加できます。重複自動除外、バックアップ、ロールバック対応。

> ⚠ **本手順書は汎用テンプレートです。** 実際の Gmail アドレスはリポジトリにコミットせず、サーバー上または `.private/` 配下で管理してください。

---

## 全体の流れ (2 か所 + 1 再起動)

| ステップ | 場所 | 所要時間 |
|---|---|---|
| 1. Google Cloud Console にテストユーザー追加 | サービス提供元の Web ブラウザ | 5 分 |
| 2. Inquira サーバー上で `.env` 更新 (本スクリプト) | Inquira サーバー | 1 分 |
| 3. Inquira 再起動 | Inquira サーバー | 1 分 |

⚠ **両方やる必要があります**。Google Cloud Console 側のみ → ログイン画面までは表示されるが「アクセスがブロックされました」エラー。`.env` 側のみ → ログイン後に 401。

---

## Step 1. Google Cloud Console でテストユーザー追加

1. https://console.cloud.google.com/apis/credentials/consent を開く
2. 該当の OAuth プロジェクトを選択
3. ページ下部の **「テスト ユーザー」** までスクロール
4. **「ADD USERS」** ボタン押下
5. 追加したい Gmail を **1 行 1 アドレス** で貼り付け (改行区切り)
6. **「保存」**

> 💡 一度に **複数まとめて貼り付け可能**。1 人ずつ追加する必要はありません。
> 反映には Google 側で 5〜10 分かかることがあります (Step 2/3 と並行で問題なし)。

---

## Step 2. Inquira サーバー上で `.env` を更新

### ダウンロード (初回のみ)

```powershell
mkdir C:\Temp -Force | Out-Null
(New-Object System.Net.WebClient).DownloadFile(
  "https://raw.githubusercontent.com/zashii5793/faq_platform/main/scripts/add_allowed_emails.ps1",
  "C:\Temp\add_allowed_emails.ps1"
)
cd C:\Temp
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 実行パターン

#### パターン A: 1 〜数人を直接指定

```powershell
.\add_allowed_emails.ps1 -Emails "newuser1@example.com,newuser2@example.com" -RestartInquira
```

#### パターン B: 大人数 → テキストファイルから読み込み

サーバー上の任意の場所に `new_users.txt` を作成し、**1 行 1 アドレス**で記載:

```text
user1@example.com
user2@example.com
user3@example.com
# コメント行 (# 始まり) と空行はスキップされます
```

実行:

```powershell
.\add_allowed_emails.ps1 -EmailsFile "C:\Temp\new_users.txt" -RestartInquira
```

#### パターン C: 事前確認のみ (実体は変更しない)

```powershell
.\add_allowed_emails.ps1 -EmailsFile "C:\Temp\new_users.txt" -DryRun
```

→ 既存登録との重複判定結果、追加予定件数を表示するだけで終了。

---

## Step 3. Inquira 再起動 (上記で `-RestartInquira` を付けなかった場合)

```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
& "$env:USERPROFILE\Inquira\start_inquira.bat"

# ヘルスチェック
Invoke-WebRequest http://127.0.0.1:8000/healthz -UseBasicParsing
```

---

## スクリプトが自動でやってくれること

| やること | 詳細 |
|---|---|
| ✅ 重複除外 | 既に登録済みのアドレスはスキップ |
| ✅ 形式検証 | メール形式が不正なら全件中断 (部分実行されない) |
| ✅ バックアップ | `.env.bak.YYYYMMDD-HHMMSS` として現在の `.env` を退避 |
| ✅ UTF-8 BOM なしで保存 | uvicorn が読める形式で書き出し (文字化け防止) |
| ✅ ヘルスチェック | `-RestartInquira` 時、起動後 30 秒以内の `/healthz` 200 を確認 |

---

## ロールバック

何か問題が起きたら、バックアップから戻せます:

```powershell
# 最新のバックアップを探す
$latest = Get-ChildItem "$env:USERPROFILE\Inquira\.env.bak.*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host "戻すバックアップ: $($latest.FullName)"

# 復元
Copy-Item $latest.FullName "$env:USERPROFILE\Inquira\.env" -Force

# 再起動
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
& "$env:USERPROFILE\Inquira\start_inquira.bat"
```

---

## 検証 (追加した本人にやってもらう)

1. ブラウザで Inquira の公開 URL を開く
2. 「Google でログイン」を押下
3. 新規追加した Gmail アカウントを選択
4. 管理画面 / 質問画面が表示されれば成功 ✅

---

## トラブルシュート

| 症状 | 原因 | 対処 |
|---|---|---|
| 「アクセスがブロックされました」 (Google) | Step 1 漏れ or 伝搬待ち | Google Cloud Console 側を再確認 → 5〜10 分待って再試行 |
| ログイン後すぐ追い返される (401) | `.env` の `ALLOWED_EMAILS` 編集失敗 | `notepad "$env:USERPROFILE\Inquira\.env"` で目視確認 |
| ヘルスチェック失敗 | `.env` 破損 or 古い Python プロセス残留 | バックアップから復元 → `Get-Process python \| Stop-Process -Force` → 再起動 |
| 何度再起動しても古い挙動 | 複数 Python プロセスが起動している | `Get-Process python` で確認、全て停止してから起動 |
| `.env` 自体が文字化けで起動しない | UTF-8 BOM 付き / Shift-JIS 化 | `scripts/recover_env.ps1` で対話入力から再生成 |

---

## 大量追加時の運用フロー (10 名以上)

10 名以上を一度に追加する場合の推奨手順:

1. **対象リスト準備**: スプレッドシートで対象 Gmail をリストアップ
2. **テキストファイル化**: 1 列を「メールアドレスのみ」にして、`new_users.txt` として保存
   - 文字コード: UTF-8 (BOM なし)
   - 改行コード: CRLF / LF どちらでも OK
3. **DryRun で確認**: `.\add_allowed_emails.ps1 -EmailsFile ... -DryRun`
4. **Google Cloud Console 側を先に登録** (反映に時間がかかるため)
5. **本番実行**: `.\add_allowed_emails.ps1 -EmailsFile ... -RestartInquira`
6. **代表 1〜2 名でログインテスト**
7. **担当者に告知** (利用 URL + 利用ガイド)

---

## 削除する場合 (退職者対応など)

本スクリプトは追加専用です。削除は手動:

```powershell
notepad "$env:USERPROFILE\Inquira\.env"
```

`ALLOWED_EMAILS=` の行から該当アドレスを削除 (カンマも一緒に) → 保存 → 再起動。

---

## 全社員開放を検討するなら

頻繁な追加が運用負担になるなら、**ドメイン許可方式** への切り替えがおすすめです:

```env
ALLOWED_EMAILS=
ALLOWED_DOMAIN=<CUSTOMER_DOMAIN>
```

→ 指定ドメインの Gmail を持つ全員がアクセス可能になり、個別追加不要に。

ただし以下が必要:
- Google OAuth 同意画面を **本番モードに昇格** (Google 審査あり)
- ALLOWED_DOMAIN に設定したドメインを **Google Workspace で管理している**

切り替えのタイミング / 手順はサービス提供元までご相談ください。

---

## セキュリティ運用ルール

- ⚠ 実値の Gmail アドレスは **本リポジトリにコミットしない**
- 実値を含む `new_users.txt` は `.private/` 配下、または運用端末ローカルのみで管理
- `.env` 自体も Git 管理対象外 (`.gitignore` 済み)
- バックアップファイル (`.env.bak.*`) も同様に管理外
