# 法的書類テンプレート

> ⚠ **重要な免責事項**
>
> これらは **雛形（テンプレート）** です。実際に公開・運用する前に、必ず **顧問弁護士または行政書士のレビュー** を受けてください。
> 業種・取引形態・取り扱う情報の種類により追加の条項が必要になる場合があります。
> 本リポジトリのメンテナは、これらの雛形を使用した結果生じた法的問題に対して一切の責任を負いません。

## 収録ファイル

| ファイル | 用途 | 公開先 URL の例 |
|---|---|---|
| `terms_of_service.md` | 利用規約 | `https://inquira.example.com/legal/terms` |
| `privacy_policy.md` | プライバシーポリシー | `https://inquira.example.com/legal/privacy` |
| `specified_commercial_transactions.md` | 特定商取引法に基づく表記 | `https://inquira.example.com/legal/sct` |

## 公開フロー

1. 各 `.md` ファイル内の `[要置換]` `[XXXX年XX月XX日]` などのプレースホルダーを実情報に置き換える
2. 顧問弁護士／行政書士にレビュー依頼（推奨：3〜10万円程度）
3. 自社サイトに HTML として掲載 or PDF として顧客に提示
4. Stripe Payment Link や契約フォームの利用規約欄に URL を貼る

## Stripe Payment Link での参照方法

Stripe ダッシュボード → 商品 → Payment Link 編集：
- **利用規約 URL**: `https://inquira.example.com/legal/terms` を必須チェックに設定
- **プライバシーポリシー URL**: 同上

これにより、決済時に顧客が必ず規約に同意したことが Stripe 側に記録される。

## 変更履歴

- 改訂のたびに「最終更新日」を本ファイル内に明記すること
- 重要な変更（個人情報の取り扱い変更、料金条項の変更等）は **30日以上前** に顧客へ通知することが望ましい
