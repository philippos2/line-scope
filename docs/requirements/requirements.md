# LineScope 要件定義書

## 1. 目的

LineScopeは、工場の設備・工程・製品・保全情報・依存関係を統合し、設備異常・故障・計画停止時の運用上の意思決定をEvidence付きで支援するシステムである。影響範囲、能力、リスク、経済的損失、対応策の費用・時間・残存リスク、不足情報を関連付けて提示する。最終意思決定、Approval、Executeは人間が行う。自然言語による参照・分析・変更準備はそのための手段とする。

業務データ更新は、明示的な更新要求、対象特定、権限確認、変更前後提示、認証済み承認、実行時再検証を経て行う。

## 2. 本書の範囲

本書はWHATを定義する。DB製品、GraphDB製品、VectorDB製品、実装言語、Framework、具体API形状は規定しない。

### 2.1 要件・受入・設計の順序

最上位は§1の業務目的、ユースケースはその達成を定義する要件、Business Scenarioはユースケースの受入仕様である。Ontology・データモデル・DB・API設計はそれらを実現する下位設計、Outbox・Projection・lock等はさらに下位の実現方式とする。

下位仕様と上位意図が矛盾したら、Safety / SecurityのHard Constraintを除き、上位を優先して下位を再設計する。既存DBやToolでできないことを理由に上位ユースケースを対象外へ移さない。未定義の業務ルールはPO判断として明示し、実現方式の都合で補完しない。各事項の正本文書はdeliverablesの責務表に従う。


## 3. 基本機能要件

### R-01 自然言語要求受付
利用者の自然言語要求を受け付ける。

### R-02 業務情報取得
設備、保全、生産運用、依存関係、更新履歴等の業務情報を取得する。

### R-03 複数情報統合
複数の業務情報を組み合わせて回答・分析する。

### R-04 業務データ更新
明示的な更新要求がある場合、権限・承認・業務制約を満たしたうえで更新できる。

### R-05 更新結果確認
更新対象、成功・失敗、変更前、変更後を確認できる。

### R-06 複数ターン確認
対象が曖昧な場合等、利用者との追加確認を経て処理を継続できる。

## 4. 依存関係・Graph業務要件

### R-07 依存関係取得
設備、工程、生産作業、製品、インフラ等の関係を取得できる。

### R-08 多段探索
一段に限定せず複数段探索できる。

### R-09 下流影響伝播
停止・故障・保全等による直接・間接の下流影響を特定できる。

### R-10 上流依存探索
対象成立に必要な上流要素を探索できる。

### R-11 共通依存探索
複数対象に共通する上流依存要素を候補として特定できる。

### R-12 代替経路探索
通常経路を利用できない場合、定義済み関係から代替経路候補を探索できる。

### R-13 単一障害点候補
重要対象への成立経路について、代替がない要素を候補として提示できる。

### R-14 依存関係更新
権限と承認を満たした利用者は、依存関係を登録・変更・無効化できる。

### R-15 経路根拠
分析結果の根拠となる代表経路を確認できる。

### R-16 不完全探索の明示
探索上限到達時、完全探索済みと誤認させない。

## 5. Agent要件

### R-17 処理選択
要求に応じて参照、Graph分析、更新準備等を選択する。

### R-18 必要情報取得
必要情報を取得してから回答・分析・更新準備を行う。

### R-19 捏造禁止
存在しない業務データ、経路、承認、更新結果を事実として生成しない。

### R-20 任意対象選択禁止
更新候補が複数ある場合、Agentが任意に一つを選んで更新しない。

### R-21 自律更新禁止
明示的な更新要求なしに業務データを更新しない。

### R-22 候補と事実の区別
原因候補、共通依存候補、代替候補、単一障害点候補と確定事実を区別する。

## 6. 更新・承認要件

### R-23 対象一意性
更新対象を一意に特定する。

### R-24 必須情報
不足値を推測補完しない。

