# Inquira IIS リバースプロキシ 自動セットアップ スクリプト
#
# このスクリプトは Inquira を https://inquira.<社内ドメイン>/ で公開するため、
# Windows Server / Windows 10/11 上で IIS リバースプロキシを自動セットアップします。
#
# 想定環境:
#   - Windows Server 2016 以降 (Windows 10/11 でも動作)
#   - 管理者権限の PowerShell から実行
#   - Inquira が localhost:8000 で動作中
#
# 事前準備 (重要):
#   Microsoft が自動ダウンロードを 403 でブロックしているため、
#   URL Rewrite と ARR の MSI は事前に手動ダウンロードが必要です。
#
#   [方法A] winget が使えるなら何もしなくて OK (Windows Server 2022 / Windows 10 1809+ に標準搭載)
#   [方法B] 手動ダウンロード:
#     1. ブラウザで https://www.iis.net/downloads/microsoft/url-rewrite を開く
#        → 「Download」リンクから rewrite_amd64_en-US.msi をダウンロード
#        → C:\Temp\rewrite_amd64.msi に配置
#     2. ブラウザで https://www.iis.net/downloads/microsoft/application-request-routing を開く
#        → 「Install this extension」から ARR をダウンロード
#        → C:\Temp\requestRouter_amd64.msi に配置
#
# 使い方:
#   PowerShell を「管理者として実行」で起動
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\setup_iis_reverse_proxy.ps1 -Hostname "inquira.example.local"
#
# やること (1コマンドで全部):
#   1. 事前条件確認 (winget または手動配置 MSI)
#   2. IIS 役割インストール (なければ)
#   3. URL Rewrite モジュール インストール (winget or MSI、なければ)
#   4. ARR モジュール インストール (winget or MSI、なければ)
#   5. 自己署名 SSL 証明書発行 (なければ)
#   6. 証明書を「信頼されたルート証明機関」に登録
#   7. IIS で「Inquira」サイト作成 (HTTP + HTTPS バインド)
#   8. web.config 配置 (リバプロ設定)
#   9. ARR の Enable Proxy
#   10. iisreset → 動作確認
#
# 失敗時:
#   ログを C:\Inquira_IIS_Setup.log に残します。エラーが出たら、そのログを共有してください。
#   .\setup_iis_reverse_proxy.ps1 -Cleanup で全部を元に戻すこともできます。

param(
    [string]$Hostname = "inquira.example.local",
    [int]$BackendPort = 8000,
    [string]$SitePath = "C:\inetpub\inquira-site",
    [string]$LogFile = "C:\Inquira_IIS_Setup.log",
    [string]$DownloadDir = "C:\Temp",
    [switch]$Cleanup,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# =====================================================
# ロギング
# =====================================================
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$Level] $Message"
    $color = switch ($Level) {
        "ERROR" { "Red" }
        "WARN"  { "Yellow" }
        "OK"    { "Green" }
        "STEP"  { "Cyan" }
        default { "White" }
    }
    Write-Host $line -ForegroundColor $color
    try {
        Add-Content -Path $LogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {}
}

# =====================================================
# 共通: 管理者権限チェック
# =====================================================
function Assert-Admin {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")) {
        Write-Log "管理者権限が必要です。PowerShell を『管理者として実行』で起動し直してください。" "ERROR"
        exit 1
    }
}

# =====================================================
# クリーンアップ (元に戻す)
# =====================================================
function Invoke-Cleanup {
    Write-Log "========= クリーンアップ開始 (元に戻します) =========" "STEP"
    Assert-Admin

    Import-Module WebAdministration -ErrorAction SilentlyContinue
    if (Test-Path "IIS:\Sites\Inquira") {
        Remove-Website -Name "Inquira" -ErrorAction SilentlyContinue
        Write-Log "IIS サイト 'Inquira' を削除" "OK"
    }

    $certs = Get-ChildItem Cert:\LocalMachine\My -ErrorAction SilentlyContinue | Where-Object { $_.Subject -eq "CN=$Hostname" }
    foreach ($c in $certs) {
        Remove-Item -Path "Cert:\LocalMachine\My\$($c.Thumbprint)" -Force -ErrorAction SilentlyContinue
        Remove-Item -Path "Cert:\LocalMachine\Root\$($c.Thumbprint)" -Force -ErrorAction SilentlyContinue
        Write-Log "証明書削除 (Thumbprint: $($c.Thumbprint))" "OK"
    }

    if (Test-Path $SitePath) {
        Remove-Item -Path $SitePath -Recurse -Force -ErrorAction SilentlyContinue
        Write-Log "サイトディレクトリ削除 ($SitePath)" "OK"
    }

    Write-Log "========= クリーンアップ完了 =========" "OK"
    Write-Log "注意: IIS 役割と URL Rewrite / ARR モジュールは削除していません (他で使う可能性があるため)。"
    exit 0
}

