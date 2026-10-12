# APIのGraph分析接続とHTTP契約

## 変更

API composition rootで、設定済みNeo4j driverとGraphAnalysis / GraphStateReaderを組み立てる。設定・driver所有権はbootstrap、HTTP応答はInterface、分析とEvidenceはApplication、実接続は既存Graph adapterへ分離する。通常handlerにSQLやdriver操作を追加しない。設定の正本はoperations §15。

api-tools §14・18に従い、Graph非CURRENT系codeをHTTP 503、不完全探索をHTTP 200かつstatus=partialへ変換する。analysis_mode=CURRENT / EXPLICIT_HISTORICALを分析dataとEvidenceに明示する。過去指定は完全point-in-time復元でも現在状態による利用可能性の確定でもない。

## 検証と残作業

実PostgreSQL / Neo4jと決定論的LLMでPOST /agentから両方向の経路と正本state versionを検証する。driverの注入・設定による生成、API終了時の所有driver解放、借用driver維持、不正設定、secret非表示、権限拒否、PATH_COUNT、REBUILDINGを確認する。試験fakeの検索接続契約不足は試験側で修正した。

標準ComposeのNeo4j / worker常駐、デモGraph投入、実LLM選択品質、RAG、SPOF、共通依存、代替は後続。通常Graph機能群はまだ完了していない。LogiScopeのコードは再利用していない。
