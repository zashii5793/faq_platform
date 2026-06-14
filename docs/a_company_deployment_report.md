# Inquira 顧客テナント 導入完了報告書 (テンプレート)

> このファイルはクライアント向けレポートの **テンプレート** です。
> 顧客固有値 (社内ドメイン / IP / 共有パス / Gmail / 証明書 Thumbprint 等) は **絶対にコミットせず**、
> `.private/` 配下にコピーして編集 → PDF 化してクライアントに渡してください。

| 項目 | 内容 |
|---|---|
| 報告日 | `<REPORT_DATE>` |
| 対象 | Inquira (社内 FAQ AI プラットフォーム) |
| 顧客 | `<CUSTOMER_NAME>` |
| 公開 URL | `https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/` |
| 構成 | オンプレ Windows Server + IIS リバプロ (HTTPS) + Google OAuth |
| 状態 | ✅ 本番稼働開始 |

---

## 1. エグゼクティブサマリ

顧客社内に Inquira を **HTTPS / Google OAuth 認証付き** で導入完了しました。
管理者は社内 LAN から `https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/` でアクセスし、登録済み Gmail でログイン可能です。

- ✅ サーバー上に Inquira (Python/FastAPI) 起動
- ✅ 社内 DNS に FQDN (`<INQUIRA_HOST>.<CUSTOMER_DOMAIN>`) 登録
- ✅ IIS リバースプロキシで HTTPS 化 (自己署名証明書)
- ✅ Google OAuth 連携 (管理者数名のホワイトリスト方式)
- ✅ データ保存先を社内ファイルサーバー (`<UNC_SHARE_PATH>`) に統一 (既存バックアップ運用に乗る)

---

## 2. 最終構成

### 2-1. ネットワーク構成図

```
[社員 PC (Edge/Chrome)]
        │  https://<INQUIRA_HOST>.<CUSTOMER_DOMAIN>/
        ▼
[社内 DNS: <AD_SERVER_NAME>]
        │  A レコード解決
        │  <INQUIRA_HOST>.<CUSTOMER_DOMAIN> → <INQUIRA_SERVER_IP>
        ▼
[Inquira サーバー: <INQUIRA_SERVER_IP>]
   ├─ IIS (443/TCP)
   │    ├─ 自己署名 SSL 証明書 (Thumbprint は内部資料のみ管理)
   │    └─ URL Rewrite + ARR (リバースプロキシ)
   │         ↓ http://127.0.0.1:8000/ にフォワード
   │         X-Forwarded-Proto: https
   │         X-Forwarded-Host: <INQUIRA_HOST>.<CUSTOMER_DOMAIN>
   │
   ├─ Inquira (uvicorn / Python 3.11) : 127.0.0.1:8000
   │    └─ Google OAuth 認証 → 管理画面・Q&A 機能
   │
   └─ <UNC_SHARE_PATH>\
        ├─ faq_master/      取り込み済みナレッジ
        ├─ audit/           質問履歴 (監査ログ)
        ├─ raw/             アップロード原本
        ├─ embeddings.npz   ベクトル検索キャッシュ
        ├─ org_settings.json
        ├─ feedback_scores.json
        └─ faq_candidates.json
```

### 2-2. ソフトウェア構成

| 層 | 製品 | バージョン |
|---|---|---|
| OS | Windows Server | 2019 / 2022 |
| Web | IIS | 10.0 |
| Web 拡張 | URL Rewrite / ARR | 3.0 |
| App | Inquira (uvicorn) | 0.x |
| Runtime | Python | 3.11.x |
| AI | Claude (Anthropic) | claude-sonnet-4-6 |
| 認証 | Google OAuth 2.0 | — |

### 2-3. アクセス制御

| 種別 | 設定 |
|---|---|
| 認証方式 | Google OAuth (アカウント選択画面) |
| 許可方式 | ホワイトリスト (`ALLOWED_EMAILS`) |
| 登録済み管理者 | `<N>` 名 (Google Cloud Console テストユーザー登録済み) |
| 将来の全社開放 | `ALLOWED_DOMAIN` 設定 + OAuth 同意画面を本番モードに昇格で可能 |

---

## 3. ここまでの経緯（試行錯誤の総括）

オンプレ環境特有の制約 (Docker 不可 / 管理者権限制限 / 社内 DNS は別管理者) で、いくつかのハマりがありました。最終的に下記の構成で安定運用に到達しました。

### 3-1. 計画変更の流れ

