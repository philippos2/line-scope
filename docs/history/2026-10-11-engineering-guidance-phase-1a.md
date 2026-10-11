# 開発ガイダンス整理 — Phase 1A

日付: 2026-10-11。確認対象: main `805b95b`（PR #134まで）。種別: 調査記録・提案。仕様正本でも正式Skillでもない。

POの提言を受け、最初はPhase 1Aに限定した。deliverablesの20文書について責務と関連節、AGENTS、判断履歴、CI定義、テストファイル・関数名を照合した。文書全体の再承認、Production Codeのcall path調査、テスト実装の網羅レビューは行っていない。名称からのテスト対応推定を、保証済みcoverageと扱わない。

## 判断の要点

- Documents / AGENTS / Skills / Tests・CIの責務分担を採用候補とする。ただしこれは単純な上下優先順位ではない。Skillが仕様を上書きせず、Testsが未定義業務ルールを勝手に確定しない。正本の選択はdeliverables §5、上位業務意図はrequirements §2.1に従う。
- 既存の開発スタンスを4つの短いSkill草案へ逆算した。配置は[草案一覧](engineering-guidance-drafts/index.md)。`.agents/skills`にはまだ配置せず、正式採用・自動発動は行っていない。
- 恒久的な方針と、チェックポイント時点の「未実装」「今回維持する」を区別する。古い実装状況をSkillへ転記しない。
- Production Code、正本文書、AGENTS、Tests、CIを変更していない。Phase 1Aの制限を通常開発の恒久的禁止にしない。

ラベル: `[既存仕様]`=正本の明示規則、`[既存方針]`=AGENTS・履歴・POの既存運用、`[提言]`=今回の整理案、`[矛盾]`=確認済み不一致、`[要PO判断]`=未確定業務判断、`[未検証]`=実装や保証の確認待ち。

## A. Canonical Documents Map

パスはdocsを基点とする。以下は関連節の責務確認であり、20文書の完全セルフレビュー合格ではない。

| Domain / Decision | 正本 | 節 | Status / Note |
|---|---|---|---|
| 文書体系・正本選択 | deliverables.md | §5・7・8 | [既存仕様] 20文書。historyは正本外 |
| 業務目的・スコープ・優先関係 | requirements/requirements.md | §1・2.1・12・14 | [既存仕様] 技術都合で上位UCを縮めない。PO-B01〜08未決定 |
| 関係・required・AND/OR・一段置換・期間・as_of | requirements/domain-model.md | §4・7〜15 | [既存仕様] 構造到達、成立、能力、安全を分離 |
| 認可・自己承認・owner・全Target | requirements/access-control.md | §3〜11 | [既存仕様] Graph roleと通常Readを区別 |
| UC・業務Goal | requirements/use-cases.md | UC-01〜21 / UC-B01〜17 | [既存仕様] 機能操作と業務目的を区別 |
| 最小権限・原子性・非Prompt依存・資源上限 | requirements/non-functional-requirements.md | §2・4〜7 | [既存仕様] 適合要件と実装合格は別 |
| 受入・重大Fail・トレーサビリティ | requirements/acceptance-criteria.md | §4〜9 | [既存仕様] §5の重大Fail Gateを維持 |
| Store責務・技術・SQLアクセス | design/architecture.md | §1〜15 | [既存仕様] Core標準、理由付きRaw SQL例外。実装状況の陳腐化あり |
| DB・制約・監査・Outbox・marker | design/data-model.md | §2・9〜12・14〜15 | [既存仕様] UUID outbox_idをwatermarkにしない |
| Agentの権限境界・Context・retry | design/agent-design.md | §1・9・11〜13 | [既存仕様] AgentはPrepareまで |
| HTTP / Tool / error / Evidence / ID契約 | implementation-design/api-tools.md | §6・7・14〜19 | [既存仕様] 空Body Execute、trusted identity、数値計算契約は追加待ち |
| 状態遷移・原子性・失効・lock・retry・同期・復旧 | implementation-design/transaction-design.md | §1〜22 | [既存仕様] 一要求全Target原子性。deadlock詳細は確認待ち |
| 認可から処理結果までの想定経路 | implementation-design/interaction-flow.md | §1〜11 | [既存仕様] 実call pathの根拠とは区別 |
| Promptの補助的制御・Evidence説明 | implementation-design/prompt-design.md | §1・2・6・7 | [既存仕様] 確定操作をPromptで保証しない |
| Qdrant・本文・再認可・version・ingestion | implementation-design/rag-design.md | §1〜9 | [既存仕様] metadataだけで認可せず生成前再確認 |
| AI品質・モデル変更・安全Evals | implementation-design/evals.md | §2・5〜7 | [既存仕様] 決定論的受入とは別。一般品質閾値は評価後 |
| 試験階層・T-R・T-L・T-SQL | implementation-design/test-plan.md | §11〜15 | [既存仕様] 試験仕様であり全実行済み一覧ではない |
| Business Scenario・数値・UC↔BS↔AC | implementation-design/business-scenarios.md | §1・3〜6 | [既存仕様] BS-01〜19・BS-G01。未決定/未実装とPASSを分離 |
| timeout・運用・監査/ログ・DB role | implementation-design/operations.md | §10・13・14 | [既存仕様] role・secret・rotation。段階実装説明の陳腐化あり |
| Agent作業規則・責務・LogiScope利用 | implementation-design/AGENTS.md | §2〜14 | [既存方針] 正本一覧には含まれるが業務モデル再定義の場所ではない |

