# Inquira FAQプラットフォーム 仕様書 v0.1

| 項目 | 内容 |
|---|---|
| 文書バージョン | 0.1 (PoC段階) |
| 作成日 | 2026-04-26 |
| 対象 | 汎用B2B社内FAQツール（PoC実装） |
| 関連文書 | [`requirements_demo_education.md`](./requirements_demo_education.md)（導入事例）, [`business_analysis.md`](./business_analysis.md), [`../ROADMAP.md`](../ROADMAP.md) |

> 本仕様書は **要件定義書を技術的に具体化した設計書** です。
> 実装と仕様は同期させること。差異が出たらどちらかを必ず更新する。
>
> 本実装は**業界・組織非依存**になっており、`ORG_NAME` / `ASSISTANT_ROLE` / `MASKING_INDUSTRY`
> 等の環境変数で導入先ごとにカスタマイズできる。

---

## 1. 全体アーキテクチャ

```
                    ┌──────────────┐
                    │ ブラウザ     │
                    └──────┬───────┘
                           │ HTTPS
                ┌──────────▼──────────┐
                │ FastAPI (uvicorn)   │
                │ ┌────────────────┐  │
                │ │ /auth/*        │  │── Google OAuth 2.0
                │ │ /api/ask       │──┤
                │ │ /api/admin/*   │  │
                │ │ /healthz       │  │
                │ └───────┬────────┘  │
                │         │           │
                │   ┌─────▼──────┐    │
                │   │ masking.py │    │
                │   └─────┬──────┘    │
                │   ┌─────▼──────┐    │
                │   │   rag.py   │────┼──→ data/faq_master/*.md|.txt
                │   └─────┬──────┘    │
                │   ┌─────▼──────┐    │
                │   │   llm.py   │────┼──→ Anthropic API
                │   └─────┬──────┘    │
                │   ┌─────▼──────┐    │
                │   │  audit.py  │────┼──→ data/audit/*.jsonl
                │   └────────────┘    │
                └─────────────────────┘
```

### モジュール責務

| モジュール | 責務 |
|---|---|
| `app/main.py` | HTTPエンドポイント、リクエスト/レスポンスモデル、ミドルウェア |
| `app/auth.py` | Google OAuth、許可ドメイン/メール判定、`require_user` 依存 |
| `app/masking.py` | 送信前マスキング（学校名・メール・電話番号） |
| `app/rag.py` | FAQ正本の読み込み、チャンク化、TF-IDF検索 |
| `app/llm.py` | Claude API 呼び出し、システムプロンプト管理 |
| `app/audit.py` | 監査ログのJSONL追記 |
| `app/config.py` | 環境変数の読み込み（pydantic-settings） |

---

## 2. APIエンドポイント仕様

### 2.1 `GET /healthz`
| 項目 | 内容 |
|---|---|
| 認証 | 不要 |
| 用途 | ヘルスチェック、監視 |
| レスポンス | `200 {"ok": true}` |

### 2.2 `GET /auth/login`
| 項目 | 内容 |
|---|---|
| 認証 | 不要 |
| 動作 | Google OAuth 同意画面へリダイレクト |

### 2.3 `GET /auth/callback`
| 項目 | 内容 |
|---|---|
| 認証 | OAuth コールバック |
| 動作 | アクセストークン取得 → `is_email_allowed()` で許可判定 → セッションに `user` 保存 → `/` へリダイレクト |
| エラー | 許可外メール → `403` + `audit:login_denied` |

### 2.4 `GET /auth/logout`
| 項目 | 内容 |
|---|---|
| 動作 | セッションクリア → `/` へリダイレクト |

### 2.5 `POST /api/ask` 【主要API】
| 項目 | 内容 |
|---|---|
| 認証 | 必須（`require_user`） |
| リクエスト | `{"question": "string"}` |
| レスポンス | `{"answer": "string", "sources": [{"chunk_id", "source", "score"}]}` |
| 処理フロー | (1) マスキング → (2) RAG検索(top_k=5) → (3) Claude呼び出し → (4) 監査ログ → (5) レスポンス返却 |
| エラー | `401` 未認証, `403` 許可外, `500` LLM/RAGエラー |

### 2.6 `POST /api/admin/reload-index`
| 項目 | 内容 |
|---|---|
| 認証 | 必須 |
| 用途 | FAQ正本フォルダの再読込（マスター更新後） |
| レスポンス | `{"chunks": <int>}` |

### 2.7 `GET /` (HTML)
| 項目 | 内容 |
|---|---|
| 動作 | 未ログインなら「Googleでログイン」、ログイン済みなら簡易UI（質問フォーム）を表示 |

---

## 3. データモデル

### 3.1 FAQマスター文書（入力）
- 形式：Markdown (`*.md`) または プレーンテキスト (`*.txt`)
- 配置：`data/faq_master/` 直下または再帰サブディレクトリ
- 推奨フォーマット：

