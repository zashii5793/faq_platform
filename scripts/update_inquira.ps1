# Inquira アップデートスクリプト (Windows / 非管理者版)
#
# 既に install.ps1 でセットアップ済みの Inquira を、GitHub の最新版に更新する。
# 安全のため:
#   - 現在のコードをタイムスタンプ付きディレクトリにバックアップ
#   - .env / .venv / データ保存先 (UNC 共有) は触らない
#   - ヘルスチェックが失敗したら自動ロールバック
#
# 使い方:
#   PowerShell を起動 (管理者権限不要):
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#       .\update_inquira.ps1                   # main ブランチ tip
#       .\update_inquira.ps1 -Version v1.2.3   # 特定タグ
#       .\update_inquira.ps1 -DryRun           # ダウンロードと検証のみ、入れ替えしない
#
# 引数:
#   -AppDir       Inquira のインストール先 (既定 %USERPROFILE%\Inquira)
#   -Version      取得するブランチ名 or タグ名 (既定 main)
#   -BackupRoot   バックアップ保管先 (既定 %USERPROFILE%\Inquira_backups)
#   -NoRollback   失敗してもロールバックしない (障害解析用)
#   -DryRun       ダウンロード/検証だけ、本体には触らない
#
# ログ:
#   %USERPROFILE%\Inquira_Update.log に追記

param(
    [string]$AppDir = (Join-Path $env:USERPROFILE "Inquira"),
    [string]$Version = "main",
    [string]$BackupRoot = (Join-Path $env:USERPROFILE "Inquira_backups"),
    [string]$Repo = "zashii5793/faq_platform",
    [switch]$NoRollback,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$logFile = Join-Path $env:USERPROFILE "Inquira_Update.log"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$Level] $Message"
    $line | Out-File -FilePath $logFile -Append -Encoding utf8
    $color = switch ($Level) {
        "STEP" { "Cyan" }
        "OK"   { "Green" }
        "WARN" { "Yellow" }
        "ERR"  { "Red" }
        default { "White" }
    }
    Write-Host $line -ForegroundColor $color
}

Write-Log "=========================================" "STEP"
Write-Log " Inquira アップデート開始" "STEP"
Write-Log "=========================================" "STEP"
Write-Log "AppDir:    $AppDir"
Write-Log "Version:   $Version"
Write-Log "BackupRoot: $BackupRoot"
Write-Log "Repo:      $Repo"
Write-Log "DryRun:    $DryRun"

# =====================================================
# Step 1: 事前チェック
# =====================================================
Write-Log "==> 1/8  事前チェック" "STEP"

if (-not (Test-Path $AppDir)) {
    Write-Log "AppDir が存在しません: $AppDir" "ERR"
    Write-Log "先に install.ps1 でセットアップしてください。" "ERR"
    exit 1
}
$envFile = Join-Path $AppDir ".env"
if (-not (Test-Path $envFile)) {
    Write-Log ".env が見つかりません: $envFile" "ERR"
    exit 1
}
$venvPython = Join-Path $AppDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Log "venv が見つかりません: $venvPython" "ERR"
    Write-Log "install.ps1 を先に実行してください。" "ERR"
    exit 1
}

# 現在のバージョンを把握 (pyproject.toml から)
$currentVersion = "unknown"
$pyproj = Join-Path $AppDir "pyproject.toml"
if (Test-Path $pyproj) {
    $verLine = Select-String -Path $pyproj -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($verLine) {
        $currentVersion = $verLine.Matches[0].Groups[1].Value
    }
}
Write-Log "    現在のバージョン: $currentVersion" "OK"

# =====================================================
# Step 2: ZIP ダウンロード
# =====================================================
Write-Log "==> 2/8  GitHub から $Version をダウンロード" "STEP"

