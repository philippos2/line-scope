# LineScope トランザクション・更新制御設計書

## 1. Isolation

通常更新はPostgreSQL `READ COMMITTED` を使用する。

Graph-affecting更新は、最初の業務データ読込より前にtransaction-scoped Advisory Lockを取得し、その後に最新値を再読込して検証する。

ロック待機には設定可能なtimeoutを設け、超過時は更新しない。

## 2. Prepare

Prepareは正本業務データを変更しない。

1. requester認可
2. 対象一意化
3. 現在値読込
4. proposed Snapshot作成
5. canonical JSONでsnapshot_hash生成
6. UpdateRequest / UpdateTarget / Approval(PENDING)作成
7. WAITING_APPROVAL

idempotency_keyはサーバ生成UUID。

## 3. Approve

Approval APIの短いTransactionで:

1. UpdateRequest → Approvalの順でrow lock
2. approver認可
3. 自己承認規則
4. PENDING確認
5. client snapshot_hash == stored snapshot_hash
6. APPROVED
7. approved_at=server_time
8. expires_at=approved_at+30分
9. UpdateRequest=APPROVED
10. commit

## 4. Execute開始条件

- authenticated_user_id == requester_id
- UpdateRequest=APPROVED
- Approval=APPROVED
- now < expires_at
- snapshot_hash一致
- consumed_at IS NULL

## 5. Execute Transaction

1. 必要ならGraph mutation advisory lock取得
2. UpdateRequest / ApprovalをFOR UPDATE
3. 開始条件再検証
4. 全Target業務行を(target_type, target_id)順にFOR UPDATEし最新値取得
5. UPDATE/DISABLE version確認
6. CREATE business key確認
7. 業務ルール・型・循環・期間重複検証
8. 全Target更新
9. BusinessUpdateHistory記録
10. Graph対象ごとにOutbox INSERT
11. Approval=CONSUMED, consumed_at設定
12. UpdateRequest=COMPLETED
13. COMMIT

## 6. 実行失敗とApproval再利用

### 再利用可能
commit前の一時的技術障害で、正本変更が確定しておらずSnapshotも有効な場合。
主TransactionをROLLBACKし、UpdateRequest/ApprovalをAPPROVEDのまま残す。

### 再利用不可
- VERSION_CONFLICT
- CREATE_CONFLICT
- BUSINESS_RULE_VIOLATION
- Snapshot不一致
- 権限変化
- 期限切れ

別の短いTransactionでUpdateRequest=INVALIDATEDまたはEXPIRED、Approval=INVALIDATEDまたはEXPIREDとする。

### commit結果不明
クライアントはexecuteを盲目的再実行せずGETで状態確認する。
execute自体はUpdateRequest単位で冪等であり、COMPLETED済みなら既存結果を返す。

## 7. Outbox状態

- PENDING
- PROCESSING
- RETRYABLE
- APPLIED
- DEAD

event採番順をcommit順とみなさない。

## 8. Projection Worker

v1は単一active workerとする。

workerはPostgreSQL Advisory Lockでleader権を取得する。

選択条件:
- status=PENDING
- またはRETRYABLEかつnext_attempt_at<=now
- commit済み行のみ

イベントはcreated_at / outbox_id順で処理してよいが、順序を正当性条件にしない。

各payloadはaggregateの完全な投影状態を含める。
Neo4jはsource_versionで古いイベントを拒否し、同version再適用は冪等成功。

## 9. Projection失敗

一時障害:
- RETRYABLE
- exponential backoff
- attempt_count増加

上限超過または恒久不正:
- DEAD
- Graph sync=ERROR
- v1ではDEAD解消まで後続Projectionを停止する

## 10. Graph Sync

- REBUILDING flag優先
- DEADまたはgraph_projection_control.fatal_errorあり -> ERROR
- PENDING / PROCESSING / RETRYABLEあり -> LAGGING
- それ以外 -> CURRENT

