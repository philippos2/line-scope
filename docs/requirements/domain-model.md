# LineScope 業務データ・業務ルール定義書

## 1. 業務エンティティ

- Equipment
- EquipmentState
- EquipmentStateHistory
- MaintenancePlan
- MaintenanceRecord
- Process
- ProductionOperation
- Product
- InfrastructureResource
- ProductionOperationEquipmentAssignment
- DependencyRelation
- UpdateRequest
- UpdateApproval
- BusinessUpdateHistory
- KnowledgeDocument

## 2. ProductionOperation

生産作業を表す。

v1で更新可能な項目:
- planned_status
- planned_start
- planned_end
- 使用Equipment集合

1つのProductionOperationは0台以上のEquipmentを使用できる。

## 3. ProductionOperationEquipmentAssignment

ProductionOperationとEquipmentの使用割当を表す正本である。

同じ事実をProductionOperationの単一FKとDependencyRelationの双方へ保持しない。

Graph上の `USES` は本エンティティから派生する。

## 4. DependencyRelation

`source -> target` を保存方向とする。`USES` はDependencyRelationとして直接登録せず、割当から派生する。

| 関係種別 | 許可source | 許可target | 保存意味 | 影響方向 | 上流探索方向 | 構造循環 |
|---|---|---|---|---|---|---|
| DEPENDS_ON | Equipment / Process / ProductionOperation | Equipment / InfrastructureResource / Process | sourceがtargetに依存 | target→source | source→target | 禁止 |
| PRECEDES | Process / ProductionOperation | 同一種別 | sourceがtargetに先行 | source→target | target→source | 禁止 |
| SUPPLIES | InfrastructureResource / Equipment | Equipment / Process / ProductionOperation | sourceがtargetへ供給 | source→target | target→source | 許容 |
| CONTROLS | Equipment | Equipment | sourceがtargetを制御 | source→target | target→source | 禁止 |
| PRODUCES | Process / ProductionOperation | Product | sourceがtargetを生産 | source→target | target→source | 禁止 |
| CAN_SUBSTITUTE | Equipment / Process / InfrastructureResource | sourceと同一種別 | sourceがtargetの代替候補 | 通常影響探索には不使用 | 通常上流探索には不使用 | 循環判定対象外 |
| USES | ProductionOperation | Equipment | 作業が設備を使用 | Equipment→ProductionOperation | ProductionOperation→Equipment | 禁止 |

## 5. 混在Graph探索

保存方向そのものではなく、上表の「影響方向」または「上流探索方向」を論理Traversal方向として使用する。

実装はCypherで関係種別ごとに方向を扱っても、Projection時に補助的な探索構造を作ってもよい。ただし業務意味論は上表を正とする。

## 6. 直接・間接影響

対象へ複数経路で到達できる場合、最短hop数で分類する。

- 1 hop = 直接
- 2 hop以上 = 間接

## 7. required

`required=true` は、関係の業務方向に沿って依存する側の成立に供給・依存先が必須であることを示す。DEPENDS_ONではsourceにtargetが必須、SUPPLIESではtargetにsourceからの供給が必須。

- DEPENDS_ON: sourceの成立にtargetが必須
- SUPPLIES: targetの成立にsourceからの供給が必須
- PRECEDES / CONTROLS / PRODUCESは関係自体を必須関係として扱い、required値は使用しない
- CAN_SUBSTITUTEでは使用しない
- USESは割当がactiveな間、当該作業に必要な設備利用関係として扱う

単一障害点候補判定では必須関係のみを成立条件に含める。

## 8. 有効期間

DependencyRelationおよびAssignmentは `effective_from <= as_of < effective_to`（effective_to NULLは無期限）の場合に有効とする。

`as_of`未指定時はサーバ時刻を使用する。

v1の禁止循環判定は安全側へ倒し、有効期間にかかわらずactiveな禁止種別関係の構造全体に対して行う。

## 9. 禁止循環

禁止循環は、DEPENDS_ON、PRECEDES、CONTROLS、USESを各関係の業務意味に従う同一論理依存グラフ上で検証する。

