# Inquira 死活監視 (watchdog)

`scripts/inquira_watchdog.ps1` を Inquira サーバーに登録すると、**社員から「サイトにアクセスできません」と言われる前に** 提供側へ通知が届きます。

---

## 仕組み

```
[Inquira サーバー] ── 5 分おき ──▶ 4 層チェック
                                   │
                    全層 OK ───────┼──▶ healthchecks.io に ping
                    どこか NG ─────┼──▶ healthchecks.io に /fail (失敗内容つき) ──▶ 即メール通知
   サーバー停止 / タスク停止 ───────┘    (ping が途絶)  ──▶ 猶予時間後にメール通知
```

| 層 | 確認内容 | NG 時に疑うもの |
|---|---|---|
| アプリ | `http://127.0.0.1:8000/healthz` | uvicorn 停止 (再起動後ログオンなし、プロセス異常終了) |
| DNS | FQDN がこのサーバーの IP に解決されるか | サーバー IP 変更 (DHCP)、A レコード削除・誤り |
| IIS | 443/TCP 待ち受け | IIS / サイト停止、W3SVC サービス停止 |
| HTTPS | `https://<FQDN>/healthz` (サーバー自身から) | バインド・証明書期限切れ・ARR 設定 |

> 社内 LAN のサーバーはクラウドから監視できないため、**サーバー側から外へ ping を送る方式** (ハートビート) にしています。
> サーバーが丸ごと落ちても「ping が来ない」ことで検知できます。

---

## セットアップ (初回 10 分)

### 1. healthchecks.io でチェックを作成 (無料枠: 20 チェック)

1. https://healthchecks.io にサインアップ
2. 「Add Check」→ Period: **5 分**, Grace: **10 分**
3. 表示される ping URL (`https://hc-ping.com/<uuid>`) を控える
4. Integrations でメール (必要ならスマホ通知・Slack 等) を設定

### 2. サーバーで登録

```powershell
cd "$env:USERPROFILE\Inquira\scripts"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\inquira_watchdog.ps1 -Fqdn <INQUIRA_HOST>.<CUSTOMER_DOMAIN> `
    -HeartbeatUrl https://hc-ping.com/<uuid> -AutoRestart -Install
```

`-Install` は登録後に 1 回実行し、結果を表示します。healthchecks.io 側が「up」になれば完了。

### 3. 解除

```powershell
.\inquira_watchdog.ps1 -Uninstall
```

---

## 運用メモ

- ログ: `%USERPROFILE%\Inquira_Watchdog.log` (1 MB でローテート)
- `-AutoRestart` で uvicorn 停止時は自動再起動します。復旧できても「落ちていた」旨は通知されます。
- タスクは「ログオン中のみ実行」で登録されます (管理者権限不要のため)。**サーバー再起動後に誰もログオンしていないと ping が途絶 → 通知** が届くので、ログオンして `start_inquira.bat` を起動してください。
  恒久対策はタスクスケジューラでの SYSTEM 起動 (要管理者権限)。
- 社員 PC 側の問題 (PC の DNS 設定、VPN 未接続、プロキシ) はサーバーからは検知できません。通知が来ていないのに「つながらない」と言われたら、まず利用者側の経路を疑ってください。

---

## 「このサイトにアクセスできません」の切り分け

ブラウザのこの表示は **IIS まで到達できていない** ことを意味します (IIS に届いて uvicorn が落ちている場合は `502 Bad Gateway` になる)。

| 社員 PC で実行 | 結果 → 原因 |
|---|---|
| `nslookup <FQDN>` | 解決できない → 社内 DNS レコード / PC の DNS 設定 |
| 〃 | サーバーと違う IP → A レコード誤り or サーバー IP 変更 |
| `Test-NetConnection <FQDN> -Port 443` | False → サーバー停止 / IIS 停止 / ファイアウォール |
| 上記すべて OK | ブラウザのエラーコード (`ERR_...`) を確認 |

サーバー側では `.\inquira_watchdog.ps1 -Fqdn <FQDN>` を 1 回実行すれば同じ切り分けが一度にできます。
