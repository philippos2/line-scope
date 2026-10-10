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
| DBアクセス標準 | SQLAlchemy Core（段階導入） | 構造化query・parameter binding・明示的Transaction。既存実装はPsycopg 3によるRaw SQLであり、Core導入済みとは扱わない |
| DB driver | Psycopg 3 | PostgreSQL接続。Core導入後もdriverとして使用可能 |
| ASGI server | Uvicorn | FastAPIのHTTP実行 |
| 構造依存の派生モデル | Neo4j | CURRENT時の依存探索。後続のGraphチェックポイントで実装する |
| 非構造文書の派生Index | Qdrant | embeddingによる文書検索。後続のRAGチェックポイントで実装する |
| LLM / embedding model | 評価後に選定 | プロダクト・model versionは未確定。試作アダプターを採用確定・品質承認と扱わない |
| Client（サーバ実装フェーズ） | HTTP / curl等 | Backendの実装・検証を先に完了する |
| Frontend（後続フェーズ） | frameworkは後続設計時に確定 | サーバサイド完成後、AIP Analystを参考にLogiScopeよりリッチなUIを構築する。現チェックポイントには含めない |

pgvectorはこの構成では採用しない。ベクトル検索の責務はQdrantに置く既存設計を維持する。
LogiScopeの技術構成を継承したものではなく、LineScopeの責務定義に基づく構成とする。
採用Backend packageのversionはbackend/pyproject.toml、検証環境と起動手順はoperations.md / README.mdに記録する。
基盤チェックポイントのhealth / readiness成功は、業務API・Graph・RAGの実装完了を意味しない。

## 13. リポジトリ構成

LineScopeは単一リポジトリとし、ルートにbackend / frontend / docsを置く。
Python packageはbackend/src/linescope、Backendテストはbackend/tests、package・依存・Tool設定はbackend/pyproject.tomlで管理する。
frontendは後続UIの配置先とし、サーバサイド完成前は実装を追加しない。
docsは仕様の正本と変更履歴を保持する。実装ディレクトリの分離でDB・認証・Approval / Executeの責務を変更しない。

## 14. Decision Packageの責務

PostgreSQLは新しい能力・費用・計画・安全・履歴情報についても業務正本を担う。必要な構造はPO-B01〜07とdata-modelで確定する。Neo4jは依存・経路の派生探索モデル、Qdrantは認可された文書の検索Indexに限定し、費用・安全判定の正本にしない。

アプリケーションの決定論的計算処理が、認可された正本入力と定義済みルールから能力不足・損失・期間計算を行う。Agentは必要なRead / Graph / 計算処理を組み合わせて説明する。現行Tool一覧には計算Toolがないため、api-toolsの拡張契約確定後に実装する。LLMに算術・安全ルールの確定を委任しない。

Decision Packageは各結果の観測時刻・version・Graph generation・評価期間を示す。既存のshared / exclusive Graph lockは構造探索の境界であり、全業務情報の同時Snapshotを保証しない。計算入力のversion付き観測結果を固定して評価し、評価後のcurrent valueと混同しない。将来予測・予定の意味と再評価条件は対応するPO判断とAPIで確定する。

## 15. SQL / Database Access Policy

2026-10-10 PO決定。優先順位はSecurity → Data integrity → Transaction correctness → Auditability → Explicitness → Maintainability → Implementation convenience。
Secure by construction. Explicit by default. Auditable by design.

### 15.1 入力とDBアクセスの境界

API / Agent → validated application/tool arguments → authorization → application/service → SQLAlchemy Core → PostgreSQLを標準とする。
LLMはnamed Toolと構造化引数だけを生成できる。LLM出力もuntrusted inputであり、型検証を認可の代替にしない。任意SQLを生成・実行するToolを追加しない。

通常のSELECT / INSERT / UPDATE / DELETE / JOIN / RETURNING / PostgreSQL ON CONFLICT / FOR UPDATE / 条件付きversion UPDATE / Transaction内の複数操作ではCoreを第一選択とする。全面ORM化は行わない。
構造化queryとdialectで通常アクセスのDB種類・version差による変更影響を抑える。PostgreSQL固有のadvisory lock・JSONB・延期可能制約等は明示的に隔離し、Core導入をDB非依存・version互換性保証とは扱わない。PostgreSQLを正本とする技術選定は維持する。
外部・動的な値は必ずbind parameterとして渡す。f-string・文字列連結・format・手動escapeで値をSQL構文へ埋め込むことは禁止する。DBから再取得した文字列も値としてbindし、SQLコードへ昇格させない。
テーブル・列・ORDER BY対象・directionは値bindでは扱えないため、外部入力から自由生成せず、固定allow-listからTable / Column / asc / desc等を選択する。