processed_atやoutbox_idの大小だけでは判定しない。

## 11. Rebuild

v1では安全性を優先してGraph-affecting更新を一時停止する。

1. 通常workerに新規claim停止を指示し、実行中処理を終了させ、専用接続でworkerと共通のsession-scoped leader advisory lockを取得する。同時Rebuildも禁止する。
2. 別の短いTransactionでrebuild_flagとrebuild_idを保存しREBUILDINGとする。
3. 専用接続でREAD COMMITTED Transactionを開始し、Graph mutationの排他transaction-scoped advisory lockを取得する。
4. Rebuild controllerがleaderを保持したまま、通常workerと同じ冪等Projection処理で未処理Outboxをdrainする。この接続では取得済みmutation lockを再取得せず、Outbox状態更新は別の短いTransactionで保存する。DEADまたはdrain処理中の重大障害があれば中止する。既存fatal_errorは復旧対象であり、それだけを理由にRebuildを拒否しない。active_generationのない初回seedはOutboxなしで構築する。
5. 未処理0を確認後、ロック保持接続の単一SQL statementで全Graph正本を一括取得し、一貫したstatement Snapshotを作る。
6. 新generationのGraphを構築し、ノード・エッジ・version・属性・件数をSnapshotと照合する。
7. 検証後、別の短いTransactionでactive_generationを切り替え、復旧対象fatal_errorとrebuild_flagを解除する。排他lockはまだ保持する。
8. 専用接続のTransactionをCOMMITしてmutation lockを解放し、leader lockを解放する。
9. 通常workerを再開する。同期状態は§10で再計算し、無条件にCURRENTとしない。

global event_id cutoffは使用しない。

## 12. 状態遷移

### UpdateRequest
PREPARED -> WAITING_APPROVAL
WAITING_APPROVAL -> APPROVED | REJECTED | INVALIDATED
APPROVED -> COMPLETED | INVALIDATED | EXPIRED
未承認要求は無期限のためWAITING_APPROVAL -> EXPIREDは存在しない。
WAITING_APPROVAL / APPROVED -> FAILED は回復不能な内部整合障害に限定し、対応するPENDING / APPROVED ApprovalはINVALIDATEDにする。COMPLETED / REJECTED / EXPIRED / INVALIDATED / FAILEDは終端であり上書きしない。

### Approval
PENDING -> APPROVED | REJECTED | INVALIDATED
未承認要求は無期限のためPENDING -> EXPIREDは存在しない。
APPROVED -> CONSUMED | INVALIDATED | EXPIRED

不正遷移は禁止。

## 13. 期限判定

期限切れ判定はexecute時に同期実施する。approveはPENDINGだけを受理し、再承認で期限を延長しない。任意のsweeperはAPPROVEDかつnow >= expires_atの要求・承認だけを同じlock順でEXPIREDへ更新してよい。正しさをsweeperへ依存しない。

## 14. 複数Target

一UpdateRequestの全Targetを一Transactionで更新する。

## 15. 更新競合・Snapshot・冪等性

Lock順序は、必要なGraph mutation lock → UpdateRequest → Approval → 業務行(target_type, target_id順)。Approve、Reject、別Transactionの失効もUpdateRequest → Approvalの順を守る。UPDATE / DISABLEは行ロック後にexpected_versionを確認し、さらにversion条件付き更新で影響行数1を要求する。CREATEはDB UNIQUE制約で最終防御する。禁止循環・期間重複はGraph mutation lock下で全Target適用後の予定集合を検証する。

Assignment変更は親ProductionOperationを必ずロックし親versionを1増加する。予定値と同時変更しても親の増加は1回。変更するAssignmentのexpected_versionもSnapshotに含める。割当差分はdomain-model §15.2の期間置換規則に従い、親version・全active Assignment集合をprepare時に固定する。保存形状はdata-model §12のequipment_assignmentsを用い、親before集合と各Assignment Targetのbeforeの一致、および全差分適用後のactive集合と親after集合の一致を検証する。親Targetがない割当差分、一部差分の欠落、集合の重複・期間重複は拒否する。割当置換が実変更なしでも予定値に実変更があれば親だけを更新でき、両方に実変更がなければ要求を作成しない。

