# Neo4j generation構築・検証

## 範囲

正本RebuildSnapshotから新UUIDのgenerationを明示Neo4j Transactionで構築する。既存generationを上書きせず、inactiveを含むノード、Relation / USES、aggregate markerを作成する。通常workerと共通の物理edge mappingを使用し、Cypherの種別identifierは固定allow-list、値はparameterで渡す。

実際のノード・エッジ・marker・generation markerの集合、属性、端点、version、hashを照合してからvalidated=true / validated_atを保存する。集合比較で件数・余分な属性・重複も検証する。検証失敗やcommit前のleader喪失は全書込みをrollbackする。Neo4j transaction timeoutを明示し、driver自動retryを使わない。

## 出所の技術判断

初期正本にはOutboxがないため架空event IDを生成しない。Snapshot由来marker / edgeのsource_rebuild_idを構築generationとし、source_outbox_idをNULLとする。data-model §12へこの配送出所を明示した。通常workerは検証済みgenerationとsnapshot_hashを確認してseed由来markerを受理し、新versionではevent出所へ置換する。同version不一致の拒否は維持する。

## 検証と後続

実Neo4j / PostgreSQLの試験で属性・件数照合、inactive、empty、既存generation拒否、欠損端点、重複入力、検証failure rollback、leader喪失、seed後の再送・新version、marker出所不正を確認する。T-R11 / R12の世代検証部分であり、全体Rebuild完了ではない。

呼出し元がPG leader / exclusive mutation lockを保持する。PG pointer切替、Outbox drain、失敗flag復旧、controller / CLI、runtime権限・Graph Toolは後続。Neo4j commit後のleader喪失は公開成功と推測せずcontrollerが状態を照合する。旧generationのcleanupは行わない。
