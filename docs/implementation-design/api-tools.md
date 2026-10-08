# LineScope API / Tool設計書

## 1. 共通HTTP Response Envelope

```json
{
  "request_id": "uuid",
  "context_id": "uuid-or-null",
  "status": "ok|partial|error",
  "answer": "LLM generated natural language or null",
  "data": {},
  "evidence": {},
  "warnings": [],
  "errors": []
}
```

`evidence`、Graph同期状態、complete、limit_reasonはサーバがTool結果から構築し、LLM文面のみへ依存しない。

## 2. POST /agent

入力:
```json
{
  "message": "...",
  "context_id": "optional",
  "as_of": "optional explicit historical time",
  "replace_update_request_id": "optional UUID of own nonterminal request to supersede"
}
```

出力は共通Envelope。

## 3. GET /update-requests/{id}

閲覧権限を確認し、canonical Snapshot、snapshot_hash、status、approval status、expires_atを返す。

## 4. POST /approvals/{approval_id}/approve

入力:
```json
{"snapshot_hash":"sha256..."}
```

認証済み承認者、権限、自己承認規則、PENDING状態、対象versionと保存Snapshot、hash一致を検証する。未承認期限は設けず、承認済み再送で期限を延長しない。
成功時 `approved_at=server_time`, `expires_at=approved_at+30min`。

## 5. POST /approvals/{approval_id}/reject

認証済み承認者が拒否する。

## 6. POST /update-requests/{id}/execute

認証済み元requesterのみ実行可能。

LLM経由ではなく専用APIで開始する。

入力Bodyは空とする。サーバはidからUpdateRequest / Approval / Snapshot / versionを取得する。

COMPLETED済みの再送では既存結果を返し、二重更新しない。

## 7. Trusted Execution Context

- authenticated_user_id
- role
- request_id

LLM引数から受け取らない。

## 8. Read Tools

- get_equipment
- search_equipment
- get_equipment_state
- get_equipment_state_history
- get_maintenance_plan
- search_maintenance_plans
- search_maintenance_records
- get_process
- get_production_operation
- get_operation_equipment_assignments
- get_product
- get_infrastructure_resource
- get_dependency_relation
- search_dependency_relations
- search_update_history

## 9. Graph Tools

- trace_downstream_impact
- trace_upstream_dependencies
- find_common_dependencies
- find_alternative_paths
- find_single_point_failure_candidates

入力:
- IDs
- relation_types optional（一般到達探索のみ）
- explicit_as_of optional
- requested_max_depth optional
- requested_max_nodes optional
- requested_max_paths optional

未指定as_ofはTool側server time。

## 10. Graph Limits

system_max_depth / nodes / paths / timeout_msを必須設定。

実効値はrequestedとsystemの小さい方。

Graph結果:
```json
{
  "graph_sync_state":"CURRENT",
  "complete":true,
  "requested_limits":{},
  "effective_limits":{},
  "limit_reason":null,
  "reached_nodes":[],
  "distances":{},
  "representative_paths":[],
  "determination":null
}
```

limit_reason: `DEPTH|NODE_COUNT|PATH_COUNT|TIMEOUT`。

一般探索は上限到達時 `complete=false` のpartial resultを返す。
SPOFは不完全時 `determination=INDETERMINATE`。

## 11. Graph Sync Errors

- LAGGING -> GRAPH_NOT_CURRENT
- ERROR -> GRAPH_UNAVAILABLE
- REBUILDING -> GRAPH_REBUILDING

非CURRENT時、Graph payloadを正常結果として返さない。

## 12. Prepare Tools

- prepare_equipment_state_update
- prepare_maintenance_plan_create
- prepare_maintenance_plan_update
- prepare_maintenance_record_create
- prepare_production_operation_update
- prepare_dependency_relation_update

`prepare_production_operation_update` はplanned_status/start/endとEquipment割当集合を同一Snapshotへ含められる。

## 13. Error Codes