```markdown
# トピック名

### Q. 質問1
A. 回答1

### Q. 質問2
A. 回答2
```

### 3.2 チャンク（内部表現）
```python
@dataclass
class Chunk:
    chunk_id: str   # 例: "出席登録.md#0"
    source: str     # 例: "出席登録.md"
    text: str       # 本文（最大600文字目安、段落単位で結合）
```

### 3.3 監査ログエントリ（JSONL）
```json
{
  "ts": "2026-04-26T22:34:23.731571+00:00",
  "event": "query",
  "user": "user@example-edu.co.jp",
  "question": "<マスク後の文面>",
  "sources": ["出席登録.md#0", "ログイン.md#0"]
}
```

| event 種別 | 追加フィールド |
|---|---|
| `login_success` | (なし) |
| `login_denied` | (なし) |
| `logout` | (なし) |
| `query` | `question`, `sources` |
| `reload_index` | `n_chunks` |

---

## 4. 認証・認可

### 4.1 認証フロー（Google OAuth 2.0 + OIDC）

```
ブラウザ          /auth/login     /auth/callback   Google
   │                  │                │            │
   │ GET /auth/login  │                │            │
   ├─────────────────▶│                │            │
   │                  │ redirect       │            │
   │ ◀────────────────┤                │            │
   │                                                │
   │ Googleで認証                                   │
   ├──────────────────────────────────────────────▶│
   │                                                │
   │ redirect to /auth/callback?code=xxx            │
   │ ◀──────────────────────────────────────────────┤
   │                  │                │            │
   │ GET /callback    │                │            │
   ├──────────────────────────────────▶│            │
   │                  │ exchange code  │            │
   │                  │ ──────────────▶│            │
   │                  │ ◀──────────────│ id_token   │
   │                  │ verify         │            │
   │                  │ is_email_allowed?           │
   │                  │ session["user"] = {...}     │
   │ redirect /       │                │            │
   │ ◀────────────────│                │            │
```

### 4.2 認可ロジック (`is_email_allowed`)
1. `ALLOWED_EMAILS` に明示列挙されたメール → 許可
2. `ALLOWED_DOMAIN` でドメイン一致 → 許可
3. 上記以外 → 拒否（`403`）

### 4.3 セッション
- `SessionMiddleware`（starlette）使用
- 署名鍵：`SESSION_SECRET`（**必ず本番では強い値に変更**）
- 保存内容：`{"email", "name"}` のみ

---

## 5. RAG 仕様（PoC）

### 5.1 チャンク化
- 区切り：空行2つ（段落単位）
- 上限：600文字／チャンク（超える場合は段落単位で分割継続）
- 結合戦略：上限を超えない範囲で連続段落を結合

### 5.2 検索（PoC実装）
- ベクトル化：`TfidfVectorizer(analyzer="char_wb", ngram_range=(2,3))`
  - 日本語の形態素解析無しでも文字n-gramでそこそこ動く（PoC用）
- スコア：内積（コサイン類似度に近似）
- top_k：5（API パラメータで上書き可）

### 5.3 本番への差し替え（ROADMAP Task 1.1）
- Embedding モデル：`intfloat/multilingual-e5-large` 推奨
- ベクトルストア：sqlite-vss / chroma / pgvector のいずれか
- インデックス再構築：`POST /api/admin/reload-index` を非同期化

---

## 6. LLM 呼び出し仕様

### 6.1 モデル
- デフォルト：`claude-sonnet-4-6`（環境変数 `CLAUDE_MODEL` で上書き可）
- max_tokens：1024
- ストリーミング：未対応（v0.2 で実装予定）

### 6.2 システムプロンプト（テンプレート）
`{org_name}` と `{role}` は環境変数 `ORG_NAME` / `ASSISTANT_ROLE` で差し込まれる。

> あなたは{org_name}の{role}アシスタントです。
> 1. 提供された [参考情報] のみを根拠に回答する
> 2. [参考情報] に答えが無い場合は推測せず「該当情報が見つかりませんでした」と伝える
> 3. 回答末尾に出典（ドキュメント名やID）を必ず明記する
> 4. マスキング済みのトークン（[氏名][メール]等）は復元せずそのまま使う
> 5. 簡潔・正確に。冗長な前置きは避ける。

### 6.3 ユーザーメッセージ構造
```
[参考情報]
[出典: <chunk_id>]
<chunk_text>

[出典: <chunk_id>]
<chunk_text>
...

質問: <マスク済み質問文>
```

### 6.4 フォールバック
- `ANTHROPIC_API_KEY` 未設定時はローカルスタブを返す（開発／デモ用）

---

## 7. マスキング仕様

汎用ルール（全業界共通）と、業界プリセット（`MASKING_INDUSTRY` で選択）の組み合わせ。