## B. Engineering Principles

| ラベル | 内容 | 根拠 | 配置候補 |
|---|---|---|---|
| [既存仕様] | Security / integrity / correctnessを利便性より優先 | architecture §15、NFR-01・04〜08 | 正本は維持、AGENTSに短いInvariant、secure-codingで手順 |
| [既存方針] | 責務分離・境界・依存方向・本体/テストの構造対応 | AGENTS §14、配置整理履歴 | AGENTS維持、architecture-reviewで実経路を確認 |
| [提言] | SOLID、High Cohesion / Low Couplingを設計判断の指針とする | 今回の提言とPOのSOLID確認。一般論だけで実装合格にしない | AGENTS短文候補、architecture-reviewの判断軸 |
| [既存仕様] | 決定論的制御とLLM説明を分離 | agent-design §12〜13、prompt-design §1、NFR-08 | 正本維持、secure-coding / transaction-review、決定論テスト |
| [既存仕様] | Core・bind・identifier制限・DB制約・最小権限を組み合わせる | architecture §15、NFR-04、test-plan §15 | secure-coding初期統合。単なるORM化チェックにしない |
| [既存仕様] | 全Target変更・履歴・成功監査・必要Outbox・承認消費を原子的に確定 | transaction-design §5・14・15・22 | transaction-reviewと実DB試験 |
| [既存方針] | 合理性のある小さな実装→試験→commit、POがmerge | 配置整理履歴、既存PR運用合意 | code-change-verification。GitHub設定の現在値は別途未確認 |
| [既存方針] | SQL表記への故障注入ではなく、意味のある処理境界と実DBを検証 | architecture §15のCore移行記録 | transaction-review / verification |
| [既存方針] | 過剰な抽象化を避け、具体的な変更負担削減と回帰リスクを比較 | AGENTS §14、architecture §15.1 | architecture-review / refactoring手順 |
| [既存仕様] | Graph探索のdepth/nodes/paths/timeout、Unknown/Incomplete、Evidenceを機械可読に保つ | api-tools §10・17、NFR-G02・04・06 | 正本維持、transaction-review / verification。実装有無はPhase 1B |
| [既存方針] | 依存packageの固定version、GitHub Actionのcommit SHA固定 | backend/pyproject.toml、CI定義 | 正本と設定は維持、secure-codingで変更影響を確認。自動脆弱性scanの新設は提言 |
| [既存仕様] | 未決定・未実装・未実行を合格扱いしない | AGENTS §13、test-plan §13、evals §6 | AGENTS維持、verificationで明示 |
| [提言] | assertion弱体化、チェック除外によるGreen化を禁止する短文 | 今回の提言。重大Fail Gate・既存試験維持方針と整合 | AGENTS改訂候補、verification |
| [既存方針] | 会話にしかない重要判断を、正本/履歴の適切な場所へ残す | AGENTS §12〜14、PO指示 | verificationの完了条件。仕様変更は正本から |