- TARGET_NOT_FOUND
- TARGET_AMBIGUOUS
- MISSING_INFORMATION
- AUTHORIZATION_DENIED
- APPROVAL_REQUIRED
- APPROVAL_HASH_MISMATCH
- APPROVAL_EXPIRED
- APPROVAL_INVALIDATED
- APPROVAL_ALREADY_CONSUMED
- EXECUTION_NOT_OWNER
- BUSINESS_RULE_VIOLATION
- VERSION_CONFLICT
- CREATE_CONFLICT
- DUPLICATE_REQUEST
- UPDATE_FAILED
- GRAPH_NOT_CURRENT
- GRAPH_UNAVAILABLE
- GRAPH_REBUILDING
- GRAPH_PATH_NOT_FOUND
- INTERNAL_ERROR
- INVALID_ARGUMENT
- AUTHENTICATION_REQUIRED
- DEPENDENCY_UNAVAILABLE
- INVALID_UPDATE_STATE
- CONTEXT_EXPIRED
- RESOURCE_BUSY
- AGENT_LIMIT_REACHED

探索上限はエラーコードではなくpartial resultの `limit_reason` で表す。

## 14. 共通契約の具体化

認証は全HTTP APIで必須。roleとuser_idはサーバ側デモユーザー設定から解決し、Body / LLM引数で上書きしない。POST /agentは任意のIdempotency-Key UUID headerを受ける。更新Prepare再試行のキーはtransaction-design §15に従う。

GET /update-requests/{id}とPrepare成功のdataは、update_request_id、approval_id、status、approval_status、canonical_snapshot（JSON object）、snapshot_hash、snapshot_schema_version、prepare_retry_key、approved_at、expires_atを含む。未承認時のapproved_at / expires_atはNULL。canonical_snapshotのhash対象文字列はtransaction-design §15の形式。閲覧時も改変・再生成で業務内容を変えない。

Approve / Reject成功は両statusとID・時刻を返す。Rejectは空Body、PENDINGのみ。Approve済みの再送は不正遷移として409で返し期限を変えない。Executeは空Bodyのみとし変更値を受け取らない。成功dataはexecution_result（確定Target before / after、history_id、approval_id、executed_at）、current_snapshot、current_versions、observed_atを含む。再送は同じexecution_resultを返す。正本再参照失敗時はcurrent_snapshot等をNULLとしwarningを付け、COMPLETEDを失敗に変えない。

errors[]は{code, message, details}、warnings[]も{code, message, details}。非CURRENTはevidenceに同期状態だけを返し、経路・到達結果を付けない。更新失敗は保存済み要求IDとstatusを返せるが成功結果を生成しない。

HTTP status: 成功200（Prepareを含む）、探索部分結果200かつstatus=partial、schema不正400、認証なし401、権限不足 / 非owner403、不存在404、状態・hash・version・CREATE・冪等性競合409、承認期限切れ410、業務制約違反422、Graph非CURRENT・Neo4j / PostgreSQL等の利用不可503、内部不整合500。状態不正はINVALID_UPDATE_STATE。400はINVALID_ARGUMENT、401はAUTHENTICATION_REQUIRED、context失効は409 CONTEXT_EXPIREDを追加する。ロックtimeoutは503 RESOURCE_BUSYで、業務変更なし。Tool数・Agent deadline超過は503 AGENT_LIMIT_REACHED。PostgreSQLの接続不可はDEPENDENCY_UNAVAILABLEとし、credential・接続先・内部SQLを返さない。内部ToolはHTTPに依存せず同じcodeとdataで返す。

Tool schemaは未知fieldを拒否し、日時はtimezone付きISO 8601、IDはUUID、entity_typeはdomain-modelの型集合、versionは正整数。業務必須・許可値はrequirements §12。省略と明示NULLを区別し、patchのNULLで必須項目を消さない。

## 15. Read Tool入出力

get系は該当ID（equipment_id / maintenance_plan_id / process_id / production_operation_id / product_id / infrastructure_resource_id / dependency_relation_id）を必須とし、一意な正本recordを返す。get_equipment_stateはequipment_idでstate_code / version / updated_at、get_operation_equipment_assignmentsはproduction_operation_idで全active Assignmentと親versionを返す。過去時刻での割当評価が必要な場合はexplicit_as_ofを受け、現在登録情報の期間評価であることを返す。

