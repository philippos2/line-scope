# LineScope 要件定義書

## 1. 目的

LineScopeは、製造設備・生産工程・保全・依存関係に関する参照、分析、更新を自然言語で支援するAI Agentシステムである。

業務データ更新は、明示的な更新要求、対象特定、権限確認、変更前後提示、認証済み承認、実行時再検証を経て行う。

## 2. 本書の範囲

本書はWHATを定義する。DB製品、GraphDB製品、VectorDB製品、実装言語、Framework、具体API形状は規定しない。

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

## 9. 対象業務

- 設備状態・履歴
- 保全予定・保全実績
- ProductionOperationの予定状態・予定時刻・Equipment割当
- 依存関係
- 下流影響、上流依存、共通依存、代替経路、単一障害点候補
- 更新履歴

## 10. 利用者

- 製造現場担当者
- 設備保全担当者
- 生産管理担当者
- 工場管理者

## 11. スコープ外

- 在庫・受注・BOM完全管理
- 実設備制御
- 本番MES/ERP接続
- UIは現在のサーバサイド実装フェーズには含めない。サーバサイド完成後の後続フェーズで構築する（§13）
- 複数工場・マルチテナント

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

EquipmentState更新の現在状態・履歴は同一Transactionで保存し、現在状態の更新時刻と履歴effective_at / recorded_atは確定実行のサーバ時刻を記録する。過去・未来の状態登録機能は追加しない。UUID・監査時刻・version等の技術メタデータ生成と業務値の推測を区別する。

## 13. 後続Frontendフェーズ

2026-10-09のプロダクトオーナー指示により、Frontendはプロダクト全体の計画へ含める。
サーバサイドを先に完成させ、その後、Palantir AIP Analystを参考にした、LogiScopeよりリッチなFrontendを構築する。
Frontendは、AIとの対話から工場の状況・依存関係・影響経路・根拠を確認し、更新案の確認・承認・実行へ進める分析ワークスペースを目指す。
対話・分析結果・根拠・更新案・承認状況を関連付けて確認できる体験とする。AIP Analystの実画面や機能の忠実な再現は要求しない。
現時点では画面・操作・Frontend frameworkの詳細を推測で確定しない。後続フェーズでUI要件・設計・受入基準を具体化する。
Frontendの追加で、認証・権限・人によるApproval / requesterによるExecuteの既存境界は変更しない。

### 13.1 オペレーション・コンソールの方向性

2026-10-09のPO提示案に基づき、Graphを中心にObject / Graph / Evidence / Actionを同一ワークスペースで関連付ける。AI対話は自然言語の分析入口・結果説明を担う。最初のUI目標は、一画面で依存Graph・AI分析・業務Actionの関係が伝わること。

候補レイアウトは左Object Explorer、中央Graph Canvas、右AI Agent Panel、下部Action / Approval Drawer、上部の簡潔な状態表示。Graphを主な表示面積とし、Object選択・Graph上の強調・Evidence・Tool結果を連動させる。面積比・詳細操作・レスポンシブ構成は後続UI設計で検証する。初回UIはObject Explorer / Graph / Agent Panelを優先し、Action Drawerは次のUI反復で追加する候補とする。

色は装飾より状態・選択・影響経路の意味に使用する。charcoal / graphite・dark navy・off-white・細い境界線を基本候補とし、CURRENT=緑、LAGGING=黄、ERROR=赤、REBUILDING=青を文字ラベルとともに表す。色だけで判定させない。

Graphはサーバの同期状態・complete / limit_reason・Evidenceに従い、非CURRENTを正常な最新分析として表示しない。エッジ保存方向と論理的な影響方向を混同せず、Toolが返した経路だけを強調する。Graph分析を許可されない現場ロールには通常Read中心の表示を提供し、UI操作で権限を拡張しない。

Object Detailは正本の項目・状態・version・観測時刻を表示する。Equipment本体versionと現在状態versionを区別する。例示にあったDEGRADED / MAINTENANCEやLocation等を未定義の状態・属性として追加しない。更新例は許可状態値（例えばRUNNING → UNDER_MAINTENANCE）と、その対象の更新権限を満たす主体を使う。

Action表示はAI RecommendationとHuman Approvalを区別し、サーバ保存canonical Snapshotのbefore / proposed、requester・approver・承認状態を確認可能にする。確定済みafterとその後のcurrent valueを区別する。人によるApproval専用APIと元requesterによるExecute専用APIの境界を維持する。Tool Traceは公開可能なTool名・入出力・根拠を対象とし、LLM内部推論・秘密情報・内部SQL/Cypherを公開しない。

状態バーは検証済みの状態だけを示し、未実装・未確認をReady / Connectedと表示しない。LLM名も採用・接続が確定した設定を参照し、提示例のQwenを選定確定と扱わない。React / TypeScript / React Flow、TanStack Query、Context / Zustandは候補として後続設計で評価し、現段階では採用・依存追加を行わない。
