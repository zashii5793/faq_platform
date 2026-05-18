# Google OAuth セットアップ手順

> 想定読者: 顧客環境への導入担当者（情シス・社内エンジニア）
> 所要時間: 30分〜1時間（初回）
> 前提: 顧客が Google Workspace を使用している

DEMO_MODE は認証なしで動くので開発確認用には便利ですが、**本番運用は必ず Google OAuth で社員アカウント認証** を有効化してください。

---

## 全体像

```
社員 → Inquira (HTTPS) → "Googleでログイン" ボタン
                              ↓
                          Google 認証画面
                              ↓ ← 社員のメールアドレス + パスワード
                        Inquira /auth/callback
                              ↓
              許可ドメイン（例: @example-edu.co.jp）チェック
                              ↓
                    ✅ 通過 → セッション開始 → チャット画面
                    ❌ 拒否 → 403 エラー
```

---

## ステップ1: Google Cloud Console プロジェクトを作成

1. [https://console.cloud.google.com/](https://console.cloud.google.com/) にアクセス
2. 顧客 Google Workspace 管理者アカウントでログイン
3. 上部「プロジェクトの選択」→ **「新しいプロジェクト」**
4. プロジェクト名: `Inquira-<顧客名>` （例: `Inquira-EduDemo`）
5. 組織: 顧客の組織（Workspace 配下）を選択
6. **作成**

> 💡 Google Workspace 配下に作成しないと、後で内部アプリ設定にできません。

---

## ステップ2: OAuth 同意画面を構成

左メニュー → **API とサービス** → **OAuth 同意画面**

### ユーザータイプの選択

- **内部 (Internal)** を選択
  - Workspace 内のメンバーのみログイン可能になる
  - 外部公開しない場合の必須選択
  - "External" にすると Google の審査が必要

### アプリ情報

| 項目 | 入力例 |
|---|---|
| アプリ名 | **Inquira 社内ヘルプデスク** |
| ユーザーサポートメール | `support@example-edu.co.jp` |
| アプリのロゴ | （任意） |
| アプリのホームページ | `https://inquira.example-edu.co.jp/` |
| プライバシーポリシー | （社内文書 URL） |
| 利用規約 | （社内文書 URL） |
| 承認済みドメイン | `example-edu.co.jp` |
| デベロッパーの連絡先 | `support@example-edu.co.jp` |

**保存して次へ**

### スコープ

「**スコープを追加または削除**」をクリック → 以下にチェック：
- `.../auth/userinfo.email`
- `.../auth/userinfo.profile`
- `openid`

これだけで OK。**ファイル等のアクセス権は不要**。

**保存して次へ**

### テストユーザー
内部アプリの場合スキップ可能。**ダッシュボードに戻る**。

---

## ステップ3: OAuth クライアント ID を作成

左メニュー → **API とサービス** → **認証情報**

1. 上部 **+ 認証情報を作成** → **OAuth クライアント ID**
2. アプリケーションの種類: **ウェブアプリケーション**
3. 名前: `Inquira Web Client`

### 承認済みの JavaScript 生成元

```
https://inquira.example-edu.co.jp
```

開発時は以下も追加：
```
http://localhost:8000
http://127.0.0.1:8000
```

### 承認済みのリダイレクト URI（重要）

```
https://inquira.example-edu.co.jp/auth/callback
```

開発時は以下も追加：
```
http://localhost:8000/auth/callback
http://127.0.0.1:8000/auth/callback
```

> ⚠ パス `/auth/callback` の最後に **スラッシュを付けないでください**。Inquira のコードは正確にこのパスを期待します。

4. **作成** をクリック

5. ポップアップに **クライアント ID** と **クライアント シークレット** が表示される
   - 例: `123456-abcdef.apps.googleusercontent.com`
   - 例: `GOCSPX-xxxxxxxxxxxxxxxxxxxx`
   - **コピーして保管**（後で .env に書く）

---

## ステップ4: Inquira の `.env` ファイルを設定

```bash
cd ~/path/to/faq_platform
cp .env.example .env
vim .env  # またはお好みのエディタ
```

```env
# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxx

# Google OAuth
GOOGLE_CLIENT_ID=123456-abcdef.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxxxxxx
GOOGLE_REDIRECT_URI=https://inquira.example-edu.co.jp/auth/callback

# 許可するドメイン（@以下、ピリオド込み）
ALLOWED_DOMAIN=example-edu.co.jp

# 個別メールも許可したい場合（カンマ区切り）
ALLOWED_EMAILS=cto@example.com,external@partner.co.jp

# セッション暗号化キー（必ず置き換え）
SESSION_SECRET=（下のコマンドで生成）

# 組織情報
PRODUCT_NAME=Inquira
ORG_NAME=導入企業
ASSISTANT_ROLE=社内ヘルプデスク

# 業界マスキング
MASKING_INDUSTRY=education

# 検索バックエンド
EMBEDDING_BACKEND=e5-small

# DEMO_MODE は本番では必ず false（または環境変数自体を削除）
DEMO_MODE=false
```

### SESSION_SECRET の生成

```bash
# 64文字の安全な乱数を生成
openssl rand -hex 32
```

出力をそのまま `SESSION_SECRET=` に貼り付け。

---

## ステップ5: 動作確認

```bash
# 仮想環境を有効化
source .venv/bin/activate

# 本番モードで起動（DEMO_MODE 無し）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

ブラウザで `https://inquira.example-edu.co.jp/` を開く（ローカルなら `http://127.0.0.1:8000/`）：

1. 「Googleでログイン」ボタンが表示される
2. クリック → Google 認証画面
3. 顧客 Workspace のアカウントで認証
4. リダイレクトされてチャット画面が出る ✅

許可外ドメインでログインを試みると `403 Forbidden` が返る ✅

---

## トラブルシューティング

### `redirect_uri_mismatch` エラー

ブラウザに「リダイレクト URI がポリシーに違反しています」と出る場合：

1. Google Cloud Console → 認証情報 → クライアント ID 編集
2. **承認済みのリダイレクト URI** に以下を**完全一致で**追加：
   - 本番: `https://inquira.example-edu.co.jp/auth/callback`
   - ローカル: `http://localhost:8000/auth/callback`
3. 末尾スラッシュ・http/https・ポート番号 すべて一致させる
4. 反映まで5分待つ（キャッシュ）

### `アクセスが拒否されました` メッセージ

`is_email_allowed` で弾かれている。`.env` の `ALLOWED_DOMAIN` を確認：
- `example-edu.co.jp` ← OK
- `@example-edu.co.jp` ← `@` は付けない
- `https://example-edu.co.jp` ← URL形式は付けない

### 「このアプリは確認されていません」警告

内部アプリ（Internal）に設定していれば本来出ないはずです。出る場合：
- OAuth 同意画面で「ユーザータイプ: 内部」になっているか
- Workspace 配下で正しく作成されているか
- `承認済みドメイン` に顧客ドメインが入っているか

### ログイン後すぐ /auth/login に戻される

セッションが保存できていない可能性。原因：
- `SESSION_SECRET` がデフォルト値のまま → 32文字以上の乱数に
- Cookie の `secure` 属性問題（HTTP で動かしているのに secure になっている等）→ HTTPS 化

---

## セキュリティチェックリスト（本番リリース前）

- [ ] `DEMO_MODE` が **false** または未設定
- [ ] `SESSION_SECRET` が 64文字以上のランダム値（`openssl rand -hex 32` 出力）
- [ ] `GOOGLE_REDIRECT_URI` が **HTTPS**（HTTP 不可）
- [ ] `ALLOWED_DOMAIN` が顧客の Workspace ドメインと一致
- [ ] OAuth 同意画面が **内部 (Internal)**
- [ ] OAuth スコープが **email/profile/openid のみ**（過剰権限なし）
- [ ] `ANTHROPIC_API_KEY` がリポジトリにコミットされていない（.env が .gitignore 済みか確認）
- [ ] 退職者対応: アカウント停止 → Workspace 側で停止すれば自動で OAuth も拒否

---

## 関連
- [docs/api_key_setup.md](./api_key_setup.md) — Anthropic API キー設定
- [docs/https_deployment.md](./https_deployment.md) — HTTPS デプロイ手順
- [scripts/production_smoke_test.py](../scripts/production_smoke_test.py) — 本番動作確認スクリプト
