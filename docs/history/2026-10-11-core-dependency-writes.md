# DependencyRelation更新・endpoint lockのCore移行

## 判断と範囲

PR #107 merge後main `bc64fd5`から開始。DependencyExecuteのendpoint FOR SHARE、DependencyRelation CREATE / UPDATEの3箇所を固定Core statementへ移行する。既存はparameterized SQLとallow-listされたIdentifierを使用しており、脆弱性修正とは扱わない。query-only Columnはmigration 002に合わせ、DDL / ORM / Engine / poolは導入しない。LogiScopeコード再利用はない。

## 維持する境界

Graph exclusive lock → Request / Approval lock → Target再検証 → endpoint参照lockの順序を維持する。endpointはEquipment / InfrastructureResource / Process / Product / ProductionOperationの固定Table / identity Columnから選び、IDをbindする。kind / ID順のlock、存在とactiveの確認、最終集合・期間・混合循環の検証はserviceに残す。

CREATEは確定afterの全業務項目・ID・versionを保存し、created_at / updated_atには既存executed_atを使う。UPDATEはID / expected_versionを条件に確定afterの業務項目・versionとupdated_atを保存し、ID / created_atは変更しない。UTC文字列、無期限終了のSQL NULL、required / activeを維持する。rowcountのVERSION_CONFLICTとUniqueViolationのCREATE_CONFLICT変換はserviceに残す。

対象tableの延期可能UNIQUEをpg_constraintから固定SQLで照会し、その名前をpsycopg IdentifierでquoteしてSET CONSTRAINTSを実行する。これはPostgreSQL固有の制約制御としてRaw SQLを維持する。外部入力から制約名を生成しない。最終集合検証 → 制約延期 → UPDATE / DISABLE → CREATE → 制約即時検査 → 履歴 / Outbox / Approval消費 / 完了 / Auditの順序とrollbackを維持する。

固定JSONB集約による全体観測とcurrent snapshotは単一statementの観測境界を明確に保つためRaw SQLを維持する。DB schema / GRANT、API / Tool、Snapshot / hash、Graph設計・業務ルールは変更しない。

## 検証

- Docker内の対象169件成功（追加8、27.89秒）。
- Docker内の全体回帰試験2,336件成功、1 skipped、1 warning（166.80秒）。
- 追加2件はUPDATE / DISABLEのstale version拒否、version増分、ID / created_at保持、旧version再使用拒否を実DBで確認する。
- 追加5件は全endpoint種別のFOR SHARE保持中の別接続更新timeout、transaction終了後の成功、未知IDとinactiveの読込を確認する。
- 追加1件はallow-list外のkindをSQL identifierへ昇格できず、拒否後も正常な参照が可能なことを確認する。SQL表記検出フックは使用しない。
- Docker内のruff check / format check成功（138 files）。

NFR-04〜06、AC-05・10〜13、T-SQL01・03〜05の対象部分の確認であり、受入基準全体の完了とは扱わない。

## 残る工程

Graph / Outbox・管理処理、Prepare / Approval等の一部参照には安全なRaw SQLが残る。通常操作はCoreを優先し、PostgreSQL固有処理と複雑な集約は具体的な理由で維持する。