search系は明示filter、page_size（1〜100、default 20）、cursorを受け、items / next_cursorを返す。安定したID順、cursorは同じfilter・認証主体に拘束する。設備filterはequipment_code / name、保全予定はequipment_id / plan_code / plan_status、保全実績はequipment_id / record_code / maintenance_plan_id、関係はtyped source / target / relation_type / active、履歴はupdate_request_id / category / occurred_from / occurred_to。get_equipment_state_historyはequipment_idと任意の半開期間・pagination。空検索はitems=[]、一意対象なしはTARGET_NOT_FOUND、複数候補からの更新一意化はTARGET_AMBIGUOUS。

検索filterはANDで合成し、省略filterは空条件とする。code・ID・状態値・boolは完全一致、設備nameはPostgreSQLのlowerによる大小文字を区別しないリテラル部分一致とし、% / _をwildcardとして扱わない。maintenance_plan_idの明示NULLは「計画との関連なし」、省略は条件なし。その他の非nullable filterの明示NULLはINVALID_ARGUMENT。activeを省略した通常参照はactive / inactive双方を返す。

cursorは署名付き継続tokenとして認証user_id・role・Tool名・正規化filterに拘束する。改ざん・異なる拘束条件はINVALID_ARGUMENT。page_sizeは途中変更できる。v1の単一APIプロセスはランダム署名keyを起動時に生成し、再起動後のcursorは無効とする。cursorは検索継続用で、更新・承認・Prepare retry keyと共用しない。DB queryはID keysetとpage_size+1のLIMITで次ページの有無を判定し、全件取得や全件数の返却を行わない。

履歴検索は最初にaccess-controlの閲覧filterを適用する。全件検索を経由して権限外件数・recordを返さない。recordの返却項目はdata-modelの該当業務列。更新対象解決後もPrepare内で再読込する。

## 16. Prepare Tool入出力

| Tool | 入力（trusted context・retry keyは別注入） |
|---|---|
| prepare_equipment_state_update | equipment_id、state_code |
| prepare_maintenance_plan_create | plan_code、equipment_id、planned_start、planned_end、plan_status |
| prepare_maintenance_plan_update | maintenance_plan_id、patch{planned_start?, planned_end?, plan_status?} |
| prepare_maintenance_record_create | record_code、equipment_id、performed_at、result、maintenance_plan_id? |
| prepare_production_operation_update | production_operation_id、patch{planned_status?, planned_start?, planned_end?}、assignment_replacement?{effective_from, effective_to, equipment_ids} |
| prepare_dependency_relation_update | operation_type=CREATE / UPDATE / DISABLE、dependency_relation_id（CREATEでは不要）、CREATEの全業務fieldまたはUPDATEのpatch、DISABLEでは追加値なし |

Prepareは現在versionをサーバ取得しSnapshotへ保存する。expected_versionをLLMが生成して権限や競合の根拠にしない。UPDATE対象IDは必須。assignment_replacementはeffective_toを明示NULL可とし、equipment_idsの空集合は可、重複は拒否。同一カテゴリ複数対象はtargets配列（各要素は{prepare_tool, input}、inputは上表の該当schema）で一要求へまとめられる。先頭prepare_toolを呼出しTool名と一致させ、他要素も同カテゴリの既知Prepare Toolだけを許可する。異なるカテゴリはBUSINESS_RULE_VIOLATION。単一入力とtargets配列を同時に渡さない。対象重複・同一行への複数操作は拒否し、Assignment差分はサーバが生成する。

DependencyRelation CREATEは全業務fieldを要求、UPDATEはbusiness keyを含む明示変更fieldだけを合成し全制約を再検証する。USES直接登録不可。required未使用種別でtrueを渡した場合はBUSINESS_RULE_VIOLATION、falseのみ受理する。

## 17. Graph Tool入出力と判定範囲

typed IDは{entity_type, entity_id}。trace_downstream_impact / trace_upstream_dependenciesはtarget、find_common_dependenciesは2件以上のdistinct targets、find_alternative_pathsはimportant_targetsとexcluded_nodes、find_single_point_failure_candidatesはimportant_targetsと任意candidate_nodesを受ける。すべてactive・存在を検証する。candidate_nodes未指定は重要対象自身を除く必須上流集合。複数重要対象は対象別結果。

