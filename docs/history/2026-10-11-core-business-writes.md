# 通常業務更新のCore移行

## 範囲と判断

PR #105 merge後main `903bfa1`から開始。設備状態UPDATE / 状態履歴INSERT、生産予定UPDATE、保全予定UPDATE / CREATE、保全実績CREATEの計6本を固定SQLAlchemy Core statementへ移行する。既存はparameterized Raw SQLであり、脆弱性修正とは扱わない。ORM / Engine / poolは導入せず、LogiScopeコードの再利用もない。

## 維持する境界

呼出元の接続とtransactionを使う。認可・lock順序・Snapshot検証・CREATE順序・rowcount / DB例外の契約変換はserviceに残す。UPDATEのID / expected_version条件、version + 1を維持する。設備状態履歴のeffective_at / recorded_atは従来のexecuted_atを使う。UTC文字列のtimestamp変換、UUID、nullable maintenance_plan_idのSQL NULL、確定afterを維持する。DB schema / GRANT、API / Tool、Approval消費、Audit / Outbox / Graph仕様は変更しない。

## テストの修正

並行CREATE試験の同期処理がSQL文字列の表記に依存していたため、Coreの空白の違いで検出できなかった。テスト側を名前付きINSERT関数の境界へ修正する。実DBの一意制約による競合、参照保全予定のshare lock保持を引き続き検証する。既存の全テスト関数とparameterizationを保持する。追加3件では設備状態・生産予定・保全予定について、stale versionで更新されないこと、成功時versionが1増えること、古いversionの再使用で更新されないことを実DBで検証する。

## 検証

- Docker内の対象197件成功（追加3、32.17秒）。
- ruff check / format check成功（134 files）。
- Docker内の全体回帰試験2,326件成功、1 skipped、1 warning（165.94秒）。

NFR-04〜06、AC-05・10・11・13、T-SQL01・03〜05の対象部分の確認であり、受入基準全体の完了とは扱わない。

## 残る工程

Graph関連カテゴリの正本更新・参照lock、Outbox / 管理処理には安全なRaw SQLが残る。固定JSONB集約、server clock、Approval消費CTEは具体的理由に基づく例外として維持する。
