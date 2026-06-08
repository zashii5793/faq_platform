# A株式会社 Windows サーバー向け Inquira インストールスクリプト
#
# 前提:
#   - Windows Server 2019 / 2022 もしくは Windows 10/11
#   - Python 3.11+ がインストール済み (py -3.11 が動く状態)
#     未インストールなら https://www.python.org/downloads/ から取得
#   - PowerShell 5.1+ (Windows 標準)
#   - 管理者権限で実行
#
# 使い方:
#   PowerShell を「管理者として実行」で起動し、このフォルダで:
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#       .\install.ps1
#
# 事前に同階層の .env ファイルを編集して
#   ANTHROPIC_API_KEY / GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REDIRECT_URI
# を実値で埋めてください。

param(
    [string]$AppDir = "C:\Inquira"
)

$ErrorActionPreference = "Stop"

# === 0. 事前チェック ===
Write-Host "==> 0/6  事前チェック"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")) {
    Write-Host "[X] 管理者権限が必要です。PowerShell を「管理者として実行」で起動し直してください。" -ForegroundColor Red
    exit 1
}

$pythonCmd = $null
foreach ($cand in @("py -3.12", "py -3.11", "python")) {
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
    Write-Host "    ANTHROPIC_API_KEY / GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET を埋めてから再実行してください。"
    exit 1
}

# === 1. アプリ配置 ===
Write-Host "==> 1/6  アプリ配置 ($AppDir)"
$projectDir = (Resolve-Path (Join-Path $scriptDir "..\..")).Path

if (-not (Test-Path $AppDir)) {
    New-Item -ItemType Directory -Path $AppDir | Out-Null
}

# robocopy で同期 (除外: .git / __pycache__ / .venv / tenants / docs / data)
$robocopyArgs = @($projectDir, $AppDir, "/E",
    "/XD", ".git", "__pycache__", ".venv", "tenants", "docs", "data",
    "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP")
$null = & robocopy @robocopyArgs
# robocopy の正常終了コードは 0-7
if ($LASTEXITCODE -gt 7) {
    Write-Host "[X] robocopy がエラー終了 (exit=$LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

$dataDir = Join-Path $AppDir "data"
if (-not (Test-Path $dataDir)) {
    New-Item -ItemType Directory -Path $dataDir | Out-Null
}

# === 2. Python venv 作成 + 依存インストール ===
Write-Host "==> 2/6  Python venv 作成 + 依存インストール (数分かかります)"
$venvPath = Join-Path $AppDir ".venv"
if (-not (Test-Path $venvPath)) {
    cmd /c "$pythonCmd -m venv `"$venvPath`""
}
$venvPython = Join-Path $venvPath "Scripts\python.exe"
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e $AppDir

# === 3. .env 配置 (SESSION_SECRET 生成 + パス置換) ===
Write-Host "==> 3/6  .env 配置"
# 32 バイトのランダム hex
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$sessionSecret = ($bytes | ForEach-Object { "{0:x2}" -f $_ }) -join ""

# Windows パスは forward-slash に変換 (Python から読みやすい形式)
$appDirForward = $AppDir.Replace("\", "/")

$envContent = $envContent `
    -replace "__GENERATED_BY_INSTALL_SH__", $sessionSecret `
    -replace "__GENERATED_BY_INSTALL_PS1__", $sessionSecret `
    -replace "__APP_DIR__", $appDirForward

Set-Content -Path (Join-Path $AppDir ".env") -Value $envContent -Encoding UTF8 -NoNewline

# === 4. 起動バッチ作成 (手動起動用) ===
Write-Host "==> 4/6  起動バッチ作成"
$startBat = @"
@echo off
cd /d $AppDir
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
"@
Set-Content -Path (Join-Path $AppDir "start_inquira.bat") -Value $startBat -Encoding ASCII

# === 5. Windows サービス化 (Task Scheduler によるシステム起動時自動実行) ===
Write-Host "==> 5/6  自動起動タスクを登録"
$taskName = "Inquira"
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
$action = New-ScheduledTaskAction -Execute (Join-Path $AppDir "start_inquira.bat")
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings | Out-Null

# 即時起動
Start-ScheduledTask -TaskName $taskName

# === 6. 起動確認 ===
Write-Host "==> 6/6  起動確認"
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
    Write-Host "公開 URL (リバプロ設定後): https://faq.a-corp.jp/"
    Write-Host "管理画面:                  https://faq.a-corp.jp/admin/upload"
    Write-Host ""
    Write-Host "ローカル動作確認:          http://localhost:8000/healthz"
    Write-Host "サービス管理:              タスクスケジューラ -> Inquira"
    Write-Host "ログ:                      $AppDir\start_inquira.bat を直接実行すると確認可能"
} else {
    Write-Host "[!] healthcheck が通りませんでした。" -ForegroundColor Yellow
    Write-Host "    手動で $AppDir\start_inquira.bat を実行してエラーログを確認してください。"
    exit 1
}
