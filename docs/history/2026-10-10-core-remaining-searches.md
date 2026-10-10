# 残り検索3本のCore移行

## 範囲と判断

PR #94 merge後main `98a5e33`から、保全予定・保全実績・依存関係検索をSQLAlchemy Coreへ移行する。設備検索と同じpage CTE / observation LEFT JOINを固定allow-listの4検索に共通化する。保全実績はmigration 002に合わせたquery-only宣言を追加し、DDL生成や新Tool公開は行わない。

入力はapplication層で検証したfilterだけを受け取り、Tool / filterの固定辞書からColumnを選ぶ。maintenance_plan_idの明示NULLはIS NULL、省略は条件なしとする。source / targetは各entity_typeとentity_idをANDし、active=falseを含む値はbindparamで渡す。NULL条件以外の外部値はSQLへ補間しない。text・UUID・bool・integerのnative bindだけであり、独自bind / result processorは不要な範囲と判断する。

既存cursor署名・binding・TTL、page_size+1件のUUID昇順、空ページの観測時刻、LATEST_PER_CALL、readonly transaction、dict_row、エラー変換を維持する。SQL構造への外部identifier挿入を行わず、reads.pyの検索Raw SQL / Identifier組立を除去する。Engine / pool / autobegin / ORMは導入しない。

## 検証

- 対象Read / search / SQL Injection / READ_DSN / DB role試験245件成功（Dockerの実PostgreSQL）。
- 追加14件: 全検索のreadonly実UPDATE拒否（追加3）、予定 / 実績codeへの攻撃文字列bindと保存値再検索（4）、残り3検索のnative全値一致・未commit version可視性・page_size+1 / keyset境界（6）、source / target / active=falseの複合条件とbool bind分離（1）。
- 既存の明示NULLと省略のcursor区別、endpoint filter、FALSE条件、空結果、role、ページング、cursor改ざん拒否も回帰確認する。
- ruff check / format check成功（128 files）。
- 全体回帰2294件成功、1件skip、既存Starlette warning 1件（158.86秒）。

NFR-04、AC-01・04、T-SQL01〜03の対象Read部分の確認であり、SQL方針全体の完了とは扱わない。既存Starlette warningと終了時logging output failed表示は別のログ改善対象。

## 残課題と次工程

単件Read8本と検索4本はCoreへ移行済み。割当ReadとPrepare / Approval / Execute / Graph / Outbox関連のDBアクセスは安全な既存Raw SQLを維持する。次は割当Readの親version・期間[start,end)・空割当・explicit_as_ofが同一statementで返る契約を確認し、単位を区切って移行する。重要更新へ今回のnative Read用橋渡しをそのまま拡張しない。

API / Tool schema、DB schema / GRANT、業務要件、Snapshot / hash、更新transaction / lock、Graph / Outbox / Projectionは変更しない。LogiScopeコードの再利用はない。
