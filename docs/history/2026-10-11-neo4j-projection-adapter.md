# 実Neo4j Projection adapter

2026-10-11。PR #113 merge後のmain `b839a2c`を起点とする。

## 変更

- Neo4jProjectionを追加。公式driverの明示transactionを使い、driverの自動transaction retryを適用経路へ導入しない。Outboxによる再送を正とする。
- validated generationを要求し、一意markerへ一時propertyのwrite / removeでwrite lockを取り、version / hashを比較する。新しいversionだけで旧edge除去・新edge作成・marker更新をatomicにcommitする。同version同hash・古いversionはmarker確認後に成功し、同version異hash・不正markerは拒否する。
- endpoint / type変更はsource_record_idで旧edgeを除去。generationとaggregateの名前空間をエッジ種別の固定集合で限定し、DependencyRelationとAssignmentが同UUIDでも相互に削除しない。DISABLEはinactive edgeとmarkerを保存する。端点不存在時は全rollbackし、ノードを推測生成しない。
- data-model §10に共通label / marker labelの物理識別を追記。既存業務意味・方向・required / USES意味論は変更しない。
- 管理用schema設置はentity / aggregate marker / generationの複合・単一UNIQUEをidempotentに作成する。通常適用はschema DDLを行わない。
- driver 6.4.0と依存pytz 2026.5をlockへ追加。テスト用Neo4j 5.26.31 Communityはtmpfs・port非公開・デモと別compose projectで動かす。CIのrequired check名は維持し、既存全テストと共に実Neo4jテストを実行する。

## SQL / Cypherの扱い

PostgreSQLのDB accessは既存SQLAlchemy Coreのまま。今回のqueryはNeo4jのCypherでありSQLAlchemyの対象外。値はdriver parameterへ渡し、エッジidentifierは既存Relation種別とUSESからなるmodule-owned allow-listだけから組み立てる。外部入力をquery textへ補間せず、悪意あるUUID / relation typeはdriverアクセス前に拒否する。schema DDLは固定文字列の管理専用処理であり、Agent / APIへ任意Cypherを公開しない。

## 検証

Docker内の対象99件成功（6.43秒）、ruff check / format check成功（146 files）。Docker内の全体回帰試験は2430 passed / 1 skipped / 1 warning（追加34件、178.83秒）。

実Neo4jで全7エッジ種別・保存方向・属性・marker hash、同version / 古いversion再送、異hash拒否、端点 / type変更、DISABLE、端点不存在rollback、edge変更後の失敗rollback、leader喪失、未検証generation、不正marker、UUID名前空間・generation分離、UNIQUE・競合write lock・server timeoutを確認する。実PostgreSQLとNeo4jを組み合わせ、Graph commit後のAPPLIED保存失敗と冪等再送による復旧も確認する。

AC-13 / 18、NFR-04〜06、T-SQL04、test-plan §6の対象部分を確認。worker / controller / Graph分析全体の受入完了とは扱わない。

## 残り

通常worker起動loop、専用credentials / DB role、運用ログ、heartbeat、seed / Rebuild / controller drain、restore、Graph ToolとUIは未実装。現在のcompose.yamlではNeo4jを起動しない。テストfixtureのgeneration / endpoint生成を製品seedやRebuildの代わりにしない。例外のworker failure分類・DEAD連携も次工程。LLM / API / PostgreSQL業務仕様・migrationは変更せず、LogiScopeコード再利用はない。

## 技術根拠

- [公式driverの明示transaction](https://neo4j.com/docs/python-manual/current/transactions/)
- [公式locking説明：一時propertyへのwriteでmarkerを直列化](https://neo4j.com/docs/operations-manual/current/database-internals/concurrent-data-access/)
- [driverのserver互換性](https://neo4j.com/docs/python-manual/current/install/)
