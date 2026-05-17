# Inquira 管理者セットアップガイド

> 想定読者: 導入企業の情シス・総務担当者
> 前提知識: 基本的な PC 操作・社内 Google Workspace 管理権限
> 所要時間: 初回セットアップ 半日〜2日 / 日常運用 週30分

---

## 目次

1. [これは何ができるツールか](#1-これは何ができるツールか)
2. [必要なもの・確認事項](#2-必要なもの確認事項)
3. [初回セットアップの全体像](#3-初回セットアップの全体像)
4. [文書を取り込む](#4-文書を取り込む)
5. [日常運用：FAQ追加リクエスト対応](#5-日常運用faq追加リクエスト対応)
6. [月次レポート出力（経営層向け）](#6-月次レポート出力経営層向け)
7. [バックアップ運用](#7-バックアップ運用)
8. [トラブルシューティング](#8-トラブルシューティング)
9. [導入支援窓口](#9-導入支援窓口)

---

## 1. これは何ができるツールか

Inquira は「**社内マニュアル・FAQ を AI が代理で答える**」プラットフォームです。

### こんな課題を解決します

| 症状 | Inquira で起こること |
|---|---|
| 同じ質問が情シス・人事・総務に毎日来る | ユーザーが Inquira に聞いて自己解決 |
| 「マニュアルどこにあったっけ？」 | キーワードで一発検索、出典付きで回答 |
| 新人の質問対応で先輩が時間を取られる | マニュアルさえあれば AI が代行 |
| ChatGPT に社内情報を入力するのが怖い | 機密情報は社内サーバから出さない設計 |

### 何ができないか（誤解防止）

- ❌ マニュアルに**書かれていない**ことには答えません（推測しません）
- ❌ AI が学習して賢くなるわけではない（「参照」型）
- ❌ 24時間365日の保守は別途契約が必要

---

## 2. 必要なもの・確認事項

### 必須

- [ ] Google Workspace 契約（社員認証に使います）
- [ ] サーバまたは社内 PC 1台（Mac mini / Linux VM / Windows いずれも可）
  - 推奨: CPU 2コア以上 / メモリ 4GB 以上 / SSD 20GB
- [ ] HTTPS 通信用ドメイン（本番運用時のみ）
- [ ] Anthropic API キー（[取得手順は後述](#21-anthropic-api-キーの取得)）

### あると良い

- [ ] Slack または Microsoft Teams（通知連携、将来対応予定）
- [ ] バックアップ先（外付け SSD / クラウドストレージ）

### 2.1 Anthropic API キーの取得

1. https://console.anthropic.com/ にアクセス（個人 Google アカウントで OK）
2. 右下 **「Plans & Billing」** で支払い方法を登録
3. **「Create Key」** ボタンで API キーを発行
4. キー全文をコピー（**この画面を閉じると二度と全文は見られません**）
5. メモアプリ等に保管 → セットアップ時に `.env` に貼り付け

#### 月額コストの目安（Haiku 4.5 モデル使用時）

| 利用規模 | 月コスト目安 |
|---|---|
| 個人テスト（月 200質問） | ¥80 |
| 部門単位（月 3,000質問） | ¥1,200 |
| 全社展開（月 20,000質問） | ¥8,000 |
| 大企業（月 100,000質問） | ¥40,000 |

> 💡 不安なら Console で **「Monthly spend limit = $20」** を設定。上限超で自動停止します。

---

## 3. 初回セットアップの全体像

```
①サーバ準備（30分）→ ②Inquiraインストール（30分）→ ③.env設定（10分）
   → ④Google OAuth設定（30分）→ ⑤起動・動作確認（10分）
   → ⑥既存ドキュメント取り込み（半日〜1日）→ ⑦社内告知
```

### ステップ① サーバ準備

#### 選択肢 A: Mac mini を社内 LAN に置く（簡単）
- 既存の Mac mini や常時起動 PC に直接インストール
- 社内 LAN 内のスマホ・PC から `http://192.168.x.x:8000/` でアクセス
- ⚠ 社外からはアクセス不可（VPN 経由なら可）

#### 選択肢 B: クラウド（推奨：本番運用）
- AWS Lightsail（月¥1,000〜）/ Render（無料枠あり）/ さくらクラウド 等
- HTTPS + 独自ドメインで社外からも安全にアクセス可能
- 詳細は別途 [`docs/https_deployment.md`](./https_deployment.md) 参照

### ステップ② Inquira インストール

ターミナルで：
```bash
git clone https://github.com/zashii5793/faq_platform.git
cd faq_platform
```

その後、Python 3.11+ または Docker のいずれかで実行：

**uv 推奨（Python セットアップが速い）**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
```

**Docker 派**
```bash
docker compose up --build
```

### ステップ③ `.env` 設定

```bash
cp .env.example .env
nano .env  # またはお好みのエディタ
```

最低限の設定：
```env
ANTHROPIC_API_KEY=sk-ant-api03-（取得したキー）
CLAUDE_MODEL=claude-haiku-4-5-20251001
ORG_NAME=株式会社○○
ASSISTANT_ROLE=社内ヘルプデスク
SESSION_SECRET=（openssl rand -hex 32 で生成）
```

本番運用なら追加で：
```env
DEMO_MODE=false
GOOGLE_CLIENT_ID=（後述）
GOOGLE_CLIENT_SECRET=（後述）
GOOGLE_REDIRECT_URI=https://inquira.your-domain.co.jp/auth/callback
ALLOWED_DOMAIN=your-domain.co.jp
```

### ステップ④ Google OAuth 設定

詳細は [`docs/google_oauth_setup.md`](./google_oauth_setup.md) に手順あり（所要 30分〜1時間）。

要点：
1. Google Cloud Console でプロジェクト作成
2. OAuth 同意画面を「内部 (Internal)」で設定
3. クライアント ID 発行 → `.env` に貼り付け

### ステップ⑤ 起動・動作確認

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

ブラウザで `http://127.0.0.1:8000/`（または `https://inquira.your-domain.co.jp/`）を開く：
- ✅ ログイン画面が出る → OAuth 連携 OK
- ✅ ログイン後にチャット画面 → 認証 OK
- ⚠ エラーが出たら ➜ [§8 トラブルシューティング](#8-トラブルシューティング)

### ステップ⑥ 既存ドキュメント取り込み

→ [§4 文書を取り込む](#4-文書を取り込む)

### ステップ⑦ 社内告知

サンプルメール文を用意しました（`docs/announcement_template.md` 予定 / 必要な場合は導入支援窓口へ）。

---

## 4. 文書を取り込む

### 4.1 推奨フォーマット

| フォーマット | 推奨度 | 備考 |
|---|---|---|
| Markdown (.md) | ★★★ | 最強。検索精度が一番高い |
| Text (.txt) | ★★★ | シンプル・安定 |
| PDF (.pdf) | ★★ | 取り込み可、レイアウトの複雑なものは精度低下 |
| Excel (.xlsx) | ★★ | Q&A 表形式なら有効 |
| PowerPoint (.pptx) | ★★ | スライド単位でチャンク化 |
| CSV (.csv) | ★★ | 列名を質問・回答にした構造で |
| JSON (.json) | ★ | キー名が日本語ならOK |
| Word (.docx) | ★ | 変換時に整形崩れあり |

### 4.2 取り込みフロー

1. ブラウザで `/admin/upload` を開く
2. **ステップ1: ファイル投入**
   - ドラッグ&ドロップ または クリックして選択
   - 複数ファイル同時OK
3. **ステップ2: クレンジング結果** を確認
   - 自動で PII 検出（マイナンバー・電話・メール等）
   - 推奨判定: ✅ 取り込み可 / ⚠ 要確認 / 🔴 取り込み非推奨
   - **チャンク単位** で個別に除外可能
4. **「選択を確定して取り込む」** ボタンで完了

### 4.3 ドキュメント作成のコツ（精度を上げる）

1. **1ファイル = 1テーマ**（例: 「VPN接続マニュアル.md」「経費精算ルール.md」）
2. **見出しを `#` `##` で明確に**（例:`## 1. 申請方法` `## 2. 承認フロー`）
3. **数値・固有名詞を明記**（「弊社」より「株式会社○○」のほうが検索に強い）
4. **Q&A 形式** が一番効く：
   ```markdown
   ## Q: VPN にログインできません

   FortiClient を起動し、ID/パスワード入力後、OTP 6桁を入力してください。
   OTP は会社支給スマホの「[OTP アプリ名]」で生成されます。
   ```

### 4.4 取り込み済み文書のメンテナンス

`/admin/upload` 画面下部「**3. 取り込み済み文書（メンテナンス）**」セクション：
- 取り込み済み文書の一覧
- ファイル単位での **削除** が可能
- マニュアル更新時は **古いバージョンを削除 → 新版をアップロード** がベスト

---

## 5. 日常運用：FAQ追加リクエスト対応

ユーザーが質問しても「該当情報なし」だった場合、画面に **「📩 FAQ追加をリクエスト」** ボタンが出ます。ユーザーがクリックすると管理者に届きます。

### 確認方法

1. ブラウザで `/admin/upload` を開く
2. 「**4. FAQ追加リクエスト**」セクションを見る
3. 質問内容・依頼者・日時が一覧表示される

### 対応フロー

```
リクエスト確認 → 対応するマニュアル作成 → /admin/upload で取り込み
   → 完了
```

> 💡 「該当情報なし」が頻発する分野は、社内ナレッジ整備の優先度シグナルになります。

---

## 6. 月次レポート出力（経営層向け）

`/admin/upload` 画面下部「**5. レポート出力**」セクションから：

| ボタン | 出力内容 | 用途 |
|---|---|---|
| 📊 質問履歴 CSV | 質問・確信度・回答日時 | 経営層への利用状況報告 |
| 📩 FAQリクエスト CSV | 未対応の要望一覧 | ナレッジ整備の優先度判断 |
| 👍 フィードバック CSV | 👍/👎評価 | 回答品質の改善検討 |
| 🗂 全ログ JSON | 全イベント | データ分析・監査対応 |

### 月次レポートのテンプレ案

```
■ Inquira 利用レポート（2026年5月）

期間: 2026/05/01 - 2026/05/31
ユーザー数: [N]名（社員 [M]名中）
質問総数: [N] 件
   うち AI 回答完了: [N] 件 ([N]%)
   うち 該当情報なし: [N] 件 ([N]%)

頻出トピック TOP5:
  1. VPN関連    XX件
  2. 経費精算   XX件
  ...

新規 FAQ追加リクエスト: [N] 件
   うち対応済み: [N] 件
   うち対応待ち: [N] 件

API コスト: ¥[N] / 月
```

CSV をスプレッドシートに貼り付けて作成できます。

---

## 7. バックアップ運用

### 7.1 手動バックアップ（任意のタイミング）

```bash
cd /path/to/faq_platform
./scripts/backup.sh
# → ./backups/inquira-backup-YYYYMMDD-HHMMSS.tar.gz が作られる
```

含まれるもの：
- 取り込み済み文書（`data/faq_master/` 等）
- 監査ログ（`data/audit/`）
- フィードバック学習データ
- `.env` ファイル（**機密情報あり**、取り扱い注意）

### 7.2 定期バックアップ（cron 設定）

毎晩 2:00 にバックアップ＋7日以上前は自動削除：

```bash
crontab -e
```
以下を追記：
```cron
0 2 * * * cd /path/to/faq_platform && ./scripts/backup.sh /path/to/backup-storage && find /path/to/backup-storage -name 'inquira-backup-*.tar.gz' -mtime +7 -delete
```

### 7.3 リストア

```bash
./scripts/restore.sh ./backups/inquira-backup-YYYYMMDD-HHMMSS.tar.gz
```

- 既存データを上書きするため、確認プロンプトが出ます
- 復元前に念のため現状もスナップショットされます

---

## 8. トラブルシューティング

### 「ローカルモード：APIキー未設定」と表示される
- `.env` の `ANTHROPIC_API_KEY=` の右側に正しいキーが入っているか
- サーバを **Ctrl+C で停止 → 再起動** したか
- `python -c "from app.config import settings; print(len(settings.anthropic_api_key))"` で 100超なら設定 OK

### 「Anthropic API キーが無効です」エラー
- Console でキーが Disable / Revoked になっていないか
- 新しいキーを発行し `.env` を更新
- 詳細は [§2.1](#21-anthropic-api-キーの取得)

### 質問しても「該当情報が見つかりませんでした」
- 関連する文書を取り込んでいるか確認（`/admin/upload` で文書一覧）
- 別の表現で質問し直す（例: 「VPN」→「リモート接続」）
- 文書の見出し・キーワードを増やして再取り込み

### ログイン後すぐ `/auth/login` に戻される
- `SESSION_SECRET` が空 or 短すぎる → `openssl rand -hex 32` で生成
- ブラウザの Cookie 設定（特に Safari の「サードパーティ Cookie ブロック」）

### サーバが起動しない
- ターミナルのエラー全文を確認
- `lsof -i :8000` で別プロセスが占有していないか
- Python バージョンが 3.11 以上か（`python --version`）

### 詳細なログを見たい
- 起動時のコンソール出力（`./scripts/demo_takaya.sh` のターミナル）
- 監査ログ: `data/audit/audit-YYYY-MM-DD.jsonl`

---

## 9. 導入支援窓口

- メール: [contact@example.com]
- 電話: [請求があれば開示]
- 営業時間: 平日 10:00 - 18:00
- 緊急対応（Enterprise プラン以上）: 別途契約に従う

### サポート範囲

| 内容 | Standard | Enterprise |
|---|---|---|
| メール質問 | 5営業日以内 | 1営業日以内 |
| 電話相談 | × | 月2回まで |
| リモート接続でのトラブル対応 | 別途見積 | 含む |
| ドキュメント取り込み代行 | 別途見積 | 月10ファイルまで含む |
| カスタマイズ開発 | 別途見積 | 別途見積（割引あり） |

---

## 関連ドキュメント

- [`docs/google_oauth_setup.md`](./google_oauth_setup.md) — Google OAuth 詳細手順
- [`docs/https_deployment.md`](./https_deployment.md) — HTTPS デプロイ手順
- [`docs/api_key_setup.md`](./api_key_setup.md) — Anthropic API キー設定詳細
- [`docs/api_cost_analysis.md`](./api_cost_analysis.md) — API コスト試算
- [`docs/legal/`](./legal/) — 利用規約・プライバシーポリシー雛形

---

最終更新: 2026年5月17日
