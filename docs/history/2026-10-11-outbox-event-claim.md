# Outboxイベントclaimの最初の実装

## 範囲

PR #110 merge後main `a1a9be9`から開始。ProjectionQueue.claimとcore_outboxのclaim statementを追加する。既存処理の移行ではなく、Projection workerに必要な最初の機能実装。worker起動・Neo4j adapter・Graph Toolは追加しない。LogiScope再利用はない。

transaction-design §8・17・20、operations §4・5、test-plan §6に従う。専用session leadershipを確認し、短いREAD COMMITTED transactionでcommit済みPENDINGまたはnext_attempt_atがDB時刻以下のRETRYABLEを1件選び、PROCESSING / attempt_count + 1 / processing_started_atをcommitする。時刻は単一statementのstatement_timestampを使う。created_at / outbox_id順は選択順だけであり、watermarkを保存しない。

## 境界

Coreの固定CTE / UPDATE / RETURNINGを使い、候補イベントだけをFOR UPDATEする。control rowのrebuild_flagを通常の参照で確認し、rebuild中・control不在・DEADがあればclaimしない。mutation advisory lockとcontrol行lockは取得しない。payloadを変更・再生成しない。leaderを開始時・commit直前・commit後に確認し、失われた場合はそれ以上の処理を止める。commit前の喪失はrollback、commit後の喪失はPROCESSINGが残り、後続lease回収の対象となる。

claimはGraph適用ではない。active_generation / fatal_error / lease / status / DEADの適用前再検証、Neo4j transaction、APPLIED、失敗時retry / DEAD、lease回収は未実装。controllerのrebuild中drainも後続。通常workerのloop・専用DB role / 権限・運用ログ・起動構成とともに、完成したworkerとして公開する前に実装する。この部品はHTTP / Agent Toolへ公開しない。既存runtimeの権限を広げず、migration / API / Tool / 業務正本更新は変更しない。

## リファクタリングを区切る根拠

残るDBアクセスの検索では、untrusted値のSQL文字列補間は確認されなかった。初回棚卸しと直近のSQL Injection / 権限 / transaction試験に加え、主要更新・Audit・OutboxはCoreへ移行済みである。安全な参照SQLを一括変換し続けるより、新機能をCore標準で実装し、関連参照は変更時に移行する判断とする。これは安全性の無条件保証やSQL Policy全体の完了宣言ではない。

## 検証

- Docker内の対象93件成功（追加14、8.46秒）。
- 新規14件でpayload / commit可視性 / attempt / DB時刻、処理中・終端・未到来retry除外、DEAD / rebuild / control不在、未commitと遅い小さいIDの可視性、mutation / control lock非取得、leader喪失のcommit前後、DB失敗rollbackを実PostgreSQLで検証。SQL表記検出フックは使わない。
- 既存Outbox登録・leader保持 / 喪失・Graph lock・同期状態 / storage試験を回帰確認。
- ruff check / format check成功（141 files）。
- Docker内の全体回帰試験2,352件成功、1 skipped、1 warning（171.03秒）。

AC-13・18、NFR-05・06、T-SQL04とtest-plan §6のclaim境界の対象部分を確認する。worker restart / 完全retry / Neo4j冪等適用等の完了とは扱わない。