PRODUCESはProductを終端とするためProductからの戻り関係を許可せず、結果として循環を形成できない。

SUPPLIESは閉ループ設備を表現し得るため循環を許容するが、探索では既訪問ノードを再展開しない。

CAN_SUBSTITUTEは循環判定対象外。

## 10. 代替経路

停止対象を除外しても重要対象の全必須成立条件を満たす構造、またはCAN_SUBSTITUTEによる置換候補を用いる構造を代替候補とする。単なる別経路の到達可能性は、必須依存を置換できる根拠としない。

構造上の候補と現在利用可能性は区別し、後者にはPostgreSQL正本の状態確認を必要とする。

## 11. 単一障害点候補

指定された重要対象について、候補要素を除外すると必要な成立経路がなく、かつ有効な代替候補がない場合に単一障害点候補とする。

探索が途中打切りの場合は「候補なし」とせず `INDETERMINATE` とする。

## 12. UpdateRequest

状態:
- PREPARED
- WAITING_APPROVAL
- APPROVED
- COMPLETED
- REJECTED
- EXPIRED
- INVALIDATED
- FAILED

実行中は永続状態として必須とせず、Transaction内部状態として扱う。

## 13. UpdateApproval

状態:
- PENDING
- APPROVED
- REJECTED
- EXPIRED
- INVALIDATED
- CONSUMED

Approvalは保存済みSnapshot Hashに対して成立する。

## 14. Business Key

| Entity | Business Key |
|---|---|
| Equipment | equipment_code |
| MaintenancePlan | plan_code |
| MaintenanceRecord | record_code |
| Process | process_code |
| ProductionOperation | operation_code |
| Product | product_code |
| InfrastructureResource | resource_code |
| ProductionOperationEquipmentAssignment | production_operation_id + equipment_id + effective_from |
| DependencyRelation | source type/id + target type/id + relation_type + effective_from |
| KnowledgeDocument | document_code + document_version |

同一論理関係について有効期間が重複するactiveレコードを業務ルールで拒否する。

## 15. レビューで確定した業務意味

### 15.1 必須成立条件・置換・SPOF

必須上流要素はAND条件であり、複数の必須依存をすべて満たす必要がある。必須上流を持たないノードは構造上の成立起点。required=falseのDEPENDS_ON / SUPPLIESは到達探索には含められるが、成立必須条件には含めない。PRECEDES / CONTROLS / PRODUCES / active USESは方向表に沿う必須条件。

停止・除外された必須要素に対し、CAN_SUBSTITUTEのsourceがtargetを置換する一段候補を評価する。候補自身の全必須依存も満たすことを要求する。置換候補からさらにCAN_SUBSTITUTEを辿る連鎖置換はv1対象外。ほかの必須依存まで免除せず、置換利用はEvidenceで明示する。通常の影響・上流到達探索にはCAN_SUBSTITUTEを混ぜない。

必須依存の循環を含む評価は、循環が成立すると仮定せずINDETERMINATEとする。循環を許容した到達探索は既訪問制御で続行可能。SPOF候補は重要対象自身を除く必須上流要素から取り、候補除外後に重要対象が成立せず、利用可能な一段代替もない場合とする。複数重要対象は対象ごとに判定する。未知の利用可能性を「代替なし」としない。

Equipmentの現在利用可能性はRUNNING=AVAILABLE、STOPPED / UNDER_MAINTENANCE=UNAVAILABLE、UNKNOWN=UNKNOWNとする。ProductionOperationはPLANNED=AVAILABLE、CANCELLED=UNAVAILABLE（予定上の利用可能性であり実行中状態ではない）。Process / InfrastructureResourceはv1に状態正本がないため構造候補まで、現在利用可能性はUNKNOWN。必須代替の利用可能性がUNKNOWNならSPOFの確定判定はINDETERMINATE。構造成立と運転能力・容量等の保証を混同しない。

### 15.2 Equipment集合変更

集合置換は利用者が明示した半開区間[start, end)内だけを対象とする。startは必須。endは明示時刻か明示NULL（無期限）を要求し、省略から無期限と推測しない。期間外の割当を保持する。重なる既存割当は区間を切り分け、置換区間は新集合を適用する。元の割当がそのまま望ましい集合・期間を満たす場合は不要な分割を行わない。

