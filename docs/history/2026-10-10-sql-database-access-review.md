# SQL / Database Access Policy採用・初回棚卸し

日付: 2026-10-10。判断主体: PO（方針・改善順序をCodexへ委任）、Codex（静的棚卸し・改善提案）。
対象revision: `8724059`（PR #87 merge後）。コード・設定・DBは変更しない調査であり、今回の変更は文書のみ。

## 1. 決定・正本と現状の区別

SQLAlchemy Coreのparameterized queryを標準DBアクセスとする。全面ORM化しない。Raw SQL / ORMは必要性を説明できる例外とし、安全な既存Raw SQLを機械変換しない。
優先順位はSecurity、Data integrity、Transaction correctness、Auditability、Explicitness、Maintainability、Implementation convenience。
POはCoreによるDB種類・version差の影響軽減も指摘した。通常CRUDのdialect吸収を活用し、PostgreSQL固有機能を隔離する。別DB対応を新しいv1要件にせず、互換性は実DBで検証する。
方針正本は[architecture §15](../design/architecture.md)、Security要件は[非機能要件NFR-04](../requirements/non-functional-requirements.md)、試験仕様は[test-plan §15](../implementation-design/test-plan.md)。更新・lock・承認・Outboxの意味は既存transaction-designを維持する。

本記録は時点付きレビューであり仕様正本ではない。Core導入、DB role分離、追加Security試験は未実装であり、今回の文書化だけで方針適合を完了扱いしない。

## 2. Current Stateと計数方法

backend/src/linescopeのPython ASTでDB execute / executemanyの呼び出し箇所を抽出し、113箇所を確認。実行時件数・SQL内のstatement数・テストfixtureのSQLは数えない。executemanyは0。scripts配下に直接のSQL実行はない。

| 分類 | 件数 | 意味 |
|---|---:|---|
| A Parameterized SQLAlchemy Core | 0 | SQLAlchemy依存・利用なし |
| B 安全なRaw SQL | 112 | 値bind98箇所と外部値を持たない固定SQL等14箇所。psycopg.sql組立を含む |
| C ORM | 0 | ORM利用なし |
| D 危険な動的SQL | 確認されたもの0 | 調査範囲でuntrusted値をSQL構文へ埋め込む経路は確認しなかった。将来の安全性保証ではない |
| E Dynamic identifier | 7 | Bに重複。readsの2箇所、dependency_executeの5箇所 |
| F Critical write path | 75 | Bに重複。変更要求保存・承認・実行・監査・Outbox処理内の呼び出し。別のread-only Snapshot観測や現在値再取得、共通Transaction設定はこの件数に含めない |
| 管理用migration script実行 | 1 | database.migrateの同梱script。bindする外部値がないDDLで、API / Agent経由なし。Bとは別計数 |

Bとmigrationの合計が113。E / Fを合計へ加えない。

| モジュール（backend/src/linescope） | 呼び出し箇所 |
|---|---:|
| approvals.py | 20 |
| audit.py | 6 |
| database.py | 8 |
| demo_seed.py | 4 |
| dependency_execute.py | 8 |
| dependency_prepare.py | 1 |
| execute.py | 29 |
| graph_leadership.py | 2 |
| graph_locks.py | 2 |
| outbox.py | 2 |
| prepare.py | 2 |
| production_assignment_execute.py | 6 |
| production_command.py | 1 |
| production_prepare.py | 2 |
| projection_state.py | 2 |
| proposals.py | 14 |
| reads.py | 4 |
| 合計 | 113 |

検索値、ID、更新値、canonical JSON、認証Context由来ID等はexecuteの第2引数へ渡す。SET TRANSACTION等の固定SQLをbindなしという理由で脆弱と判定しない。

## 3. Security Findings

### S-01 runtime DB権限過大 / 未分離 — High、MUST FIX

