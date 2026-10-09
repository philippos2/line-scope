# LineScope ユースケース詳細仕様書

## 1. 共通

- 対象を一意に特定する。
- 権限を確認する。
- 不足情報を推測しない。
- 更新はPrepare→Approval API→Execute APIの3段階とする。
- Graph分析はCURRENT時のみ実行する。

## 2. UC-01 設備状態確認
全ロール。設備特定→現在状態取得→回答。不在・曖昧なら更新なしで終了。

## 3. UC-02 設備履歴確認
全ロール。設備・期間特定→履歴取得→時系列回答。

## 4. UC-03 保全履歴確認
全ロール。設備または保全識別子→保全実績取得→回答。

## 5. UC-04 生産影響確認
保全・生産管理・工場管理。対象特定→Graph CURRENT確認→UC-16〜20の必要分析→根拠付き回答。

## 6. UC-05 設備状態更新
要求者: 現場・保全・工場管理。Prepare→Snapshot確認→承認→元要求者がExecute API→正本再確認。

## 7. UC-06 保全予定登録
要求者: 保全・工場管理。CREATE。plan_code等で重複検証。

## 8. UC-07 保全予定変更
要求者: 保全・工場管理。version一致を必須とする。

## 9. UC-08 保全結果登録
要求者: 保全・工場管理。record_codeを持つCREATE。

## 10. UC-09 生産運用情報変更
要求者: 生産管理・工場管理。
対象:
- planned_status
- planned_start
- planned_end
- Equipment割当集合

Equipment割当はProductionOperationEquipmentAssignmentを正本として同一UpdateRequest内で原子的に変更し、GraphのUSESをOutbox経由で更新する。

## 11. UC-10 更新後確認
COMPLETED後にPostgreSQL正本を再参照する。Graph更新を伴う場合、CURRENTになるまでGraph分析は正常結果を返さない。

## 12. UC-11 曖昧な更新要求
候補を提示し、同じcontext_idで利用者確認を受ける。Agentが任意選択しない。

## 13. UC-12 未承認更新
Execute APIはAPPROVEDでないUpdateRequestを拒否する。

## 14. UC-13 Snapshot変更
承認対象のtarget、operation、before、after、versionが変わった場合、ApprovalをINVALIDATEDとし再Prepareする。

## 15. UC-14 更新途中失敗
業務更新をROLLBACKする。技術的再試行可能障害では承認を再利用可能とし、version/業務ルール競合ではINVALIDATEDとする。

## 16. UC-15 重複実行
同一UpdateRequestまたはApprovalの再Executeで二重更新しない。COMPLETED済みなら既存結果を返す。

## 17. UC-16 下流影響伝播分析
影響方向をBFSで探索し、最短hopで直接/間接を分類する。上限到達時は部分結果と不完全性を返す。

## 18. UC-17 上流依存探索
上流探索方向をBFSで探索し、代表経路を返す。

## 19. UC-18 共通依存候補探索
複数対象の上流集合を比較し、共通要素と代表経路を候補として返す。

## 20. UC-19 代替経路探索
停止対象を除外した構造候補を探索し、PostgreSQL状態で実利用可能性を確認する。

## 21. UC-20 単一障害点候補探索
指定重要対象に対し必須経路・代替を評価する。探索打切り時は `INDETERMINATE`。

## 22. UC-21 依存関係登録・変更・無効化
要求者: 保全・生産管理・工場管理。承認者: 工場管理者。自己承認不可。
Prepare→Snapshot→Approval API→元要求者Execute API→共通Graph mutation lock→再検証→正本更新→履歴→Outbox→commit。

## 23. レビューで確定した補足

UC-10 / 15は確定afterと現在再参照を別フィールドで返し、別更新のversion差を示す。UC-13はSnapshotを編集せず、旧PENDING / APPROVEDをINVALIDATEDとして新規Prepareする。

UC-04 / 16〜20は保全・生産管理・工場管理のみ。UC-09の期間付き集合置換はdomain-model §15.2、UC-19 / 20の成立条件・利用可能性・過去分析は§15.1・15.3に従う。未承認要求は無期限だがapprove時に再検証する。Prepare結果IDは人が承認者へ渡し、通知機能を追加しない。

## 24. 運用上の意思決定支援ユースケース

今回の案のUC-01〜15は、本書の既存UCとの番号衝突を避けUC-B01〜15として採番する。元案の順番・意図は保持する。業務分析のActorは工場管理者・生産管理担当者・設備保全担当者を想定し、新情報の認可詳細はrequirements §14.3 PO-B07で確定する。旧UCは処理フロー、新UCは業務目的を表すため併存する。

### UC-B01 設備異常の影響範囲

対象設備、直接／間接影響、Process / ProductionOperation / Product、関係種別、必須性、経路、代替候補、Evidence、complete、uncertaintyを提示する。影響なしと確認不能を区別する。InfrastructureResourceの被影響意味はPO-B08。

