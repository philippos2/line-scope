# 初回Graph構築の明示管理CLI

install-graph-schema / rebuild-graph / rebuild-graph --recoverを管理CLIへ追加した。GraphAdministrationは既存leaderとRebuildControllerを呼び、通常workerやAgentへschema・公開・回復の権限を追加しない。graph-adminは通常Compose起動から外し、helpを既定とする。正本はoperations §17。

schema作成の各statementを明示・時間制限付きNeo4j transactionへ変更し、1ms未満が無制限timeoutへ変換されることを既存timeout helperで防ぐ。各DDLのcommit単位は既存どおりで、複数DDL全体のrollbackを保証しない。leader → mutation排他の順で保持する。

実PostgreSQL / Neo4jで初回検証済みgeneration公開、再構築・旧generation保持、leader競合、残存flagの明示回復、実CLIを検証した。業務デモGraph・実LLM選択品質は後続。一連の通常Graph機能群はまだ完了していない。LogiScopeコードは再利用していない。
