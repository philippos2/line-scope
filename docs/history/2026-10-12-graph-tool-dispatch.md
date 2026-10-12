# 通常Graph Toolの内部登録とAgent接続

## 変更範囲

ToolDispatcherへGraphAnalysisを明示注入した場合に限り、trace_downstream_impact / trace_upstream_dependenciesを公開する。未注入の既存API起動構成ではGraph Toolを広告しない。Read / Prepareの既存経路と、Approval / Execute非公開を維持する。

Tool入力はapi-tools §9・10・17のtyped target、relation filter、explicit_as_of、requested limitsを表し、追加フィールドを拒否する。実行時の認可・入力検証・同期判定・時間上限・Evidence生成は既存GraphAnalysisとread gateに委ねる。trusted retry metadataをGraph入力へ転送しない。

ReadAgentは公開されたGraph Toolだけを呼び出せる。プロンプトは探索不完全と影響なしを区別し、到達関係から停止・安全・能力を断定しない。プロンプトのみを安全保証とせず、非CURRENT時にGraph結果を公開しない既存境界を実DB試験で確認する。

## 検証範囲と残作業

実PostgreSQL / Neo4jと決定論的LLMで、両方向の経路・state version・Evidenceの保持、PATH_COUNTによる不完全結果、REBUILDING時の拒否を検証する。未注入時の非公開、schemaコピーの独立性、権限・未知入力の拒否も確認する。

API composition rootのNeo4j接続設定・必須system limits・接続ライフサイクルは後続。実LLMの選択品質、RAG、SPOF、共通依存、代替分析は対象外。通常Graph機能の一連の追加はまだ完了していない。LogiScopeのコードは再利用していない。
