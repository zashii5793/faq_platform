# 社内 DNS への A レコード追加 ご依頼書

> **宛先**: A社 AD 管理者（社内インフラ運用ご担当）
> **依頼者**: A社 Inquira 運用担当
> **所要時間**: AD 管理者の作業は **5 分以内**
> **管理者権限**: 必要（社内 DNS サーバーへのアクセス権限）

---

## 1. 依頼概要

社内 FAQ サービス（**Inquira**）を社員 PC から利用できるようにするため、
社内 DNS サーバーへの **A レコード 1 件の追加** をお願いいたします。

| 項目 | 値 |
|---|---|
| ホスト名（FQDN） | `inquira.<社内ドメイン>` |
| 解決先 IP | `<INQUIRA_SERVER_IP>` （Inquira サーバー） |
| ゾーン | 社内ドメインの前方参照ゾーン |
| 用途 | 社内 LAN 限定の Q&A サービス（外部公開なし） |
| 外向き通信 | A社サーバー → Anthropic API（HTTPS）のみ |

---

## 2. 何のために必要か

```
社員のノート PC                    A社サーバー
    │  ① http://inquira.<社内ドメイン>:8000/
    │     にアクセス
    ▼
社内 DNS (<DNS_SERVER_IP>)
    │  ② 「inquira.<社内ドメイン> ってどこ？」
    │  ③ 「<INQUIRA_SERVER_IP> だよ」 ←★ ココの A レコードが必要
    ▼
A社サーバー (<INQUIRA_SERVER_IP>)
    │ ④ Inquira が応答 (Web 画面)
    ▼
社員のノート PC
```

A レコードがないと、社員のブラウザが Inquira サーバーの場所を見つけられず、社員から利用できません。

---

## 3. 作業手順（GUI）

社内 DNS サーバーで操作する想定。リモート操作の場合は適宜読み替えてください。

### Step 1. DNS マネージャーを起動

スタート → 検索ボックスに `dns` → **「DNS マネージャー」**

### Step 2. ゾーンを選択

左ペインで：
```
DNS
└─ <DNS サーバー名>
   └─ 前方参照ゾーン
      └─ <社内ゾーン名>   ← クリック
```

### Step 3. A レコードを追加

1. 右ペインの空白部分を右クリック → **「新しいホスト (A or AAAA)」**
2. ダイアログに入力：

   | 項目 | 値 |
   |---|---|
   | 名前 | **`inquira`** |
   | IP アドレス | **`<INQUIRA_SERVER_IP>`** |
   | 関連付けられた PTR レコードを作成 | チェックなしで OK |

3. **「ホストの追加」** → **OK** → **「完了」**

---

## 4. 作業手順（PowerShell — GUI でなくコマンドで済ませたい場合）

DNS サーバー上、または DNS 管理権限のある PC で：

```powershell
Add-DnsServerResourceRecordA `
    -ZoneName "<社内ドメイン>" `
    -Name "inquira" `
    -IPv4Address "<INQUIRA_SERVER_IP>"
```

確認：

```powershell
Get-DnsServerResourceRecord -ZoneName "<社内ドメイン>" -Name "inquira"
```

---

## 5. 動作確認（依頼者側で実施）

設定完了のご連絡をいただいたら、依頼者側で以下を確認します：

```powershell
nslookup inquira.<社内ドメイン>
# 期待: Address: <INQUIRA_SERVER_IP>
```

---

## 6. ご対応後にご連絡いただきたい内容

- ✅ A レコード追加完了
- 設定時のエラーがあれば内容

ご連絡をいただいたら、Inquira 側の設定（OAuth リダイレクト URI 追加、`.env` 更新、Inquira 再起動）を続けて行います。

---

## 7. 補足: セキュリティ

| 観点 | 内容 |
|---|---|
| 外部公開 | なし。社内 LAN 限定 |
| 外向き通信 | Inquira サーバーから `api.anthropic.com`（AI 回答生成）と `accounts.google.com`（社員ログイン認証）のみ |
| データ保存先 | 社内ファイルサーバー（UNC 共有）配下。社外への送信なし |
| 認証 | Google ログイン（事前登録した社員 Gmail のみ通過） |

---

## サポート窓口

不明点があれば Inquira 運用担当（依頼者）までご連絡ください。