# =====================================================
# 事前条件チェック
# =====================================================
function Test-Prerequisites {
    Write-Log "==> 事前条件チェック" "STEP"

    $results = @{
        WinGet = $false
        UrlRewriteMsi = $false
        ArrMsi = $false
        UrlRewriteAlreadyInstalled = $false
        ArrAlreadyInstalled = $false
    }

    # winget の有無
    $wingetCmd = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetCmd) {
        Write-Log "    winget: あり (パス: $($wingetCmd.Source))" "OK"
        $results.WinGet = $true
    } else {
        Write-Log "    winget: なし"
    }

    # 既存インストールの確認
    if (Test-Path "$env:windir\System32\inetsrv\rewrite.dll") {
        Write-Log "    URL Rewrite: 既にインストール済み" "OK"
        $results.UrlRewriteAlreadyInstalled = $true
    }

    if ((Test-Path "$env:windir\System32\inetsrv\config\schema\rewrite_schema.xml") -or
        (Get-ChildItem "$env:windir\System32\inetsrv\config\schema" -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*arr*" })) {
        Write-Log "    ARR: 既にインストール済み" "OK"
        $results.ArrAlreadyInstalled = $true
    }

    # ローカル MSI
    $rewriteCandidates = @(
        "$DownloadDir\rewrite_amd64.msi",
        "$DownloadDir\rewrite_amd64_en-US.msi",
        "$DownloadDir\urlrewrite.msi"
    )
    foreach ($p in $rewriteCandidates) {
        if (Test-Path $p) {
            Write-Log "    URL Rewrite MSI: $p" "OK"
            $results.UrlRewriteMsi = $p
            break
        }
    }

    $arrCandidates = @(
        "$DownloadDir\requestRouter_amd64.msi",
        "$DownloadDir\arr.msi"
    )
    foreach ($p in $arrCandidates) {
        if (Test-Path $p) {
            Write-Log "    ARR MSI: $p" "OK"
            $results.ArrMsi = $p
            break
        }
    }

    # 判定
    $needRewrite = -not $results.UrlRewriteAlreadyInstalled
    $needArr = -not $results.ArrAlreadyInstalled

    if ($needRewrite -and -not $results.WinGet -and -not $results.UrlRewriteMsi) {
        Write-Log ""
        Write-Log "[X] URL Rewrite モジュールが手に入りません。" "ERROR"
        Write-Log "    以下のいずれかで対応してください:" "WARN"
        Write-Log "    [A] winget を入れる (Windows Server 2022 / Windows 10 以降に標準搭載)"
        Write-Log "    [B] ブラウザで以下を開いて MSI をダウンロード:"
        Write-Log "        https://www.iis.net/downloads/microsoft/url-rewrite"
        Write-Log "        → 『Install this extension』から落として $DownloadDir に置く"
        Write-Log ""
        return $false
    }

    if ($needArr -and -not $results.WinGet -and -not $results.ArrMsi) {
        Write-Log ""
        Write-Log "[X] ARR モジュールが手に入りません。" "ERROR"
        Write-Log "    以下のいずれかで対応してください:" "WARN"
        Write-Log "    [A] winget を入れる"
        Write-Log "    [B] ブラウザで以下を開いて MSI をダウンロード:"
        Write-Log "        https://www.iis.net/downloads/microsoft/application-request-routing"
        Write-Log "        → MSI を落として $DownloadDir に置く"
        Write-Log ""
        return $false
    }

    return $results
}

