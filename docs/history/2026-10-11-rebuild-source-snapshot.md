# Rebuild用正本Snapshot取得

## 実装範囲

transaction-design §11手順5の、一貫したPostgreSQL statement Snapshot取得を内部部品として実装する。`persistence/core_graph_snapshot.py` がSQLAlchemy Coreの固定UNION ALLで5種のノードとDependencyRelation / Assignmentを単一statementで取得し、`graph/rebuild_snapshot.py` が通常Projectionと同じpayload builderで正規化する。

active=false、過去・未来の期間を含む全登録Relation / Assignmentを保持する。ノードはtype / ID / entity_version / activeのみを投影し、設備状態・予定値・名称等をGraphへ追加しない。SQL identifierはコード内の固定表、値はCoreのbind parameterで渡す。

## 呼出し契約

呼出し元がleaderとREAD COMMITTED transaction、exclusive mutation lockを所有する。readerはisolationと既存exclusive lockを検査するが、leader取得・Outbox drain・未処理0判定は後続controllerの責務である。readerは接続を開かず、lock再取得・commit・rollback・control変更をしない。既存lockの検査だけはPostgreSQL固有のpg_locks問い合わせをbind parameter付きRaw SQLで行う。

内部Snapshot hashはschema_version=1、ID順のノードと型・ID順の正規化aggregate payloadを対象とする。observed_at、generation、配送event IDを含めない。timestampは既存canonical UTC形式、NULL / active=falseはそのまま保持する。これは更新ApprovalのCanonical Snapshotとは別の内部形式である。

## 試験と未実装

実PostgreSQLで全型、inactive、NULL、version変更、時刻・session timezoneによらないhash、empty集合、lock拒否、単一source statementとcaller rollbackを検証する。T-R系のRebuild一貫性に対応する部分部品の試験であり、Rebuild全体やGraph CURRENTの成立とは扱わない。

Neo4j世代構築・件数/属性検証、drain、generation切替、失敗復旧、controller権限・CLIは後続。HTTP / Agent Toolに公開しない。初回seedとして利用可能とするには後続の構築・検証・公開が必要。
