# コミット前チェックリスト

## 自動チェック（コピペで実行）

```bash
# 1. 秘密情報スキャン
git diff --cached | grep -inE 'sk-ant-|GOCSPX-|AIza[0-9A-Za-z_-]{35}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|192\.168\.|10\.[0-9]+\.[0-9]+\.[0-9]'

# 2. 危険なファイルがステージされていないか
git status --porcelain | grep -E '\.env$|\.pem$|\.key$|/\.private/|credentials'

# 3. テストと Lint
ruff check . && pytest -q
```

いずれも「出力なし / 全て pass」であることを確認する。

## 目視チェック

- [ ] 顧客名・顧客ドメイン・社内 IP・UNC パスが含まれていないか
- [ ] 個人名（自分の氏名を含む）が含まれていないか
- [ ] バージョンを上げた場合、2 箇所（`pyproject.toml` / `__init__.py`）が同期しているか
- [ ] CHANGELOG の `[Unreleased]` に今回の変更を書いたか
- [ ] 新機能の場合、テストを追加したか
- [ ] コミットメッセージが「何をしたか」ではなく「何のために」を含んでいるか

## Git 運用

- [ ] 作業ブランチが命名規約に沿っているか（`feature/` `fix/` `hotfix/`）
- [ ] **週 1 回以上、main にマージしているか**
      （AI が作ったブランチに実装が取り残される事故の防止）

## 検出パターンの意味

| パターン | 何を検出するか |
|---|---|
| `sk-ant-` | Anthropic API キー |
| `GOCSPX-` | Google OAuth クライアントシークレット |
| `AIza[...]{35}` | Google API キー |
| `BEGIN ... PRIVATE KEY` | 秘密鍵 |
| `192.168.` / `10.x.x.x` | 社内 IP アドレス |
