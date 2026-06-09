# Inquira 顧客導入 — 留意点と事前ヒアリング項目

> A社（初の本格オンプレ導入）の経験から、次の顧客導入時にハマらないための整理。
> 顧客とのキックオフ前に「事前ヒアリングシート」を埋めてもらい、設計判断を済ませてから動く。

---

## ハマリポイント TOP 10（A社で実際に発生）

| # | 症状 | 原因 | 防ぐためのヒアリング |
|---|---|---|---|
| 1 | Docker 前提で進めていたが Docker 不可と途中で判明 | 顧客環境の事前確認不足 | 「Docker 使えますか？」 |
| 2 | Windows Server を Linux 用 install.sh で進めようとした | OS 確認不足 | 「OS は何ですか？」 |
| 3 | 管理者権限なし → タスクスケジューラ SYSTEM 起動できず | 権限確認不足 | 「サーバーの管理者権限ありますか？」 |
| 4 | install.ps1 が文字化けしてパースエラー | UTF-8 BOM なしを PowerShell が Shift-JIS で解釈 | スクリプトを **BOM 付き UTF-8** で配布する |
| 5 | CMD と PowerShell の構文を混同 | 顧客側のターミナル誤認識 | 案内コマンドに「**PowerShell で**」を明示 |
| 6 | Google OAuth が IP アドレスのリダイレクト URI を拒否 | Google 仕様 | 「社内 DNS で FQDN を割り当てられますか？」 |
| 7 | Google OAuth テストユーザー登録を忘れて全員ログイン不可 | 手順書から漏れていた | 提供側準備リストに必ず含める |
| 8 | DNS 設定権限がない（Inquira 担当者 ≠ AD 管理者） | 権限分離の見落とし | 「DNS 設定は誰が触れますか？」 |
| 9 | リポジトリに顧客固有値（メール・サーバーパス）を書いてしまった | 提供側ミス | プレースホルダ運用 + コミット前 grep |
| 10 | Mac → Windows サーバーへ ZIP を直接渡せない（RDP） | 転送経路の確認不足 | GitHub からダウンロード方式を最初から案内 |

---

## 顧客キックオフ前 事前ヒアリングシート

以下を顧客に埋めてもらってから、設計と手順書を確定する。

### 1. インフラ環境

| 項目 | 例 | 備考 |
|---|---|---|
| サーバー OS | Windows Server 2022 / Ubuntu 22.04 / etc. | install スクリプトが変わる |
| Docker 利用可否 | 可 / 不可 | 可なら docker compose、不可なら native install |
| サーバー IP | 192.168.x.x | 内部 IP（社内 LAN） |
| サーバーの管理者権限 | 担当者本人にあり / なし | なしなら タスクスケジューラ SYSTEM 不可、IIS 不可 |
| Python 3.11+ の有無 | あり / なし | なしなら事前インストール案内 |
| インターネット接続（外向き） | api.anthropic.com / accounts.google.com に到達可能か | 必須 |

### 2. ネットワーク・DNS

| 項目 | 例 | 備考 |
|---|---|---|
| 社内ドメイン | acme.jp / acme.co.jp / acme.com | Google OAuth は `.local` 不可 |
| 社内 DNS サーバー IP | 192.168.x.x | DNS 管理サーバーのアドレス |
| DNS への A レコード登録権限 | 担当者あり / AD 管理者依頼 | なければ依頼書（AD_REQUEST.md）を渡す |
| 希望サブドメイン | inquira / faq / kb | 社内 DNS に登録するホスト名 |
| 公開 URL の形式 | http://inquira.acme.jp:8000/ / https://inquira.acme.jp/ | HTTPS 化するなら IIS リバプロ依頼 |

### 3. データ保存先

| 項目 | 例 | 備考 |
|---|---|---|
| 保存先の希望 | ローカル / UNC 共有 | UNC なら接続情報・権限・パスを確認 |
| UNC パス | `\\fileserver\share\inquira` | 担当者がアクセスできるか実機確認 |
| バックアップ運用 | 既存バックアップに data/ を追加 | 必須 |

### 4. アクセス制御・認証