### R-25 変更前後提示
更新前に対象、操作、変更前、変更後予定を提示する。

### R-26 認証済み承認
確定更新前に、認証済み承認者の明示的承認を必要とする。

### R-27 承認経路
自然言語の解釈だけを承認成立条件としない。

### R-28 承認内容一致
実更新内容は承認済みSnapshotと一致しなければならない。

### R-29 承認失効
対象、操作、Snapshot、version等が変化した場合、承認を失効させる。

### R-30 承認期限
承認は承認成立から30分で失効する。

### R-31 実行主体
承認済み更新は、認証済みの元要求者による明示的な実行要求でのみ開始する。

### R-32 原子性
一つの更新要求に含まれる複数変更は部分確定を正常完了として残さない。

### R-33 重複更新防止
同じ更新要求または承認を二重実行しない。

### R-34 CREATE競合
CREATEはversionではなく一意性、業務キー、冪等性に基づいて競合を検出する。

### R-35 更新履歴
更新要求、承認、対象、変更前後、結果を追跡可能とする。

## 7. 一貫性要件

### R-36 正本最新性
確定済み更新後の正本参照は最新確定状態を返す。

### R-37 派生Graph最新性
正本との同期が確認できる場合のみGraph分析を正常な最新結果として返す。

### R-38 非同期反映中
派生Graphが追随中または異常状態のとき、古い結果を正常な最新結果として返さない。

### R-39 並行更新
並行更新によって禁止循環、重複、二重承認消費等の不整合を成立させない。

### R-40 設備割当一意正本
ProductionOperationとEquipmentの割当情報は単一の正本から管理し、GraphのUSES関係はその正本から派生させる。

## 8. 例外分類

- 対象不存在
- 対象非一意
- 必須情報不足
- 権限不足
- 承認未取得
- 承認不一致
- 承認期限切れ
- 承認失効
- 承認二重消費
- 業務ルール違反
- version競合
- CREATE競合
- 重複要求
- 更新失敗
- Graph非最新
- Graph利用不可
- Graph再構築中
- 探索上限到達
- 代替経路不存在

## 9. プロダクトがやること（対象業務）

単一工場の業務判断支援を対象とする。以下はプロダクト全体の目標であり、現在の実装済み一覧ではない。

| 対象 | 実現する業務目的 | 要件・ユースケース |
|---|---|---|
| 業務Objectの把握 | Equipment、Process、ProductionOperation、Product、InfrastructureResource、設備状態・保全予定・実績・履歴を関連付けて確認する | R-01〜03、UC-01〜03、UC-B12・16 |
| 依存・影響分析 | 直接／間接影響、影響経路、上流依存、共通依存、代替、SPOF候補を根拠付きで提示する | R-07〜16、UC-04・16〜20、UC-B01 |
| 生産と経済の評価 | 能力低下、代替の吸収可否、必要量不足、停止・劣化損失、納期・復旧期限を定義済み入力・ルールで評価する | R-B02・04・07、UC-B02・03・05・11 |
| リスクと対応案比較 | Safety / Production / Quality / Delivery / Cascade / Economic riskを区別し、修理・交換・継続・代替を共通条件で比較する。Hard Safety Constraint違反案を除外する | R-B03・05・06・08、UC-B04・06〜10・12 |
| Evidenceと不足情報 | 正本・経路・文書・計算入力と式・仮定を追跡し、未知と不完全性、推定と確定を区別する | R-19・22、R-B09・10、UC-B13・15 |
| 人間の変更と確認 | 明示要求からPrepare、認証済み人間のApproval、元requesterのExecuteへ進み、結果・履歴・現在値を確認する | R-04〜06・23〜40、UC-05〜15・21、UC-B14・17 |
| 分析ワークスペース | Object・Graph・Evidence・比較案・Actionを関連付けて確認できるFrontendを後続フェーズで提供する | §13。画面詳細は後続設計 |