## C. AGENTS.md評価

現在85行。行数自体の閾値は設けない。現時点で長大なWorkflowを移す必要は小さい。

| 現行節 | 評価 | 案 |
|---|---|---|
| §1〜3 | 残す | 文書入口・正本責務・不一致を黙認しない規則 |
| §4〜5・8・11 | 残す/重複を短くする | trusted identity、Agent確定操作禁止、RAG再認可等は常時Invariant。詳細は正本参照 |
| §6〜7 | 正本文書参照を維持 | DB/Graphの仕様を複製しない |
| §9 | 残す | AC→Test・重大Fail。コマンドや長いChecklistはverificationへ |
| §10 | 残す/短くする候補 | LogiScopeは一般パターンのみ、適用理由説明。別プロダクトの仕様を継承しない |
| §12〜13 | 正本参照へ整理する候補 | 歴史的採用日や一覧の再記述を減らし、requirements §14.3 / deliverablesを参照 |
| §14 | 原則は残す、手順はSkillへ | 境界・依存・純粋検証・transaction保持は常時原則。移動手順や差分確認はarchitecture-reviewへ |
| 根元の入口 | [提言] 追加候補 | root AGENTS.mdは現状存在しない。文書のAGENTSはdocs配下。rootに短い入口・適用Skill案内を置き、詳細を複製しない |

改訂候補の最小内容: deliverablesへの入口、責務/依存/明示性、trusted identity/人の確定操作、正本不一致の扱い、Test弱体化禁止、意味に基づくSkill発動条件。Phase 1Aでは実際のAGENTSを変更していない。

## D. Skill候補

名前は他リポジトリとの衝突を避けてlinescope prefixを付ける。草案の本文は現在の作業姿勢を表す候補で、契約・数値を再定義しない。

| 候補 | 責務/Trigger・Concrete Keywords | 境界・取り込む情報 | 初期評価/優先 |
|---|---|---|---|
| linescope-architecture-review | router / service / repository / adapter / dependency / boundary。新component・依存変更・refactoring | AGENTS §14、architecture、実call path比較。SOLIDは判断軸 | 独立、優先高、草案あり |
| linescope-secure-coding | authorization / role / Trusted Execution Context / Tool argument / SQL / Cypher / secret / RAG | 認可・入力→authority/SQLのdata flow・最小権限・秘匿。transaction保証は次Skill | 独立、優先高、草案あり |
| linescope-transaction-review | UpdateRequest / Approval / Execute / expected_version / Outbox / advisory lock / projection / Rebuild / retry | transaction-designと実装の境界・並行性・復旧を確認。新規状態機械を発明しない | 独立、優先高、草案あり。正本と同名を避けreviewとした |
| linescope-code-change-verification | 変更後検証 / pytest / ruff / CI / migration / PR / commit | 試験選択・実測結果・未実施・片付け・POへの引渡し。変更許可を拡大しない | 独立、優先高、草案あり |
| database-access | SQL / Core / role / migration | secure-codingへ初期統合、transactionの検証はtransaction-review | 独立保留。DB専用棚卸しを繰り返す場合に分割 |
| refactoring | 構造整理・behavior維持 | architecture-reviewへ初期統合、検証はverification | 独立保留。Rule of Threeはヒューリスティックで境界違反放置の理由にしない |
| doc-consistency-review | State / error / Tool / Requirement→AC→Test | 正本・重複・参照をarchitecture-reviewへ初期統合 | 全文書横断レビューが反復するなら独立 |
| graph-projection | generation / marker / drain / CURRENT / lease | transaction-reviewへ初期統合 | 現状頻出だがworkflow重複を避け、復旧が複雑化したら分割 |
| agent-tool-contract | Tool Input/Output / Evidence / context / idempotency | architecture-reviewとsecure-codingの必要部分 | 独立保留。Tool追加反復時に再評価 |
| scenario-testing | Given/When/Then / BS / fixture / Golden | Businessと技術試験の分離はverificationに参照。詳細はbusiness-scenarios | Business受入実装時に独立を再評価。fixtureを業務規則へ昇格させない |