| 項目 | 例 | 備考 |
|---|---|---|
| 管理者 Gmail（最大数名） | admin1@..., admin2@... | OAuth 同意画面テストユーザー登録 + ALLOWED_EMAILS |
| 一般社員開放 | する / しない | する場合は ALLOWED_DOMAIN に会社ドメインを設定 |
| 会社ドメイン（Google Workspace） | acme.jp | ALLOWED_DOMAIN の値 |

### 5. HTTPS / IIS 設定

| 項目 | 例 | 備考 |
|---|---|---|
| IIS が入っているか | 入っている / 入っていない | 入っていなければ HTTPS 化は別途検討 |
| URL Rewrite + ARR モジュール | 入っている / 入っていない | リバプロに必須 |
| SSL 証明書 | 既存社内 CA / Let's Encrypt / 新規発行 | 用意ルート |
| IIS の管理権限 | 担当者あり / IT 部門依頼 | なければ IIS_SETUP_REQUEST.md を渡す |

### 6. 役割分担

| フェーズ | 担当 | 想定 |
|---|---|---|
| 提供側準備（OAuth・.env 作成） | 提供側 | 15 分 |
| Python インストール | 顧客 | 10 分 |
| Inquira インストール | 顧客 | 15 分 |
| 社内 DNS 設定 | AD 管理者 | 5 分（依頼書あり） |
| IIS リバプロ設定 | IT 部門 | 30 分（依頼書あり） |
| ナレッジ投入 | 顧客 Inquira 管理者 | 30 分〜数時間 |
| 社員告知 | 顧客 | — |

---

## 設計上の判断ポイント

### A. データ保存先: ローカル vs UNC 共有

| 観点 | ローカル | UNC 共有 |
|---|---|---|
| バックアップ | 個別 PC 単位 | 既存ファイルサーバーのバックアップに乗せられる |
| 引越し容易性 | サーバー入れ替えで消える | データだけ残る |
| 起動時の依存 | なし | 共有のマウント・認証キャッシュが必要 |
| 推奨 | PoC | **本番** |

### B. 自動起動: スタートアップフォルダ vs タスクスケジューラ SYSTEM

| 観点 | スタートアップ | タスク (SYSTEM) |
|---|---|---|
| 管理者権限 | 不要 | 必要 |
| サーバー再起動時の挙動 | 誰かがログオンするまで起動しない | ログオン関係なく起動 |
| 推奨 | PoC | **24h 運用** |

### C. 公開 URL: localhost / IP / FQDN

| 形式 | Google OAuth 通る | 全社員から見える | 推奨用途 |
|---|---|---|---|
| `http://localhost:8000/` | ○ | × (サーバー上のブラウザのみ) | デモ・PoC |
| `http://192.168.x.x:8000/` | × (Google が IP 拒否) | △ (社内 LAN) | 不可 |
| `http://inquira.acme.jp:8000/` | ○ | ○ | **本番（HTTP）** |
| `https://inquira.acme.jp/` | ○ | ○ | **本番（HTTPS）** |

### D. SSL 化: 必要 / 不要

| 観点 | 不要 (HTTP) | 必要 (HTTPS) |
|---|---|---|
| ブラウザの「保護されていない通信」警告 | 出る | 出ない |
| 社員からの心象 | 怪しまれる | 安心 |
| 構築コスト | 0 | IIS リバプロ + SSL 証明書 |
| 推奨 | PoC のみ | **本番** |

---

## 提供側オペレーション標準フロー

### Phase 0: 商談時

1. 「事前ヒアリングシート」を渡す
2. 環境を確認
3. 「導入できます／できません」「いつ頃」を回答

### Phase 1: キックオフ（顧客対応開始）

1. OAuth 同意画面に顧客管理者 Gmail を **「テストユーザー」登録**（5 分、ここを忘れない）
2. OAuth クライアントに **リダイレクト URI 追加**：
   - `http://localhost:8000/auth/callback`
   - `http://<希望サブドメイン>.<顧客社内ドメイン>:8000/auth/callback`
3. 顧客用 `.env` を作成（実値入り。リポジトリには含めない）