$tempDir = Join-Path $env:TEMP ("inquira_update_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
$zipPath = Join-Path $tempDir "source.zip"

$urlCandidates = @(
    "https://github.com/$Repo/archive/refs/tags/$Version.zip",
    "https://github.com/$Repo/archive/refs/heads/$Version.zip"
)

$downloaded = $false
foreach ($url in $urlCandidates) {
    try {
        Write-Log "    試行: $url"
        (New-Object System.Net.WebClient).DownloadFile($url, $zipPath)
        if ((Get-Item $zipPath).Length -gt 1000) {
            Write-Log "    ダウンロード成功 ($([math]::Round((Get-Item $zipPath).Length / 1KB, 1)) KB)" "OK"
            $downloaded = $true
            break
        }
    } catch {
        Write-Log "    失敗: $($_.Exception.Message)" "WARN"
    }
}

if (-not $downloaded) {
    Write-Log "ZIP のダウンロードに失敗。-Version の指定が正しいか確認してください ($Version)" "ERR"
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}

# =====================================================
# Step 3: ZIP 展開と検証
# =====================================================
Write-Log "==> 3/8  ZIP 展開 + 整合性検証" "STEP"

Expand-Archive -Path $zipPath -DestinationPath $tempDir -Force

# 展開後のルートディレクトリは "<repo>-<version>" になる
$extracted = Get-ChildItem $tempDir -Directory | Select-Object -First 1
if (-not $extracted) {
    Write-Log "ZIP 展開後にディレクトリが見つかりません" "ERR"
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}
$srcRoot = $extracted.FullName
Write-Log "    展開先: $srcRoot"

# 必須ファイルの存在チェック
$required = @("app", "scripts", "pyproject.toml")
foreach ($r in $required) {
    if (-not (Test-Path (Join-Path $srcRoot $r))) {
        Write-Log "必須コンテンツが不足: $r" "ERR"
        Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
        exit 1
    }
}

# 新バージョンの確認
$newVersion = "unknown"
$newPyproj = Join-Path $srcRoot "pyproject.toml"
$newVerLine = Select-String -Path $newPyproj -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
if ($newVerLine) {
    $newVersion = $newVerLine.Matches[0].Groups[1].Value
}
Write-Log "    新バージョン: $newVersion" "OK"

if ($currentVersion -eq $newVersion -and $Version -notmatch "^(main|master)$") {
    Write-Log "現在と同じバージョンです。更新不要。" "OK"
    Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
}

if ($DryRun) {
    Write-Log "==> DryRun モード: ここで終了。実体には変更を加えていません。" "OK"
    Write-Log "    展開済みソースは $srcRoot に残っています (確認用)" "OK"
    exit 0
}

# =====================================================
# Step 4: 現在の状態をバックアップ
# =====================================================
Write-Log "==> 4/8  現在のコードをバックアップ" "STEP"

if (-not (Test-Path $BackupRoot)) {
    New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
}
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $BackupRoot "$ts-v$currentVersion"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

# コードのみバックアップ (data, .venv, .env はバックアップしない = 触らない)
$toBackup = @("app", "scripts", "pyproject.toml", "README.md", "ROADMAP.md", "CHANGELOG.md", "LICENSE")
foreach ($item in $toBackup) {
    $src = Join-Path $AppDir $item
    if (Test-Path $src) {
        $dst = Join-Path $backupDir $item
        Copy-Item -Path $src -Destination $dst -Recurse -Force
    }
}
Write-Log "    バックアップ完了: $backupDir" "OK"

# =====================================================
# Step 5: Inquira 停止
# =====================================================
Write-Log "==> 5/8  Inquira (uvicorn) 停止" "STEP"
$pyProcs = Get-Process python -ErrorAction SilentlyContinue
if ($pyProcs) {
    $pyProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Log "    Python プロセスを停止 ($($pyProcs.Count) 件)" "OK"
} else {
    Write-Log "    実行中の Python プロセスなし" "OK"
}

# =====================================================
# Step 6: コード入れ替え
# =====================================================
Write-Log "==> 6/8  新コードを配置" "STEP"

function Replace-Folder {
    param([string]$Name)
    $src = Join-Path $srcRoot $Name
    $dst = Join-Path $AppDir $Name
    if (-not (Test-Path $src)) { return }
    if (Test-Path $dst) {
        Remove-Item $dst -Recurse -Force
    }
    Copy-Item -Path $src -Destination $dst -Recurse -Force
    Write-Log "    更新: $Name"
}

function Replace-File {
    param([string]$Name)
    $src = Join-Path $srcRoot $Name
    $dst = Join-Path $AppDir $Name
    if (-not (Test-Path $src)) { return }
    Copy-Item -Path $src -Destination $dst -Force
    Write-Log "    更新: $Name"
}

Replace-Folder "app"
Replace-Folder "scripts"
Replace-File "pyproject.toml"
Replace-File "README.md"
Replace-File "ROADMAP.md"
Replace-File "CHANGELOG.md"
Replace-File "LICENSE"

Write-Log "    コード入れ替え完了" "OK"

# =====================================================
# Step 7: 依存パッケージ更新
# =====================================================
Write-Log "==> 7/8  pip 依存パッケージを更新" "STEP"
try {
    & $venvPython -m pip install --quiet --upgrade pip
    & $venvPython -m pip install --quiet -e $AppDir
    Write-Log "    pip install 完了" "OK"
} catch {
    Write-Log "    pip install 失敗: $($_.Exception.Message)" "ERR"
    if (-not $NoRollback) {
        Write-Log "    ロールバックを実行します" "WARN"
        foreach ($item in $toBackup) {
            $bak = Join-Path $backupDir $item
            $tgt = Join-Path $AppDir $item
            if (Test-Path $bak) {
                if (Test-Path $tgt) { Remove-Item $tgt -Recurse -Force }
                Copy-Item -Path $bak -Destination $tgt -Recurse -Force
            }
        }
        Write-Log "    ロールバック完了 (旧コードに戻りました)" "OK"
    }
    exit 1
}

# =====================================================
# Step 8: 起動とヘルスチェック
# =====================================================
Write-Log "==> 8/8  Inquira 起動 + ヘルスチェック" "STEP"
$startBat = Join-Path $AppDir "start_inquira.bat"
if (Test-Path $startBat) {
    Start-Process -FilePath $startBat -WindowStyle Minimized
    Write-Log "    start_inquira.bat を起動しました" "OK"
} else {
    Write-Log "start_inquira.bat が見つかりません: $startBat" "ERR"
    exit 1
}

# 起動待ち (最大 30 秒)
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
    Write-Log "    ヘルスチェック OK (/healthz 200)" "OK"
} else {
    Write-Log "    ヘルスチェック失敗 (30秒以内に応答なし)" "ERR"
    if (-not $NoRollback) {
        Write-Log "    自動ロールバックを実行します..." "WARN"
        Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        foreach ($item in $toBackup) {
            $bak = Join-Path $backupDir $item
            $tgt = Join-Path $AppDir $item
            if (Test-Path $bak) {
                if (Test-Path $tgt) { Remove-Item $tgt -Recurse -Force }
                Copy-Item -Path $bak -Destination $tgt -Recurse -Force
            }
        }
        & $venvPython -m pip install --quiet -e $AppDir
        Start-Process -FilePath $startBat -WindowStyle Minimized
        Write-Log "    ロールバック完了。旧バージョン ($currentVersion) で起動中" "OK"
        exit 1
    } else {
        Write-Log "    -NoRollback 指定のため、ロールバックしません。手動対処が必要です。" "WARN"
        Write-Log "    バックアップ: $backupDir" "WARN"
        exit 1
    }
}

# =====================================================
# 完了
# =====================================================
Write-Log "=========================================" "OK"
Write-Log " アップデート完了: $currentVersion -> $newVersion" "OK"
Write-Log "=========================================" "OK"
Write-Log ""
Write-Log "バックアップ: $backupDir"
Write-Log "ログ: $logFile"
Write-Log ""
Write-Log "問題が発生したら、以下で手動ロールバック可能:"
Write-Log "  Get-Process python | Stop-Process -Force"
Write-Log "  Copy-Item '$backupDir\*' '$AppDir' -Recurse -Force"
Write-Log "  & '$startBat'"

# 一時ファイルを削除
Remove-Item $tempDir -Recurse -Force -ErrorAction SilentlyContinue

exit 0