初期4つの発動は変更の意味で選ぶ。普通の1行修正に全Skillを強制しない。一つの変更で複数の境界を動かす場合だけ組み合わせる。共通仕様は正本参照でありSkill間にも複製しない。

## E. Tests / CI Guardrail Map

確認粒度はファイル・関数名とCI定義。Existsは「対応候補が存在する」の意味で、実装coverage認定ではない。

| Critical Fail / Invariant | Existing Test / CI | Exists? | 次の確認 |
|---|---|---|---|
| 認可・owner・全Target・自己承認 | application/test_approval_policy.py、test_execute_policy.py、interfaces/test_execute_api.py | あり | Phase 1Bでrole matrixと拒否時の状態不変を確認 |
| 任意Tool・Agent確定操作・trusted retry | agent/test_agent_tools.py: test_unregistered_tools_do_not_dispatch / test_prepare_metadata_is_trusted_and_only_one_attempt_per_turn | あり | Tool registry、context注入、Agent側非公開をcall pathで確認 |
| SQL値/identifier Injection | application/test_sql_injection.py、persistence/test_core_*.py、graph/test_neo4j_projection.py | あり | 許可自由文字列のbindと二次Injection、全動的identifierを確認 |
| DB least privilege | persistence/test_db_roles.py: test_query_role_rejects_mutation_ddl_and_private_tables等 | あり | 標準runtime接続・controller未導入roleの残範囲を確認 |
| Snapshot/hash・NULL/version・不変性 | domain/test_canonical.py、test_snapshot.py、各カテゴリSnapshotテスト | あり | schemaと保存Target再構成、型境界を確認 |
| 更新/履歴/監査/Outbox/消費のrollback | application/test_execute.py、test_dependency_execute.py、test_prepare_audit.py | あり | failure注入段階と別Transaction監査を確認 |
| 二重Execute・並行CREATE/UPDATE・禁止cycle | application/test_execute.py: test_parallel_execute_returns_same_result_and_updates_once、test_dependency_execute.py: test_concurrent_requests_cannot_together_create_cycle等 | あり | barrierと実DBの並行性、version条件を確認 |
| CURRENT判定はcommit済み集合 | graph/test_projection_storage.py: test_entire_committed_event_set_controls_sync / test_uncommitted_control_and_event_changes_are_not_visible | あり | 逆転commitの実験、Core判定式を確認 |
| Projection冪等性・PG ACK失敗 | graph/test_neo4j_projection.py: test_real_neo4j_commit_survives_pg_ack_failure_and_replay_is_idempotent | あり | source_version/markerのlockと比較を確認 |
| Rebuild/Restore前段・leader/lock | graph/test_rebuild_*.py、test_restore_staging.py | 部分 | 履歴ではRestore接続・crash復旧・I/O予算伝播は未実装。全T-R12合格としない |
| ログ秘匿・出力失敗・相関 | test_logging.py、interfaces/test_*_observability.py、application/test_tool_logging.py | あり | 原子性とstdout障害の区別を確認 |
| RAG再認可・version/本文検証・Injection | test-plan T-R18、AC-R01〜03 | 試験仕様あり、独立実装suiteは一覧に見つからない | Phase 1Bで実装有無を確認。仕様記載だけで合格にしない |
| Graph探索limit / 不完全性 / SPOF | test-plan T-R10・14〜16等 | 試験仕様あり、探索Toolの対応suiteは一覧から特定できない | Phase 1Bでdispatchから実装・試験を特定。同期部品試験で代替しない |
| BS-01〜19 / Golden受入 | business-scenarios §4、test-plan §13 | 仕様あり、専用Gherkin runnerは一覧に見つからない | 業務受入実装時に追跡。技術試験の件数で代替しない |
| 層のimport方向・Router DB依存防止 | 専用Architecture Testは一覧に見つからない | 未検証 | Phase 1BでAST/依存実態確認、Phase 1Cで小さいguardrail案 |
| pytest・lint・migration・起動 | .github/workflows/ci.yml: Tests and migrations | あり | 全backend tests、ruff、起動、migration、always cleanup。10分timeout |
| Conventional PR title | .github/workflows/pr-title.yml: PR title | あり | title形式を検証。Squash/branch protectionはGitHub設定で別物 |

