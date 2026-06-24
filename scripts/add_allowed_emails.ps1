# Inquira 許可ユーザー追加スクリプト (Windows)
#
# .env の ALLOWED_EMAILS に新規ユーザーを追加し、Inquira を再起動する。
# 重複自動除外、バックアップ自動作成、ロールバック手順あり。
#
# 使い方:
#   PowerShell を起動して:
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#
#   1 人追加:
#       .\add_allowed_emails.ps1 -Emails "newuser@example.com"
#
#   複数追加 (カンマ区切り):
#       .\add_allowed_emails.ps1 -Emails "user1@example.com,user2@example.com,user3@example.com"
#
#   テキストファイルから読み込み (1 行 1 アドレス):
#       .\add_allowed_emails.ps1 -EmailsFile "C:\Temp\new_users.txt"
#
#   再起動も自動でやる:
#       .\add_allowed_emails.ps1 -Emails "..." -RestartInquira
#
#   試算のみ (実体には変更を加えない):
#       .\add_allowed_emails.ps1 -Emails "..." -DryRun
#
# 引数:
#   -Emails           カンマ区切りのメールアドレス
#   -EmailsFile       メールアドレス一覧のテキストファイル (1 行 1 アドレス)
#   -EnvPath          .env のパス (既定 %USERPROFILE%\Inquira\.env)
#   -RestartInquira   実行後に Inquira を自動再起動
#   -DryRun           変更内容のプレビューのみ (実体には変更しない)

param(
    [string]$Emails = "",
    [string]$EmailsFile = "",
    [string]$EnvPath = (Join-Path $env:USERPROFILE "Inquira\.env"),
    [switch]$RestartInquira,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# =====================================================
# Step 1: 入力チェック
# =====================================================
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " Inquira 許可ユーザー追加" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $EnvPath)) {
    Write-Host "[X] .env が見つかりません: $EnvPath" -ForegroundColor Red
    exit 1
}

# 追加対象アドレスの収集
$newEmails = @()

if ($EmailsFile) {
    if (-not (Test-Path $EmailsFile)) {
        Write-Host "[X] EmailsFile が見つかりません: $EmailsFile" -ForegroundColor Red
        exit 1
    }
    $newEmails += Get-Content $EmailsFile | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" -and $_ -notmatch "^#" }
}

if ($Emails) {
    $newEmails += $Emails.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
}

if ($newEmails.Count -eq 0) {
    Write-Host "[X] 追加対象のメールアドレスが指定されていません" -ForegroundColor Red
    Write-Host "    -Emails か -EmailsFile を指定してください" -ForegroundColor Yellow
    exit 1
}

# メールアドレス形式の簡易検証
$invalidEmails = $newEmails | Where-Object { $_ -notmatch '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$' }
if ($invalidEmails.Count -gt 0) {
    Write-Host "[X] メールアドレスの形式が不正です:" -ForegroundColor Red
    $invalidEmails | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    exit 1
}

Write-Host "  追加対象 ($($newEmails.Count) 件):" -ForegroundColor White
$newEmails | ForEach-Object { Write-Host "    + $_" -ForegroundColor Green }
Write-Host ""

# =====================================================
# Step 2: 現在の ALLOWED_EMAILS を読み取り
# =====================================================
$envContent = Get-Content $EnvPath -Raw -Encoding UTF8
$currentLine = ($envContent -split "`r?`n") | Where-Object { $_ -match "^\s*ALLOWED_EMAILS\s*=" } | Select-Object -First 1

if (-not $currentLine) {
    Write-Host "[X] .env に ALLOWED_EMAILS の行が見つかりません" -ForegroundColor Red
    exit 1
}

$currentValue = ($currentLine -replace "^\s*ALLOWED_EMAILS\s*=\s*", "").Trim()
$currentEmails = @()
if ($currentValue) {
    $currentEmails = $currentValue.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
}

Write-Host "  現在の登録 ($($currentEmails.Count) 件):" -ForegroundColor White
$currentEmails | ForEach-Object { Write-Host "    - $_" -ForegroundColor DarkGray }
Write-Host ""

# =====================================================
# Step 3: マージと重複除外
# =====================================================
$allEmails = ($currentEmails + $newEmails) | Sort-Object -Unique
$skipped = $newEmails | Where-Object { $currentEmails -contains $_ }
$actuallyAdded = $newEmails | Where-Object { $currentEmails -notcontains $_ }

if ($skipped.Count -gt 0) {
    Write-Host "  スキップ (既に登録済み、$($skipped.Count) 件):" -ForegroundColor Yellow
    $skipped | ForEach-Object { Write-Host "    = $_" -ForegroundColor Yellow }
    Write-Host ""
}