### Phase 2: 顧客サーバーへインストール

1. GitHub からブランチ ZIP をダウンロード（顧客側）
2. `.env` を配置（実値入り）
3. `install.ps1 -DataDir "<UNC 共有>"` 実行
4. `http://localhost:8000/` でローカル動作確認

### Phase 3: 社内公開

1. AD 管理者に **AD_REQUEST.md** を渡して DNS 設定依頼
2. AD 管理者の作業完了確認（`nslookup`）
3. `.env` の `GOOGLE_REDIRECT_URI` を FQDN に更新
4. Inquira 再起動
5. 社員 PC から `http://<FQDN>:8000/` で動作確認

### Phase 4: HTTPS 化（任意）

1. IT 部門に **IIS_SETUP_REQUEST.md** を渡して IIS リバプロ依頼
2. 完了確認
3. `.env` の `GOOGLE_REDIRECT_URI` を `https://<FQDN>/auth/callback` に更新
4. Inquira 再起動

### Phase 5: 引き渡し

1. 顧客 Inquira 管理者に **a_company_admin_quickstart.pdf** を渡す
2. 全社員告知用に **a_company_user_quickstart.pdf** を渡す
3. 1 週間後にフォロー（FAQ 候補レビュー、削減効果確認）

---

## 配布ドキュメントの整理

顧客には以下を **段階的に** 渡す（一度に全部渡すと混乱）：

| 渡すタイミング | 渡し先 | ドキュメント |
|---|---|---|
| キックオフ | 提供側自身 | `deployment_lessons_learned.md` (本書) |
| インストール時 | 顧客 IT 部門 | `a_company_install_guide.pdf` |
| DNS 設定 | AD 管理者 | `AD_REQUEST.md`（このドキュメント風に整形） |
| HTTPS 化 | IT 部門 | `IIS_SETUP_REQUEST.md` PDF |
| ナレッジ投入 | 顧客 Inquira 管理者 | `a_company_admin_quickstart.pdf` |
| 全社告知 | 顧客 → 社員 | `a_company_user_quickstart.pdf` |

---

## 顧客情報の取り扱いルール

| 種類 | 例 | 取り扱い |
|---|---|---|
| 顧客実名 | （顧客の正式社名） | リポジトリ NG（`<顧客名>` のようなプレースホルダにする） |
| 顧客ドメイン | （顧客の社内ドメイン） | リポジトリ NG（`<顧客社内ドメイン>` のようなプレースホルダにする） |
| 社内 IP | `<INQUIRA_SERVER_IP>` | リポジトリ NG（チャット・実機の `.env` のみ） |
| UNC パス | `\\fileserver\share\inquira` | リポジトリ NG |
| 管理者 Gmail | `admin@example.com` | リポジトリ NG。`.env` も `.gitignore` |
| API キー | `sk-ant-...` | リポジトリ NG。`~/.inquira_provider_secrets` |
| OAuth Client Secret | `GOCSPX-...` | リポジトリ NG |

コミット前に必ず：

```bash
git diff --cached | grep -iE 'gmail|@.*\.(jp|com)|\\\\|株式会社|file[0-9]+|192\.168\.|sk-ant-|GOCSPX'
# 何かヒットしたら add をやり直す
```

---

## 改善 TODO（A社後の宿題）

- [ ] `install.ps1` の OS 判定を追加（CMD 実行を検知して PowerShell を促す）
- [ ] `install.ps1` の事前チェックに「.env のプレースホルダ残存検知」をより明確に
- [ ] OAuth リダイレクト URI に IP は弾かれる旨を、提供側準備リストに明記
- [ ] DNS 設定の権限が無いケースを前提とした手順書を初期から用意（AD_REQUEST.md）
- [ ] 「事前ヒアリングシート」を Excel/Google Form 化して顧客記入を効率化
- [ ] `tenants/<slug>/` の生成を `add_tenant.sh` から `add_tenant.ps1` も用意（Windows 提供側オペ用）
- [ ] 配布 ZIP の自動生成スクリプト（`build_customer_package.py`）
- [ ] ヘルスチェック確認スクリプト（OAuth まで通るかを自動診断）