型チェック専用job、依存脆弱性scan、重大Fail ID→実テストの完全対応表は、確認したCI定義にない。ruffの現選択はE4/E7/E9/F/Iで、層間依存やセキュリティ全体の静的保証ではない。[提言] 必要なguardrailはPhase 1Bの欠落確認後に追加候補を選ぶ。構造化で不要な例外を禁止しない。

今回pytestを再実行していない。直前PR #134の2665 passed / 1 skipped / 1 warningはその変更の確認結果であり、この調査による全安全要件合格ではない。

## F. 矛盾・重複・陳腐化

1. [未検証] 実コードとの全不一致はPhase 1B未実施のため判定しない。確認した主要契約に新しい致命的な文書間矛盾は見つからなかったが、全体無矛盾を保証しない。
2. [既存方針] AGENTSはdocs/implementation-design配下だけにある。root入口追加は発見性改善の候補。現在の配置だけを脆弱性と断定しない。
3. [矛盾] architecture §12の「既存実装はRaw SQL」「Core導入済みとは扱わない」は、同書§15の後続移行記録と時点が異なる。恒久方針の矛盾というより実装状態記述の陳腐化。Phase 1B後に状況をhistory/実装一覧へ分離する改訂案を作る。
4. [矛盾] architecture §15末尾等の「Rebuild drain未実装」「専用role後続」、operations §13.8の「DB監査/Tool/workerへの接続未実装」は、後日のRebuild/role/監査接続履歴・現在のテスト一覧と時点が異なる。最新の実装保証はPhase 1Bで確認する。古い文章を現行禁止規則としてSkillへ複製しない。
5. [提言] architecture §15の大量の移行チェックポイント説明はpolicyと進捗を混在させる。policyを維持して進捗をhistoryへ整理する候補。今回移動/削除していない。
6. [既存仕様] AGENTS §5/11、agent-design §9、api-tools §6で確定操作禁止が重複するが、責務ごとの安全境界として妥当。独立した値・状態定義を増やすことは避ける。
7. [既存方針] historyの「未実装」は当日の状態として有効。歴史的記録を古いという理由だけで現在仕様へ書き換えない。一方、history一覧だけで現時点の完成状況を再構成する負担は大きい。
8. [提言] Skill内にtimeout数値、state一覧、全Tool schemaをコピーしない。正本参照と照合手順に限定する。

## G. 必須5論点・要PO判断

### G1. Executeの起動経路

[既存仕様] 解決済み。api-tools §6・7・14、access-control §5・9、agent-design §9、transaction-design §4・18。認証済みの専用Execute API、空Body、元requesterのみ。LLM/AgentにExecute Toolを公開しない。新規Executeでは現在権限と承認条件を再検証する。

[未検証] 実際のHTTP→context→owner/権限→application呼出し、公開registryの完全確認はPhase 1B。[提言] 既存仕様を維持し、不明だからAgent経路も追加することはしない。

### G2. Idempotency Key

[既存仕様] 解決済み。transaction-design §2・15・20、api-tools §14・18、agent-design §12。

