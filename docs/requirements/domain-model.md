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
