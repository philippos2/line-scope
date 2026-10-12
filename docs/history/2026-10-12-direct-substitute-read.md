# 一段CAN_SUBSTITUTEの内部Graph読取

仕様正本ではなく、実装チェックポイントの記録。

正本domain-model §4 / §15.1 / §15.3に従い、既存Graph readerへsubstitute_candidatesを追加した。検証済み単一世代・Neo4j read transaction・PostgreSQL共有分析gate内で、指定targetへ入る直接CAN_SUBSTITUTEのsourceと関係factsをページ取得する。候補から先の関係は辿らず、通常影響／上流探索へCAN_SUBSTITUTEを追加しない。

activeな両端・関係、有効期間[start, end)、世代をfilterする。Equipment / Process / InfrastructureResourceに対象型を限定し、同一種別・正規UUID・正のsource version・required=falseを検証する。値はCypher bindで渡し、関係種別とquery構造は固定する。不正な関係factsはGraph未利用扱いで失敗し、正常な空集合へ隠さない。

順序はsourceの型・ID・source record ID。limit + 1でhas_moreを判定し、サーバ側のcontinuationで次ページを取得する。has_moreは候補なし／探索完全の判定ではなく、後続Applicationが全体予算と収集完全性へ反映する。候補存在は運転利用可能性・能力・安全性の保証ではない。除外対象自身を含め、どのsourceを実行可能代替として評価するかは後続の候補選択層が確認する。

追加17の実DBテストと既存Graph reader回帰、計43テストで、向き、ページ送り、一段制限、inactive、有効期間、同一種別と破損facts、不正引数、対象欠落を検証した。AC-G05 / G06 / G09、T-R14 / R15の候補読取部分を支えるが、共有予算での収集・必須閉包、PostgreSQL利用可能性、評価結果と関係／経路Evidenceの結合、Application / Tool / API公開は後続。
