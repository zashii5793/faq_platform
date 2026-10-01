# Inquira 死活監視スクリプト (Windows / 非管理者版)
#
# Inquira サーバー上で 5 分おきに実行し、「社員がブラウザで開けない」状態を
# 層ごとに切り分けて検知する。結果は外部の死活監視サービス (healthchecks.io 等) に
# ハートビートとして送信し、異常時・ハートビート途絶時に提供側へ通知させる。
#
# 確認する層 (社員 PC からのアクセス経路と同じ順):
#   1. アプリ   : http://127.0.0.1:8000/healthz  (uvicorn が生きているか)
#   2. DNS      : FQDN が「このサーバーの IP」に解決されるか
#   3. IIS      : 443/TCP が待ち受けているか
#   4. HTTPS    : https://<FQDN>/healthz が 200 を返すか (IIS → uvicorn の経路全体)
#
# 通知の仕組み (ハートビート方式):
#   - 全層 OK          → <HeartbeatUrl> に ping
#   - どこかで NG      → <HeartbeatUrl>/fail に失敗内容を POST → 即時通知
#   - サーバー停止 / 再起動後ログオンなし / タスク停止
#                      → ping が途絶 → 監視サービス側が猶予時間後に通知
#   サーバー自体が落ちた場合も検知できるのがポイント。
#
# 使い方:
#   PowerShell を起動 (管理者権限不要):
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#       .\inquira_watchdog.ps1 -Fqdn inquira.example.local                    # 1 回だけ実行 (動作確認)
#       .\inquira_watchdog.ps1 -Fqdn inquira.example.local -HeartbeatUrl https://hc-ping.com/<uuid> -AutoRestart -Install
#                                                                            # 5 分おきのタスクとして登録
#       .\inquira_watchdog.ps1 -Uninstall                                     # タスク登録解除
#
# 引数:
#   -Fqdn          社員がアクセスする FQDN (必須。-Uninstall 時は不要)
#   -HeartbeatUrl  死活監視サービスの ping URL (省略時はログのみ)
#   -AutoRestart   アプリ層が NG のとき start_inquira.bat で自動再起動を試みる
#   -AppDir        Inquira のインストール先 (既定 %USERPROFILE%\Inquira)
#   -Install       この引数のまま 5 分おきに実行するタスクを登録
#   -Uninstall     タスクを削除
#
# ログ:
#   %USERPROFILE%\Inquira_Watchdog.log に追記 (1 MB 超でローテート)

param(
    [string]$Fqdn,
    [string]$HeartbeatUrl = "",
    [switch]$AutoRestart,
    [string]$AppDir = (Join-Path $env:USERPROFILE "Inquira"),
    [int]$IntervalMinutes = 5,
    [switch]$Install,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$taskName = "InquiraWatchdog"
$logFile = Join-Path $env:USERPROFILE "Inquira_Watchdog.log"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$Level] $Message"
    $line | Out-File -FilePath $logFile -Append -Encoding utf8
    $color = switch ($Level) {
        "OK"   { "Green" }
        "WARN" { "Yellow" }
        "ERR"  { "Red" }
        default { "White" }
    }
    Write-Host $line -ForegroundColor $color
}

# --- タスク登録 / 解除 ---
if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "タスク $taskName を削除しました"
    exit 0
}

if (-not $Fqdn) {
    Write-Host "-Fqdn を指定してください (例: -Fqdn inquira.example.local)" -ForegroundColor Red
    exit 2
}

