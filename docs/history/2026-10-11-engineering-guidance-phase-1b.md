# 開発ガイダンス整理 — Phase 1B

## 対象と位置づけ

基準はmain `805b95b`（PR #134）。[Phase 1A](2026-10-11-engineering-guidance-phase-1a.md)で残した主要call pathを実装で確認した記録であり、仕様正本ではない。Production code、正本文書、AGENTS、正式Skillは変更していない。全コード・全テストの網羅レビュー、業務受入の完了判定ではない。

## 実際の構成と境界

現状はApplicationサービスを中心とするLayered Architectureに近い。MVCや厳密なClean Architectureの完成を主張しない。

| 経路 | 実装の入口と委譲先 | 責務・注意点 |
|---|---|---|
| 起動 | `bootstrap.build_api_services` | Database、サービス、Ollama、Dispatcherを組み立てるcomposition root |
| 認証 | `interfaces.http_logging.RequestMiddleware` → `ExecutionContext` | 設定のbearer tokenからuser/roleを決定。LLMによる自己申告を採用しない |
| HTTP検索・変更 | `interfaces.api.create_app`内handler → Application | 業務handlerにSQL/Core/Session操作はない。readinessのDatabase.checkは診断経路として例外 |
| Agent | `AgentApplication.run` → Prepareサービス / `ReadAgent` | 会話・retry・業務振り分け。HTTPから分離済み |
| Read | `ReadTools.run` → `persistence.core_reads` → Database | Core SELECT、READ COMMITTED / READ ONLY、検索用接続。Applicationが検証・Evidenceを担当 |
| Prepare | 各Prepareサービス → `ProposalStore.save` → Core INSERT | 正本参照・検証後、要求・Target・Approval・置換失効・Auditを一括保存 |
| Approval | `HumanApproval` → `_HumanApproval._approve/_reject` | Request→Approval lock、全Target検証、状態とAuditの同時確定 |
| Execute | `HumanExecute` → `_UpdateExecute._execute` → Core / 固定SQL | Applicationがtransactionと取得順を所有。業務更新・履歴・Approval消費・確定結果・Audit・対象カテゴリのOutboxを同時確定 |
| 失敗 | `_UpdateExecute._retire` / `audit.failed_attempt` | 主transaction rollback後の別transaction。lock下で再検証し、完了済み要求を上書きしない |
| Projection | `ProjectionWorker.run_once` → ProjectionApplication → Neo4jProjection | PG lease/fence、排他mutation lock、Neo4j明示transaction、PG ACK。分散transactionにはしていない |
| Rebuild | `RebuildController.run` → drain / source snapshot / generation build / publish | 初回・通常Rebuildの内部部品。Restore stageは別部品でcontroller未接続 |

ApplicationとPersistenceの境界は完全ではない。`ProposalStore`は保存だけでなく認可・Snapshot検証・例外変換も担う。Executeにも固定parameterized SQLが残る。純粋な`execute_policy`はDB-awareな`proposals`から型・定数をimportする。フォルダ整理だけで依存反転済みとは扱わない。

## 必須5論点の実装確認

1. **Execute起動経路 — [既存仕様]に整合。** 認証済み人間用APIからHumanExecuteへ渡す。ownerと現在role、承認者role、Snapshot/hash、期限、versionを検証する。ToolDispatcherにApproval / Executeは公開されない。
2. **Idempotency — [既存仕様]に整合する経路を確認。** サーバ発行の実行idempotency UUIDと、Prepare retry keyを区別する。AgentInputはIdempotency-KeyまたはUUIDを用い、保存はowner/keyの一意性と入力hash一致を検証する。retry keyのTTLは設けない。確定結果の再送と、その後のcurrent観測を分離する。
3. **Failure Record — 一部未実装。** 期限切れ・競合失効は主transactionのrollback後に別transactionで再検証しAuditと確定する。失敗試行Auditも別transactionで、保存障害は固定ログへ落とす。一方、transaction-designの回復不能整合障害に対する`FAILED/INVALIDATED`への更新経路は見つからない。許容状態組の定義だけで実装済みとは扱わない。現状は検証拒否とエラーで停止し、業務変更を通さない。
4. **Isolation / Lock — 主要順序を確認。** ProposalStoreは明示READ COMMITTED。Graph関係Executeはmutation lockをRequest/Approval lockより先に取得し、Targetを規定順でlockする。Core抽出によってcommit所有権を移していない。LockNotAvailable/QueryCanceledはRESOURCE_BUSY。Docker内で例外継承を確認したところDeadlockDetectedとSerializationFailureはOperationalErrorであり、ProposalStoreではDEPENDENCY_UNAVAILABLEへ変換される。これを通常のlock timeoutと同じ契約と説明しない。Projectionは別の明示的transient分類を持つ。
5. **Outbox Ordering — 確認した経路では問題なし。** OutboxはUUIDであり、claimのcreated_at/id順は処理選択用。ProjectionStateはcommit済みOutbox全状態とcontrolを一つのstatementで観測し、最大IDのwatermarkでCURRENTを判定しない。Neo4jはaggregate version/hashで適用・再送・古いイベントを判定する。一般的なsequence取得順をcommit順と同一視してよいという結論ではない。一次資料の確認はPhase 1A、逆順commitの並行実験は未実施。