# =====================================================
# IIS モジュールインストール (winget または MSI)
# =====================================================
function Install-IISModule {
    param(
        [string]$Name,
        [string]$WinGetId,
        [string]$MsiPath,
        [bool]$WinGetAvailable,
        [bool]$AlreadyInstalled
    )

    if ($AlreadyInstalled) {
        Write-Log "    $Name は既にインストール済み" "OK"
        return $true
    }

    # winget 試行
    if ($WinGetAvailable) {
        Write-Log "    winget で $Name をインストール中..."
        $proc = Start-Process winget -ArgumentList "install --id $WinGetId --accept-source-agreements --accept-package-agreements --silent" -Wait -PassThru -NoNewWindow
        if ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq -1978335189) {
            # -1978335189 = "no applicable upgrade found" = 既にインストール済み
            Write-Log "    $Name インストール完了 (winget)" "OK"
            return $true
        }
        Write-Log "    winget でのインストール失敗 (ExitCode: $($proc.ExitCode))。MSI を探します..." "WARN"
    }

    # MSI 試行
    if ($MsiPath -and (Test-Path $MsiPath)) {
        Write-Log "    MSI からインストール: $MsiPath"
        $proc = Start-Process msiexec.exe -ArgumentList "/i `"$MsiPath`" /quiet /norestart" -Wait -PassThru
        if ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq 1638) {
            # 1638 = "別バージョンが既にインストール済み" = OK
            Write-Log "    $Name インストール完了 (MSI)" "OK"
            return $true
        }
        Write-Log "    MSI からのインストール失敗 (ExitCode: $($proc.ExitCode))" "ERROR"
        return $false
    }

    Write-Log "[X] $Name のインストール手段がありません" "ERROR"
    return $false
}

# =====================================================
# Cleanup モード
# =====================================================
if ($Cleanup) {
    Invoke-Cleanup
}

# =====================================================
# メイン処理
# =====================================================
Write-Log "========= Inquira IIS リバースプロキシ自動セットアップ =========" "STEP"
Write-Log "ホスト名:           $Hostname"
Write-Log "バックエンドポート:  $BackendPort"
Write-Log "IIS サイトパス:     $SitePath"
Write-Log "ダウンロード置き場: $DownloadDir"
Write-Log "ログ:               $LogFile"
Write-Log ""

Assert-Admin

# 事前条件チェック
$prereq = Test-Prerequisites
if (-not $prereq) {
    Write-Log ""
    Write-Log "事前準備をしてから再実行してください。" "ERROR"
    exit 1
}

if ($CheckOnly) {
    Write-Log ""
    Write-Log "事前条件 OK。-CheckOnly モードのためここで終了します。" "OK"
    Write-Log "本番実行時は -CheckOnly を外して再実行してください。"
    exit 0
}

# =====================================================
# Step 1: IIS 役割
# =====================================================
Write-Log "==> 1/10  IIS 役割インストール" "STEP"
$iisInstalled = $false
try {
    $iis = Get-WindowsFeature -Name Web-Server -ErrorAction Stop
    if ($iis.Installed) {
        Write-Log "    IIS は既にインストール済み" "OK"
        $iisInstalled = $true
    } else {
        Write-Log "    IIS をインストール中..."
        Install-WindowsFeature -Name Web-Server -IncludeManagementTools -ErrorAction Stop | Out-Null
        Write-Log "    IIS インストール完了" "OK"
        $iisInstalled = $true
    }
} catch {
    # Windows 10/11 や Server Core で Get-WindowsFeature が無い場合
    Write-Log "    Get-WindowsFeature 不可。Enable-WindowsOptionalFeature で試行..." "WARN"
    try {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName IIS-WebServerRole -ErrorAction Stop
        if ($feature.State -eq "Enabled") {
            Write-Log "    IIS は既にインストール済み" "OK"
        } else {
            Enable-WindowsOptionalFeature -Online -FeatureName IIS-WebServerRole -All -NoRestart -ErrorAction Stop | Out-Null
            Write-Log "    IIS インストール完了" "OK"
        }
        $iisInstalled = $true
    } catch {
        Write-Log "IIS のインストールに失敗: $($_.Exception.Message)" "ERROR"
        Write-Log "手動でサーバーマネージャから『Web サーバー (IIS)』をインストールしてから再実行してください。"
        exit 1
    }
}

# =====================================================
# Step 2: URL Rewrite
# =====================================================
Write-Log "==> 2/10  URL Rewrite モジュール" "STEP"
$ok = Install-IISModule -Name "URL Rewrite" -WinGetId "Microsoft.IIS.URLRewrite" -MsiPath $prereq.UrlRewriteMsi -WinGetAvailable $prereq.WinGet -AlreadyInstalled $prereq.UrlRewriteAlreadyInstalled
if (-not $ok) { exit 1 }

# =====================================================
# Step 3: ARR
# =====================================================
Write-Log "==> 3/10  ARR (Application Request Routing) モジュール" "STEP"
$ok = Install-IISModule -Name "ARR" -WinGetId "Microsoft.IIS.ApplicationRequestRouting" -MsiPath $prereq.ArrMsi -WinGetAvailable $prereq.WinGet -AlreadyInstalled $prereq.ArrAlreadyInstalled
if (-not $ok) { exit 1 }

# =====================================================
# Step 4: 自己署名 SSL 証明書
# =====================================================
Write-Log "==> 4/10  自己署名 SSL 証明書" "STEP"
$cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Subject -eq "CN=$Hostname" } | Sort-Object NotAfter -Descending | Select-Object -First 1
if ($cert -and $cert.NotAfter -gt (Get-Date).AddDays(30)) {
    Write-Log "    既存証明書を使用 (Thumbprint: $($cert.Thumbprint), 有効期限: $($cert.NotAfter.ToString('yyyy-MM-dd')))" "OK"
} else {
    Write-Log "    新規発行中..."
    $cert = New-SelfSignedCertificate `
        -DnsName $Hostname `
        -CertStoreLocation "Cert:\LocalMachine\My" `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -NotAfter (Get-Date).AddYears(5) `
        -FriendlyName "Inquira Self-Signed Cert"
    Write-Log "    発行完了 (Thumbprint: $($cert.Thumbprint))" "OK"
}

# =====================================================
# Step 5: 信頼ルート登録
# =====================================================
Write-Log "==> 5/10  証明書を信頼されたルート証明機関に登録" "STEP"
$rootExisting = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
if ($rootExisting) {
    Write-Log "    既にルートに登録済み" "OK"
} else {
    $store = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "LocalMachine")
    $store.Open("ReadWrite")
    $store.Add($cert)
    $store.Close()
    Write-Log "    ルートに登録完了" "OK"
}

# =====================================================
# Step 6: IIS サイト作成
# =====================================================
Write-Log "==> 6/10  IIS サイト作成" "STEP"
Import-Module WebAdministration -ErrorAction Stop

if (-not (Test-Path $SitePath)) {
    New-Item -ItemType Directory -Path $SitePath -Force | Out-Null
    Write-Log "    サイトディレクトリ作成: $SitePath"
}

$siteName = "Inquira"
if (Test-Path "IIS:\Sites\$siteName") {
    Write-Log "    既存サイトを削除して作り直し"
    Remove-Website -Name $siteName
}

New-Website -Name $siteName -PhysicalPath $SitePath -Port 80 -HostHeader $Hostname -Force | Out-Null
Write-Log "    HTTP バインド作成 (80 / $Hostname)" "OK"

New-WebBinding -Name $siteName -IPAddress "*" -Port 443 -Protocol "https" -HostHeader $Hostname -SslFlags 1 -ErrorAction SilentlyContinue
Write-Log "    HTTPS バインド作成 (443 / $Hostname)" "OK"

$bindingPath = "IIS:\SslBindings\!443!$Hostname"
if (Test-Path $bindingPath) { Remove-Item $bindingPath -Force }
New-Item -Path $bindingPath -Value $cert -SSLFlags 1 | Out-Null
Write-Log "    SSL 証明書をバインド" "OK"

# =====================================================
# Step 7: web.config
# =====================================================
Write-Log "==> 7/10  web.config (リバプロ設定) 配置" "STEP"
$webConfig = @"
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="ReverseProxyToInquira" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:$BackendPort/{R:1}" />
          <serverVariables>
            <set name="HTTP_X_FORWARDED_PROTO" value="https" />
            <set name="HTTP_X_FORWARDED_HOST" value="{HTTP_HOST}" />
          </serverVariables>
        </rule>
      </rules>
    </rewrite>
    <security>
      <requestFiltering>
        <requestLimits maxAllowedContentLength="1073741824" />
      </requestFiltering>
    </security>
  </system.webServer>
</configuration>
"@
Set-Content -Path "$SitePath\web.config" -Value $webConfig -Encoding UTF8
Write-Log "    web.config 配置完了" "OK"

# =====================================================
# Step 8: ARR Enable Proxy
# =====================================================
Write-Log "==> 8/10  ARR Enable Proxy" "STEP"
$appcmd = "$env:windir\System32\inetsrv\appcmd.exe"
& $appcmd set config -section:system.webServer/proxy /enabled:"True" /commit:apphost | Out-Null
Write-Log "    ARR プロキシ有効化" "OK"

# OAuth など外部 IdP へのリダイレクトを壊さないため、
# Location ヘッダのホスト名書き換え (既定 True) を無効化する。
# これを忘れると Google OAuth リダイレクト時に
# https://accounts.google.com/... が https://<自分のホスト>/... に
# 書き換わってログインが 404 で落ちる。
& $appcmd set config -section:system.webServer/proxy /reverseRewriteHostInResponseHeaders:"False" /commit:apphost | Out-Null
Write-Log "    Location ヘッダ書き換え無効化 (OAuth 互換)" "OK"

& $appcmd set config -section:system.webServer/rewrite/allowedServerVariables /+"[name='HTTP_X_FORWARDED_PROTO']" /commit:apphost 2>$null | Out-Null
& $appcmd set config -section:system.webServer/rewrite/allowedServerVariables /+"[name='HTTP_X_FORWARDED_HOST']" /commit:apphost 2>$null | Out-Null
Write-Log "    allowedServerVariables 設定完了" "OK"

# =====================================================
# Step 9: IIS 再起動
# =====================================================
Write-Log "==> 9/10  IIS 再起動" "STEP"
& iisreset /restart | Out-Null
Write-Log "    iisreset 完了" "OK"
Start-Sleep -Seconds 5

# =====================================================
# Step 10: 動作確認
# =====================================================
Write-Log "==> 10/10  動作確認" "STEP"

try {
    $localCheck = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/healthz" -UseBasicParsing -TimeoutSec 10
    if ($localCheck.StatusCode -eq 200) {
        Write-Log "    バックエンド (Inquira) 応答 OK" "OK"
    }
} catch {
    Write-Log "    バックエンド (Inquira) が応答しません。先に Inquira を起動してください。" "WARN"
    Write-Log "    起動コマンド: & `"`$env:USERPROFILE\Inquira\start_inquira.bat`""
}

