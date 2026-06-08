# Inquira インストール手順 — A株式会社 IT 部門向け

> 想定読者: A社サーバー管理者・IT 部門ご担当者様
> 所要時間: **30 分〜1 時間** (Python 未導入時は +10 分)
> 対象 OS: Windows Server 2019 / 2022 (Linux 用手順は末尾に併記)

---

## 全体像

```
   社員のPC                       A社 Windows サーバー
   ┌──────────────┐              ┌─────────────────────────────────┐
   │ ブラウザ      │              │  ┌────────────┐                  │
   │              │   HTTPS      │  │ IIS         │ ローカル転送      │
   │ faq.a-corp.jp├─────────────►│  │ (リバプロ)   ├──► localhost:8000│
   │              │              │  └────────────┘    │             │
   └──────────────┘              │                    ▼             │
                                 │              ┌─────────────┐     │
                                 │              │ Inquira     │     │
                                 │              │ (Python)    │     │
                                 │              └─────────────┘     │
                                 │   起動: Windows タスクスケジューラ │
                                 └─────────────────────────────────┘
```

このパッケージで構築するのは右側（A社サーバー内）。
左側のブラウザから到達できるようにするため、IIS のリバースプロキシ設定も最後に行います。

---

## 事前準備（A社IT部門にお願いする項目）

| # | 項目 | 確認方法 |
|---|---|---|
| 1 | Python 3.11 以上がインストール済み | PowerShell で `py -3.11 --version` |
| 2 | 管理者権限の PowerShell が使える | スタートメニュー → PowerShell を右クリック →「管理者として実行」 |
| 3 | IIS がインストール済み | サーバーマネージャーで「Web サーバー (IIS)」役割を確認 |
| 4 | IIS の「URL Rewrite」モジュール | https://www.iis.net/downloads/microsoft/url-rewrite |
| 5 | IIS の「ARR (Application Request Routing)」モジュール | https://www.iis.net/downloads/microsoft/application-request-routing |
| 6 | サーバーの SSL 証明書 (`faq.a-corp.jp` 用) | 既存社内 CA でも Let's Encrypt でも可 |
| 7 | DNS で `faq.a-corp.jp` → サーバー IP に向ける | 社内 DNS の管理画面 |

> ⚠ 4 と 5 が未インストールでも Inquira 自体は起動できますが、社員からアクセスできるのは IIS 経由になるので、Step 5 までに入れておいてください。

> Python 3.11 が無い場合: https://www.python.org/downloads/ から
> Python 3.11 をダウンロード → インストーラで **`Add python.exe to PATH` に必ずチェック** → 完了後 PowerShell を起動し直して `py -3.11 --version` で確認。

---

## Step 1. ZIP を受け取って解凍 (5 分)

弊社 (Inquira 提供側) から ZIP ファイルを受領 → サーバーの任意の場所に解凍。

```
C:\Temp\inquira-a_company\
    ├ app\
    ├ scripts\
    ├ pyproject.toml
    └ tenants\
       └ a_company\
          ├ install.ps1
          ├ start_inquira.bat
          ├ inquira.service
          ├ .env             ← 弊社が実値を埋めた状態でお渡し済
          └ README.md         ← このファイル
```

`.env` には Anthropic API キー等の機密情報が含まれます。**配布後はこの ZIP の取り扱いに注意してください**（USB から削除、暗号化保管、等）。

---

## Step 2. インストールスクリプト実行 (5 分)

**PowerShell を「管理者として実行」** で起動して、以下を実行：

```powershell
cd C:\Temp\inquira-a_company\tenants\a_company
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

スクリプトが自動でやること：

| Step | 内容 |
|------|------|
| 1/6 | Python 3.11+ を検出 |
| 2/6 | `C:\Inquira\` にソースをコピー |
| 3/6 | Python venv 作成 + 依存パッケージインストール（数分） |
| 4/6 | `.env` を `C:\Inquira\.env` に配置（SESSION_SECRET をランダム生成） |
| 5/6 | Windows タスクスケジューラに `Inquira` タスクを登録（サーバー起動時に自動起動） |
| 6/6 | http://127.0.0.1:8000/healthz でヘルスチェック |

最後に `✅ Inquira 起動完了` と出れば成功です。

---

## Step 3. ローカル動作確認 (2 分)

サーバー上で同じ PowerShell から：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/healthz
```

`StatusCode: 200` で本文が `{"ok": true}` なら、Inquira 本体は正常に動いています。

ブラウザがあれば `http://127.0.0.1:8000/` を開いて、Google ログイン画面が出ることも確認できます。

---

## Step 4. SSL 証明書を IIS にインストール (10 分)

> ⚠ A社で標準的に使っている SSL 配布方法がある場合はそちらに従ってください。
> 以下は一般的な手順です。

1. IIS マネージャー → サーバー名選択 → 中央ペインの「サーバー証明書」をダブルクリック
2. 右側の「証明書の要求の作成」もしくは「インポート」で `faq.a-corp.jp` 用証明書を登録
3. IIS マネージャー → 左ペインの「サイト」 → 既定の Web サイト or 新規 Web サイトに対し、右側「バインド」 →「追加」 → 種類: `https`, ホスト名: `faq.a-corp.jp`, 証明書: 上で登録したもの

---