失敗後の別Transactionは同じ順でlockを取り、状態・hash・期限・競合原因を再検証する。依然APPROVEDの同一Snapshotに失効原因が成立する場合だけINVALIDATED / EXPIREDにする。COMPLETED / CONSUMED等の終端状態を上書きしない。他Executeが成功済みなら既存結果を返す。

Approvalは一UpdateRequestにつき1件。PREPAREDはPrepare Transaction内部の中間状態とし、Target・PENDING Approval・WAITING_APPROVALを同時commitする。SnapshotとTargetは保存後不変。内容変更は旧要求・承認をINVALIDATEDとし、新規Prepareする。PENDINGも失効できる。approve時もhash再計算、対象version / CREATE一意性を確認し、不一致はINVALIDATED。無関係な変更では失効しない。

RejectはApproveと同じ権限・自己承認規則を確認し、WAITING_APPROVAL / PENDINGの組だけREJECTEDにする。承認済みの取消操作には使わない。無権限者のApprove / Reject、送信hashの誤り、非owner Executeでは状態を変えない。ownerの新規Executeでrequester / approverの必要権限喪失を検出した場合は承認失効規則に従う。

期限はlock取得後の実時刻で判定し、now >= expires_atなら失効。Transaction開始時刻に固定された時計を使わない。業務更新後・承認消費直前にも確認し、期限到達ならROLLBACKする。PENDINGに期限を設けない。

COMPLETEDのTransactionでexecution_resultと確定after_snapshotを保存する。再Executeはowner確認後にこの結果を返す。commit後の正本再参照は別のcurrent_snapshot / current_versions / observed_atとして返し、別更新があればversion差を示す。再参照失敗は更新失敗と混同せず、確定結果と警告を返す。

### canonical Snapshot v1

schema_version=1、requester_id、supersedes_update_request_id（通常NULL）、targetsを含む。Targetはtarget_type、target_id、business_key、operation_type、before、after、expected_versionを含み、Assignment差分を含む全業務変更を列挙する。CREATEのtarget_idはPrepareで生成し固定、before / expected_versionはNULL。before / afterは全業務項目とversionを含み、実行時付与の監査時刻は含めない。業務値の不足を時刻等で推測補完しない。

object keyをUnicode code point順、空白なしUTF-8 JSONで直列化する。文字列は引用符・逆斜線・制御文字をJSON escapeし、その他Unicodeは保持。数値は整数のみ。UUIDは小文字標準形、時刻はUTCのYYYY-MM-DDTHH:mm:ss.ffffffZ。schema上の省略可能項目もNULLを明示する。targetsは(target_type, target_id)順、集合は重複を拒否してID順、ordered arrayは順序維持。SHA-256の小文字hexをsnapshot_hashとしcanonical文字列も保存する。説明文・request_id・Approval時刻・Outbox IDはhash対象外。

### Prepare再試行

idempotency_keyは従来どおりサーバ生成UUID。別にtrusted orchestratorがPrepare前にprepare_retry_keyを生成・固定する。POST /agentのIdempotency-Key UUIDがあればこれを使用し、なければサーバ生成する。LLMはretry keyを生成・変更しない。一/agentでPrepareは最大1要求（複数Target可）。

(requester_id, prepare_retry_key)をUNIQUEとし、同じ正規化入力の再送は既存要求を返し、異なる入力はDUPLICATE_REQUEST。prepare_input_hashはTool名・解決済み対象・明示提案値から生成し、再取得したbefore / versionを含めない。HTTP再送は保存済みagent_input_hash（message、明示as_of、context_id、replace_update_request_id）を先に照合し、要求保存済みならLLMを再実行しない。内部再送もPrepare入力を変えない。同キーの並行PrepareはUNIQUE競合後に既存結果・入力hashを確認する。rollbackなら同キーで再試行可。キーを知らない応答喪失は自動再Prepareしない。