中心はUC-B09とGolden ScenarioのDecision Packageである。検索・チャットは業務判断の入口であり、Graph表示やOntologyの構築そのものを最終目的としない。対象内の能力・経済・安全等に未確定の入力があれば§14.3で判断し、計算できない範囲と既知の結果を明示する。

## 10. 利用者

- 製造現場担当者
- 設備保全担当者
- 生産管理担当者
- 工場管理者

## 11. プロダクトがやらないこと（スコープ外）

| スコープ外 | 境界 |
|---|---|
| AIによる自律的な最終意思決定・Approval / Execute | AIは調査・比較・変更準備を支援する。案の提示を承認や確定実行と扱わない |
| 実設備の自動制御 | 設備状態や計画等の業務情報を承認付きで変更する。PLC等への指令・設備停止を直接行う製品ではない |
| 在庫・受注・BOMの完全管理 | 必要な生産量・buffer等は判断支援の入力として扱えるが、取引・在庫・受注全体を管理するERPを構築しない |
| 本番MES / ERP接続 | 現スコープでは実業務システムとの本番連携を実装しない。判断用入力の保有と外部システム連携を区別する |
| 複数工場・マルチテナント | 単一工場を対象とし、工場間・tenant間の管理は含めない |

不足データから根拠のない事実・安全保証・将来故障確率・総合Risk Scoreを生成しない。これは機能範囲を削る理由ではなく、対象内の全分析に適用する品質・Safety / Security上の制約である。

### 11.1 対象外と混同しないもの

| 区分 | 扱い |
|---|---|
| 後続フェーズ | Frontendは対象内。サーバサイド完成後に構築する。今のフェーズで作らないことをプロダクトの対象外としない |
| PO判断待ち | 能力・費用・安全・計画・履歴・新情報権限等の意味はPO-B01〜08で確定する。対象内だが推測で実装しない |
| 未実装 | Agent、Graph、RAG、Approval / Execute等は対象内。現時点の実装状況はREADMEで示す |
| 下位設計の限界 | 過去as_ofの限定、一段代替、既存Snapshot形状、将来停止予約の未定義等はdomain / API / transactionの現行契約。上位要件との不整合は§2.1に従って明示再設計する |

スコープ変更は業務目的・ユースケース・受入仕様への影響を明示して判断する。既存制御を黙って解除せず、Safety / Securityを維持し、必要な下位契約・テストを改訂する。

## 12. v1業務入力・状態値

| 対象 | 許可値・必須項目 |
|---|---|
| EquipmentState UPDATE | state_code: RUNNING / STOPPED / UNDER_MAINTENANCE / UNKNOWN |
| MaintenancePlan CREATE | plan_code、equipment_id、planned_start、planned_end、plan_status必須。plan_status: PLANNED / CANCELLED |
| MaintenancePlan UPDATE | planned_start、planned_end、plan_statusの明示patch。合成後も必須項目を満たす。plan_code・equipment_idは変更不可 |
| MaintenanceRecord CREATE | record_code、equipment_id、performed_at、空でないresult必須。maintenance_plan_idのみ任意NULL |
| ProductionOperation UPDATE | planned_status: PLANNED / CANCELLED、planned_start、planned_endのpatch、または明示期間付きEquipment集合置換。合成後の予定状態・開始・終了は必須 |
| DependencyRelation | endpoint型・ID、relation_type、effective_from、明示effective_to（NULL可）、required必須。型・循環はdomain-modelに従う |

planned_start < planned_end、effective_from < 非NULL effective_toを要求する。必須業務値をNULLにしない。patchは少なくとも1つの実変更を含む。設備状態は許可集合内の変更を許可し、保全・生産予定はPLANNEDとCANCELLED間の変更を許可する。追加の状態遷移制限は設けない。予定状態に実績状態を追加しない。

