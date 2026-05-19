# データ保存ガイド

> 想定読者: 導入企業の情シス担当者・運用担当者
> 内容: Inquira が「何を」「どこに」保存し、どう設定変更・バックアップするか

---

## 🔒 重要な前提

**Inquira は完全ローカル保存型**です。

- ✅ ファイルもログも**すべて Inquira を動かしているサーバ内に保存**
- ✅ クラウドにデータが上がるのは **Anthropic API への質問内容のみ**（マスキング済み）
- ❌ 外部 DB なし・外部ストレージなし・SaaSデータベースなし
- ❌ Inquira 開発元（あなたの会社）にはデータが送信されない

---

## 📂 保存場所の全体マップ

デフォルトでは Inquira インストールディレクトリ配下の `./data/` に保存：

```
faq_platform/
├── data/
│   ├── faq_master/             ← 取り込み済みドキュメントの整形済みコピー
│   │   ├── VPN接続マニュアル.md
│   │   ├── 経費精算ルール.md
│   │   └── ...
│   ├── raw/                    ← アップロード時の生ファイル（任意保管）
│   ├── audit/                  ← 監査ログ（日次ローテーション）
│   │   ├── audit-2026-05-18.jsonl
│   │   ├── audit-2026-05-19.jsonl
│   │   └── ...
│   ├── index.json              ← 検索インデックス（自動再生成可）
│   ├── embeddings.npz          ← Embedding キャッシュ（自動再生成可）
│   ├── feedback_scores.json    ← 👍/👎 学習スコア
│   └── org_settings.json       ← 管理画面で編集した組織情報
└── .env                        ← APIキー・OAuth情報（最重要機密）
```

---

## 📊 保存先一覧（詳細）

| # | データ種別 | デフォルトパス | 環境変数 | 容量目安 | バックアップ |
|---|---|---|---|---|---|
| 1 | FAQマスター（整形済み） | `./data/faq_master/` | `FAQ_MASTER_DIR` | 文書数 × 数KB | **必須** |
| 2 | 検索インデックス | `./data/index.json` | `INDEX_PATH` | 文書数 × 10KB | 不要（自動再生成） |
| 3 | 監査ログ | `./data/audit/` | `AUDIT_LOG_DIR` | 月 100MB〜1GB | **必須**（法令保全） |
| 4 | フィードバック学習 | `./data/feedback_scores.json` | `FEEDBACK_PATH` | 数KB〜数百KB | 推奨 |
| 5 | 組織情報設定 | `./data/org_settings.json` | `ORG_SETTINGS_PATH` | 1KB未満 | 推奨 |
| 6 | アップロード生ファイル | `./data/raw/` | `RAW_UPLOAD_DIR` | 文書数 × ファイルサイズ | 任意 |
| 7 | Embeddingキャッシュ | `./data/embeddings.npz` | `EMBEDDING_CACHE_PATH` | 文書数 × 数MB | 不要（自動再生成） |
| 8 | .env 設定ファイル | `./.env` | — | 数KB | **最重要・別管理** |

---

## 🛠 保存場所を変更する

すべての保存先は `.env` ファイルで上書き可能です。

### 例1: データをすべて外付け SSD に置く（Mac）

```env
FAQ_MASTER_DIR=/Volumes/SSD1/inquira/faq_master
INDEX_PATH=/Volumes/SSD1/inquira/index.json
AUDIT_LOG_DIR=/Volumes/SSD1/inquira/audit
FEEDBACK_PATH=/Volumes/SSD1/inquira/feedback_scores.json
ORG_SETTINGS_PATH=/Volumes/SSD1/inquira/org_settings.json
RAW_UPLOAD_DIR=/Volumes/SSD1/inquira/raw
EMBEDDING_CACHE_PATH=/Volumes/SSD1/inquira/embeddings.npz
```

### 例2: Windows で D ドライブに置く

```env
FAQ_MASTER_DIR=D:\InquiraData\faq_master
INDEX_PATH=D:\InquiraData\index.json
AUDIT_LOG_DIR=D:\InquiraData\audit
FEEDBACK_PATH=D:\InquiraData\feedback_scores.json
ORG_SETTINGS_PATH=D:\InquiraData\org_settings.json
RAW_UPLOAD_DIR=D:\InquiraData\raw
EMBEDDING_CACHE_PATH=D:\InquiraData\embeddings.npz
```