| 当初プラン | 課題 | 採用プラン |
|---|---|---|
| クラウド SaaS (Render) | 「データを社外に出したくない」 | オンプレに変更 |
| Docker Compose | サーバーで Docker 不可 | ネイティブ Python インストール |
| `http://<IP>:8000/` で運用 | Google OAuth が **IP リダイレクト URI を拒否** | 社内 DNS で FQDN 払い出し |
| HTTP (port 8000) で運用 | OAuth 状態 Cookie が `SameSite=Lax` で破損、Edge から不安定 | **IIS + HTTPS リバプロ** で `https://<FQDN>/` に統一 |
| データはサーバーローカル保存 | 既存バックアップが共有領域のみ | UNC 共有配下に統一 |

### 3-2. 設定段階で発生した問題と恒久対策

| # | 発生事象 | 直接原因 | 恒久対策 (リポジトリ反映済み) |
|---|---|---|---|
| 1 | `install.ps1` の日本語コメントが文字化けし PowerShell パースエラー | UTF-8 BOM なしの `.ps1` を PowerShell 5.1 が Shift-JIS で誤解釈 | スクリプト全てに **UTF-8 BOM** を付けて配布 |
| 2 | `Invoke-WebRequest -OutFile` で GitHub Raw から DL すると BOM が剥がれて再発 | `Invoke-WebRequest` が UTF-8 BOM を捨てる仕様 | 案内コマンドを `(New-Object System.Net.WebClient).DownloadFile(...)` に変更 |
| 3 | OAuth で「アクセスがブロックされました」 | Google Cloud Console の OAuth 同意画面が **テストモード** で対象 Gmail 未登録 | 提供側準備リスト (`deployment_lessons_learned.md`) に明記 |
| 4 | `.env` が破損し起動不可 (文字化け) | 文字コード変換コマンド (`Get-Content -Encoding`) を 2 回かけて二重変換 | **対話入力で `.env` を再生成する `scripts/recover_env.ps1`** を追加 |
| 5 | 旧 Python プロセス残留で古い設定のまま応答 | 再起動時に Stop-Process を忘れた | 再起動手順を `Get-Process python \| Stop-Process -Force` から開始するよう統一 |
| 6 | ブラウザで HTTPS タイムアウト | **DNS A レコードが Inquira サーバーと別マシンの IP** を指していた | `lessons_learned` 登録 + 手順書で「Inquira サーバーの実 IP を必ずダブルチェック」を強調 |
| 7 | Google ログイン後に `{"detail":"Not Found"}` | **IIS ARR の `reverseRewriteHostInResponseHeaders`** (既定 true) が Location ヘッダの `accounts.google.com` を自ホストに書き換えていた | `setup_iis_reverse_proxy.ps1` v2 で **`false` に設定する処理を自動化** (今後の顧客では再発しない) |

### 3-3. 教訓 (次の顧客導入で同じ罠を避ける)

`docs/deployment_lessons_learned.md` の「ハマリポイント TOP 13」に追加済み。特に重要な 3 点:

1. **PowerShell スクリプトは必ず UTF-8 BOM 付きで配布**。BOM なしは Shift-JIS と誤解釈される。
2. **DNS A レコードは Inquira サーバーの実 IP を必ずダブルチェック**。AD 管理者と Inquira 担当者が別の場合、IP を取り違える事故が起きる。
3. **IIS で OAuth プロキシする時は ARR の `reverseRewriteHostInResponseHeaders=false`**。既定の `true` は外部 IdP リダイレクトを壊す。

---

## 4. 残課題と推奨対応

### 4-1. 短期 (1〜2 週間以内)

| # | 課題 | 推奨対応 | 担当 |
|---|---|---|---|
| 1 | 自己署名証明書のブラウザ警告 | 社員 PC の Edge/Chrome では「保護されていない通信」警告が出る。AD のグループポリシーで証明書をルートストアに配布すれば解消 | 顧客 IT 部門 |
| 2 | OAuth 同意画面がテストモード | 100 人を超えるユーザーで使う場合は **本番モードに昇格** が必要 (Google 審査あり) | 提供側 |
| 3 | 管理者の追加 | Google Cloud Console の「テストユーザー」と `.env` の `ALLOWED_EMAILS` の両方に追加 | 提供側 |

### 4-2. 中期 (1〜3 ヶ月)

| # | 課題 | 推奨対応 |
|---|---|---|
| 4 | サーバー再起動時の自動起動 | 現在はスタートアップフォルダ方式 (ログオン依存)。タスクスケジューラ SYSTEM 起動に切り替え (要管理者権限) |
| 5 | バックアップ確認 | `<UNC_SHARE_PATH>` が既存のファイルサーバーバックアップ対象に含まれているか確認 |
| 6 | 監視 / アラート | `https://<FQDN>/healthz` を社内監視に登録 (Zabbix/PRTG 等) |
| 7 | 全社員開放 | `.env` に `ALLOWED_DOMAIN=<CUSTOMER_DOMAIN>` を追加すれば、ホワイトリスト無しで全社員ログイン可能 |