- 入力源: 認証済みAPI / Agent / Toolの入力。credentialはサーバ設定であり外部入力からroleを選択する経路はない。
- 構造: compose.yamlのAPIとmigrateが同じlinescope DSNを継承し、PostgreSQL初期化POSTGRES_USERもlinescope。create_appは同じDatabaseをRead / Prepare / Approval / Executeへ注入する。用途別roleのCREATE / GRANT / REVOKEは存在しない。
- 到達可能性: SQL Injectionが成立することを確認した指摘ではない。新規DBの標準Compose初期化ではAPIもsuperuser接続となる構成であり、アプリの誤実装・侵害時の影響をDBで抑えられない。現在のREAD ONLY Transactionは有益だが、credential自体からmutation / DDL権限を除いたことにはならない。
- 根拠: [PostgreSQL公式image説明](https://github.com/docker-library/docs/blob/master/postgres/README.md#postgres_user)はPOSTGRES_USERがsuperuserとして作成されると説明する。既存volumeの実role属性は別途確認が必要。今回docker psで稼働コンテナがなく、実DB権限の照会は行っていない。
- 是正: migration / bootstrap管理接続と非superuser runtime接続を分離。Read用と認可済み変更用の接続を分け、read roleは必要SELECTのみ、runtimeはDDL禁止、audit / historyは原則INSERTだけ等の用途別GRANT。schema / sequence / function / default privilegesと将来workerの必要権限も確認し、管理credentialをAPIへ渡さない。

### S-02 Injection回帰テストの網羅性不足 — Medium、MUST FIX

- 入力源: 設備名・業務コード・保全結果等のAPI / Tool自由文字列、未知filter / Tool / identifier候補。
- 構造: 現実装は値bindと型・key制限。悪意文字列の検索によるSQL構造変更は確認していない。
- 到達可能性: 脆弱性の再現ではなく検証不足。test_search_reads.pyのtest_explicit_filtersに`'; DELETE FROM equipment; --`を設備名検索へ渡す1ケースがある。しかしAPI / Agent境界、ORによる検索拡大、更新での保存・再読込（second-order）、DB不変、DB roleまでの体系的な検証ではない。
- 是正: T-SQL01〜05を段階実装し、悪意文字列は単なる値となること、型不一致は拒否されること、表・行・監査が意図せず変わらないことを実PostgreSQLでassertする。
- 前回の限定調査で専用ケースを見落としていたため訂正。「テストが存在しない」ではなく「既存1ケースだけでは不足」。

### S-03 動的SQL候補のdata flow確認 — Informational、NO CHANGE / 一部SHOULD FIX

| 箇所 | 入力源・組立 | 実際の到達可能性 | 判断 |
|---|---|---|---|
| reads.pyのget / search | Tool名とfilterはuntrustedだがSCHEMASと固定GET_TOOLS / SEARCH_TOOLSで制限。table / columnは固定対応表または検証済みfilter fieldからsql.Identifier、値はbind、ORDER BYは固定ID | 任意identifier・SQL断片は通らない | 今回はNO CHANGE。Core移行の最初の通常query候補 |
| dependency_execute.pyのendpoint / INSERT / UPDATE | entity typeは検証済み固定domain集合からENDPOINT_TABLESへ解決。列は固定FIELDS。値はbind | 外部値がSQL構文にならない | NO CHANGE。identifier quotingとallow-listを維持 |
| dependency_execute.pyのSET CONSTRAINTS | dependency_relationのpg_constraintからdeferrable UNIQUE名を取得しsql.Identifierで引用 | DB文字列を無引用のSQLとして実行しない。自由なAPI引数なし | NO CHANGE。採用例外理由を保つ |
| proposals.py / approvals.py / execute.pyのLOOKUP.replace | 固定定数内の固定WHERE / SELECTだけを置換。ID等は第2引数bind | replaceに外部文字列を渡さない | Injection修正不要。保守性上は構造化query化候補 |
| graph_locks.py、execute.pyのquery切替 | サーバbool / 内部集合から固定SQLを選択し値bind | 条件がSQL断片を生成しない | NO CHANGE |
| database.pyのmigration script | 同梱sqlファイル、CLI管理操作。testsだけが代替sourcesを注入 | HTTP / Agentからscriptを受け取る経路なし | 管理用Raw SQL維持。S-01のcredential分離は必要 |

テストfixtureのf-stringで固定テーブル名・trigger操作を組み立てる処理も存在するが、本番入力経路ではない。文字列操作だけでSQL Injectionと断定しない。

## 4. Transaction Review

| 処理 | 境界・lock・version | 監査 / Outbox / 状態 |
|---|---|---|
| Prepare | 正本の別read-only観測からcanonical Snapshotを固定し、ProposalStore.saveの一Transactionで要求・全Target・Approval保存。retry一意制約、置換時Request → Approval lock | PREPARE監査、新要求保存と旧要求失効・置換監査が原子的。業務値・Outboxは変更しない。観測から保存までversionが変わる可能性はApprove / Executeで再検証 |
| Approve / Reject | ProposalStore._transaction下、Request → Approval → 対象lock。canonical/hash、現在role、version / CREATE一意性等を検証 | 承認・要求状態・成功監査が同一commit。業務正本 / Outboxは対象外。競合時失効をcommitしてから定義済みエラーを返す |
| Execute | Graph差分時はGraph排他 → Request → Approval → 業務対象。owner、現在requester / approver権限、全before / version / CREATE条件、hash、期限、最終業務制約を検証。条件付きUPDATEとrowcount確認 | 正本、history、必要Outbox、Approval消費、COMPLETED・固定execution_result、成功監査が同一Transaction。Outbox helperは独自commitしない |
| 失敗後の失効 / 失敗監査 | 主Transactionのrollback後に別Transactionで対象を再lock・再検証し、終端結果を上書きしない | 失効状態とその監査は同一commit。別の失敗試行監査はbest effortで、保存できなければ秘匿した運用イベント。成功監査欠落の部分commitとは異なる |
| Execute後の現在値 | 業務commit後の別read-only Transaction、単一statement観測 | 現在値取得失敗でCOMPLETEDを失敗へ戻さない。確定after / resultを現在値で変更しない |
| Projection worker | session leader基盤のみ実装 | claim / lease / 投影 / 状態更新のatomicityは未実装。既存Outbox原子性からworker完成を推論しない |

既存の重要更新では部分commitを導く独立commitは確認していない。PK / FK / UNIQUE / NOT NULL / CHECKと条件付きversion更新を確認した。期間重複・Graph循環・多態endpoint等の一部跨行制約はアプリ検証とGraph lockに依存するため、DB制約だけで全不変条件が保証されるとは扱わない。

根拠テスト: test_proposalsのPENDING保存 / 要求置換rollback、test_approval_observabilityの成功監査失敗rollback、test_executeの業務 / history / 消費rollback、test_dependency_executeとtest_production_assignment_executeの各書込段階・後半Outbox失敗による全rollback、各version競合 / 並行Execute、test_business_schema / test_update_request_schema / test_projection_storageのDB制約試験。

DBエラーはProposalStore / ReadToolsで定義済みcodeへ変換しAPIはcodeだけを返す。middlewareも未知例外をINTERNAL_ERRORへ秘匿。logging._diagnosticは例外本文・引数・locals・SQL・source行を出さず型と限定frameだけを記録する。現時点でSQL / bind値の実行ログは有効化していない。

## 5. Recommended Changesと実行順

| 分類 | 変更 |
|---|---|
| MUST FIX | S-01: 管理 / 非superuser runtime / read roleを分離し、実DBの否定テストでDML / DDL拒否を確認 |
| MUST FIX | S-02: API / ToolのSQL Injection回帰テストとDB不変assertを追加 |
| SHOULD FIX | 新規通常DBアクセスをCoreへ統一。まずRead層で依存・Table / Column・bind・error変換を整え、安全な移行例を確立 |
| SHOULD FIX | Coreの例外ラッパー・connection / Transaction所有・logging秘匿を既存契約に合わせ、重要更新への適用前に回帰テストを確保 |
| OPTIONAL | 安全な既存通常Raw SQLの段階移行。期間重複をDB EXCLUDE等で補強できるか、既存期間意味論と互換性を別途評価 |
| NO CHANGE | 既存の正しいlock順序、version / canonical hash、承認期限・状態遷移、確定afterと現在値の分離、必要Outbox条件。migration・advisory lock等の必要Raw SQLは維持 |
| NO CHANGE | 全面ORM化は行わない。SQL安全性を理由に自動flush等の新しい意味を持ち込まない |

実行順は(1) Injection回帰テストの基準確立、(2) DB role分離と権限拒否テスト、(3) Read層からCore標準を導入、(4) 必要性のある既存箇所だけ段階移行。明白なInjection脆弱性が見つかれば(1)の前に最優先修正する。Graph workerの新しい通常DBアクセスはCore基盤整備後に進める。
各段階を小さいPRとし、POがmergeする。今回の文書だけで実装開始・適合完了としない。

## 6. Migration Risk

- Transaction: SQLAlchemyのautobegin・Connection所有・commit / rollback範囲・例外ラッパーで独立commitを入れない。psycopg直実行とCore接続を一操作内で無計画に混在させない。
- Lock: 同じ物理接続・取得順・READ COMMITTED・timeoutを維持。session leaderをconnection poolへ返して他用途に残さず、transaction lockと混同しない。
- Version / Approval: 条件付きUPDATEのrowcount、現在権限、期限のclock_timestamp、失効再検証、COMPLETED replayを維持。
- Snapshot: UUID / timestamp / NULL / JSON / decimalのdriver変換、RowMapping等による返却形状・順序がcanonical内容やhashを変えないことを検証。
- Outbox / Graph: business、履歴、Outbox、consume、結果、成功監査の同じTransactionを維持。deferred UNIQUE / 最終集合検証、完全payload、同aggregate version一意性を保持。未実装workerの完成を前提にしない。
- 権限: read / mutation経路へ正しい接続を注入する。Prepareの業務観測はreadだが要求・Approval・監査保存はwriteなので、Agent全体を単一read roleへ機械切替しない。必要SELECT・FK参照・sequence / schema権限不足で正しい更新を壊さない。
- 既存DB: 初期化scriptは既存volumeでは再実行されない。volume削除や履歴消去で解決せず、管理経路の明示的role provision / grantと非破壊なupgradeを設計する。

## 7. 検証・残課題

今回実施: Python AST棚卸し、各動的候補の入力源追跡、重要更新・DB schema・既存試験の静的確認、文書リンク・diff確認。コード・設定・DBを変更せず、pytestや攻撃入力の新規実行はしていない。直前PR #87の2184 passed / 1 skippedとCI成功はそのPRの結果であり、この監査の追加試験結果ではない。

未完了: Core導入、DB role / credential分離、実DBの権限属性・GRANT確認、T-SQL追加実装・実行、worker / Projection。現状はpolicy完全適合ではない。今後の変更が会話履歴なしで追えるよう、正本に方針、履歴に時点付き事実・未対応・再開順序を分離して記録する。