既存フローとの対応: UC-04・16〜20。

### UC-B02 生産能力への影響

通常／残存能力、低下率、必要生産量、不足量、影響製品を示す。完全停止と能力低下を区別する。

既存フローとの対応: UC-04・16。

### UC-B03 代替設備による吸収

CAN_SUBSTITUTE候補、必要能力、現在の空き能力、不足量、残存影響・リスクを示す。構造候補だけで十分な代替としない。

既存フローとの対応: UC-19。

### UC-B04 リスク評価

Safety / Production / Quality / Delivery / Cascade / Economic riskとuncertaintyを分け、根拠のない総合スコアを作らない。

既存フローとの対応: UC-04・16。

### UC-B05 経済的損失

対象別・時間当たり・累積損失、計算期間・式・入力・Evidence、推定／確定、不完全性を示す。未知を0とせず、加算条件を検証する。

既存フローとの対応: UC-04。

### UC-B06 修理案評価

修理費・所要時間・修理中の生産損失・総経済影響・修理後の残存リスクを示す。

既存フローとの対応: UC-03・04。

### UC-B07 交換案評価

交換費・調達lead time・作業時間・交換までの暫定期間・停止損失・暫定対応を示す。

既存フローとの対応: UC-03・04。

### UC-B08 次回保全・更新まで継続

次回までの期間、累積損失、継続リスク、Safety constraint、Quality impact、単純費用回収期間と比較の前提を示す。Hard Constraint違反案を実行可能候補に含めない。

既存フローとの対応: UC-03・04。

### UC-B09 複数対応案比較

修理・交換・継続・代替を同一条件で比較する。各案の実行可能性と除外理由、費用・時間・損失・多面的リスク・前提・不明事項・Evidenceを提示し、人間へ判断を残す。

既存フローとの対応: UC-04・19。

### UC-B10 安全制約による除外

安全上許容できない案、理由、適用基準、Evidence、残る候補を示す。経済合理性でHard Safety Constraintを上書きしない。

既存フローとの対応: UC-04。

### UC-B11 納期・生産計画影響

buffer、許容停止時間、復旧期限、不足量、影響製品、Delivery riskを根拠がある範囲で提示する。

既存フローとの対応: UC-04・16。

### UC-B12 故障・保全履歴による修理／交換比較

故障・修理履歴、過去停止影響、今回の案、比較できる将来影響、判断できない将来予測を分けて提示する。

既存フローとの対応: UC-02・03・04。

### UC-B13 情報不足の明示

既知／未知、計算不能項目、partial result、incomplete / indeterminate、追加必要データを示す。0、FALSE、NONE、UNKNOWN、INDETERMINATE、NOT AVAILABLEを混同しない。

既存フローとの対応: UC-01〜04。

### UC-B14 分析から変更Prepare

分析後の明示的更新要求についてproposed change、before / after、Prepare、Approval要求を提示する。AgentはApproval / Executeしない。「次回保全で停止」はPO-B05確定まで現在状態更新に読み替えない。

既存フローとの対応: UC-05〜09・11〜15・21。

### UC-B15 Evidenceで判断根拠を説明

重要な結論をsource object、relation / path、database fact、document citation、計算入力・式、前提、不確実性に結び付ける。

既存フローとの対応: UC-01〜21。

## 25. Golden Use Case

UC-B09を中心に、異常設備について「影響範囲、継続リスク、停止損失、代替能力、修理、交換、次回保全までの継続」を比較する。Decision PackageはImpact → Risk → Economic Impact → Options → Constraints → Comparison → Evidence → Unknownsを含む。必要な情報が不足すれば部分結果と不足を返し、最終意思決定は人間へ残す。

利用者の「故障した」は報告・分析仮定として扱えるが、正本の状態更新と混同しない。分析要求だけではUpdateRequestを生成しない。対応するBusiness Scenario、固定期待値、ACは[Business Scenario仕様](../implementation-design/business-scenarios.md)を参照する。

## 26. レビューで補った業務ユースケース

### UC-B16 対象を確認して調査を継続する

設備名が曖昧なら候補を提示し、利用者の識別情報・選択後に正本を再検証する。不在と複数候補を区別する。対象確定前に特定設備の影響・損失を断定せずPrepareしない。既存UC-01・11、R-06・20・23を業務調査に具体化する。

### UC-B17 人間による変更後の結果を確認する

利用者は準備した案を人間のApprovalと元requesterのExecuteで確定した後、確定after、現在値、履歴、Graph同期状態を確認し、必要なら再分析する。確定後の別更新があれば元の確定結果と現在の差を示す。既存UC-10・15、R-05・35〜38を業務判断の後続確認として整理する。

UC-B01〜15はPO提示案、UC-B16・17は今回の不足レビューによる補足。追加試験はBS-13〜19を参照する。LogiScopeは業務の問いから根拠・判断へ進むデモの雰囲気のみを参考にし、業務仕様・Tool・コード・構成は継承していない。
