# Inquira IIS リバースプロキシ 自動セットアップガイド

`setup_iis_reverse_proxy.ps1` の使い方です。

## このスクリプトが何をやるか

A社サーバーで Inquira を `https://inquira.example.local/` で公開できるように、IIS のリバースプロキシを自動セットアップします。

**1コマンドで以下を全部やります**：

1. IIS 役割インストール
2. URL Rewrite モジュール インストール
3. ARR (Application Request Routing) モジュール インストール
4. 自己署名 SSL 証明書 発行 + 信頼登録
5. IIS で「Inquira」サイト作成（HTTP 80 + HTTPS 443）
6. `web.config` 配置（リバプロ設定）
7. ARR の Enable Proxy
8. iisreset
9. 動作確認

すべてのログは `C:\Inquira_IIS_Setup.log` に残ります。

---

## 事前準備（重要）

⚠ Microsoft が `download.microsoft.com` を自動アクセスから 403 でブロックしています。
そのため、URL Rewrite と ARR の MSI は以下のいずれかの方法で用意する必要があります。

### 方法A: winget を使う（推奨）

Windows Server 2022 / Windows 10 1809 以降には winget が標準搭載されています。

PowerShell で以下を打って、`winget` コマンドが認識されれば準備完了：

```powershell
winget --version
```

→ バージョン番号が出れば OK、スクリプトを実行できます。

### 方法B: ブラウザで手動ダウンロード（winget が無い古い環境）

サーバーの IE か Edge で、以下の 2 つの MSI をダウンロード：

1. **URL Rewrite** — https://www.iis.net/downloads/microsoft/url-rewrite
   → 「Install this extension」リンクから最新版の MSI をダウンロード
   → `C:\Temp\rewrite_amd64.msi` に保存

2. **ARR** — https://www.iis.net/downloads/microsoft/application-request-routing
   → 「Install this extension」リンクから最新版の MSI をダウンロード
   → `C:\Temp\requestRouter_amd64.msi` に保存

---

## 実行手順

### Step 1: スクリプトをサーバーにコピー

スクリプトを A社サーバーの任意の場所（例: `C:\Temp\`）に置きます。

GitHub から落とすなら：

```powershell
mkdir C:\Temp -Force | Out-Null
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/zashii5793/faq_platform/claude/add-roadmap-docs-RmQNp/scripts/setup_iis_reverse_proxy.ps1" -OutFile "C:\Temp\setup_iis_reverse_proxy.ps1" -UseBasicParsing
```

### Step 2: 事前チェック（壊さずに準備状況だけ確認）

PowerShell を **「管理者として実行」** で起動して：

```powershell
cd C:\Temp
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup_iis_reverse_proxy.ps1 -CheckOnly
```

→ 「事前条件 OK」が出れば本番実行可能。
→ NG メッセージが出たら、その指示に従って winget を入れるか MSI を配置。

### Step 3: 本番実行

```powershell
.\setup_iis_reverse_proxy.ps1 -Hostname "inquira.example.local"
```

→ ステップごとに進捗が表示されます。
→ 最後に「セットアップ完了」と出れば成功です。

### Step 4: スクリプト完了後のあと 3 ステップ

スクリプト最後に表示される指示通り：

1. **Google Cloud Console** で承認済みリダイレクト URI に
   `https://inquira.example.local/auth/callback` を追加 → 保存 → 5〜10 分待つ

2. **Inquira の `.env`** の `GOOGLE_REDIRECT_URI` を以下に書き換え：
   ```
   GOOGLE_REDIRECT_URI=https://inquira.example.local/auth/callback
   ```

3. **Inquira 再起動**：
   ```powershell
   Get-Process python | Stop-Process -Force
   & "$env:USERPROFILE\Inquira\start_inquira.bat"
   ```

### Step 5: 動作確認

ブラウザで：

```
https://inquira.example.local/
```

→ Google ログイン → 管理者 Gmail でログイン → 動けば成功 🎉

---

## オプション引数

| 引数 | 既定値 | 説明 |
|---|---|---|
| `-Hostname` | `inquira.example.local` | 社員がアクセスする FQDN |
| `-BackendPort` | `8000` | Inquira が動いているポート |
| `-SitePath` | `C:\inetpub\inquira-site` | IIS サイトの物理パス |
| `-LogFile` | `C:\Inquira_IIS_Setup.log` | ログ出力先 |
| `-DownloadDir` | `C:\Temp` | 手動ダウンロード MSI の置き場所 |
| `-CheckOnly` | （無効） | 事前条件チェックのみ実行 |
| `-Cleanup` | （無効） | セットアップを巻き戻す（証明書・サイト・SSL バインドを削除） |

例：
```powershell
# 別のホスト名で実行
.\setup_iis_reverse_proxy.ps1 -Hostname "faq.example.local"

# セットアップを巻き戻す
.\setup_iis_reverse_proxy.ps1 -Cleanup
```

---

## トラブルシューティング

### 「IIS 役割インストールに失敗」と出る

- サーバーの再起動が必要な場合があります。一度サーバーを再起動して再実行。

### winget も MSI も無いと言われる

- 事前準備（方法A or 方法B）を実施してから再実行。
- 方法B でダウンロードした MSI の置き場所は `C:\Temp\` がデフォルト。
  別の場所に置いた場合は `-DownloadDir` 引数で指定。

### 自己署名証明書で警告が出る

- これは想定動作。
- このサーバー自身の Edge では警告が出ません（証明書をルートに登録済み）。
- 社員 PC の Edge / Chrome では警告が出るので、AD のグループポリシーで配布するのが本番運用。
- それまでは社員に「詳細設定 → アクセス」をクリックしてもらえばアクセスできます。

### スクリプト実行中にエラーで止まった

- `C:\Inquira_IIS_Setup.log` の最後の方を見ると、どこで止まったかわかります。
- `-Cleanup` で巻き戻してから、エラー原因を解消して再実行。

### バックエンド (Inquira) が応答しない

- スクリプトの最後の「動作確認」で「Inquira が応答しません」と出た場合：
  ```powershell
  & "$env:USERPROFILE\Inquira\start_inquira.bat"
  ```
  で Inquira を起動してから、ブラウザで `https://inquira.example.local/` を試してください。

---

## このスクリプトの安全性

- 既存の IIS サイト「Inquira」がある場合のみ削除して作り直します（他のサイトには触れません）
- 既存の URL Rewrite / ARR がインストール済みなら再インストールしません
- すべてのログが残るので、何が起きたかは後で追跡可能
- `-Cleanup` で巻き戻し可能（IIS 役割 / モジュール本体は残します。他で使う可能性のため）
