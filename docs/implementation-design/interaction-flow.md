# LineScope 対話・処理フロー設計書

本書は処理の責務順序を示す。実行・成功の証拠そのものではない。質問欄の語彙と応答境界は[限定照会設計](../design/demo-question-chat.md)、実測範囲は[検証結果](../demo/verified-findings.md)を参照する。

## 1. Read
質問欄 -> POST /agent -> 共通検索で対象解決 -> 限定9観点の全文照合 -> 型付きRead -> PostgreSQL -> Evidence検証・コードの回答生成 -> Envelope -> 同じ質問欄。対象曖昧・対応外は会話で確認／案内し、LLMへフォールバックしない。構造化された既存Readはその契約を維持する。

## 2. Graph
User -> /agent -> Agent -> Graph Tool -> Sync Check
- CURRENT: Neo4j探索 -> structured evidence -> コードによる結果表示 -> Envelope
- 非CURRENT: error -> Envelope。Neo4j結果は返さない

## 3. Prepare
User -> /agent -> Agent -> Prepare Tool -> PostgreSQL -> canonical Snapshot/hash -> UpdateRequest WAITING_APPROVAL -> User

## 4. Approval
Approver -> GET UpdateRequest -> canonical Snapshot/hash確認
-> POST /approvals/{id}/approve(snapshot_hash)
-> Authentication/Authorization
-> APPROVED + 30分期限

LLMを承認経路に使用しない。

## 5. Execute
Requester -> POST /update-requests/{id}/execute
-> Authentication
-> requester ownership check
-> Approval/expiry/Snapshot/version再検証
-> Transaction
-> History/Outbox
-> Commit
-> PostgreSQL再参照
-> result

## 6. Graph反映
Projection worker -> committed pending Outbox集合 -> Neo4j idempotent upsert -> APPLIED
pendingが残る間LAGGING。

## 7. ProductionOperation割当変更
Prepareで新Equipment集合をSnapshot化
-> Approval
-> ExecuteでAssignment差分を原子的に更新
-> 各変更をOutbox
-> USESへProjection

## 8. 代替経路
Graph構造候補 -> PostgreSQLでEquipment/Operationと必須インフラの登録状態確認 -> 三値評価 -> 「構造候補」と「登録条件による利用可能性」を分けて回答。実運転可否とはしない。

## 9. 曖昧対象
Agent -> candidates + context_id -> User choice -> same context_id -> resolve。

## 10. 整合境界の具体化

Graph: 認可 → shared mutation lock → CURRENT / generation確認 → 単一Neo4j read Transaction → 必要なPostgreSQL状態のstatement Snapshot → 終了時同期再確認 → サーバEvidence → lock解放 → 結果の契約に従うコードの表示。通常質問の回答をLLMへ再解釈させない。時刻・temporal_scopeを返す。

Prepare: trusted retry key固定 → 同キー既存要求確認 → 単一カテゴリ・業務入力検証 → canonical Snapshot保存 → ID / hash返却。承認者へIDは人が渡す。

Execute: exclusive mutation lock（必要時） → Request / Approval → 業務行lock → requester / approver現在権限と期限・version検証 → 全変更・履歴・監査・Outbox・保存結果をcommit → 現在値再参照。確定結果と現在値は別フィールド。

割当: 明示[start, end)と新集合 → 既存区間分割を含む全差分Snapshot → 承認 → 同一TransactionでCREATE / UPDATE / DISABLEと親version更新 → USES Projection。期間外の割当は保持する。

Rebuild: 通常worker停止・leader引継ぎ → REBUILDING → 排他mutation lock → controllerがOutbox drain → 単一statement正本Snapshot → 新generation検証 → 切替 → lock / leader解放 → 状態再判定。

## 11. 意思決定支援フロー

対象特定・認可 → 分析条件と評価期間の確認 → CURRENT下の影響探索 → 正本の状態・能力・経済・計画・安全・履歴入力取得 → 決定論的計算 → 制約と案比較 → Evidence / Unknowns付きDecision Packageを提示する。追加入力・計算契約はPO判断後に確定する。

不足時は既知部分と評価別の不完全性を提示する。分析だけではPrepareしない。利用者が明示的に変更準備を要求した場合のみ、権限・カテゴリ・対象・業務値を再検証して既存Prepareフローへ進む。将来停止の方式はPO-B05を解決するまで補完しない。人のApproval APIと元requesterのExecute APIはAgent対話から独立した確定操作として維持する。
