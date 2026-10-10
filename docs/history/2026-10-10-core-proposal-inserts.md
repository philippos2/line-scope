# Prepare proposal INSERTのCore移行

## 判断と範囲

PR #100 merge後main `5236f3e`から開始。ProposalStore.saveの新規UpdateRequest / UpdateTarget / PENDING ApprovalのINSERT 3本を移行する。既存は安全なparameterized Raw SQLであり、脆弱性修正ではない。

固定Column参照・named値により、保存項目・ON CONFLICT対象・JSONB型の対応を局所的に確認できる利益がある。query-only宣言はmigration 003の対象Columnだけを表し、DDL生成や共通ORMモデルとして扱わない。呼出元の業務判断・transaction・並行処理を隠すrepository / executorは導入しない。

## transactionと型の確認

requester / role認可、カテゴリ制限、canonical Snapshot検証、ID生成、Target順序、置換のUpdateRequest → Approval lock、旧状態検証と失効、Audit、commit / rollbackはProposalStoreに残す。保存後の固定JSONB集約LOOKUPと_savedのhash / Target / metadata再検証も変更しない。

UpdateRequestは(requester_id, prepare_retry_key)の固定ColumnでON CONFLICT DO NOTHING RETURNINGを維持する。負けた並行retryはREAD COMMITTEDの次statementで勝者を再取得し、入力hash不一致をDUPLICATE_REQUESTにする。新しいTarget / Approval / Auditはinsertした勝者だけが保存する。

canonical text / hashは変換せずbind、schema version=1とDB DEFAULT監査時刻を維持する。Targetのbusiness_key / before / afterは明示psycopg Jsonb adaptationを使う。CREATE before / expected_versionはSQL NULLを渡し、JSON nullに置換しない。compile後にSQLAlchemy bind processorを通さない点をコードに記録する。

新要求・全Target・PENDING Approval・旧失効・Auditは同一transaction。Target / Approval / Audit失敗で部分commitしない。DB schema / GRANT、API / Tool、承認期限、version、正本 / Outbox / Graph仕様は変更しない。LogiScope再利用はない。

## 検証

- Docker内の実PostgreSQLでproposal保存 / retry / 置換、Prepare Audit、SQL Injection、DB rolesの152件成功（追加5）。
- 追加4件で設備・保全・生産・依存関係のcanonical text / hash・Target JSONB・CREATE SQL NULL・DEFAULT時刻・PENDING状態を確認。日本語と攻撃文字列を含むrequesterを値として保存し、設備テーブルと再読込・retryを維持する。
- 追加1件でTarget INSERT失敗がUpdateRequest / Target / Approval / Auditを全rollbackし、同一keyの再試行が新規保存になることを確認。DB例外本文も秘匿する。
- 既存の並行retry勝者・内容不一致・owner scope・CREATE ID固定・置換lock / 並行競合・旧失効 / Approval / Audit保存失敗rollback・DB roleを回帰確認する。
- ruff check / format check成功（131 files）。
- Docker内の全体回帰試験2,319件成功、1 skipped、1 warning（165.79秒）。

NFR-04〜06、AC-05〜08・11・13、T-SQL01・03〜05の対象proposal部分の確認であり、重要更新全体の完了とは扱わない。既存Starlette warningは対象外。

## 残る工程

proposal保存の置換lock / 旧失効と固定JSONB LOOKUPは安全なRaw SQLのまま。Execute正本・履歴・Outbox / 状態更新、Graph / Outbox、管理処理も残る。利点と型・lock・transactionリスクを個別判断して次のcheckpointを選ぶ。
