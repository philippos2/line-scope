# 実装前の最終確認記録

日付: 2026-10-09

## 経緯

利用者から、実装中に解釈が揺れやすい意味論・Snapshot・同期・Rebuild・API契約を再確認するよう指示を受けた。新しいレビュー文書を追加せず、必要な修正を既存19文書へ反映する方針で作業した。

その後、利用者の「ちょっと待って。いくつか確認したい」という指示により作業を停止した。本記録は、続いて依頼された履歴整理の一環として作成したものである。

## 反映内容

| 対象文書 | 補足した契約 |
|---|---|
| [domain-model.md](../requirements/domain-model.md) | AND依存と代替候補間OR、AVAILABLE候補優先、UNKNOWNのみなら未確定、一段置換のみ、除外前から不成立の対象をSPOFと断言しない |
| [transaction-design.md](../implementation-design/transaction-design.md) | retry keyはuser・更新要求単位、永続保存・TTLなし、終端再送でも旧要求返却、内容不一致409。decimal / float・重複JSON key・surrogate・timezoneなし拒否、C0 escape固定、schema version拒否。worker claim後のlock、leader → mutationの順、同期変化時の結果破棄、切替前後crash確認 |
| [data-model.md](../design/data-model.md) | generation markerのvalidated / snapshot_hash / validated_atと、検証後のcontrol pointer切替 |
| [api-tools.md](../implementation-design/api-tools.md) | retry契約の参照、contextと更新要求・承認・冪等性の区別、全Targetの権限・承認条件を満たさない場合の全体拒否 |
| [test-plan.md](../implementation-design/test-plan.md) | retry scope・終端・異内容、canonical境界値、leader / mutation競合、generation切替crash、OR・未知・一段置換の追加ケース |

いずれも前段で採用された業務方針と既存設計の具体化であり、一般AI品質の数値閾値や具体モデルを固定していない。

## 停止時点と検証範囲

追加修正は保存済み。関連正本文書を突き合わせたが、この追加修正後の最終機械チェックと実装テストは、停止時点で未完了。前段のセルフレビュー・文書チェック結果は[前段報告](2026-10-09-documentation-update-report.md)に記載しており、追加修正の実装検証結果を意味しない。

実行環境準備として空のsrc / tests / scriptsディレクトリ、ローカルPython仮想環境と依存パッケージを用意した。プロダクトの実装ソースはまだ作成していない。Dockerソケットへのアクセスは拒否され、サービスを起動できたとは扱っていない。

実装作業は停止中。利用者の確認が終わるまで再開しない。