## 16. Graph分析の整合境界

Graph Toolは共通Graph mutation advisory lockをshared transaction-scopedで取得し、その後CURRENTとactive_generationを確認する。Graph-affecting Execute、Projection適用、Rebuildは同じキーのexclusive lockを使う。ProjectionはNeo4j commitとOutbox APPLIED確認まで排他lockを保持する。

Graph Toolは単一Neo4j read Transactionで同じgenerationを探索し、サーバEvidence構築・終了時同期再確認までshared lockを保持する。終了時もCURRENTを要求する。LLM説明中はlockを保持しない。graph_generation、graph_observed_at、as_ofをEvidenceに含め、観測時点の結果として返す。lock待ちもTool timeoutに含める。

状態確認はPostgreSQLの単一statement Snapshotで行い、state_observed_atと確認versionを返す。全ストアの同時Snapshotではない。利用可能性・過去分析の業務意味はdomain-model §15に従う。過去as_ofでは現在状態の利用可能性を適用しない。

## 17. Outbox・Rebuild復旧

PENDING / RETRYABLE → PROCESSING → APPLIED | RETRYABLE | DEAD。PROCESSING lease超過はRETRYABLE、DEAD → RETRYABLEは原因修正後の管理操作のみ、APPLIEDは終端。attempt_countはclaimごとに増加。Neo4j commit後のAPPLIED保存失敗も再送で同version冪等適用。古いversionも新しいmarker確認後APPLIEDとする。同versionで異なるpayloadはDEAD。

leaderは専用接続のsession advisory lock。接続喪失時はNeo4j処理を中断する。旧処理が残る競合もNeo4j aggregate markerへのwrite lock取得後のversion比較で直列化する。

Rebuild失敗時は旧generationを保持しfatal_errorを記録、flag解除後はERROR。接続喪失でflagが残った場合、次controllerがleader取得後rebuild_id・公開状態を確認し、未検証generationを破棄するか、検証済み切替の完了を確認して復旧する。flagが残る間REBUILDING。lock保持時間にもhard timeoutを設け、超過時は未検証Graphを公開せず中止する。

## 18. 権限・カテゴリ・業務入力

requesterと承認者の現在権限をexecute時に再検証し、必要権限喪失はINVALIDATED。COMPLETED再送はowner・閲覧権限確認で保存結果を返す。一UpdateRequestは単一カテゴリ。業務入力はrequirements §12、割当・成立条件はdomain-model §15に従う。承認成立後30分、owner限定、全Target原子性は維持する。

## 19. Prepare Snapshotの一貫性と要求の置換

Prepareの正本読込は単一statement Snapshotを使い、親・関連Assignment・対象行を一貫して取得する。そのSnapshotから差分を作る。Executeではlock下の最新親version・Assignment集合・変更行versionを再検証する。Prepareで業務変更lockを長時間保持しない。

POST /agentにreplace_update_request_idがある場合、trusted orchestratorがPrepareへ注入する。旧要求のrequester本人だけを許可し、旧要求・承認をlockしてWAITING_APPROVAL / PENDINGまたはAPPROVED / APPROVEDだけをINVALIDATEDにする。新要求保存と旧失効は同一Prepare Transaction。終端要求の置換はINVALID_UPDATE_STATE。新Prepare失敗なら旧要求も変更しない。旧IDはcanonical Snapshotのsupersedes_update_request_idに含める。対象version変化だけでの失効はapprove / execute時の検知で行う。

approveも保存canonical Snapshotからhashを再計算し、requestとapprovalのhashが等しいことを要求する。権限変更は認証サーバの現在user設定でrequester / approver IDから解決し、LLM・過去のrole自己申告を使用しない。認証設定参照不能はfail closedの一時障害とし、権限喪失が確定した場合と区別する。

