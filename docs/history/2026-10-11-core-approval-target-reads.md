# Approvalの業務Target参照・lockのCore移行

## 判断と範囲

PR #109 merge後main `98a3ba2`から開始。設備状態 / 保全予定FOR UPDATE、保全予定 / 保全実績CREATE競合SELECTの4箇所を固定Core statementへ移行する。core_businessの既存query-only Columnを共有し、DDL / ORM / Engine / poolは導入しない。既存SQLもparameterizedであり、脆弱性修正とは扱わない。LogiScope再利用はない。

## 維持する境界

Request / Approval lockとTarget取得の順序、全Targetのbefore比較、UUID / UTC正規化、認可・承認期限・Audit・commit / rollbackはserviceに残す。設備状態は3項目、保全予定は既存7項目を取得し、通常blocking FOR UPDATEをtransaction終了まで維持する。CREATE競合はIDまたは業務コードのEXISTSとして、UUID / text配列をbindする。未存在行のlock / 予約を導入せず、Executeでの再検証とDB UNIQUEを維持する。DB schema / GRANT、API / Tool、Snapshot / hash、更新・Outboxの業務仕様は変更しない。

## 検証

- Docker内の対象235件成功（追加2、29.87秒）。
- 追加2件で設備状態 / 保全予定のlock中は別接続更新がtimeoutし、transaction終了後に更新できることを実DBで確認する。SQL表記への依存は追加しない。
- 既存のbefore変更 / CREATE競合、承認の並行実行・期限・権限、Audit失敗rollback、複合保全 / Execute再検証、API秘匿、SQL Injection / DB rolesを回帰確認。
- ruff check / format check成功（139 files）。
- Docker内の全体回帰試験2,338件成功、1 skipped、1 warning（168.11秒）。

NFR-04〜06、AC-05・10〜13、T-SQL03〜05の対象部分の確認であり、受入基準全体の完了とは扱わない。

## 工程と進捗説明の補正

前の進捗説明・履歴末尾ではworker / controllerを既存SQLの残作業として含めていたが、現コードにはまだ実装されていない。これらは今後の機能実装であり、Core移行残件ではない。以前の「7〜8割」は未集計の概算で、この混同を含んでいたため正確な完了率として使用しない。

主要な業務更新・Audit・Outbox登録のCore化は完了した。安全な既存参照SQLを一括でゼロにすることは完了条件とせず、独立したCore化の連続工程は今回で区切り、新機能実装を優先する。残る通常参照は関連機能の変更時に保守効果を判断して段階的に移行する。新規DBアクセスはCoreを標準とし、PostgreSQL固有制御・固定JSONB集約は理由を明示して維持する。これは実装上の工程判断で、SQL Policyの要件変更ではない。
