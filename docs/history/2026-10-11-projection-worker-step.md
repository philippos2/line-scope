# Projection workerの1件処理・失敗分類

2026-10-11。PR #114 merge後のmain `a6e1895`を起点とする。

## 変更

- 取得済み専用leaderを使うProjectionWorker.run_onceを追加。ERROR / REBUILDINGではBLOCKEDとし、初期化 / 復旧待ちでattemptを消費しない。通常時はlease回収 → 1件claim → 実Neo4j適用 / APPLIED保存、または再試行 / DEADへ接続する。
- 保存payloadの恒久不正を識別するProjectionPayloadErrorを追加し、marker不正はProjectionIntegrityErrorへ統一。一般ValueErrorやプログラム異常を恒久不正と誤判定しない。
- driverのretryable障害・Graph generation不在 / 未検証・PostgreSQLの接続 / lock / statement timeout等は既存backoffとattempt上限へ接続。再試行不可のdriver query / 設定異常・未知例外・leader喪失は停止し、未確定PROCESSINGを残して次leaderのlease回収へ渡す。失敗保存自体が失敗した場合も確定遷移ログを出さない。
- 適用前後で再検証に拒否された場合は内部結果FENCED。APPLIEDやRETRYABLEへ推測更新しない。FENCED / BLOCKED / IDLEはDBの新状態やHTTP契約ではなく、内部1回処理の結果を表す。
- 実Neo4j adapterのtransaction timeoutがlease未満であることを構築時に要求。
- 構造化ログへOutbox状態の許可enumを追加。成功・retry・DEADのcommit後ログ、期限切れ回収と上限済みclaimの退役ログを追加する。生payload・exception message / args・SQL / Cypher・credentialsを記録せず、未知障害は既存の安全なクラス / frame診断だけを出す。実行ごとのrequest_idと同じ業務ID / attemptで相関する。
- DBアクセスは既存Core / 既存の固定・parameter化済み同期状態観測を再利用。回収UPDATEのRETURNINGへログ用metadataを追加し、ProjectionQueueの公開戻り値（ID一覧）は維持。新しい生SQLやDDL・ORMを通常処理へ追加しない。

## 検証

Docker内の対象157件成功（15.78秒）、ruff check / format check成功（148 files）。Docker内の全体回帰試験は2455 passed / 1 skipped / 1 warning（追加25件、183.67秒）。実PostgreSQLと実Neo4jで1件成功・空queue・ERROR / REBUILDING停止、恒久payload / hash不正・上限 / 期限切れ回収、秘密を含む例外のログ秘匿、leader喪失・失敗保存障害、Graph commit後の一時APPLIED保存障害と冪等再送を確認する。

AC-13 / 18、NFR-04〜06、T-SQL04、test-plan §6とoperations §13の対象部分であり、worker運用全体の完了とは扱わない。

## 未実装

常駐loop / CLI / compose接続、専用DB role / credentials、heartbeat、seed / Rebuild / controller drain / restoreとGraph Toolは後続。今回のクラスをAPIやAgentへ公開せず、デモ環境で常駐workerを起動しない。業務・権限・API / Tool / migrationは変更しない。LogiScope再利用なし。

## 技術根拠

[公式driverのis_retryableと明示transactionでの独自retry分類](https://neo4j.com/docs/api/python-driver/current/api.html)を使い、例外メッセージの文字列照合で分類しない。
