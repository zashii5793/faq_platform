# Anthropic API キーの確認・取得・テスト手順

## ステップ1：既にキーを持っているか確認

### 1-A. パソコン内を検索

ターミナルで以下を実行：

```bash
# 環境変数に設定済みか
echo $ANTHROPIC_API_KEY

# シェル設定ファイル内に書き込まれているか
grep -r "ANTHROPIC_API_KEY" ~/.zshrc ~/.bashrc ~/.zprofile 2>/dev/null

# プロジェクトディレクトリ内の .env ファイル
cd ~/path/to/faq_platform
grep "ANTHROPIC_API_KEY" .env 2>/dev/null
```

何か出てきたらそのキーを使えます（`sk-ant-` から始まる文字列）。

### 1-B. Anthropic Console で確認

1. ブラウザで [https://console.anthropic.com/](https://console.anthropic.com/) にアクセス
2. ログイン（Claude.ai と同じ Anthropic アカウントが使えます）
3. 左メニュー → **「API Keys」** をクリック
4. 既存のキー一覧が表示される

> ⚠ Anthropic Console は **APIプラン用のアカウント** が必要です。Claude Pro/Team とは別契約。
> ログインできない場合はステップ2へ。

---

## ステップ2：キーを新規取得（無い場合）

### 2-A. Anthropic Console アカウント作成

1. [https://console.anthropic.com/](https://console.anthropic.com/) で **「Sign up」**
2. メールアドレスを入力 → 認証メールから登録
3. 組織情報を入力（個人なら個人名でOK）
4. クレジットカード登録 OR プリペイドクレジット入金

> 💡 **無料クレジット $5** が初回登録時に付与されます（テスト用に十分）。

### 2-B. API キー生成

1. ログイン後 → 左メニュー **「API Keys」**
2. **「Create Key」** ボタン
3. キー名を入力（例：`inquira-demo_company-demo`）
4. **`sk-ant-xxxxxxxxxx...`** が表示される
5. **このキーは1回しか表示されない** ので、必ずコピーして保管

> 🔒 キーは **パスワードと同じ機密情報** です。リポジトリにコミット禁止。`.env` ファイルに書く（`.gitignore` 済み）。

---

## ステップ3：動作確認

### 3-A. 環境変数を一時的に設定して接続テスト

```bash
cd ~/path/to/faq_platform

# 仮想環境を有効化（demo.sh を一度走らせていれば .venv がある）
source .venv/bin/activate

# 接続テスト
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxx python scripts/test_anthropic.py
```

成功すると以下が表示されます：

```
🔑 APIキー: sk-ant-api03...XXXX (長さ: 108文字)

📡 接続テスト中... (約2秒)
✅ 接続成功（1.85秒）
   モデル:     claude-sonnet-4-6
   応答:       OK
   入力tokens:  18
   出力tokens:  4

💰 このリクエストの料金: $0.000114 (約 0.0177円)

📊 月額試算（参考）:
     5名 ×  5質問/日 × 22日 = 月  550質問 ≈ $0.07 (約 11円)
    35名 × 10質問/日 × 22日 = 月7,700質問 ≈ $1.04 (約 161円)
   100名 × 15質問/日 × 22日 = 月33,000質問 ≈ $4.46 (約 691円)

✅ APIキーは正常に動作しています。
```

### 3-B. .env に設定して恒久化

```bash
# .env ファイルを作成（無ければ）
cp .env.example .env

# 編集
vim .env  # または好きなエディタで
```

```env
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxx
CLAUDE_MODEL=claude-sonnet-4-6
```

---

## ステップ4：本番モードで起動

`.env` 設定後、`DEMO_MODE` を外して起動：

```bash
# デモ会社用（実APIで動作）
FAQ_MASTER_DIR=./data/demo_company_faq \
  SESSION_SECRET="$(openssl rand -hex 32)" \
  ORG_NAME="デモ会社株式会社" \
  ASSISTANT_ROLE="整備工場サポート" \
  uvicorn app.main:app --host 127.0.0.1 --port 8000
```

ブラウザで `http://127.0.0.1:8000/` を開いて質問すると、**Claude が実際の文章で回答** を返します（ローカルモードのスタブではなく）。

---

## 参考：料金体系（2026年4月時点）

| モデル | 入力 (1Mトークン) | 出力 (1Mトークン) |
|---|---|---|
| Claude Opus 4.7 | $15 | $75 |
| **Claude Sonnet 4.6** （標準） | **$3** | **$15** |
| Claude Haiku 4.5 | $1 | $5 |

> 1質問あたり平均 5,000トークン（参考含む）と仮定すると：
> - Sonnet 4.6: **約 $0.05 = 約 8円/質問**
> - Haiku 4.5: 約 1.5円/質問
> - Opus 4.7: 約 36円/質問

### 月額コスト試算

| 利用者 | 質問/日 | 営業日 | 月の質問数 | Sonnet 月額 |
|---|---|---|---|---|
| 5名（デモ会社） | 5 | 22 | 550 | **約 4,400円** |
| 35名（教育系A社） | 10 | 22 | 7,700 | **約 6万円** |
| 100名（中堅企業） | 15 | 22 | 33,000 | **約 26万円** |

> ⚠ 上記は **API利用料のみ**。サーバ代・運用費は別途。
> 本番運用時は `Inquira` 側で **キャッシュ・レート制限** を入れて 30〜50% コスト削減可能。

---

## トラブルシューティング

### `authentication_error: invalid x-api-key`
- APIキーが間違っている／無効化されている
- Anthropic Console で **「Active」** 状態か確認
- `sk-ant-` で始まっているか

### `rate_limit_error`
- 短時間に大量リクエスト
- Console で組織のレート上限を確認
- 必要なら **「Increase rate limit」** をリクエスト

### `credit_balance_too_low`
- クレジット残高不足
- Console → **「Billing」** でチャージ
- 自動チャージ設定も可能

### 月額が想定より高い
- **キャッシュ未使用**：同じ質問の再検索でも毎回API呼び出し
- 対策：`Inquira` で「同一質問は5分間キャッシュ」を実装可能（要相談）

---

## 関連
- [scripts/test_anthropic.py](../scripts/test_anthropic.py) — 接続テストスクリプト
- [.env.example](../.env.example) — 設定テンプレ
- [docs/setup_guide_mac.md](./setup_guide_mac.md) — Mac セットアップ全体