relation_typesは一般到達探索でのみ任意filterとして使い、Evidenceに分析範囲を返す。代替 / SPOFは全成立関係とCAN_SUBSTITUTEを対象とし、限定relation_types入力はINVALID_ARGUMENTで拒否する。

limitsは正整数。実効limitはmin(requested, system)、未指定はsystem。timeoutはサーバ設定のみ。深度は起点0、nodesは起点を含むdistinct数、pathsは返却代表経路数。BFSの同層node順・edge順もID辞書順に固定。到達しただけで上限扱いにせず、さらに未探索・未返却の対象がある場合complete=falseとする。同時制限はTIMEOUT → NODE_COUNT → DEPTH → PATH_COUNTの順でlimit_reasonを選ぶ。

Evidenceは§10に加えgraph_generation、graph_observed_at、as_of、temporal_scope=CURRENT_REGISTRATION_AT_AS_OF、relation_types、state_observed_at、state_versionsを含む。pathはnodes（typed ID列）、edges（source_record_id、relation_type、保存source/target、論理traversal方向）、hops。distance keyはtyped IDの標準文字列表現。find_common_dependenciesは共通candidateと各入力からの代表経路、alternativeは候補と置換元/先・必須依存Evidence・availability=AVAILABLE / UNAVAILABLE / UNKNOWNを返す。

SPOFのfindingsはimportant_target、candidate、determination=CANDIDATE / NOT_CANDIDATE / INDETERMINATE、reasons、paths、alternativesを含む。すべて確定なら全体determination=DETERMINATE、一部でも未確定ならINDETERMINATE。到達探索が完全でも必須循環・利用可能性不明なら判定はINDETERMINATEとしreasons=CYCLIC_REQUIREMENTS / UNKNOWN_AVAILABILITYを返す。探索打切り時は全体INDETERMINATEとreason=INCOMPLETE_SEARCH。completeは探索完全性だけを表し、業務判定の確定性とは区別する。

起点はdistance=0でEvidenceに保持し、直接/間接影響の返却分類からは除く。循環で再到達しても起点を影響対象へ戻さない。評価に必要な経路Evidenceがpaths上限で返せない場合もcomplete=false。完全探索で候補がない場合は空集合を返し、UNKNOWNを候補なしに変えない。

## 18. 誤り・曖昧性・更新置換

補足確認はHTTP 200、status=ok、data.needs_input=trueとcontext_id / candidates / missing_fieldsで返す。曖昧な更新Prepareの内部ToolはTARGET_AMBIGUOUSであり、Agentは更新要求を作らず確認へ戻る。エラーが解消されていないのに更新成功とは表現しない。

replace_update_request_idは本人の未完了要求を新Snapshotへ置き換える明示指定。サーバからPrepareへ注入しLLMによる旧要求選択を許可しない。Snapshotのsupersedes_update_request_idへ保存する。contextから暗黙に旧要求を失効させない。

EquipmentStateやProductionOperationの現在利用可能性の判定を返す場合、使用した正本versionとstate_observed_atを必須とする。equipment_idがない知識検索も同じ再認可を行う。

GETは保存statusとeffective_statusを返す。APPROVEDで期限到達ならeffective_status=EXPIREDとし、表示だけでDB状態を変更しない。executeは同期判定で実際に失効させる。

as_ofを明示する場合は受信時サーバ時刻以前を要求し、未来値はINVALID_ARGUMENT。未指定はGraph Tool開始時に一度だけserver timeを決め、同一分析の全探索に使う。temporal_scopeに加えanalysis_mode=CURRENT / EXPLICIT_HISTORICALを返す。EXPLICIT_HISTORICALでは利用可能性を現在状態から確定しない。

Read paginationは一呼出し時点の最新正本を返し、ページ間で正本変更があり得ることを示す。複数ページを一つの更新Snapshotと扱わず、Prepareの単一statement Snapshotで確定対象を再取得する。

retry key scope / 永続性はtransaction-design §20に固定する。context_idは補足会話識別子であり、更新要求・承認・冪等性キーの代用ではない。Snapshotでは整数以外の数値型を拒否する。一要求の全Targetの要求権限・承認権限・自己承認条件を満たさない場合は全体拒否し、一部だけの承認・実行を行わない。