差分のTarget ID・期間・before / afterはPrepareで固定する。必要な保持区間と新集合区間を求め、同じ業務キーの既存行はUPDATE、存在しないキーはCREATE、不要となるactive行はDISABLEする。inactive行とキーが一致する場合もversion付きUPDATEで再有効化する。境界だけ接する区間は重複ではない。空集合も明示要求なら許可する。無期限置換の場合はstart以降の将来割当も置換対象になるため、影響する全割当をSnapshotで提示する。

### 15.3 as_ofと過去分析

v1の過去as_ofは現在登録されているactive関係・割当の有効期間評価に限定する。当時の登録内容や設備状態の完全再現は対象外。後からDISABLEされた関係は過去as_ofでも探索対象外。結果にCURRENT_REGISTRATION_AT_AS_OFとanalysis_modeを示す。明示過去時点はEXPLICIT_HISTORICAL、未指定のサーバ時刻分析はCURRENTとする。過去の利用可能性は現在状態から推定せずUNKNOWNとする。SPOFは構造上の評価と現在利用可能性を分離し、過去の代替利用可能性が判定に必要ならINDETERMINATE。

### 15.4 循環方向とSnapshot変更

禁止循環の論理依存方向は§4の上流探索方向で統一し、DEPENDS_ON / PRECEDES / CONTROLS / USES混在集合を検証する。禁止種別・SUPPLIES循環許容は変更しない。

保存済みSnapshotは編集せず、旧要求・承認をINVALIDATEDにして新規Prepareする。PENDINGも対象変更で失効できる。

代替候補間はOR（少なくとも一候補の全AND依存・利用可能性が成立）とする。AVAILABLE候補があればUNKNOWN候補が併存してもその代替は利用可能。AVAILABLEなしでUNKNOWNが残れば未確定。候補の依存側でさらに置換を必要とするものは、一段置換の成立確認に使わない。SPOFは除外前の重要対象が構造成立していることも確認し、もともと不成立・循環未確定ならINDETERMINATEとする。探索打切りは全体INDETERMINATEであり、候補なしと返さない。

## 16. 業務判断支援の意味論

EquipmentStateのRUNNING / STOPPED等は稼働状態であり、劣化程度、安全認定、生産能力、空き能力を表さない。RUNNING=AVAILABLEは既存の構造候補評価の利用可能性であり、十分な生産・安全・品質条件の保証ではない。劣化観測と稼働状態を別の業務情報として扱い、その項目・判定条件はPO-B04および本書の正式安全入力に従う。

CAN_SUBSTITUTEはsourceがtargetを置換する一段候補のままとし、推移閉包しない。能力評価は製品・単位・期間・使用中負荷が一致した条件で行う。構造成立、状態利用可能性、能力充足、安全条件を別々に評価し、未知を成立済みまたは証明済みの不成立へ変換しない。

損失は到達経路の本数ではなく業務対象と定義済みの損失項目を基準に計算する。同じProductに複数経路で到達しても重複加算しない。複数製品・品質損失との独立加算条件はPO-B02で確定する。

Graphのcompleteは探索の完全性であり、能力・経済・安全・リスク情報の完全性ではない。0は既知の数値、FALSEは既知の否定、NONEは確認済みの不存在、UNKNOWNは情報不足、INDETERMINATEは判定不能、NOT AVAILABLEは取得・提供不能として区別する。各フィールドの型や理由コードはAPI契約確定時に定義し、既存のNULL（無期限や計画との関連なし）を一律UNKNOWNへ読み替えない。

将来の計画期間・what-if評価は、現在Graphと登録済み業務入力・仮定に基づく条件付き分析として観測時点と評価期間を区別する。既存as_ofを未来予測や完全なpoint-in-time履歴復元に転用しない。将来停止の予約と現在状態更新を区別する。期間・予定・履歴はPO-B01・05・06と本書の正式対応計画・故障履歴に従う。