Write-Host "  最終的な登録数: $($currentEmails.Count) → $($allEmails.Count) 件 (実追加 $($actuallyAdded.Count) 件)" -ForegroundColor Cyan
Write-Host ""

if ($actuallyAdded.Count -eq 0) {
    Write-Host "  すべて既に登録済みです。変更不要。" -ForegroundColor Green
    exit 0
}

if ($DryRun) {
    Write-Host "==> DryRun モード: ここで終了。.env には変更を加えていません。" -ForegroundColor Cyan
    exit 0
}

# =====================================================
# Step 4: .env のバックアップ
# =====================================================
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = "$EnvPath.bak.$ts"
Copy-Item -Path $EnvPath -Destination $backupPath -Force
Write-Host "  バックアップ作成: $backupPath" -ForegroundColor White

# =====================================================
# Step 5: .env を書き換え (UTF-8 BOM 無しで保存)
# =====================================================
$newValue = $allEmails -join ","
$newEnvContent = ($envContent -split "`r?`n") | ForEach-Object {
    if ($_ -match "^\s*ALLOWED_EMAILS\s*=") {
        "ALLOWED_EMAILS=$newValue"
    } else {
        $_
    }
}
$joinedContent = $newEnvContent -join "`r`n"

# UTF-8 BOM 無しで書き出し
[System.IO.File]::WriteAllText($EnvPath, $joinedContent, [System.Text.UTF8Encoding]::new($false))
Write-Host "  .env 更新完了" -ForegroundColor Green
Write-Host ""

# =====================================================
# Step 6: Inquira を再起動 (オプション)
# =====================================================
if ($RestartInquira) {
    Write-Host "==> Inquira を再起動中..." -ForegroundColor Cyan

    # 既存プロセスを停止
    $pyProcs = Get-Process python -ErrorAction SilentlyContinue
    if ($pyProcs) {
        $pyProcs | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Write-Host "    Python プロセスを停止 ($($pyProcs.Count) 件)" -ForegroundColor White
    }

    # 起動バッチを実行
    $startBat = Join-Path (Split-Path $EnvPath -Parent) "start_inquira.bat"
    if (Test-Path $startBat) {
        Start-Process -FilePath $startBat -WindowStyle Minimized
        Write-Host "    start_inquira.bat 起動" -ForegroundColor White

        # ヘルスチェック (最大 30 秒待機)
        $healthOk = $false
        for ($i = 0; $i -lt 15; $i++) {
            Start-Sleep -Seconds 2
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz" -UseBasicParsing -TimeoutSec 3
                if ($r.StatusCode -eq 200) {
                    $healthOk = $true
                    break
                }
            } catch {}
        }

        if ($healthOk) {
            Write-Host "    ヘルスチェック OK (/healthz 200)" -ForegroundColor Green
        } else {
            Write-Host "    ヘルスチェック失敗 (30 秒以内に応答なし)" -ForegroundColor Yellow
            Write-Host "    手動で確認: Invoke-WebRequest http://127.0.0.1:8000/healthz -UseBasicParsing" -ForegroundColor Yellow
        }
    } else {
        Write-Host "    [警告] start_inquira.bat が見つかりません: $startBat" -ForegroundColor Yellow
        Write-Host "    手動で再起動してください" -ForegroundColor Yellow
    }
}

# =====================================================
# 完了サマリ
# =====================================================
Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host " 完了" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  実追加: $($actuallyAdded.Count) 件" -ForegroundColor White
Write-Host "  バックアップ: $backupPath" -ForegroundColor White
Write-Host ""

if (-not $RestartInquira) {
    Write-Host "次のステップ: Inquira の再起動が必要です" -ForegroundColor Yellow
    Write-Host '  Get-Process python | Stop-Process -Force' -ForegroundColor White
    Write-Host '  & "$env:USERPROFILE\Inquira\start_inquira.bat"' -ForegroundColor White
    Write-Host ""
}

Write-Host "ロールバックする場合:" -ForegroundColor Yellow
Write-Host "  Copy-Item '$backupPath' '$EnvPath' -Force" -ForegroundColor White
Write-Host ""
Write-Host "⚠ 重要: Google Cloud Console 側にもテストユーザー登録が必要です" -ForegroundColor Yellow
Write-Host "  https://console.cloud.google.com/apis/credentials/consent" -ForegroundColor White
Write-Host "  → テストユーザー → ADD USERS で同じアドレスを追加してください" -ForegroundColor White
Write-Host ""

exit 0