- idempotency_keyはサーバ生成UUID。prepare_retry_keyとは区別する。
- prepare_retry_keyはtrusted orchestratorが固定。/agentのClient Idempotency-Key UUIDがあれば使用、なければサーバ生成。LLMは生成/変更しない。
- scopeは(requester_id, prepare_retry_key)、一更新要求。成功Prepareと永続保存しTTLなし。context TTL/Approval期限とは別。
- 同じ入力は終端でも既存要求を返し、異内容は409 DUPLICATE_REQUEST。別の新要求に流用しない。rollback未保存のみ再試行可能。
- 応答喪失でキー不明なら自動再Prepareしない。COMPLETED ExecuteはUpdateRequest単位の既存結果を返す。

[未検証] 正規化hash、HTTP入力照合、UNIQUE競合、context失効後の再送の実経路はPhase 1B。[提言] 「key」の一語に統合せず、用途別識別子を維持する。

### G3. Failure Record

[既存仕様] 別Transactionが必要な場合と再利用条件は解決済み。transaction-design §6・12・15・19・22、operations §13.6。

一時障害の主TransactionはrollbackしてAPPROVEDを保持する。確定した業務競合・期限等は、別Transactionで同じlock順に最新状態・hash・原因を再確認しINVALIDATED/EXPIREDへ変更し、終端を上書きしない。失効状態とその監査は同一commit。失敗試行監査はrollback後の別Transaction、保存不能時は秘匿したaudit.persist_failedログへfallback。未作成Requestの架空FKは作らない。

FAILEDは回復不能内部整合障害に限定し、対応ApprovalをINVALIDATEDとする。すべてのrollbackをFAILEDにしない。

[未検証] FAILED検出と保存の具体経路、別Transactionで保存できない場合の各API応答、並行成功後の退役処理はPhase 1B。[提言] 状態と観測ログを分離し、保存不能を保存成功として返さない。新しい失敗遷移を追加するなら設計変更として扱う。

### G4. Isolation / Lock / Timeout / Deadlock / Retry

[既存仕様] Isolation/lock順/timeout/主要retryは解決済み。transaction-design §1・5・15〜17・20、operations §10。

- 通常更新はREAD COMMITTED。必要なGraph mutation lock→Request→Approval→業務行(target_type,target_id順)。失効・Rejectでも親Request先行。
- worker/controllerはleader→mutation、Graph分析はshared mutationのみ。worker claimの短いcommitとGraph適用/ACKまでの排他保持を区別。
- lock timeout 5000ms、Rebuild 60000ms等はoperationsの技術既定。Read/Graph retryは最大2回・全体deadline内。Outbox retry/lease/backoffは同節の契約。
- commit不明はGET確認、AgentからExecute自動retryしない。

[未検証] deadlock SQLSTATEの具体的error mappingと自動retry可否は文書に専用定義を見つけられなかった。実装が既存の一時障害規則で処理しているかPhase 1Bで確認する。timeoutの残予算伝播もRebuild履歴で未完了。

[提言] deadlockは主Transaction rollbackを前提に既存の一時障害/再試行契約との整合を調べ、勝手な再Executeやlock順変更をしない。単なる技術的error分類は既存契約内で決定できるが、利用者向けretry/状態契約の変更が必要ならPOへ提示する。未確認実装を直ちに[要PO判断]へ昇格させない。

### G5. Outbox Ordering / Sequence / Commit Order

[既存仕様] 採番順をcommit順にしない設計は解決済み。NFR-G08、architecture §7、data-model §2 graph_outbox / §6、transaction-design §7・8・10・11・17・19。outbox_idはUUIDでありBIGSERIALによる順序採番ではない。CURRENTはcommit済み集合とcontrolの単一statement観測、最新Projectionはaggregate source_version/marker。created_at/outbox_idは選択順であり正当性条件ではない。

