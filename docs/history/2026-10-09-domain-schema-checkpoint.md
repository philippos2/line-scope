# 業務スキーマチェックポイント

2026-10-09。利用者の「当初想定した順番」で進める指示に基づき、基盤PR #1の次を業務正本スキーマに限定した。仕様正本19文書の業務要件は変更していない。

## 変更

`feat/domain-schema`で追加migration `002_business_schema.sql`を作成。退避済みLineScope先行実装の10テーブル部分を再確認して使用した。LogiScopeコードは再利用していない。

equipment、equipment_current_state、maintenance_plan、maintenance_record、process、production_operation、product、infrastructure_resource、production_operation_equipment_assignment、dependency_relationを追加。正整数version、FK、業務キー、許可状態値・Relation型組合せ、required未使用種別false、開始終了の大小をDB制約で保護する。maintenance_record.resultは空・空白のみを拒否する。Graph業務キーはDEFERRABLE INITIALLY IMMEDIATE。

基盤テストの「業務テーブルなし」という過去チェックポイント固有の条件を更新し、001から002へのupgrade、再実行・並行適用・checksum・DDL rollbackを維持した。READMEの現在実装範囲を更新し、CONTRIBUTINGへ利用者指定のmerge後更新・枝打ち手順を記録した。

## 検証・対応

Python 3.14.4、実PostgreSQL 18.6で45テスト成功。ruff check / format成功。既存Starlette/httpxの非推奨警告1件。Docker内での実行はまだ未検証。

- AC-11: 業務キー重複のDB拒否（Prepareの競合分類は後続）。
- AC-G12: Relation型組合せ・USES直接登録拒否（循環・endpoint存在/activeは後続）。
- T-R21: 状態値・必須値・時刻範囲のDB防御、保全実績が現在状態・生産予定を変更しないこと。
- T-R08: NULL終了の割当、無効行を含むキー一意性、deferred業務キー交換（期間差分ロジックは後続）。

これらは受入基準全体の達成・リリース可を意味しない。状態遷移、API/Tool、認可、Graph、Outboxはこのチェックポイントの実装対象外。

## 未実装・後続

- equipment_state_historyは必須FK先UpdateRequestと同じ更新スキーマ段階に追加する。
- 期間重複・混在循環・endpoint存在/active・保全計画と実績の設備一致は、文書どおり更新トランザクションで検証する。
- versionの自動増分、更新権限、承認、監査、Outbox、Graph、Read APIは未実装。
- Docker実行基盤、LLM/embedding選定、RAG、Frontendは後続。現在のチェックポイントに仮APIやTODO動作を追加していない。
- 過去のstashを保全し、全体をpopしていない。