保全実績登録は設備状態・保全予定・生産予定を自動変更しない。maintenance_plan_id指定時は同じequipment_idの既存計画であることを要求する。DependencyRelationのrequired未使用種別はfalseを要求し、true入力を拒否する。関係自体の必須性はdomain-modelの規則で評価する。

EquipmentState更新の現在状態・履歴は同一Transactionで保存し、現在状態の更新時刻と履歴effective_at / recorded_atは確定実行のサーバ時刻を記録する。既存のEquipmentState UPDATEは過去・未来の状態登録を行わない。将来停止を扱うUC-B14の方式は§14.3のPO-B05で確定するまで、このUPDATEへ予約実行の意味を付与しない。UUID・監査時刻・version等の技術メタデータ生成と業務値の推測を区別する。

## 13. 後続Frontendフェーズ

2026-10-09のプロダクトオーナー指示により、Frontendはプロダクト全体の計画へ含める。
サーバサイドを先に完成させ、その後、Palantir AIP Analystを参考にした、LogiScopeよりリッチなFrontendを構築する。
Frontendは、AIとの対話から工場の状況・依存関係・影響経路・根拠を確認し、更新案の確認・承認・実行へ進める分析ワークスペースを目指す。
対話・分析結果・根拠・更新案・承認状況を関連付けて確認できる体験とする。AIP Analystの実画面や機能の忠実な再現は要求しない。
現時点では画面・操作・Frontend frameworkの詳細を推測で確定しない。後続フェーズでUI要件・設計・受入基準を具体化する。
Frontendの追加で、認証・権限・人によるApproval / requesterによるExecuteの既存境界は変更しない。

### 13.1 オペレーション・コンソール案（候補）

2026-10-09にPOが共有したChatGPTの案を、有力なUI候補の一つとして保持する。POは内容を妥当と評価しているが、案全体の採用・UI仕様の確定ではない。後続UI設計で他案とも比較し、採否を判断する。以下のレイアウト・表示方針・技術候補はこの案の内容であり、認証・権限・Graph同期・承認等の既存仕様はどのUI案にも適用する。

本案はGraphを中心にObject / Graph / Evidence / Actionを同一ワークスペースで関連付ける。AI対話は自然言語の分析入口・結果説明を担う。最初のUI目標は、一画面で依存Graph・AI分析・業務Actionの関係が伝わること。

候補レイアウトは左Object Explorer、中央Graph Canvas、右AI Agent Panel、下部Action / Approval Drawer、上部の簡潔な状態表示。Graphを主な表示面積とし、Object選択・Graph上の強調・Evidence・Tool結果を連動させる。面積比・詳細操作・レスポンシブ構成は後続UI設計で検証する。初回UIはObject Explorer / Graph / Agent Panelを優先し、Action Drawerは次のUI反復で追加する候補とする。

色は装飾より状態・選択・影響経路の意味に使用する。charcoal / graphite・dark navy・off-white・細い境界線を基本候補とし、CURRENT=緑、LAGGING=黄、ERROR=赤、REBUILDING=青を文字ラベルとともに表す。色だけで判定させない。

Graphはサーバの同期状態・complete / limit_reason・Evidenceに従い、非CURRENTを正常な最新分析として表示しない。エッジ保存方向と論理的な影響方向を混同せず、Toolが返した経路だけを強調する。Graph分析を許可されない現場ロールには通常Read中心の表示を提供し、UI操作で権限を拡張しない。

Object Detailは正本の項目・状態・version・観測時刻を表示する。Equipment本体versionと現在状態versionを区別する。例示にあったDEGRADED / MAINTENANCEやLocation等を未定義の状態・属性として追加しない。更新例は許可状態値（例えばRUNNING → UNDER_MAINTENANCE）と、その対象の更新権限を満たす主体を使う。