## Step 5. IIS のリバースプロキシ設定 (10 分) ← ここが Step 5

「社員のブラウザからの `https://faq.a-corp.jp/` を、サーバー内部の `http://localhost:8000/` に転送する」 設定です。

### 5-1. IIS で新しいサイトを作る

1. IIS マネージャー → 左ペイン「サイト」を右クリック → **「Web サイトの追加」**
2. 以下を入力：
   - サイト名: `Inquira`
   - 物理パス: `C:\Inquira\iis_site` (空でOK。下記で `web.config` を置く)
   - バインド: 種類 `https`, ホスト名 `faq.a-corp.jp`, ポート `443`, SSL 証明書: Step 4 のもの
3. 「OK」

### 5-2. リバプロ設定ファイルを置く

`C:\Inquira\iis_site` フォルダを作成し、その中に **`web.config`** を作成して以下を貼り付け：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="ReverseProxyToInquira" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:8000/{R:1}" />
          <serverVariables>
            <set name="HTTP_X_FORWARDED_PROTO" value="https" />
            <set name="HTTP_X_FORWARDED_HOST" value="{HTTP_HOST}" />
          </serverVariables>
        </rule>
      </rules>
    </rewrite>
    <!-- 大きめアップロード許可 (社内マニュアル PDF 等) -->
    <security>
      <requestFiltering>
        <requestLimits maxAllowedContentLength="1073741824" />
      </requestFiltering>
    </security>
  </system.webServer>
</configuration>
```

### 5-3. ARR のプロキシ機能を ON にする

1. IIS マネージャー → 一番上のサーバー名（A社サーバー名）を選択
2. 中央ペインの **「Application Request Routing キャッシュ」** をダブルクリック
3. 右側の **「Server Proxy Settings...」** をクリック
4. **「Enable proxy」** にチェックを入れて「Apply」

### 5-4. 反映

IIS マネージャーで `Inquira` サイトを右クリック → 「再起動」、もしくは PowerShell で：

```powershell
iisreset
```

---

## Step 6. 外部から動作確認 (5 分)

社員の PC（または別端末）のブラウザで開く：

```
https://faq.a-corp.jp/
```

- Google ログイン画面が表示される
- 弊社からお伝えした **管理者 Gmail のいずれか** でログインできる

これで完了です 🎉

ログインした管理者は `https://faq.a-corp.jp/admin/upload` を開いて、マニュアル・規程・FAQ などの資料をドラッグ&ドロップで投入できます。

---

## 困ったとき (よくあるトラブル)

### Python 3.11 が無いと言われる

PowerShell を再起動して `py -3.11 --version` を確認。出ない場合は https://www.python.org/downloads/ から再インストール（**`Add to PATH` チェック必須**）。

### `install.ps1` が「実行できません」とエラー

PowerShell を **「管理者として実行」** で起動し直す。それでも出る場合は：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

を `install.ps1` の前に実行。

### `http://127.0.0.1:8000/healthz` が応答しない

サーバー上で `C:\Inquira\start_inquira.bat` を**直接ダブルクリック**して、コンソールにエラーが出ていないか確認。よくある原因：
- `.env` の Anthropic API キーが壊れている
- ポート 8000 が他のアプリで使用中

### IIS でアクセスすると「502 Bad Gateway」

- ARR の `Enable proxy` がオフ → Step 5-3 を再確認
- Inquira 本体が止まっている → タスクスケジューラで `Inquira` タスクを「実行」
- Windows Firewall が `localhost:8000` を遮断 → 普通は localhost 同士なので関係ないですが、念のため確認

### IIS でアクセスすると「Google ログインで認可エラー」

`https://faq.a-corp.jp/auth/callback` がリダイレクト URI として Google Cloud Console 側に登録されていない可能性。弊社にご連絡ください（こちらで OAuth 設定を追加します）。

---

## 運用コマンド (Windows)

```powershell
# 状態確認
Get-ScheduledTask -TaskName Inquira
Invoke-WebRequest http://127.0.0.1:8000/healthz

# 再起動
Stop-ScheduledTask -TaskName Inquira
Start-ScheduledTask -TaskName Inquira

# 手動起動 (デバッグ時)
C:\Inquira\start_inquira.bat

# IIS 再起動
iisreset
```

---

## バックアップ対象

A社の通常バックアップに以下を追加してください：

- `C:\Inquira\data\` 配下まるごと（ナレッジ・監査ログ・FAQ 候補・フィードバック）
- `C:\Inquira\.env`（再構築用、ただし機密なので暗号化保管）

---

## サポート窓口

不明点・トラブル時は弊社サポート（個別 Slack / メールでご案内済み）までご連絡ください。

---

## (参考) Linux サーバーの場合

Ubuntu / Debian / RHEL / Rocky / AlmaLinux の場合は `install.ps1` ではなく `install.sh` を使います：

```bash
sudo ./install.sh
# → /opt/inquira/ に配置、systemd で自動起動、journalctl -u inquira -f でログ確認
```

リバースプロキシは nginx 設定例：

```nginx
server {
    listen 443 ssl http2;
    server_name faq.a-corp.jp;
    ssl_certificate     /etc/ssl/certs/faq.a-corp.jp.crt;
    ssl_certificate_key /etc/ssl/private/faq.a-corp.jp.key;
    client_max_body_size 1024M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