現行関係表のInfrastructureResourceは上流の供給・依存資源として到達できるが、Equipment停止から同資源への通常下流影響は定義されていない。UC-B01の意味はPO-B08で確定し、影響方向を勝手に反転しない。

## 経済入力

EconomicInputは設備と共通比較期間に対する条件付きの費用見積。REPAIR / REPLACE / CONTINUEの各案について、直接費（JPY）、停止損失・劣化損失（JPY/hour × 明示時間）を独立した項目として保持する。各項目は出典、推定／確定、適用期間、独立加算の確認を持つ。Graph到達だけでは実停止・損失を認定しない。項目が全費用を網羅することも明示入力し、非網羅・未知・非独立があれば総額不明。既知の独立項目の小計は別表示する。能力・安全・将来計画の適否や最適案は本計算から導出しない。

## 正式能力入力

CapacityInputは一設備・一製品・一評価期間・一数量単位の能力と需要の明示入力。通常能力、使用中負荷、予約負荷、必要能力はいずれも同じ数量単位/hourであり、異なる製品・単位・期間を合算しない。出典・推定／確定と期間を保持する。負荷の網羅性・重複なしを確認できなければ利用可能能力はUNKNOWN。負荷が通常能力を超える入力もUNKNOWNとし黙ってゼロ補正しない。互換性はtrue / false / nullで明示し、GraphのCAN_SUBSTITUTEから生成しない。能力充足は安全・品質・実稼働の充足ではない。

bufferは同製品・同数量単位。一定需要・供給、他の引当なし、復旧後の需要充足という条件が明示され、毎時不足量が正の場合だけ条件付き復旧期限を算出する。ゼロ不足を無期限の納期保証へ変換しない。評価期間外までの期限や可変需要・calendar・複数納期への引当はこの単純モデルの保証外。

## 正式安全入力

- SafetyInputは一設備に対する出典・適用期間付きの観測、安全基準、継続条件、登録上の判断、推定／確定、リスク資料を保持する。
- 停止必須は継続候補から除外。条件付き継続は登録された前提の範囲に限り、不明や期限外を安全としない。
- 基準の数値・悪化確率・故障原因をLLMや設備状態から生成しない。
- 単一入力の評価を設備全体の安全認定としない。複数記録や欠落した安全条件を合算・補完せず、実運転許可を発行しない。
- RUNNING等は稼働状態の事実であり、安全認定と別。登録済みの停止必須判断があっても、実際にRUNNINGであるという事実登録を拒否しない。

## 正式対応計画・故障履歴

- MaintenanceInputは一設備の出典付き入力。kindはREPAIR_PLAN / REPLACEMENT_PLAN / INTERIM_PLAN / FAILURE_RECORD / REPAIR_RECORDを明示する。稼働状態や既存の自由文保全実績から分類を生成しない。
- 計画ではperiod_start / period_endが費用評価期間。lead_time_hours（調達待ち）・work_hours（作業）・downtime_hours（停止）を別に保持する。暫定終了interim_untilは評価期間内とし、不明はnull。
- 交換費を除く直接費direct_cost_jpyと、明示的に算入するreplacement_cost_jpyを区別する。include_replacement_costはtrue / false / null。算入条件と必要値が既知のときだけ計画直接費小計を返す。停止・劣化損失を含む総経済影響や優劣は本入力だけで認定しない。期間外費用の按分・加除はしない。
- 履歴のperiodは過去の事象期間。past_loss_jpyは過去停止損失であり、将来案の費用へ加算しない。将来故障確率は生成しない。
- 既存MaintenancePlanを同じ設備の予定として任意関連付けできる。予定本体・状態は従来モデルを維持する。将来のPLANNED予定の最早開始を次回候補とし、同時刻の候補は明示選択する。上限超過で候補が不完全なら次回を判定しない。

## 正式入力を組み立てるDecision Package

Decision Packageは更新対象の新しい正本ではなく、明示した入力と現在Graphの読取結果をまとめたviewである。入力のID・version・観測日時、比較期間と情報の不足を保持し、全ストアの同時Snapshotや設備全体の運転許可を意味しない。経済・能力・安全・計画の意味は各入力の正本に従い、比較層で新しい値を生成・補完しない。
