# IIS リバースプロキシ設定 ご依頼書

> **宛先**: A社 IT 部門 ご担当者様
> **依頼者**: A社 Inquira 管理者
> **所要時間**: 30 分（IIS 操作に慣れていれば 15 分）
> **管理者権限**: 必要（IIS 設定変更のため）

---

## 1. 依頼の概要

Inquira（社内向け FAQ Q&A サービス）が現在 A社サーバー内で動作しています。
これを **社員のブラウザから `https://faq.a-corp.jp/` で利用可能**にするため、
**IIS のリバースプロキシ設定**をお願いいたします。

### 現状

- Inquira 本体は A社サーバー上で `http://localhost:8000/` で稼働中
- 動作確認済み（サーバー上のブラウザからアクセス可能）
- 社員の PC からは現状アクセス不可（公開 URL がないため）

### この設定で実現すること

```
   社員のPC                         A社サーバー
   ┌──────────┐                     ┌─────────────────────────┐
   │ ブラウザ  │  HTTPS              │  ┌──────────┐            │
   │          │ ──────────────────►│  │ IIS       │  ローカル │
   │          │ faq.a-corp.jp       │  │ (これを   ├─────►8000│
   │          │                     │  │ 設定する)  │            │
   └──────────┘                     │  └──────────┘            │
                                    │      ▼                    │
                                    │   ┌────────┐              │
                                    │   │Inquira │              │
                                    │   │動作中  │              │
                                    │   └────────┘              │
                                    └─────────────────────────┘
```

---

## 2. 事前に確認・準備いただきたい項目

| # | 項目 | 確認方法・対応 |
|---|---|---|
| 1 | IIS がインストール済み | サーバーマネージャー →「役割の追加」で「Web サーバー (IIS)」がインストール済みか確認 |
| 2 | IIS の **URL Rewrite** モジュール | https://www.iis.net/downloads/microsoft/url-rewrite からインストール |
| 3 | IIS の **ARR (Application Request Routing)** モジュール | https://www.iis.net/downloads/microsoft/application-request-routing からインストール |
| 4 | サーバーの SSL 証明書 (`faq.a-corp.jp` 用) | 既存社内 CA でも Let's Encrypt でも可。未取得なら別途ご相談 |
| 5 | 社内 DNS で `faq.a-corp.jp` → サーバー IP の登録 | 社内 DNS 管理画面で、A社サーバーの IP（Inquira 起動時のログに表示済み）に向ける |
| 6 | サーバーの 443 ポートを社内に公開 | Windows Firewall / 社内ファイアウォール設定 |

⚠ 上記 2 / 3 のモジュールが未インストールでも Inquira は動いていますが、本設定には必要です。

---

## 3. 設定手順

### 3-1. IIS で新しいサイトを作る

1. **IIS マネージャー** を起動（スタートメニュー →「IIS マネージャー」）
2. 左ペインで A社サーバーを展開 →「**サイト**」を右クリック → **「Web サイトの追加」**
3. 以下を入力：

   | 項目 | 値 |
   |---|---|
   | サイト名 | `Inquira` |
   | 物理パス | `C:\inetpub\inquira-site` （存在しなければ作成） |
   | バインド種類 | `https` |
   | ホスト名 | `faq.a-corp.jp` |
   | ポート | `443` |
   | SSL 証明書 | 事前に IIS に登録した `faq.a-corp.jp` 用証明書 |

4. **「OK」** を押す

### 3-2. リバースプロキシ設定ファイルを置く

`C:\inetpub\inquira-site\` フォルダ（存在しなければ作成）の中に
**`web.config`** というファイル名で以下の内容を保存：

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

> ⚠ `<rewrite>` セクションが「未認識」エラーになる場合は、URL Rewrite モジュールが未インストールです（事前準備の項目 2）。

### 3-3. ARR のプロキシ機能を ON にする

1. IIS マネージャー → 一番上の **サーバー名（A社サーバー名）** を選択
2. 中央ペインの **「Application Request Routing キャッシュ」** をダブルクリック
3. 右側の **「Server Proxy Settings...」** をクリック
4. **「Enable proxy」** にチェックを入れて **「Apply」**

> この設定はサーバー全体に効きます。1 回設定すれば以降の Inquira 再起動でも有効。

### 3-4. 設定の反映

IIS マネージャーで `Inquira` サイトを右クリック → **「再起動」**、もしくは PowerShell で：

```powershell
iisreset
```

---

## 4. 動作確認

### 4-1. サーバー上で確認

```powershell
# Inquira 本体が稼働中であること（変わらず）
Invoke-WebRequest http://127.0.0.1:8000/healthz

# IIS 経由でアクセスできること
Invoke-WebRequest https://faq.a-corp.jp/healthz -SkipCertificateCheck
# → {"ok": true} が返れば OK
```

### 4-2. 別 PC のブラウザから確認

社内 LAN の別 PC で `https://faq.a-corp.jp/` を開く：

- SSL の鍵マークが表示される（証明書 OK）
- Google ログイン画面が表示される

---

## 5. 完了したらお知らせいただきたいこと

設定完了後、以下を Inquira 管理者（依頼者）にご連絡ください：

- ✅ IIS 設定完了の旨
- 動作確認時のエラーがあれば内容

その後、Inquira 管理者が `.env` の `GOOGLE_REDIRECT_URI` を更新します
（`http://localhost:8000/auth/callback` → `https://faq.a-corp.jp/auth/callback`）。

---

## 6. トラブル対応

### 502 Bad Gateway

- ARR の「Enable proxy」がオフ → 3-3 を再確認
- Inquira 本体が止まっている → `Invoke-WebRequest http://127.0.0.1:8000/healthz` で確認、止まっていれば `%USERPROFILE%\Inquira\start_inquira.bat` で再起動

### 404 Not Found

- IIS の `Inquira` サイトの物理パスが間違っている、または `web.config` が無い
- 3-1 と 3-2 を再確認

### 「`<rewrite>` セクションが認識できません」

- URL Rewrite モジュール未インストール → 事前準備の項目 2

### SSL エラー

- バインドの SSL 証明書が `faq.a-corp.jp` 以外になっている
- 証明書の有効期限切れ
- 中間証明書が組み込まれていない

---

## 7. 参考: 同等の設定（nginx の場合）

IIS の代わりに **nginx** を使う場合は、以下の設定ファイルで同じ動作になります：

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

---

## サポート窓口

不明点・トラブル時は Inquira 提供側（弊社）まで。Inquira 管理者経由でご連絡ください。
