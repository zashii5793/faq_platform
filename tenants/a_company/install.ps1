# A株式会社 Windows サーバー向け Inquira インストールスクリプト (非管理者版)
#
# 管理者権限なしで動くように:
#   - インストール先: %USERPROFILE%\Inquira (デフォルト)
#   - 自動起動:       スタートアップフォルダにショートカット配置 (ログオン時に起動)
#   - IIS 設定:       このスクリプトでは行わない (IT 部門への依頼が別途必要)
#
# 前提:
#   - Windows Server 2019 / 2022 もしくは Windows 10/11
#   - Python 3.11+ が PATH に通っていること (py -3.11 が動く)
#   - PowerShell 5.1+ (Windows 標準)
#
# 使い方:
#   PowerShell を起動 (管理者権限不要) し、このフォルダで:
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#       .\install.ps1
#
#   インストール先を変えたい場合:
#       .\install.ps1 -AppDir "D:\Inquira"
#
#   データ保存先をネットワーク共有 (UNC) にしたい場合:
#       .\install.ps1 -DataDir "\\<fileserver>\<share>\<path>"
#
#   両方指定する場合:
#       .\install.ps1 -AppDir "C:\Users\you\Inquira" -DataDir "\\<fileserver>\<share>\<path>"
#
# 事前に同階層の .env ファイルを編集して
#   ANTHROPIC_API_KEY / GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI
# を実値で埋めてください (リポジトリには実値を入れない運用)。

