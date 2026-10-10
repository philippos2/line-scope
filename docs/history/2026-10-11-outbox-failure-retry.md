# Outbox失敗retry・DEADとlease回収

## 範囲と仕様

PR #111 merge後main `735ed1e`から開始。ProjectionQueueにfail / recover_expiredを追加し、claimに回数上限の防御を追加する。transaction-design §9・17・20とoperations §4・5・技術既定値に従い、max_attempts=5 / lease_seconds=30、backoff=min(2^(attempt-1),60)秒を既定とする。内部constructorで正の整数に限り指定可能とし、環境設定・worker起動は今回追加しない。LogiScope再利用はない。

## 状態と境界

一時失敗はRETRYABLEとDB時刻基準のnext_attempt_atを記録する。恒久失敗または最終attemptはDEADとし、後続claimを停止する。失敗報告はoutbox ID / PROCESSING / attempt_count / processing_started_atを照合し、古い報告・重複・終端状態にはFalseを返して変更しない。失敗時にattemptを増やさずpayloadも変更しない。

期限を超えたPROCESSINGはRETRYABLEへ戻し、即時再試行可能なDB時刻を保存する。新しいPROCESSINGと他状態は変更せず、attemptは維持する。rebuild中・control不在は通常回収を停止する。仕様の「lease超過はRETRYABLE」を維持しつつ、上限済み回収イベントは次claimでDEADとし6回目のPROCESSINGを開始しない。通常の最終attempt失敗はその時点でDEADとなる。

DB操作は固定Core / bind parameter。専用session leaderを開始時・commit直前・commit後に確認し、短いREAD COMMITTED transactionで保存する。failure / 回収はmutation lockを新たに取らない。将来のworkerは適用中のmutation lockとこの状態保存境界を組み合わせる。last_errorはPROJECTION_TRANSIENT_FAILURE / PROJECTION_PERMANENT_FAILURE / PROJECTION_ATTEMPTS_EXHAUSTED / PROJECTION_LEASE_EXPIREDの固定codeだけとし、例外本文・SQL・credential・payloadは保存しない。

## 検証

- Docker内の対象112件成功（追加19、10.94秒）。
- backoff 1 / 2 / 16 / 60秒、恒久・最終失敗、DEADによるGraph ERRORと後続停止、古いattempt / 開始時刻 / 終端の拒否を実DBで確認。
- lease回収対象と新しいPROCESSINGの区別、rebuild / control不在、attempt維持、回収済み最終attemptが6回目を開始しないこと、failure / 回収DB失敗のrollbackを実DBで確認。
- 不正config拒否はDBを使わない試験。既存claim / Outbox / leader / Graph lock / 同期状態試験を維持し、SQL表記の検出フックは追加しない。
- ruff check / format check成功（142 files）。
- Docker内の全体回帰試験は2371 passed / 1 skipped / 1 warning（175.31秒）。

AC-13・18、NFR-04〜06、T-SQL04とtest-plan §6の対象部分の確認であり、Projection worker全体の完了とは扱わない。

## 未実装

Neo4j適用、適用前lease / status / DEAD / generation再検証、APPLIED保存・同version冪等性、heartbeat、controller drain、専用DB role・運用ログ・起動loopは後続。内部部品はHTTP / Agent Toolへ公開せず、既存runtime権限 / migration / 業務正本の更新仕様を変更しない。
