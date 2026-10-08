# LineScope 対話・処理フロー設計書

## 1. Read
User -> POST /agent -> Agent -> Read Tool -> PostgreSQL -> Envelope -> User

## 2. Graph
User -> /agent -> Agent -> Graph Tool -> Sync Check
- CURRENT: Neo4j探索 -> structured evidence -> LLM説明 -> Envelope
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
Graph構造候補 -> PostgreSQLでEquipment/Operation状態確認 -> 「構造候補」と「現在利用可能」を分けて回答。

## 9. 曖昧対象
Agent -> candidates + context_id -> User choice -> same context_id -> resolve。

## 10. 整合境界の具体化

Graph: 認可 → shared mutation lock → CURRENT / generation確認 → 単一Neo4j read Transaction → 必要なPostgreSQL状態のstatement Snapshot → 終了時同期再確認 → サーバEvidence → lock解放 → LLM説明。時刻・temporal_scopeを返す。

Prepare: trusted retry key固定 → 同キー既存要求確認 → 単一カテゴリ・業務入力検証 → canonical Snapshot保存 → ID / hash返却。承認者へIDは人が渡す。

Execute: exclusive mutation lock（必要時） → Request / Approval → 業務行lock → requester / approver現在権限と期限・version検証 → 全変更・履歴・監査・Outbox・保存結果をcommit → 現在値再参照。確定結果と現在値は別フィールド。

割当: 明示[start, end)と新集合 → 既存区間分割を含む全差分Snapshot → 承認 → 同一TransactionでCREATE / UPDATE / DISABLEと親version更新 → USES Projection。期間外の割当は保持する。

Rebuild: 通常worker停止・leader引継ぎ → REBUILDING → 排他mutation lock → controllerがOutbox drain → 単一statement正本Snapshot → 新generation検証 → 切替 → lock / leader解放 → 状態再判定。
