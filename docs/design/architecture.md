# LineScope システムアーキテクチャ設計書

## 1. 構成原則

- PostgreSQL = System of Record
- Neo4j = Dependency Graph Derived Read Model
- Qdrant = RAG Derived Vector Index
- 承認 = 認証済みApproval API
- 実行 = 認証済みExecute API
- Graph Projection = PostgreSQL Transactional Outbox
- Graph分析 = CURRENT時のみ
- v1 = 単一工場

## 2. 構成

```text
Client
  |
  +-- POST /agent
  +-- GET  /update-requests/{id}
  +-- POST /approvals/{id}/approve|reject
  +-- POST /update-requests/{id}/execute
              |
Application API / Authentication
              |
        Agent Orchestrator
          /      |       \
 Read Tools   Graph Tools  Prepare Tools
    |            |             |
PostgreSQL     Neo4j       PostgreSQL
    |                          |
    +------ Transactional Outbox
                    |
             Projection Worker
                    |
                  Neo4j

Knowledge Retrieval -> Qdrant -> PostgreSQL metadata re-authorization
```

## 3. 認証と実行境界

user_id / roleはTrusted Execution ContextとしてAPI層から注入する。

ApprovalとExecuteはLLMの意図解釈から切り離す。

## 4. PostgreSQL

業務正本、承認、更新要求、履歴、Outbox、KnowledgeDocument metadataを保持する。

## 5. Neo4j

構造依存探索専用。任意CypherをLLMへ公開しない。

## 6. Qdrant

非構造文書の意味検索用。認可の正本ではない。

## 7. Graph同期状態

同期判定はcommit済みOutbox状態集合とgraph_projection_controlで行う。優先順位はtransaction-designを正とする。

- CURRENT: 初期化済みgenerationがあり、REBUILDING / ERROR条件がなく、commit済みGraph対象イベントがすべてAPPLIED
- LAGGING: PENDING / PROCESSING / RETRYABLEが存在
- ERROR: DEADまたはfatal_errorが存在（未初期化・generation欠損・Projection重大障害等）
- REBUILDING: 再構築中

global event_id watermarkのみでCURRENTを判定しない。

## 8. Graph-affecting更新

以下はGraph対象:
- DependencyRelation CREATE / UPDATE / DISABLE
- ProductionOperationEquipmentAssignment CREATE / UPDATE / DISABLE
- Graphノード存在に影響する対象エンティティの作成・無効化を将来追加した場合

設備状態・保全結果等の状態値はNeo4jへ複製せず、必要時PostgreSQLを読む。

## 9. Rebuild

v1では再構築中にGraph-affecting更新を共通Advisory Lockで短時間停止できる方式を採る。これによりcommit順watermarkに依存せず一貫Snapshotから再構築する。

## 10. 障害分離

Neo4j障害はGraph分析、Qdrant障害はRAG、LLM障害は自然言語処理に限定する。PostgreSQL障害時は正本参照・更新を停止する。

## 11. 整合境界

Graph分析はshared、Graph-affecting更新・Projection・Rebuildはexclusiveの共通Graph mutation lockを使う。Evidenceに観測時刻とgenerationを載せる。設備状態等は別のPostgreSQL statement Snapshotで確認し、分散Transactionは導入しない。

Rebuild controllerは単一workerと同じleader lockを取得してOutboxをdrainし、mutation lock下で正本Snapshotから新generationを構築する。順序・復旧はtransaction-design §11・17に従う。

## 12. 技術構成と実装チェックポイント

| 層 | 採用技術 | 責務・実装時期 |
|---|---|---|
| Backend | Python / FastAPI | HTTP API、認証済み実行Context、Tool制御。最初の実装チェックポイントで起動基盤を作る |
| 正本DB | PostgreSQL | 業務データ、Approval、UpdateRequest、履歴、Outbox、文書metadata。最初は接続・migration基盤のみ |
| DB driver | Psycopg 3 | PostgreSQL接続・Transaction制御 |
| ASGI server | Uvicorn | FastAPIのHTTP実行 |
| 構造依存の派生モデル | Neo4j | CURRENT時の依存探索。後続のGraphチェックポイントで実装する |
| 非構造文書の派生Index | Qdrant | embeddingによる文書検索。後続のRAGチェックポイントで実装する |
| LLM / embedding model | 評価後に選定 | プロダクト・model versionは未確定。試作アダプターを採用確定・品質承認と扱わない |
| Client | HTTP / curl等 | v1ではUIを実装しないため、Reactは未採用 |

pgvectorはこの構成では採用しない。ベクトル検索の責務はQdrantに置く既存設計を維持する。
LogiScopeの技術構成を継承したものではなく、LineScopeの責務定義に基づく構成とする。
採用packageのversionはpyproject.toml、検証環境と起動手順はoperations.md / README.mdに記録する。
基盤チェックポイントのhealth / readiness成功は、業務API・Graph・RAGの実装完了を意味しない。
