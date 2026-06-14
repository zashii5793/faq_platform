#
# Inquira .env 再生成スクリプト
#
# 二重エンコードや文字化けで壊れた .env を、クリーンな状態で作り直します。
# 対話で実値を入力すれば、UTF-8 BOM 無しで正しい .env を書き出します。
#
# 使い方:
#   PowerShell で:
#     (New-Object System.Net.WebClient).DownloadFile("https://raw.githubusercontent.com/zashii5793/faq_platform/claude/add-roadmap-docs-RmQNp/scripts/recover_env.ps1", "C:\Temp\recover_env.ps1")
#     cd C:\Temp
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#     .\recover_env.ps1
#
# やること:
#   1. 既存 .env をバックアップ (.env.broken.YYYYMMDD-HHMMSS)
#   2. 対話で 5 項目を入力 (新 API キー、OAuth、Redirect URI 等)
#   3. SESSION_SECRET を新規生成
#   4. .env を UTF-8 BOM 無しで書き出し

param(
    [string]$EnvPath = "%USERPROFILE%\Inquira\.env",
    [string]$Hostname = "inquira.example.local",
    [string]$DataShare = "//fileserver/share/システム/inquira_share"
)

# 既存 .env のバックアップ
if (Test-Path $EnvPath) {
    $ts = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = "$EnvPath.broken.$ts"
    Copy-Item $EnvPath $backup -Force
    Write-Host ""
    Write-Host "既存の .env を退避: $backup" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " Inquira .env 再生成" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "新しい実値を入力してください。" -ForegroundColor White
Write-Host "(入力中の文字は表示されます。後ろから誰かに見られないよう注意)" -ForegroundColor DarkGray
Write-Host ""

# 1. Anthropic API キー
Write-Host "[1/4] 新しい Anthropic API キー (sk-ant-... で始まる):" -ForegroundColor Cyan
$anthropic = Read-Host
while ([string]::IsNullOrWhiteSpace($anthropic) -or -not $anthropic.StartsWith("sk-ant-")) {
    Write-Host "  -> sk-ant- で始まるキーを入力してください" -ForegroundColor Red
    $anthropic = Read-Host
}

# 2. Google Client ID
Write-Host ""
Write-Host "[2/4] Google Client ID (...apps.googleusercontent.com):" -ForegroundColor Cyan
$google_id = Read-Host
while ([string]::IsNullOrWhiteSpace($google_id) -or -not $google_id.EndsWith("apps.googleusercontent.com")) {
    Write-Host "  -> apps.googleusercontent.com で終わる ID を入力してください" -ForegroundColor Red
    $google_id = Read-Host
}

# 3. Google Client Secret
Write-Host ""
Write-Host "[3/4] 新しい Google Client Secret (GOCSPX-... で始まる):" -ForegroundColor Cyan
$google_secret = Read-Host
while ([string]::IsNullOrWhiteSpace($google_secret) -or -not $google_secret.StartsWith("GOCSPX-")) {
    Write-Host "  -> GOCSPX- で始まるシークレットを入力してください" -ForegroundColor Red
    $google_secret = Read-Host
}

# 4. ALLOWED_EMAILS
Write-Host ""
Write-Host "[4/4] 管理者の Gmail (カンマ区切り、複数可):" -ForegroundColor Cyan
Write-Host "  例: admin1@gmail.com,admin2@gmail.com" -ForegroundColor DarkGray
$emails = Read-Host
if ([string]::IsNullOrWhiteSpace($emails)) {
    Write-Host "  -> 空のため、暫定で 'admin@example.com' を入れます。後で notepad で書き換えてください" -ForegroundColor Yellow
    $emails = "admin@example.com"
}

# SESSION_SECRET 自動生成
$secret = -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })

# .env の中身を組み立て
$envContent = "PRODUCT_NAME=Inquira`r`n"
$envContent += "ORG_NAME=A株式会社`r`n"
$envContent += "ASSISTANT_ROLE=社内ヘルプデスク`r`n"
$envContent += "`r`n"
$envContent += "ANTHROPIC_API_KEY=$anthropic`r`n"
$envContent += "CLAUDE_MODEL=claude-sonnet-4-6`r`n"
$envContent += "`r`n"
$envContent += "GOOGLE_CLIENT_ID=$google_id`r`n"
$envContent += "GOOGLE_CLIENT_SECRET=$google_secret`r`n"
$envContent += "GOOGLE_REDIRECT_URI=https://$Hostname/auth/callback`r`n"
$envContent += "`r`n"
$envContent += "ALLOWED_DOMAIN=`r`n"
$envContent += "ALLOWED_EMAILS=$emails`r`n"
$envContent += "`r`n"
$envContent += "SESSION_SECRET=$secret`r`n"
$envContent += "`r`n"
$envContent += "DEMO_MODE=false`r`n"
$envContent += "HOST=0.0.0.0`r`n"
$envContent += "PORT=8000`r`n"
$envContent += "`r`n"
$envContent += "FAQ_MASTER_DIR=$DataShare/faq_master`r`n"
$envContent += "INDEX_PATH=$DataShare/index.json`r`n"
$envContent += "AUDIT_LOG_DIR=$DataShare/audit`r`n"
$envContent += "FEEDBACK_PATH=$DataShare/feedback_scores.json`r`n"
$envContent += "ORG_SETTINGS_PATH=$DataShare/org_settings.json`r`n"
$envContent += "RAW_UPLOAD_DIR=$DataShare/raw`r`n"
$envContent += "SHARED_QA_META_PATH=$DataShare/shared_qa_meta.json`r`n"
$envContent += "FAQ_CANDIDATES_PATH=$DataShare/faq_candidates.json`r`n"
$envContent += "FAQ_CANDIDATE_SETTINGS_PATH=$DataShare/faq_candidate_settings.json`r`n"
$envContent += "IMPACT_SETTINGS_PATH=$DataShare/impact_settings.json`r`n"
$envContent += "EMBEDDING_CACHE_PATH=$DataShare/embeddings.npz`r`n"

# UTF-8 BOM 無しで書き出し
[System.IO.File]::WriteAllText($EnvPath, $envContent, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host " 完了!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "出力: $EnvPath" -ForegroundColor White
Write-Host "ホスト: https://$Hostname/" -ForegroundColor White
Write-Host ""

# 確認
Write-Host "中身プレビュー (秘匿項目はマスク):" -ForegroundColor Cyan
Get-Content $EnvPath | ForEach-Object {
    if ($_ -match "^(ANTHROPIC_API_KEY|GOOGLE_CLIENT_SECRET|SESSION_SECRET)=") {
        $key = ($_ -split "=", 2)[0]
        Write-Host "  $key=*** (masked)" -ForegroundColor DarkGray
    } else {
        Write-Host "  $_" -ForegroundColor White
    }
}

Write-Host ""
Write-Host "次にやること:" -ForegroundColor Cyan
Write-Host "  1. Google Cloud Console に承認済みリダイレクト URI を追加:"
Write-Host "     https://$Hostname/auth/callback"
Write-Host ""
Write-Host "  2. Inquira を再起動:"
Write-Host "     Get-Process python | Stop-Process -Force"
Write-Host "     & `"`$env:USERPROFILE\Inquira\start_inquira.bat`""
Write-Host ""
Write-Host "  3. 動作確認:"
Write-Host "     Invoke-WebRequest http://127.0.0.1:8000/healthz -TimeoutSec 10 -UseBasicParsing"
Write-Host ""