許容組: WAITING_APPROVAL/PENDING、APPROVED/APPROVED、COMPLETED/CONSUMED、REJECTED/REJECTED、EXPIRED/EXPIRED、INVALIDATED/INVALIDATED、FAILED/INVALIDATED。組不整合は確定更新を拒否し、監査・内部障害として記録する。

Snapshot照合はcanonical保存文字列だけでなく、保存UpdateTargetから同じ規則で再構成したhashも確認する。request / approval / Targetのどれかが一致しなければ更新しない。監査timestampはhash対象外でも、確定execution_resultには実行サーバ時刻を付与する。

Prepareの提案値作成に複数Target間の区間差分がある場合、全差分を作った後に一意性・期間重複・循環を検証する。UPDATEによる区間縮小 / DISABLEを先に適用してからCREATEを適用し、制約上の一時重複を避ける。すべて同一Transaction内であり中間状態をcommitしない。

初回seedは通常API公開前に行い、Outboxなしで正本初期化する。Restore等でgeneration欠損かつ未処理が残る場合は、排他lock下でまず正本の作業用generationを検証してdrain先に用意する（operations §10）。この場合もDEAD中止と全イベント状態集合での判定を維持する。

Graph業務キーの検証は全Target適用後の予定集合に対して行う。別Targetが同Transactionで移動する旧キーをCREATE_CONFLICTと誤判定しない。Graph業務キーUNIQUEは必要時DEFERREDにして最終検証し、制約エラーは全ROLLBACKする。通常CREATEの業務キーとPrepare retryの一意制約は即時確認する。CREATEの不存在行はFOR UPDATEできないため、DB一意制約とGraph lockが防御となる。

Graph Syncはcontrol rowとcommit済みOutbox集合を同一PostgreSQL statementで評価する。control行欠損・active_generation=NULLもERRORとし、依存ストアへの接続不可は正常結果を返さない。

## 20. 実装前最終確認の固定事項

Prepare retry keyは認証user_id単位・一更新要求単位。成功Prepareとともに永続保存しTTLを設けず、context TTL・Approval期限とは独立する。終端要求の同キー再送も旧要求を返し、新規要求に流用しない。異なる正規化受付入力・Prepare内容は409 DUPLICATE_REQUEST。未保存でrollbackした呼出しのみ同キーを再試行可能とする。

canonical v1ではdecimal / float（1.0を含む）を拒否し、整数・boolean・string・NULL・array・objectだけを許可する。objectの重複key、Unicode surrogate、timezoneなし時刻を拒否する。C0制御文字は小文字hexの\u00xx、引用符・逆斜線はそれぞれ\"・\\でescapeする。Unicode正規化を勝手に行わない。UUID・timestamp正規化はschemaで型が指定された値だけに行い、本文文字列は変えない。schema_version未知は更新拒否。Snapshotに含むnullable業務列は省略せずNULLを保存する。

Projection workerのclaim TransactionはPROCESSINGをcommitしてから、exclusive mutation lockを取って適用する。claim時にmutation lock待ちやGraph control行lockを保持しない。適用前にlease・status・DEAD停止・generationを再検証し、別TransactionでAPPLIEDを記録するまでmutation lockを保持する。Rebuild controllerはleaderを取得してからmutation lockを取得し、通常workerもleader → mutationの順序とする。Graph Toolはshared mutationのみでleaderを取らない。分析中にfatal_error / rebuild_flagが変われば終了時の同期確認で結果を破棄する。

Rebuildの既存flag復旧はleader取得後に旧公開generationとrebuild_idを確認し、未検証切替を完了済みと推測しない。公開済みgenerationの検証情報をNeo4j側にgeneration markerとして保存し、control pointerとの照合で切替前後のcrashを区別する。旧generationを破棄するのは新generation検証・公開後の管理cleanupだけとする。