Action表示はAI RecommendationとHuman Approvalを区別し、サーバ保存canonical Snapshotのbefore / proposed、requester・approver・承認状態を確認可能にする。確定済みafterとその後のcurrent valueを区別する。人によるApproval専用APIと元requesterによるExecute専用APIの境界を維持する。Tool Traceは公開可能なTool名・入出力・根拠を対象とし、LLM内部推論・秘密情報・内部SQL/Cypherを公開しない。

状態バーは検証済みの状態だけを示し、未実装・未確認をReady / Connectedと表示しない。LLM名も採用・接続が確定した設定を参照し、提示例のQwenを選定確定と扱わない。React / TypeScript / React Flow、TanStack Query、Context / Zustandは候補として後続設計で評価し、現段階では採用・依存追加を行わない。

## 14. 業務判断支援の追加要件

今回のUC-B01〜15とBS-01〜12 / BS-G01の意図を既存文書との不整合時に優先する。以下はプロダクト要件であり、現在の実装完了や物理スキーマ確定を意味しない。未決定事項は§14.3を正とし、既存の更新契約を暗黙に拡張しない。

### 14.1 R-B01〜R-B10

| ID | 要件 |
|---|---|
| R-B01 | 直接・間接影響、工程・製品、経路、関係種別、必須性、代替候補、探索の完全性を提示する。「影響なし」と「確認不能」を区別する |
| R-B02 | 通常能力・残存能力・必要生産量・空き能力・不足量を評価する。構造上の代替関係と能力面の充足を区別する |
| R-B03 | Safety / Production / Quality / Delivery / Cascade / Economic riskとuncertaintyを区別する。根拠のない総合スコアや将来故障確率を作らない |
| R-B04 | 対象別・時間当たり・期間累積の損失を、入力、単位、期間、計算式、Evidence、推定／確定の区別とともに提示する。未知を0としない |
| R-B05 | Repair / Replace / Continue until planned maintenance or replacement / Substituteを共通の比較条件で評価し、実行可能性、費用、時間、生産影響、残存リスク、前提、不明事項を示す |
| R-B06 | Hard Safety Constraintに違反する案を実行可能候補から除外し、基準とEvidenceを示す。経済利益で安全条件を上書きしない |
| R-B07 | 生産計画・納期についてbuffer、許容停止時間、復旧期限、不足量を根拠がある範囲で評価する |
| R-B08 | 故障・保全履歴と過去の停止影響を考慮し、確認できる将来影響と判断不能な予測を区別する |
| R-B09 | 判明分、計算不能項目、追加必要データ、各評価の完全性を示す。0 / FALSE / NONE / UNKNOWN / INDETERMINATE / NOT AVAILABLEを意味に応じて区別する |
| R-B10 | Impact → Risk → Economic Impact → Options → Constraints → Comparison → Evidence → UnknownsをDecision Packageとして提示する。分析だけではPrepareしない。明示的更新要求後は既存のPrepare → Human Approval → requester Execute境界を守る |

数値計算は決定論的なアプリケーション処理が行い、LLMへ委任しない。Golden Use CaseはUC-B09を中心とする。意思決定支援用の生産・費用・安全情報は対象に含むが、在庫・受注・BOMの完全管理、実設備制御、本番MES/ERP接続は引き続き対象外。

### 14.2 必要データの仕様存在分類

A=現仕様に存在、B=現仕様から一部導出可能、C=現仕様には必要な意味・構造が存在しない。実装済みかどうかとは別の分類である。自由記述や文書に記載できることだけでは、計算用正本の定義済みとは扱わない。