if ($Install) {
    $argsList = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`" -Fqdn $Fqdn -AppDir `"$AppDir`""
    if ($HeartbeatUrl) { $argsList += " -HeartbeatUrl $HeartbeatUrl" }
    if ($AutoRestart) { $argsList += " -AutoRestart" }
    # schtasks /TR は 261 文字制限があるため Register-ScheduledTask を使う
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argsList
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
    try {
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    } catch {
        Write-Host "タスク登録に失敗しました: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
    Write-Host "タスク $taskName を登録しました ($IntervalMinutes 分おき)" -ForegroundColor Green
    Write-Host "続けて 1 回実行して動作確認します..."
}

# --- ログローテート ---
if ((Test-Path $logFile) -and ((Get-Item $logFile).Length -gt 1MB)) {
    Move-Item $logFile "$logFile.1" -Force
}

# --- 各層のチェック ---
function Test-LocalApp {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz" -UseBasicParsing -TimeoutSec 5
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

$failures = @()

# 1. アプリ層
$appOk = Test-LocalApp
if (-not $appOk -and $AutoRestart) {
    $startBat = Join-Path $AppDir "start_inquira.bat"
    if (Test-Path $startBat) {
        Write-Log "アプリ無応答のため再起動を試みます" "WARN"
        Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Start-Process -FilePath $startBat -WindowStyle Minimized
        for ($i = 0; $i -lt 15 -and -not $appOk; $i++) {
            Start-Sleep -Seconds 2
            $appOk = Test-LocalApp
        }
        if ($appOk) {
            # 自動復旧できても「落ちていた」事実は通知する
            $failures += "アプリ: 無応答だったため自動再起動 → 復旧"
        }
    }
}
if (-not $appOk) { $failures += "アプリ: http://127.0.0.1:8000/healthz 無応答 (uvicorn 停止?)" }

# 2. DNS 層
$localIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -ne "127.0.0.1" } | ForEach-Object { $_.IPAddress })
try {
    $resolved = @(Resolve-DnsName -Name $Fqdn -Type A -DnsOnly -ErrorAction Stop |
        Where-Object { $_.IPAddress } | ForEach-Object { $_.IPAddress })
    if ($resolved.Count -eq 0) {
        $failures += "DNS: $Fqdn の A レコードなし"
    } elseif (-not ($resolved | Where-Object { $localIps -contains $_ })) {
        $failures += "DNS: $Fqdn → $($resolved -join ',') だがこのサーバーの IP は $($localIps -join ',') (IP 変更 or レコード誤り)"
    }
} catch {
    $failures += "DNS: $Fqdn を名前解決できない ($($_.Exception.Message))"
}

# 3. IIS 層 (443 待ち受け)
$listen443 = Get-NetTCPConnection -LocalPort 443 -State Listen -ErrorAction SilentlyContinue
if (-not $listen443) { $failures += "IIS: 443/TCP を待ち受けていない (IIS / サイト停止?)" }

# 4. HTTPS 経路全体 (自己署名証明書のため -k で検証スキップ。--resolve で DNS 層と切り分け)
$curlExe = Join-Path $env:SystemRoot "System32\curl.exe"
if (Test-Path $curlExe) {
    $code = & $curlExe -ks -o NUL -w "%{http_code}" --max-time 10 --resolve "${Fqdn}:443:127.0.0.1" "https://$Fqdn/healthz"
    if ($code -ne "200") { $failures += "HTTPS: https://$Fqdn/healthz が $code (IIS バインド / 証明書 / ARR 設定?)" }
}

# --- 結果の記録と通知 ---
if ($failures.Count -eq 0) {
    Write-Log "全層 OK" "OK"
    if ($HeartbeatUrl) {
        try { Invoke-WebRequest -Uri $HeartbeatUrl -UseBasicParsing -TimeoutSec 10 | Out-Null }
        catch { Write-Log "ハートビート送信失敗: $($_.Exception.Message)" "WARN" }
    }
    exit 0
}

$body = "host=$env:COMPUTERNAME fqdn=$Fqdn`n" + ($failures -join "`n")
foreach ($f in $failures) { Write-Log $f "ERR" }
if ($HeartbeatUrl) {
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
        Invoke-WebRequest -Uri "$($HeartbeatUrl.TrimEnd('/'))/fail" -Method Post -Body $bytes `
            -ContentType "text/plain; charset=utf-8" -UseBasicParsing -TimeoutSec 10 | Out-Null
    } catch { Write-Log "失敗通知の送信失敗: $($_.Exception.Message)" "WARN" }
}
exit 1