try {
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $httpsCheck = Invoke-WebRequest -Uri "https://$Hostname/healthz" -UseBasicParsing -TimeoutSec 15
    if ($httpsCheck.StatusCode -eq 200) {
        Write-Log "    HTTPS 経由で応答取得 OK (https://$Hostname/healthz)" "OK"
    }
} catch {
    Write-Log "    HTTPS チェック失敗: $($_.Exception.Message)" "WARN"
    Write-Log "    手動で確認: https://$Hostname/healthz" "WARN"
}

# =====================================================
# 完了メッセージ
# =====================================================
Write-Log ""
Write-Log "========= セットアップ完了 =========" "OK"
Write-Log ""
Write-Log "■ 次にやること (3 ステップ):"
Write-Log ""
Write-Log "[1] Google Cloud Console に承認済みリダイレクト URI を追加:"
Write-Log "    https://$Hostname/auth/callback"
Write-Log "    URL: https://console.cloud.google.com/apis/credentials"
Write-Log ""
Write-Log "[2] Inquira の .env を更新:"
Write-Log "    notepad `$env:USERPROFILE\Inquira\.env"
Write-Log "    -> GOOGLE_REDIRECT_URI=https://$Hostname/auth/callback"
Write-Log ""
Write-Log "[3] Inquira 再起動:"
Write-Log "    Get-Process python | Stop-Process -Force"
Write-Log "    & `"`$env:USERPROFILE\Inquira\start_inquira.bat`""
Write-Log ""
Write-Log "■ 動作確認:"
Write-Log "    ブラウザで https://$Hostname/ を開く"
Write-Log ""
Write-Log "■ 失敗したら:"
Write-Log "    ログ: $LogFile を共有してください"
Write-Log "    元に戻す: .\setup_iis_reverse_proxy.ps1 -Cleanup"
Write-Log ""