### 15.2 Raw SQLとORMの例外

Raw SQLは、SQLそのものの方が明確な処理、PostgreSQL固有機能、Coreで過度に複雑になる集計 / CTE / window、根拠のある性能上の必要性で許容する。値はbindし、Transaction境界と選択理由をコードまたは設計から追跡可能にする。Core経由のRaw SQLは固定textとbindを使用する。外部入力を渡すtext(f"...")等は禁止する。
固定DDL・同梱migration script・値を持たない固定SQLは、外部入力を受けない管理経路の例外として扱う。migrationはruntime roleで実行しない。
ORMはCoreと比較した明確な保守上の利益を説明できる場合だけ限定採用する。Prepare / Approval / Execute / Snapshot / Audit / Outbox / Projectionの重要更新に、autoflush、lazy loading、identity map、dirty tracking、cascade等を理由なく持ち込まない。

### 15.3 整合性・権限・監査

PostgreSQLをSystem of Recordとし、PK / FK / UNIQUE / NOT NULL / CHECK等で保証できる不変条件はDBでも強制する。アプリ検証はDB制約の代替ではない。
重要更新は、認可確認・lock / 現在値・expected version・業務不変条件・正本更新・業務監査・対象Outboxを明示的Transactionで確定する。途中失敗は全rollbackし、stale versionを暗黙上書きしない。
ApprovalはExecuteとは別Transactionであり、承認だけでは業務正本を更新しない。Executeでは対象version・保存Snapshot・現在権限・期限を再検証し、必要Outbox、承認消費、COMPLETED結果、成功監査まで原子的に確定する。lock順序・対象Outboxの条件・失敗後の別Transactionによる失効と失敗監査はtransaction-designを正とし、この概念図を理由に既存状態遷移を変更しない。

DB roleは検索と認可済み変更を分離し、runtimeにDDL・superuser権限を与えない。Read Toolへ不要なUPDATE / DELETE権限を渡さない。migration / bootstrapと将来のworkerにも用途別の必要権限だけを付与する。
password / token / credential / secretや不要な機密情報をログへ出さない。SQLログのbind値も同様。業務監査はwho、操作、対象、前後version、結果、時刻、相関IDを追跡し、Debug logと分離する。DB例外は定義済みAPI errorへ変換し、SQL本文・schema・hostname・path・stackを外部へ返さない。ログ契約はoperationsを正とする。

### 15.4 移行と適合確認

既存アクセスをA Core / B 安全なRaw SQL / C ORM / D 危険・疑わしい動的SQL / E identifier組立 / F 重要更新に棚卸しする。E / Fは他分類と重複する。文字列操作だけで脆弱性と断定せず、untrusted inputからSQL構文へのdata flowを確認する。
危険な動的SQL → 安全なparameterization → Core適用の順に改善し、安全な既存Raw SQLを非ORMという理由だけで機械変換しない。新規通常アクセスはCoreを標準とする。重要更新を抽象化・コード削減のために意味変更しない。
適合はInjection、認可、atomic rollback、version競合、DB制約、DB roleの自動テストで確認する。重要変更を開始する前に棚卸し結果・推奨変更・Transaction / lock / Approval / Snapshot / Outbox / Projectionへの移行リスクを報告する。
実装状況・不足・改善順序は[2026-10-10棚卸し](../history/2026-10-10-sql-database-access-review.md)に記録し、本節の方針を実装済みと混同しない。

初回Core移行はget_equipment / get_equipment_stateのSELECTに限定する。固定Table / Columnのquery-only宣言からSELECTとUUID bindを構築し、PostgreSQL psycopg dialectでcompileしたSQL本文とparameter辞書を分離して既存psycopg接続で実行する。literal_bindsやparameterの文字列補間は使用しない。DB型・制約の正本はmigrationであり、宣言からDDLを生成しない。
この橋渡しはUUIDをbindする2本のRead専用で、汎用のSQLAlchemy実行層ではない。SQLAlchemy Engine / pool / autobegin / ORMを導入せず、既存のreadonly Transaction・接続寿命・dict_row・DB例外変換を維持する。JSON / custom type等のbind・result processorを必要とする処理や重要更新へそのまま拡張しない。後続移行は型処理・接続所有権・lock・rollbackの必要性を個別評価する。