param(
    [string]$AppDir = (Join-Path $env:USERPROFILE "Inquira"),
    # データ保存先。UNC 指定可: -DataDir "\\<fileserver>\<share>\<path>"
    # 空ならローカル ($AppDir\data) を使う
    [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"

# === 0. 事前チェック ===
Write-Host "==> 0/5  事前チェック"

$pythonCmd = $null
foreach ($cand in @("py -3.12", "py -3.11", "py", "python")) {
    try {
        $verOutput = & cmd /c "$cand --version 2>&1"
        if ($verOutput -match "Python 3\.(11|12|13)") {
            $pythonCmd = $cand
            Write-Host "    Python: $verOutput  ($cand)"
            break
        }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Host "[X] Python 3.11+ が見つかりません。" -ForegroundColor Red
    Write-Host "    https://www.python.org/downloads/ から Python 3.11 インストーラを取得してください。"
    Write-Host "    インストール時に [Add python.exe to PATH] にチェックを入れること。"
    exit 1
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $scriptDir ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "[X] $envFile が見つかりません。.env.template をコピーして実値を埋めてください。" -ForegroundColor Red
    exit 1
}
$envContent = Get-Content $envFile -Raw
if ($envContent -match "__FILL_FROM_PROVIDER_SECRETS__") {
    Write-Host "[X] .env に未設定の項目があります (__FILL_FROM_PROVIDER_SECRETS__)。" -ForegroundColor Red
    exit 1
}

# データ保存先を決定 (UNC か ローカルか)
if (-not $DataDir) {
    $DataDir = Join-Path $AppDir "data"
}
$isUnc = $DataDir.StartsWith("\\")

Write-Host "    インストール先: $AppDir"
Write-Host "    データ保存先:   $DataDir $(if ($isUnc) { '(UNC ネットワーク共有)' } else { '(ローカル)' })"

# UNC の場合は事前にアクセス可能か確認 (権限なし or 共有未マウントだとここで失敗)
if ($isUnc) {
    Write-Host "    UNC アクセス確認中..."
    try {
        if (-not (Test-Path $DataDir -ErrorAction Stop)) {
            New-Item -ItemType Directory -Path $DataDir -Force -ErrorAction Stop | Out-Null
        }
        # 書き込み権限確認 (テストファイル作成→削除)
        $testFile = Join-Path $DataDir ".inquira_write_test"
        Set-Content -Path $testFile -Value "ok" -ErrorAction Stop
        Remove-Item $testFile -Force -ErrorAction Stop
        Write-Host "    UNC アクセス OK (読み書き可)" -ForegroundColor Green
    } catch {
        Write-Host "[X] UNC パス $DataDir にアクセスできません:" -ForegroundColor Red
        Write-Host "    $($_.Exception.Message)" -ForegroundColor Red
        Write-Host ""
        Write-Host "    確認事項:"
        Write-Host "    - エクスプローラーで $DataDir を開けるか"
        Write-Host "    - 書き込み権限があるか (共有フォルダの権限設定)"
        Write-Host "    - 接続資格情報がキャッシュ済みか (net use で確認)"
        exit 1
    }
}

# === 1. アプリ配置 ===
Write-Host "==> 1/5  アプリ配置"
$projectDir = (Resolve-Path (Join-Path $scriptDir "..\..")).Path

if (-not (Test-Path $AppDir)) {
    New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
}

$robocopyArgs = @($projectDir, $AppDir, "/E",
    "/XD", ".git", "__pycache__", ".venv", "tenants", "docs", "data",
    "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP")
$null = & robocopy @robocopyArgs
if ($LASTEXITCODE -gt 7) {
    Write-Host "[X] robocopy がエラー終了 (exit=$LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

# データ保存先のディレクトリを確保 (ローカルの場合のみ。UNC は上で作成済み)
if (-not $isUnc -and -not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
}

# === 2. Python venv 作成 + 依存インストール ===
Write-Host "==> 2/5  Python venv 作成 + 依存インストール (数分かかります)"
$venvPath = Join-Path $AppDir ".venv"
if (-not (Test-Path $venvPath)) {
    cmd /c "$pythonCmd -m venv `"$venvPath`""
}
$venvPython = Join-Path $venvPath "Scripts\python.exe"
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e $AppDir

# === 3. .env 配置 (SESSION_SECRET 生成 + パス置換) ===
Write-Host "==> 3/5  .env 配置"
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$sessionSecret = ($bytes | ForEach-Object { "{0:x2}" -f $_ }) -join ""

# パスを Python が扱いやすい forward-slash 形式に変換
# (Windows でも pathlib.Path は forward-slash を受け付ける。UNC も同じ要領で動く)
$appDirForward = $AppDir.Replace("\", "/")
$dataDirForward = $DataDir.Replace("\", "/")

$envContent = $envContent `
    -replace "__GENERATED_BY_INSTALL_SH__", $sessionSecret `
    -replace "__GENERATED_BY_INSTALL_PS1__", $sessionSecret `
    -replace "__APP_DIR__", $appDirForward `
    -replace "__DATA_DIR__", $dataDirForward
Set-Content -Path (Join-Path $AppDir ".env") -Value $envContent -Encoding UTF8 -NoNewline

# === 4. 起動バッチ + スタートアップ ショートカット ===
Write-Host "==> 4/5  起動バッチ作成 + ログオン時自動起動を登録"
$startBat = @"
@echo off
cd /d $AppDir
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
"@
$startBatPath = Join-Path $AppDir "start_inquira.bat"
Set-Content -Path $startBatPath -Value $startBat -Encoding ASCII

# スタートアップフォルダにショートカットを置く (管理者権限不要)
$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Inquira.lnk"
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $startBatPath
$shortcut.WorkingDirectory = $AppDir
$shortcut.WindowStyle = 7  # Minimized
$shortcut.Save()
Write-Host "    自動起動: $shortcutPath"

# 即時起動
Start-Process -FilePath $startBatPath -WindowStyle Minimized

# === 5. 起動確認 ===
Write-Host "==> 5/5  起動確認"
$ok = $false
for ($i = 1; $i -le 15; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
}
Write-Host ""
if ($ok) {
    Write-Host "✅ Inquira 起動完了" -ForegroundColor Green
    Write-Host ""

    # 社内 LAN からアクセスできる IP を表示
    $ips = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne 'WellKnown' }).IPAddress
    Write-Host "▼ アクセス URL"
    Write-Host "    このPCから (ローカル):  http://localhost:8000/"
    if ($ips) {
        foreach ($ip in $ips) {
            Write-Host "    社内 LAN から:          http://${ip}:8000/"
        }
    }
    Write-Host ""
    Write-Host "▼ データ保存先"
    Write-Host "    $DataDir"
    if ($isUnc) {
        Write-Host "    ※ UNC ネットワーク共有を使用しています。"
        Write-Host "      接続資格情報がキャッシュされていないと起動時にアクセスエラーになります。"
        Write-Host "      ログオン後すぐエクスプローラーで上記パスを一度開くか、net use で永続化してください。"
    }
    Write-Host ""
    Write-Host "▼ 自動起動"
    Write-Host "    Windows にログオンするたびに Inquira が自動起動します。"
    Write-Host "    ※ サーバーを再起動した場合、誰かがログオンするまで起動しません。"
    Write-Host "      24時間稼働させたい場合は、A社 IT 部門に「タスクスケジューラを SYSTEM"
    Write-Host "      ユーザーで登録する」依頼が必要です (管理者権限が要るため)。"
    Write-Host ""
    Write-Host "▼ 公開 URL (https://faq.a-corp.jp/) で社員に使ってもらうには"
    Write-Host "    A社 IT 部門に IIS リバースプロキシ設定を依頼してください。"
    Write-Host "    依頼内容は tenants/a_company/IIS_SETUP_REQUEST.md を渡してください。"
    Write-Host ""
    Write-Host "▼ 停止"
    Write-Host "    タスクバーの uvicorn ウィンドウを閉じる、または PowerShell で:"
    Write-Host "        Get-Process python | Where-Object { `$_.MainWindowTitle -like '*uvicorn*' } | Stop-Process"
} else {
    Write-Host "[!] healthcheck が通りませんでした。" -ForegroundColor Yellow
    Write-Host "    手動で $startBatPath をダブルクリックして、エラーログを確認してください。"
    exit 1
}