PostgreSQLの[公式sequence仕様](https://www.postgresql.org/docs/18/functions-sequence.html)はnextvalで値を原子的に返し、rollbackでも値を再利用しないことを定義する。ここから、採番をcommit完了の証拠にできないことが分かる。ただしこれは今回のLineScopeコードでの並行commit実験ではない。

判定: **設計は問題なし。BIGSERIALによるwatermark懸念は設計上該当しない。実装上の全遵守はPhase 1Bまで判断不能。** 対応候補test_projection_storageの全状態集合/未commit不可視性テストは存在するが、逆転commitの試験内容は未レビュー。

Phase 1Bでは同期判定・claim・markerを実コードで追跡する。必要なら使い捨てDBでAが先に採番、Bが後に採番して先commit、Aが後commitする最小実験を行う。一般的sequenceの確認と、LineScopeが遅いcommitを取りこぼさない試験を分ける。実験は管理用デモDBで行わない。

### G6. 真のPO未決定事項

[要PO判断] requirements §14.3 PO-B01〜08は未決定と記載されている。共通比較期間/費用、損失と加算、能力/余裕/互換性、安全/劣化、修理・交換/将来停止、故障履歴、新情報の権限、InfrastructureResourceの影響意味。既存の決定をSkillで確定しない。

推奨は既存要件の意図を保持し、実装へ入る対象の業務意味だけを必要時に確定すること。今回はこれらの採否や数値を決めていない。開発ガイダンス導入と業務PO判断を一括承認にしない。

## H. Phase 1BのCall Path・次の作業

| 優先 | 実経路 | 確認目的 |
|---|---|---|
| 1 | UpdateRequest→Approval→Execute→History/Audit/Outbox→失効別Transaction | owner、全Target、atomicity、FAILED、commit不明、冪等性 |
| 2 | Authentication→Trusted Execution Context→Application/Tool認可 | LLM/Bodyからauthorityへ越境しないこと |
| 3 | HTTP Router→Application→Persistence/Core→PostgreSQL | 実責務・依存方向、readiness/bootstrapの例外、ProposalStore混在 |
| 4 | LLM adapter→Tool registry→引数検証→Read/Graph/Prepare | 公開契約、limit、retry、Evidence、確定操作非公開 |
| 5 | Neo4j read / write / marker、同期判定/claim | 探索の実装有無、source_version、全イベント集合、採番順依存なし |
| 6 | Projection / Rebuild / Restore | lease/ACK/leader/排他、stage後ticket、crash/timeout未完成境界 |
| 7 | Qdrant search / upsert / 正本再認可 | 実装がなければ未実装と明記。存在しない経路を設計図から実装済み扱いしない |

変更の前にcall pathと代表的な故障試験を確認する。Architecture Pattern名は確認後に評価する。Phase 1Cでroot AGENTS案、Skill正式配置案、必要な最小guardrail、正本の陳腐化修正案を作る。Phase 2は採用済みの範囲だけ変更する。

## Repositoryだけから再開できるかの代理指標

[提言] 数値目標を先に置かず、Phase 1Bで次の事実を記録する。

- rootから文書入口・適用方針へ到達できるか。
- 変更対象の決定について正本を一つ指定できるか。historyを現仕様と取り違えないか。
- 主要call pathの責務・接続所有者・transaction所有者をコードから説明できるか。
- 重大Fail→AC→試験の対応が確認できるか。存在/未検証/未実装を区別できるか。
- architecture上の禁止依存を検知する仕組みがあるか。必要な例外は理由付きか。
- 過去の会話だけに残る運用合意、独立して重複した状態/数値定義、古い進捗を現仕様として読む箇所がないか。

今回の草案作成で運用合意を明文化したが、実装やTests/CIの保証を増やしたわけではない。

## 今回の成果物検証

- skill-creator付属quick_validate.pyで4草案のfrontmatter/name/descriptionと本文形式を検証し、全件成功。Skillの判断品質や実コード適合を証明する検証ではない。
- 新規Markdownの相対ファイルリンク、git diff --checkを確認。
- 発動条件を「Executeのlock変更」「自由文字列検索の変更」「本文だけの文書修正」に照らして手動確認。必要なSkillだけを選び、普通の文書修正に全レビューを強制しない構成とした。独立Agentによるbehavior評価は未実施。
- 文書・草案のみのためbackend pytestは再実行していない。正式導入時は配置後の参照、発見、代表的な実作業での振る舞いを別途確認する。