### 7.1 汎用ルール（GENERIC_RULES）
| 対象 | 置換トークン |
|---|---|
| メールアドレス | `[メール]` |
| 電話番号（日本） | `[電話番号]` |
| クレジットカード番号 | `[カード番号]` |
| マイナンバー | `[マイナンバー]` |
| IPアドレス | `[IPアドレス]` |
| URL | `[URL]` |

### 7.2 業界プリセット
| `MASKING_INDUSTRY` | 追加ルール |
|---|---|
| `general` | 追加なし |
| `education` | 学校名 → `[学校名]` |
| `healthcare` | 診療番号 (MRN) → `[診療番号]` |
| `finance` | 7桁口座番号 → `[口座番号]` |

### 7.3 拡張方法
顧客固有のパターンは `app/masking.py` の `MaskRule` を生成して `build_rules(extra=...)` に渡す。
将来的には `data/masking_rules.yaml` のような外部設定ファイルから読み込む形に進化させる予定。

> **既知の限界**：完全な PII 検出は保証せず、**漏出時の被害を減らす"防御層"** という位置づけ。
> 高精度が必要な業務では NER モデルや専用 PII 検出 API（AWS Comprehend, GCP DLP 等）と併用すること。

---

## 8. 設定（環境変数）

| 変数 | 必須 | 既定 | 説明 |
|---|---|---|---|
| `PRODUCT_NAME` | × | `Inquira` | プロダクト表示名 |
| `ORG_NAME` | × | `（貴社）` | 導入企業名（システムプロンプトに差込） |
| `ASSISTANT_ROLE` | × | `社内ヘルプデスク` | アシスタントの役割名 |
| `MASKING_INDUSTRY` | × | `general` | `general\|education\|healthcare\|finance` |
| `ANTHROPIC_API_KEY` | 本番○ | (空) | Claude API キー |
| `CLAUDE_MODEL` | × | `claude-sonnet-4-6` | 使用モデル |
| `GOOGLE_CLIENT_ID` | 本番○ | (空) | OAuth クライアントID |
| `GOOGLE_CLIENT_SECRET` | 本番○ | (空) | OAuth シークレット |
| `GOOGLE_REDIRECT_URI` | 本番○ | `http://localhost:8000/auth/callback` | OAuth コールバックURL |
| `ALLOWED_DOMAIN` | 推奨 | (空) | 例: `example-edu.co.jp` |
| `ALLOWED_EMAILS` | × | (空) | カンマ区切りメール |
| `SESSION_SECRET` | 本番○ | `dev-secret-change-me` | セッション署名鍵 |
| `FAQ_MASTER_DIR` | × | `./data/faq_master` | FAQ正本フォルダ |
| `INDEX_PATH` | × | `./data/index.json` | インデックスメタ保存先 |
| `DEMO_MODE` | × | `false` | `true` で認証バイパス（**本番禁止**） |
| `HOST`, `PORT` | × | `0.0.0.0`, `8000` | サーバ待受 |

---

## 9. エラー処理

| 状況 | HTTP | レスポンス |
|---|---|---|
| 未ログインで `/api/ask` | 401 | `{"detail": "not signed in"}` |
| 許可外メールでログイン | 403 | `{"detail": "<email> は許可されていません"}` |
| Anthropic API エラー | 500 | (例外伝播、ログ記録) |
| インデックス空（FAQ未投入） | 200 | 空 sources で「参考情報なし」回答 |

---

## 10. 動作確認手順

### 10.1 ローカル（デモモード、API キー不要）
```bash
DEMO_MODE=1 FAQ_MASTER_DIR=./data/demo_faq SESSION_SECRET=demo \
  uvicorn app.main:app --host 127.0.0.1 --port 8000

# 別ターミナルで:
curl -s -X POST http://127.0.0.1:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"出席の保存ボタンが効かない"}'
```

### 10.2 本番想定（フル機能）
```bash
cp .env.example .env  # 値を埋める
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 10.3 テスト
```bash
pytest -v
```

---

## 11. 既知の限界（PoC段階）

- **TF-IDF検索の精度**：日本語形態素解析を使っていないため、専門用語の揺れに弱い。Phase 1 Task 1.1 で Embedding に差し替える前提
- **マスキングが正規表現ベース**：固有名詞辞書を持っていないので、生徒氏名のような一般名詞混じりは検出不能。Phase 1 Task 1.3 で辞書／NER 連携を検討
- **画像チャンクなし**：PDF/Excel/画像はテキストのみ。スクリーンショット参照型の問い合わせには不向き
- **キャッシュなし**：同じ質問でも毎回 LLM を呼ぶ。月額コスト試算では1名あたり10質問/日想定だが、要モニタリング

---

## 12. 変更履歴
| 版 | 日付 | 内容 |
|---|---|---|
| 0.1 | 2026-04-26 | 初版（PoC実装に対応） |