### 例3: ネットワークドライブ (NAS) に置く

```env
FAQ_MASTER_DIR=/mnt/nas/inquira/faq_master
INDEX_PATH=/mnt/nas/inquira/index.json
AUDIT_LOG_DIR=/mnt/nas/inquira/audit
# ... 他も同様
```

> ⚠ **注意点**: NAS 経由は読み書きが遅いです。**起動時のインデックス再構築が数秒〜数十秒余計にかかる**ことがあります。

### 設定変更後の手順

1. `.env` を編集して保存
2. Inquira サーバを **Ctrl+C で停止 → 再起動**
3. 起動ログに新しいパスが表示されることを確認
4. 既存データを新しい場所に**手動で移動またはコピー**

```bash
# 例: ./data/ から /mnt/nas/inquira/ に移動
mv ./data/* /mnt/nas/inquira/
```

---

## 💾 バックアップ運用

### 必須バックアップ対象（消えると復旧不可）

| 項目 | 理由 |
|---|---|
| `data/faq_master/` | 取り込み済み文書。アップロード元から再取得できない可能性 |
| `data/audit/` | 監査ログ。**法令保全の対象になる場合あり** |
| `.env` | APIキー・OAuth secret。Anthropic Console から再発行可能だが手間 |

### 推奨バックアップ対象

| 項目 | 理由 |
|---|---|
| `data/feedback_scores.json` | 👍/👎 で学習した検索精度を保持 |
| `data/org_settings.json` | 管理画面で編集した組織情報 |
| `data/raw/` | 原本ファイル（再アップロード可なら不要） |

### 不要バックアップ対象（自動再生成）

| 項目 | 再生成方法 |
|---|---|
| `data/index.json` | Inquira 起動時に `faq_master/` から自動再構築 |
| `data/embeddings.npz` | 起動時に `faq_master/` から自動再エンコード |

---

### バックアップスクリプト（標準同梱）

```bash
# Mac / Linux / Git Bash (Windows)
./scripts/backup.sh
# → ./backups/inquira-backup-YYYYMMDD-HHMMSS.tar.gz が作られる
```

含まれるもの: 上記の「必須」「推奨」全部 + `.env`（注意: 機密情報）

### 定期バックアップ（cron / タスクスケジューラ）

#### Mac / Linux: cron

毎晩 2:00 にバックアップ + 7日以上前を自動削除：

```bash
crontab -e
```
追記：
```cron
0 2 * * * cd /path/to/faq_platform && ./scripts/backup.sh /backup/destination \
    && find /backup/destination -name 'inquira-backup-*.tar.gz' -mtime +7 -delete
```

#### Windows: タスクスケジューラ

1. タスクスケジューラを起動
2. 「基本タスクの作成」→ 「Inquira バックアップ」
3. トリガー: 毎日 2:00
4. 操作: プログラムの開始
   - プログラム: `C:\Program Files\Git\bin\bash.exe`
   - 引数: `-c "cd /c/inquira && ./scripts/backup.sh /d/backup"`

### リストア

```bash
./scripts/restore.sh ./backups/inquira-backup-20260518-020000.tar.gz
```

- 既存データを上書きするため、確認プロンプトが出ます
- 復元前に念のため現状もスナップショットされます

---

## 🗄 容量見積もり

### 小規模（部門単位、月 3,000質問・文書 50本）

| 項目 | 月間増加 | 1年で |
|---|---|---|
| `faq_master/` | ~ 200KB（追加文書ぶん） | 数MB |
| `audit/` | ~ 50MB（質問1件あたり 1〜2KB） | 約 600MB |
| `feedback_scores.json` | ~ 1KB | ~ 数KB |
| **合計** | **約 50MB/月** | **約 600MB/年** |

→ **SSD 5GB あれば 5年持つ**

### 中規模（全社展開、月 20,000質問・文書 200本）