| 項目 | 分類 | 根拠・不足 |
|---|---|---|
| loss per operating hour | C | Product等に損失率・通貨・適用条件なし |
| operating hours/day | C | 稼働calendarなし。予定開始終了差は実稼働時間とは限らない |
| production capacity | C | 製品・単位・期間別能力なし |
| available capacity | C | 能力・使用中負荷・予約負荷なし |
| required production volume | C | 生産量・需要・比較期間なし |
| repair cost | C | 保全実績resultは費用項目ではない |
| repair duration | C | 予定期間は修理所要時間の保証ではない |
| replacement cost | C | 交換費用なし |
| replacement duration | C | 交換作業期間なし |
| parts lead time | C | 調達期間なし |
| next planned maintenance | B | PLANNEDのMaintenancePlan期間から候補抽出可能。「次回」の選択条件はPO-B05 |
| next planned replacement | C | MaintenancePlanに保全／交換の種別なし |
| degradation / stopped distinction | C | STOPPEDは存在するが、劣化の観測・程度・継続条件なし |
| safety stop criteria | C | 適用対象・停止基準・判定入力の契約なし |
| permissible continued-operation conditions | C | 許容条件・有効期限・判断根拠なし |
| failure history | C | 状態履歴は停止原因を示さず、STOPPEDを故障と同一視できない |
| maintenance history | A | MaintenanceRecordと設備・実施時刻・result。費用・故障分類等は別途必要 |
| quality loss | C | 不良量・金額・損失との重複規則なし |
| production buffer | C | 在庫／工程余裕の意思決定用入力なし |
| permissible downtime | C | 需要・buffer・納期との算出規則なし |

### 14.3 PO Decision一覧（未決定）

業務判断支援を採用すること自体は確定済み。以下は追加案に明記されていない業務意味を確定するための事項であり、Codexが実装時に補完しない。未決定の機能を正常利用可能と表示しない。

| ID | 確定が必要な事項 | 影響範囲 |
|---|---|---|
| PO-B01 | 共通比較期間、稼働時間calendar、費用範囲（直接費／停止損失／共通の将来交換費等）、推定／確定の条件。BS-03の150日は単純費用回収期間として保持し、厳密な案比較との関係を確定する | BS-02・03・07・10・12・G01、経済AC、DB / 計算Tool |
| PO-B02 | 損失率の定義、通貨、適用期間、完全停止と劣化の計算、独立加算条件、品質損失との二重計上防止 | BS-02・03・09・G01、Productと経済入力 |
| PO-B03 | 製品別能力・単位・必要量・空き能力の期間と予約負荷、代替互換性、buffer・納期・復旧期限の導出規則 | BS-05・06・G01、UC-B02・03・11 |
| PO-B04 | 劣化の観測情報、承認された安全基準と適用条件、継続許容の根拠・有効期間、リスク資料の信頼性。安全不明時の候補表示と、分析での除外を実更新時にも検証する範囲 | BS-03・04・11・G01、状態／安全入力、Execute業務制約 |
| PO-B05 | 修理／交換計画の区別、所要時間と調達lead timeの区別、暫定案の期間、次回計画の選び方。UC-B14の「次回保全で停止」が保全予定作成か、将来状態変更の予約か | BS-03・07・G01、UC-B06〜08・14、計画／更新契約 |
| PO-B06 | 故障・修理履歴、過去停止損失の正本と登録主体、履歴の対象期間、将来予測の根拠。現在Graphのas_ofで履歴を復元しない | BS-12、UC-B12、履歴DB / Tool |
| PO-B07 | 新しい費用・能力・安全情報の登録／閲覧権限、更新カテゴリ、承認条件、Evidenceの公開範囲。既存Graph権限だけで新データの閲覧を許可しない | access-control、全Target / Snapshot / API |
| PO-B08 | 「影響するInfrastructureResource」が被影響対象か、上流依存資源の提示か。現行関係表には設備からInfrastructureResourceへの通常の下流影響関係がない | UC-B01、関係モデル / Graph / AC |

技術実装判断として、UCの番号分離、構造化結果による検証、計算をLLMから分離することを採用する。数量の単位・桁・丸めはPO-B01〜03の意味確定後に設計へ反映し、binary floatや新しいSnapshot形状を先行採用しない。PO判断確定時にはRequirements / Domain / Access / Data / API / Transaction / AC / Testを対応して更新する。