### 4-3. 長期 (運用フェーズ)

| # | 課題 | 推奨対応 |
|---|---|---|
| 8 | ナレッジの継続投入 | 管理画面の「📁 ファイル取り込み」タブから随時追加。社内マニュアル更新時にセットで運用 |
| 9 | FAQ 候補レビュー | 月 1 回、管理画面の「📋 FAQ 候補」タブをレビュー (自動承認モードを ON にすれば省略可) |
| 10 | 工数削減効果の可視化 | 管理画面の「📊 業務インパクト」タブで毎月のレポート生成。経営報告に活用可能 |

---

## 5. 運用手順 (顧客 IT 部門 / 管理者向け)

### 5-1. 健全性チェック

```powershell
# バックエンドが応答するか
Invoke-WebRequest http://127.0.0.1:8000/healthz -UseBasicParsing
# → StatusCode: 200, Content: {"ok":true}

# HTTPS 経由で応答するか
curl.exe -ks https://<FQDN>/healthz
# → {"ok":true}
```

### 5-2. 手動再起動

```powershell
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
& "$env:USERPROFILE\Inquira\start_inquira.bat"
```

### 5-3. 設定変更 (管理者追加など)

`%USERPROFILE%\Inquira\.env` を notepad で開いて編集 → 上記の手順で再起動。

例: 管理者を追加するには:
```
ALLOWED_EMAILS=admin1@example.com,admin2@example.com,新規追加@example.com
```
**かつ Google Cloud Console の OAuth テストユーザーにも同じアドレスを追加**。

### 5-4. ログ確認

| ログ | 場所 |
|---|---|
| Inquira 出力 | `start_inquira.bat` を**フォアグラウンド起動**してコンソールで確認 |
| 質問履歴 (監査) | `<UNC_SHARE_PATH>\audit\audit-YYYY-MM-DD.jsonl` |
| IIS アクセスログ | `C:\inetpub\logs\LogFiles\W3SVC<n>\` |
| IIS セットアップログ | `C:\Inquira_IIS_Setup.log` |

---

## 6. 添付資料 / 関連ドキュメント

| 文書 | 用途 |
|---|---|
| `tenants/<slug>/README.md` | 顧客向け導入手順書 (IT 部門・管理者向け) |
| `scripts/setup_iis_reverse_proxy.ps1` | IIS リバプロ自動セットアップ (v2: ARR 自動修正組み込み済み) |
| `scripts/setup_iis_reverse_proxy_README.md` | 上記スクリプトの使い方 |
| `scripts/recover_env.ps1` | `.env` を対話入力から再生成するレスキュースクリプト |
| `docs/deployment_lessons_learned.md` | 経験を次の顧客導入に活かすための社内ナレッジ |

---

## 7. セキュリティ事項

| 項目 | 状態 |
|---|---|
| API キー (Anthropic) | 顧客用に新規発行、`.env` のみに保管 (Git 管理外) |
| Google OAuth Client Secret | 同上 |
| `.env` ファイル | UNC 共有ではなく **サーバーローカル (`%USERPROFILE%\Inquira\.env`)** に保管 |
| 質問履歴 | 社内ファイルサーバー内に保管 (社外送信されるのは Claude API への質問本文のみ) |
| 監査ログ | `audit-YYYY-MM-DD.jsonl` で全質問・回答・ユーザーを記録 |

> **重要**: トラブルシュート中に Slack/メールで API キー等を共有した場合は、必ず Anthropic Console / Google Cloud Console で **キーをリセット** してください。

---

## 8. 顧客固有値のテンプレート埋め置き

実際にクライアントに渡すレポートでは、以下を実値に置換してください (このファイルでは **絶対に置換せず**、`.private/` で作業)。

| プレースホルダ | 例 (内部用) |
|---|---|
| `<CUSTOMER_NAME>` | 株式会社 ◯◯ |
| `<CUSTOMER_DOMAIN>` | acme.local / acme.co.jp |
| `<INQUIRA_HOST>` | inquira / faq / kb |
| `<INQUIRA_SERVER_IP>` | 192.168.x.x |
| `<AD_SERVER_NAME>` | AD-SERVER xxxx |
| `<UNC_SHARE_PATH>` | `\\fileserver\share\inquira` |
| `<N>` | 管理者人数 |
| `<REPORT_DATE>` | YYYY-MM-DD |

---

**報告者:** 提供側
**承認:** (顧客 IT 部門)