## 実装済みと未実装の区別

- ReadToolsは13本。契約にある設備状態履歴・更新履歴検索は未接続。
- ToolDispatcherはRead 13本とPrepare 6本。ReadAgentの通常sessionはPrepare非公開で、任意SQL/Cypher、Approval、Executeを持たない。
- AgentApplicationの自然言語Prepare振り分けは設備状態・保全予定・生産予定。内部Prepare Toolの種類と同じ範囲が自然言語から使えるとは限らない。
- Graph投影・Rebuildの内部部品は存在する。Graph探索ToolのAgent接続、Qdrant / retrieval、業務計算・Decision Packageは未実装。API起動時にこれらを組み立ててはいない。
- workerの1件処理と常駐運用は別。Restore controller接続、途中失敗復旧、runtime運用構成は残件。
- Agent予算は呼出し境界で確認する。全blocking I/Oを絶対deadlineで強制中断できると主張しない。

## 改善候補と優先度

| 優先度 | 項目 | 推奨 |
|---|---|---|
| 高・正確性 | 回復不能障害のFAILED遷移未実装 | 正本文書の条件を満たす場合だけ、別transactionの再検証・Audit・終端保護を実装して試験する。全INTERNAL_ERRORをFAILEDにしない |
| 中・契約 | deadlockの例外変換とoutcome unknown分類 | 通信途絶との区別、既存error contract、retry規則を確認する。安全制御を変えず限定変更する |
| 中・構造 | ProposalStore / 純粋Policyの依存 | 共有型・定数とPersistence操作を分離する候補。transaction所有権・lock順・rollbackはApplicationに維持 |
| 継続・機能 | Graph Read、RAG、履歴、業務受入 | 未実装を進捗・Skillで隠さず、機能ごとの実装と受入を進める |
| 中・guardrail | 禁止依存の自動検査 | Router→SQL/driver、domain→HTTP/driver等を具体的に検査する。readiness / composition rootは例外理由を明示 |
| 低・文書 | 古いcheckpoint記述 | 現在仕様と時点の記録を区別し、正本の古い進捗記述を後続整理で修正する |

これらは本レビューで採用・実装した変更ではない。新しい業務要件やPO-B01〜08を決定する根拠にしない。

## 検証の範囲

- 実コードの上記主要経路、権限注入、固定SQL / Core境界、Neo4jのparameter / identifier allow-listを確認した。確認対象で外部文字列をSQL/Cypherコードへ補間する経路は見つからなかった。全Repositoryの脆弱性不存在を証明するものではない。
- 既存の`test_projection_storage`で、将来retryの未適用イベントをAPPLIED watermarkが隠さないこと、未commit状態の不可視性を検証する試験を読んだ。
- `test_dependency_execute`の複数段階rollback、並行cycle拒否、mutation lock先行、timeout後retryを検証する試験を確認した。SQL文字列一致に依存せず、状態とlockの効果を確認する。
- Dockerの既存test imageでpsycopgのDeadlockDetected / SerializationFailureの継承を実測した。両方OperationalErrorの派生型だった。
- この文書調査でpytest全体は再実行していない。PRの必須CIによる回帰結果はPRへ別途記録する。

## Phase 1Cへの引継ぎ

四つの[Skill草案](engineering-guidance-drafts/index.md)は正式配置せず維持する。短いroot AGENTSによる入口、正本参照、意味によるSkill発動、具体的guardrailの案を次に整える。純粋Policyの依存やFAILED等の未実装事項を「すでに守られているInvariant」として誤記しない。Skillsは作業手順であり、仕様・実装・Testsの代替ではない。