| 項目 | 月間増加 | 1年で |
|---|---|---|
| `faq_master/` | ~ 1MB | 約 10MB |
| `audit/` | ~ 300MB | 約 3.6GB |
| **合計** | **約 300MB/月** | **約 3.6GB/年** |

→ **SSD 20GB あれば 5年持つ**

### 大規模（月 100,000質問・文書 1,000本）

| 項目 | 月間増加 | 1年で |
|---|---|---|
| `faq_master/` | ~ 5MB | 約 60MB |
| `audit/` | ~ 1.5GB | 約 18GB |
| **合計** | **約 1.5GB/月** | **約 18GB/年** |

→ **SSD 100GB を推奨**

---

## 🧹 古い監査ログのクリーンアップ

監査ログは日次ローテーションされ、`audit-YYYY-MM-DD.jsonl` 形式で保存されます。
法令保全期間（一般的に 3〜5年）を過ぎたものは削除して構いません。

```bash
# 90日より古い監査ログを削除
find ./data/audit -name 'audit-*.jsonl' -mtime +90 -delete
```

```powershell
# Windows PowerShell: 90日より古いものを削除
Get-ChildItem .\data\audit\audit-*.jsonl |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-90) } |
  Remove-Item
```

---

## 🔐 セキュリティ上の注意

### ファイル権限

`./data/` 配下は **Inquira を動かすOSユーザーのみが読み書きできる権限** に設定してください。

```bash
# Mac / Linux
chmod 700 ./data
chmod 600 ./.env
```

```powershell
# Windows PowerShell（管理者）
$acl = Get-Acl .\data
$acl.SetAccessRuleProtection($true, $false)  # 継承を切る
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "$env:USERNAME","FullControl","ContainerInherit,ObjectInherit","None","Allow")
$acl.AddAccessRule($rule)
Set-Acl .\data $acl
```

### 暗号化

ディスク全体の暗号化を推奨：
- Mac: **FileVault** を有効化（システム環境設定 → セキュリティとプライバシー）
- Windows: **BitLocker** を有効化（Pro エディション以上）
- Linux: **LUKS** または **eCryptfs**

### バックアップ先の暗号化

`./backups/` を NAS / クラウドに転送する場合は、必ず暗号化して送信：

```bash
# tar.gz を更に GPG で暗号化
gpg --symmetric --cipher-algo AES256 ./backups/inquira-backup-*.tar.gz
# → .gpg ファイルを NAS/Dropbox 等へ
```

---

## 🚨 トラブルシューティング

### 「ディスク容量不足」エラー

```bash
# data/ の使用量を確認
du -sh ./data/*
```

`audit/` が肥大化していることが多いです。古いログを削除：
```bash
find ./data/audit -name 'audit-*.jsonl' -mtime +180 -delete
```

### インデックスが壊れた疑い

```bash
# インデックスとEmbeddingキャッシュを削除 → 起動時に自動再構築
rm ./data/index.json ./data/embeddings.npz
./scripts/demo_company.sh
```

### ファイル権限エラー（書き込み不可）

```bash
# 所有者を Inquira 実行ユーザーに修正
sudo chown -R $(whoami) ./data
chmod -R u+rwX ./data
```

### 「組織情報が保存されない」

`ORG_SETTINGS_PATH` の親ディレクトリへの書き込み権限を確認：
```bash
ls -la $(dirname ./data/org_settings.json)
```

---

## 📖 関連ドキュメント

- [`docs/setup_for_admin.md`](./setup_for_admin.md) — 管理者セットアップ全体
- [`docs/setup_guide_mac.md`](./setup_guide_mac.md) — Mac セットアップ
- [`docs/setup_guide_windows.md`](./setup_guide_windows.md) — Windows セットアップ
- [`docs/api_cost_analysis.md`](./api_cost_analysis.md) — APIコスト試算
- [`docs/legal/`](./legal/) — 利用規約・プライバシーポリシー雛形
- [`scripts/backup.sh`](../scripts/backup.sh) — バックアップスクリプト
- [`scripts/restore.sh`](../scripts/restore.sh) — リストアスクリプト

---

最終更新: 2026-05-19
